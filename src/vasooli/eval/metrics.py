"""Scoring a run.

Three groups, and the ordering is deliberate:

1. **Money recovered.** What the track asks for.
2. **What it cost to get it.** Wasted contacts, relationship capital, churned
   accounts, human minutes. These exist so that a policy cannot win by
   harassment, and they are reported on the same table as recovery rather than
   in an appendix.
3. **Behaviour under its own rules.** Promise-respect, guardrail firings,
   restraint rate.

Converting relationship damage into rupees requires assumptions, and they are
stated here rather than buried: a churned account costs one year of gross margin
on the business it was doing. Both the raw and the money-converted forms are
reported, so a reader who disagrees with the conversion can still read the
counts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timedelta

from ..domain.enums import CONTACT_INSENSITIVE, HUMAN_MINUTES, Intervention
from ..domain.money import Paise, fmt, to_rupees
from ..sim import calibration as cal
from ..sim.world import World
from .runner import RunResult

# --- Assumptions used to convert cost into money. Both are designer priors. ---

GROSS_MARGIN = 0.18
"""Gross margin on the business a churned buyer represented. Manufacturing SME
range; the churn cost scales linearly with it, so a reader who prefers 0.10 can
scale the number by eye."""

CHURN_COST_YEARS = 1.0
"""Years of lost business charged when an account churns. One year is the
conservative choice - a relationship of several years' tenure is plausibly worth
more, and we deliberately do not claim that."""

OWNER_HOURLY_RUPEES = 300.0
"""Value of an hour of the owner's time. She is her own sales head and her own
collections department, so the hour spent chasing is an hour not spent selling."""


@dataclass
class Metrics:
    policy: str
    world_fingerprint: str
    seed: int
    horizon_days: int

    # --- recovery ---
    book: Paise = 0
    recovered: Paise = 0
    recovery_rate: float = 0.0
    outstanding: Paise = 0
    #: Disputed value forgiven by credit note. Unblocks the remainder, is not
    #: recovery, and is never added to `recovered`.
    written_off: Paise = 0
    #: Invoices that were blocked at the buyer's intake - never uploaded, no PO -
    #: and were repaired by a document chase. On an aging report these are
    #: indistinguishable from ordinary overdue.
    intake_repairs: int = 0
    dso_days: float = 0.0
    #: Weighted mean days from due date to payment. Lower is better and it is
    #: not the same as recovering more - a policy can collect the same rupees
    #: faster, which is worth real money to someone borrowing at 18%.
    mean_days_to_collect: float = 0.0

    # --- cost ---
    messages: int = 0
    wasted_messages: int = 0
    wasted_message_rate: float = 0.0
    relationship_spent: int = 0
    churned_accounts: int = 0
    churned_revenue_share: float = 0.0
    churn_cost: Paise = 0
    human_minutes: int = 0
    human_cost: Paise = 0

    # --- net ---
    net_value: Paise = 0

    # --- behaviour ---
    decisions: int = 0
    holds: int = 0
    restraint_rate: float = 0.0
    promise_violations: int = 0
    promises_seen: int = 0
    promise_respect_rate: float = 1.0
    escalations: int = 0
    intervention_mix: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def _churn_cost(world: World, result: RunResult) -> tuple[Paise, float]:
    """Money value of the accounts this policy destroyed."""
    total: int = 0
    share_lost = 0.0
    rev_by_merchant = {m.merchant_id: m.annual_revenue for m in world.merchants}
    for bid, br in result.state.buyers.items():
        if not br.churned:
            continue
        buyer = world.buyers[bid]
        annual = rev_by_merchant[world.buyer_merchant[bid]] * buyer.revenue_share
        total += int(annual * GROSS_MARGIN * CHURN_COST_YEARS)
        share_lost += buyer.revenue_share
    return Paise(total), share_lost


def _promise_violations(result: RunResult) -> tuple[int, int]:
    """Contacts made while a promise was live and not yet due.

    The stopping rule the whole pitch rests on. Counted from ground-truth
    promises in simulator state rather than from the agent's own belief, because
    a policy that fails to *notice* a promise has still broken it.
    """
    st = result.state
    grace = int(cal.PROMISE_GRACE_DAYS.value)
    # Counted as *promises that were violated*, not as violating contacts. The
    # earlier version summed contacts, so three messages during one promise
    # window scored as three violations against one promise and the "respect
    # rate" went negative - an unbounded number presented as a percentage.
    by_buyer: dict[str, list] = {}
    for msg in st.outbound:
        by_buyer.setdefault(msg.buyer_id, []).append(msg.sent_at.date())

    violated = 0
    seen = 0
    for bid, br in st.buyers.items():
        sent_days = by_buyer.get(bid, ())
        for p in br.promises:
            seen += 1
            window_end = p.promised_date + timedelta(days=grace)
            if any(p.made_on < d < window_end for d in sent_days):
                violated += 1
    return violated, seen


def score(world: World, result: RunResult) -> Metrics:
    st = result.state
    book = Paise(sum(i.amount for i in world.invoices.values()))
    recovered = st.total_collected()
    outstanding = st.total_outstanding()

    wasted = sum(1 for m in st.outbound if world.truth[m.buyer_id].archetype in CONTACT_INSENSITIVE)
    churn_cost, share_lost = _churn_cost(world, result)
    minutes = sum(b.human_minutes for b in st.buyers.values())
    human_cost = Paise(int(minutes / 60.0 * OWNER_HOURLY_RUPEES * 100))

    # Days from due date to payment, weighted by amount.
    weighted = 0.0
    for p in st.payments:
        inv = world.invoices[p.invoice_id]
        weighted += p.amount * (p.received_on - inv.due_date).days
    mean_days = (weighted / recovered) if recovered else 0.0

    # DSO on the standard formula: closing receivables over credit sales,
    # annualised across the horizon.
    dso = (outstanding / book * result.days) if book else 0.0

    holds = sum(1 for d in result.decisions if d.chosen is Intervention.HOLD)
    escalations = sum(
        1
        for m in st.outbound
        if m.intervention
        in (Intervention.OWNER_ESCALATION, Intervention.MSMED_NOTICE, Intervention.SAMADHAAN_FILING)
    )
    mix: dict[str, int] = {}
    for m in st.outbound:
        mix[m.intervention.value] = mix.get(m.intervention.value, 0) + 1

    violations, promises = _promise_violations(result)

    return Metrics(
        policy=result.policy_name,
        world_fingerprint=result.world_fingerprint,
        seed=result.seed,
        horizon_days=result.days,
        book=book,
        recovered=recovered,
        recovery_rate=recovered / book if book else 0.0,
        outstanding=outstanding,
        written_off=st.write_offs,
        intake_repairs=st.intake_repairs,
        dso_days=dso,
        mean_days_to_collect=mean_days,
        messages=len(st.outbound),
        wasted_messages=wasted,
        wasted_message_rate=wasted / len(st.outbound) if st.outbound else 0.0,
        relationship_spent=sum(b.relationship_spent for b in st.buyers.values()),
        churned_accounts=sum(1 for b in st.buyers.values() if b.churned),
        churned_revenue_share=share_lost,
        churn_cost=churn_cost,
        human_minutes=minutes,
        human_cost=human_cost,
        net_value=Paise(recovered - churn_cost - human_cost),
        decisions=len(result.decisions),
        holds=holds,
        restraint_rate=holds / len(result.decisions) if result.decisions else 0.0,
        promise_violations=violations,
        promises_seen=promises,
        promise_respect_rate=1.0 - (violations / promises) if promises else 1.0,
        escalations=escalations,
        intervention_mix=mix,
    )


# ---------------------------------------------------------------------------
# Paired comparison
# ---------------------------------------------------------------------------


@dataclass
class PairedDiff:
    metric: str
    a_policy: str
    b_policy: str
    mean_diff: float
    ci_low: float
    ci_high: float
    n_clusters: int

    @property
    def significant(self) -> bool:
        return (self.ci_low > 0) or (self.ci_high < 0)


def paired_bootstrap(
    world: World,
    a: RunResult,
    b: RunResult,
    *,
    metric: str = "recovered",
    n_boot: int = 2000,
    seed: int = 7,
    alpha: float = 0.05,
) -> PairedDiff:
    """Bootstrap CI on the per-buyer difference between two policies.

    Resamples **buyers**, not payments. The buyer is the unit that was randomised
    and payments cluster hard within one, so bootstrapping payments would
    understate the interval badly.

    Valid only because the two runs used common random numbers - see sim/rng.py.
    Without that pairing this compares two independent draws and the interval
    means something quite different.
    """
    import random as _random

    def per_buyer(res: RunResult) -> dict[str, float]:
        out = {bid: 0.0 for bid in world.buyers}
        if metric == "recovered":
            for p in res.state.payments:
                out[p.buyer_id] += p.amount
        elif metric == "messages":
            for m in res.state.outbound:
                out[m.buyer_id] += 1
        elif metric == "net_value":
            rev = {bid: 0.0 for bid in world.buyers}
            for p in res.state.payments:
                rev[p.buyer_id] += p.amount
            rev_by_m = {m.merchant_id: m.annual_revenue for m in world.merchants}
            for bid, br in res.state.buyers.items():
                cost = 0.0
                if br.churned:
                    annual = rev_by_m[world.buyer_merchant[bid]] * world.buyers[bid].revenue_share
                    cost += annual * GROSS_MARGIN * CHURN_COST_YEARS
                cost += br.human_minutes / 60.0 * OWNER_HOURLY_RUPEES * 100
                rev[bid] -= cost
            out = rev
        else:
            raise ValueError(f"unsupported metric {metric!r}")
        return out

    av, bv = per_buyer(a), per_buyer(b)
    ids = sorted(world.buyers)
    diffs = [av[i] - bv[i] for i in ids]
    n = len(diffs)
    observed = sum(diffs) / n

    rnd = _random.Random(seed)
    means = []
    for _ in range(n_boot):
        s = sum(diffs[rnd.randrange(n)] for _ in range(n))
        means.append(s / n)
    means.sort()
    lo = means[int(alpha / 2 * n_boot)]
    hi = means[int((1 - alpha / 2) * n_boot)]

    return PairedDiff(
        metric=metric,
        a_policy=a.policy_name,
        b_policy=b.policy_name,
        mean_diff=observed,
        ci_low=lo,
        ci_high=hi,
        n_clusters=n,
    )


def format_table(rows: list[Metrics]) -> str:
    """Fixed-width comparison table. Cost columns sit beside recovery, never below."""
    hdr = (
        f"{'policy':<16}{'recovered':>11}{'rate':>7}{'net':>11}{'msgs':>7}"
        f"{'waste':>7}{'churn':>7}{'hrs':>6}{'hold%':>7}{'promise':>9}"
    )
    lines = [hdr, "-" * len(hdr)]
    for m in rows:
        lines.append(
            f"{m.policy:<16}"
            f"{fmt(m.recovered, compact=True):>11}"
            f"{m.recovery_rate:>6.1%}"
            f"{fmt(m.net_value, compact=True):>11}"
            f"{m.messages:>7}"
            f"{m.wasted_message_rate:>6.0%}"
            f"{m.churned_accounts:>7}"
            f"{m.human_minutes / 60:>6.0f}"
            f"{m.restraint_rate:>6.0%}"
            f"{m.promise_respect_rate:>9.0%}"
        )
    return "\n".join(lines)
