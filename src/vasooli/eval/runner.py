"""Drives one policy over one world for the full horizon."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ..agent.view import build_view
from ..domain.models import Decision
from ..sim import dynamics
from ..sim.state import RunState
from ..sim.world import World
from .protocol import Policy


@dataclass
class RunResult:
    policy_name: str
    world_fingerprint: str
    seed: int
    state: RunState
    decisions: list[Decision] = field(default_factory=list)
    days: int = 0


def run(world: World, policy: Policy, *, seed: int | None = None, horizon: int | None = None) -> RunResult:
    st = dynamics.new_run(world, seed=seed)
    horizon = horizon or world.horizon_days
    decisions: list[Decision] = []

    for offset in range(horizon):
        day = world.start_date + timedelta(days=offset)
        st.day = day

        # Buyers with nothing outstanding need no ledger. On a book where a
        # growing share settles over the horizon this is a large saving, and it
        # cannot change any decision: a policy has nothing to decide about a
        # buyer who owes nothing.
        active = [bid for bid in world.buyers if st.open_invoice_ids(bid, world)]
        view = build_view(world, st, day, buyer_ids=active)

        if hasattr(policy, "observe"):
            policy.observe(view, day)

        for i, decision in enumerate(policy.decide(view, day)):
            # Stamp a deterministic decision id centrally rather than trusting
            # each policy's default. Keeps audit trails byte-identical across
            # runs, which is what makes two report artifacts diffable.
            decision = decision.model_copy(
                update={"decision_id": f"dec_{decision.buyer_id[-8:]}_{day.isoformat()}_{i:03d}"}
            )
            decisions.append(decision)
            dynamics.apply_decision(world, st, decision)

        dynamics.advance(world, st, day)

    return RunResult(
        policy_name=policy.name,
        world_fingerprint=world.fingerprint(),
        seed=st.seed,
        state=st,
        decisions=decisions,
        days=horizon,
    )
