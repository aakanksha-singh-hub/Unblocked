"""Invariants the simulation must hold, or no number downstream means anything."""

from __future__ import annotations

from datetime import timedelta

import pytest

from vasooli.agent.view import build_view
from vasooli.domain.enums import BuyerArchetype, Intervention
from vasooli.domain.models import Buyer, BuyerTruth, Decision
from vasooli.eval import baselines, runner
from vasooli.sim import dynamics
from vasooli.sim.world import generate


@pytest.fixture(scope="module")
def small_world():
    return generate(n_merchants=2, buyers_per_merchant=25, horizon_days=120)


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


def test_world_generation_is_deterministic():
    assert generate(seed=99).fingerprint() == generate(seed=99).fingerprint()


def test_different_seeds_give_different_worlds():
    assert generate(seed=1).fingerprint() != generate(seed=2).fingerprint()


def test_run_is_deterministic(small_world):
    a = runner.run(small_world, baselines.StaticLadder())
    b = runner.run(small_world, baselines.StaticLadder())
    assert a.state.total_collected() == b.state.total_collected()
    assert len(a.state.outbound) == len(b.state.outbound)


def test_common_random_numbers_pair_across_policies(small_world):
    """The property the whole paired comparison rests on.

    A buyer nobody contacts under either policy must experience an identical
    payment stream. If a policy contacting *other* buyers perturbs this one,
    the runs are not paired and every confidence interval computed on their
    difference is wrong.
    """
    quiet = runner.run(small_world, baselines.NeverChase())
    ladder = runner.run(small_world, baselines.StaticLadder())

    contacted = {m.buyer_id for m in ladder.state.outbound}
    untouched = [b for b in small_world.buyers if b not in contacted]
    assert untouched, "test is vacuous if the ladder contacted everyone"

    for bid in untouched:
        qs = [(p.invoice_id, p.received_on, p.amount) for p in quiet.state.payments if p.buyer_id == bid]
        ls = [(p.invoice_id, p.received_on, p.amount) for p in ladder.state.payments if p.buyer_id == bid]
        assert qs == ls, f"{bid} desynchronised between policies"


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


def test_no_invoice_is_overpaid(small_world):
    st = runner.run(small_world, baselines.BlastWeekly()).state
    paid: dict[str, int] = {}
    for p in st.payments:
        paid[p.invoice_id] = paid.get(p.invoice_id, 0) + p.amount
    for iid, total in paid.items():
        assert total <= small_world.invoices[iid].amount, f"{iid} overpaid"


def test_outstanding_never_negative(small_world):
    st = runner.run(small_world, baselines.BlastWeekly()).state
    assert all(rt.outstanding >= 0 for rt in st.invoices.values())


def test_ledger_balances(small_world):
    """Collected plus outstanding equals the book, exactly. Integer paise means
    this is an equality and not an approximation - if it ever needs a tolerance,
    a float has crept in."""
    st = runner.run(small_world, baselines.StaticLadder()).state
    book = sum(i.amount for i in small_world.invoices.values())
    assert st.total_collected() + st.total_outstanding() == book


def test_all_payments_are_integers(small_world):
    st = runner.run(small_world, baselines.BlastWeekly()).state
    assert all(isinstance(p.amount, int) and not isinstance(p.amount, bool) for p in st.payments)


# ---------------------------------------------------------------------------
# Structural blockers
# ---------------------------------------------------------------------------


def test_portal_blocked_invoices_are_never_paid(small_world):
    """The silent killer must actually be fatal, or the agent's highest-value
    discovery is worthless."""
    st = runner.run(small_world, baselines.BlastWeekly()).state
    blocked = {
        iid
        for iid, inv in small_world.invoices.items()
        if small_world.buyers[inv.buyer_id].uses_ap_portal and not inv.portal_submitted
    }
    assert blocked, "test is vacuous with no portal-blocked invoices"
    paid = {p.invoice_id for p in st.payments}
    assert not (blocked & paid)


def test_fully_disputed_invoice_is_blocked(small_world):
    st = runner.run(small_world, baselines.BlastWeekly()).state
    for bid, br in st.buyers.items():
        for d in br.disputes:
            if d.status != "open" or d.disputed_amount is not None:
                continue
            for iid in d.invoice_ids:
                after = [
                    p for p in st.payments if p.invoice_id == iid and p.received_on > d.raised_on
                ]
                assert not after, f"{iid} paid while fully disputed"


# ---------------------------------------------------------------------------
# Leakage
# ---------------------------------------------------------------------------


def test_buyer_type_carries_no_archetype():
    assert "archetype" not in Buyer.model_fields
    assert "archetype" in BuyerTruth.model_fields


def test_ledger_view_exposes_no_ground_truth(small_world):
    """Walk the object graph the agent receives and assert nothing reachable from
    it is a BuyerTruth. This is the guarantee the classifier numbers depend on."""
    st = dynamics.new_run(small_world)
    view = build_view(small_world, st, small_world.start_date)

    seen: set[int] = set()
    stack = [view]
    while stack:
        obj = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        assert not isinstance(obj, BuyerTruth), "ground truth reachable from LedgerView"
        if isinstance(obj, dict):
            stack.extend(obj.keys()); stack.extend(obj.values())
        elif isinstance(obj, (list, tuple, set)):
            stack.extend(obj)
        elif hasattr(obj, "__dict__"):
            stack.extend(vars(obj).values())


def test_view_hides_unissued_invoices(small_world):
    st = dynamics.new_run(small_world)
    day = small_world.start_date + timedelta(days=10)
    view = build_view(small_world, st, day)
    for lg in view.ledgers.values():
        assert all(iv.invoice.issue_date <= day for iv in lg.invoices)


# ---------------------------------------------------------------------------
# Costs are actually charged
# ---------------------------------------------------------------------------


def test_hold_costs_nothing(small_world):
    st = dynamics.new_run(small_world)
    bid = next(iter(small_world.buyers))
    dynamics.apply_decision(
        small_world,
        st,
        Decision(buyer_id=bid, as_of=small_world.start_date, chosen=Intervention.HOLD, rationale="t"),
    )
    br = st.buyers[bid]
    assert br.relationship_spent == 0 and br.human_minutes == 0 and not st.outbound
    assert st.audit, "a hold must still be audited - restraint is a decision"


def test_escalation_charges_relationship_capital(small_world):
    st = dynamics.new_run(small_world)
    bid = next(iter(small_world.buyers))
    dynamics.apply_decision(
        small_world,
        st,
        Decision(
            buyer_id=bid,
            as_of=small_world.start_date,
            chosen=Intervention.MSMED_NOTICE,
            rationale="t",
        ),
    )
    assert st.buyers[bid].relationship_spent == 45


def test_intervention_effect_is_order_independent(small_world):
    """A helping and a harming contact on the same day must compose the same way
    regardless of the order they were appended."""
    bid = next(
        b for b in small_world.buyers if small_world.truth[b].archetype is BuyerArchetype.DISPUTER
    )
    day = small_world.start_date

    def factor(order):
        st = dynamics.new_run(small_world)
        st.buyers[bid].contacts = [(day, iv) for iv in order]
        return dynamics._intervention_factor(small_world, st, bid, day)

    a = factor([Intervention.DISPUTE_RESOLUTION, Intervention.FIRM_REMINDER])
    b = factor([Intervention.FIRM_REMINDER, Intervention.DISPUTE_RESOLUTION])
    assert a == pytest.approx(b)
