"""Cached application state for the UI.

One simulated run is executed at startup and held in memory. Deliberately not
re-run per request: a page that re-simulates 180 days on every click is slow,
and worse, it means two pages of the same dashboard can disagree with each other
about what happened.

The world is smaller than the evaluation's (180 buyers rather than 728) so
startup stays a few seconds. Evaluation numbers on the /evaluation page are read
from artifacts written by the full-scale run, not from this one - the dashboard
shows a book you can browse, the artifacts carry the measured claims, and the
page says which is which.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from ..agent.inference import ArchetypeModel
from ..agent.policy import CauseMatchedPolicy
from ..domain.enums import Intervention
from ..domain.models import Decision
from ..eval import baselines, metrics, runner
from ..eval.runner import RunResult
from ..sim.world import World, generate

ARTIFACTS = Path("artifacts")


@dataclass
class BuyerCard:
    buyer_id: str
    name: str
    city: str
    state: str
    revenue_share: float
    terms: int
    tenure: int
    outstanding: int
    recovered: int
    original: int
    oldest_dpd: int
    open_invoices: int
    blocked_invoices: int
    inferred: str | None
    confidence: float
    truth: str
    messages: int
    replies: int
    last_action: str
    last_action_on: str | None
    held_for: str | None
    churned: bool

    @property
    def recovery_pct(self) -> float:
        return 100.0 * self.recovered / self.original if self.original else 0.0


@dataclass
class AppState:
    world: World
    result: RunResult
    policy: CauseMatchedPolicy
    baseline: RunResult
    summary: metrics.Metrics
    baseline_summary: metrics.Metrics
    cards: list[BuyerCard] = field(default_factory=list)
    decisions_by_buyer: dict[str, list[Decision]] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)

    def card(self, buyer_id: str) -> BuyerCard | None:
        return next((c for c in self.cards if c.buyer_id == buyer_id), None)


def _load_artifact(name: str) -> Any:
    path = ARTIFACTS / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def build(*, merchants: int = 4, buyers: int = 45, seed: int = 20260824) -> AppState:
    world = generate(seed=seed, n_merchants=merchants, buyers_per_merchant=buyers)
    udyam = {
        b: next(m.udyam_registered for m in world.merchants if m.merchant_id == world.buyer_merchant[b])
        for b in world.buyers
    }
    model = ArchetypeModel.load() if (ARTIFACTS / "models/archetype.pkl").exists() else None
    policy = CauseMatchedPolicy(model=model, merchant_udyam=udyam)
    policy.name = "cause-matched"

    result = runner.run(world, policy)
    base = runner.run(world, baselines.NeverChase())

    by_buyer: dict[str, list[Decision]] = {}
    for d in result.decisions:
        by_buyer.setdefault(d.buyer_id, []).append(d)

    st = result.state
    cards: list[BuyerCard] = []
    for bid, buyer in world.buyers.items():
        invs = [i for i in world.invoices.values() if i.buyer_id == bid]
        rts = [st.invoices[i.invoice_id] for i in invs]
        outstanding = sum(r.outstanding for r in rts)
        original = sum(r.original for r in rts)
        open_rts = [r for r in rts if r.is_open]
        blocked = sum(1 for r in open_rts if not r.portal_submitted or not r.has_po)

        end = world.start_date.replace(year=world.start_date.year)
        last_day = max((d.as_of for d in by_buyer.get(bid, [])), default=None)
        dpd = max(
            ((last_day or world.start_date) - i.due_date).days
            for i in invs
        ) if invs else 0

        acted = [d for d in by_buyer.get(bid, []) if d.chosen is not Intervention.HOLD]
        held = [d for d in by_buyer.get(bid, []) if d.chosen is Intervention.HOLD]
        last_hold_reason = None
        if held:
            failed = [g for g in held[-1].gates if not g.passed]
            last_hold_reason = failed[0].gate if failed else "no_positive_value"

        beliefs = policy.beliefs.buyers.get(bid)
        cards.append(
            BuyerCard(
                buyer_id=bid,
                name=buyer.legal_name,
                city=buyer.city,
                state=buyer.state,
                revenue_share=buyer.revenue_share,
                terms=buyer.agreed_terms_days,
                tenure=buyer.tenure_months,
                outstanding=outstanding,
                recovered=original - outstanding,
                original=original,
                oldest_dpd=dpd,
                open_invoices=len(open_rts),
                blocked_invoices=blocked,
                inferred=(beliefs.archetype.value if beliefs and beliefs.archetype else None),
                confidence=(beliefs.confidence if beliefs else 0.0),
                truth=world.truth[bid].archetype.value,
                messages=len(st.outbound_by_buyer.get(bid, [])),
                replies=len(st.inbound_by_buyer.get(bid, [])),
                last_action=(acted[-1].chosen.value if acted else "none"),
                last_action_on=(acted[-1].as_of.isoformat() if acted else None),
                held_for=last_hold_reason,
                churned=st.buyers[bid].churned,
            )
        )

    cards.sort(key=lambda c: -c.outstanding)

    return AppState(
        world=world,
        result=result,
        policy=policy,
        baseline=base,
        summary=metrics.score(world, result),
        baseline_summary=metrics.score(world, base),
        cards=cards,
        decisions_by_buyer=by_buyer,
        artifacts={
            "evaluation": _load_artifact("evaluation.json"),
            "breakeven": _load_artifact("breakeven.json"),
            "sensitivity": _load_artifact("sensitivity.json"),
            "inference": _load_artifact("inference_report.json"),
            "extraction": _load_artifact("extraction_report.json"),
        },
    )
