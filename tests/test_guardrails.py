"""Guardrail tests.

These carry more weight than any other tests here. The project's central claim
about judgement is that stopping rules are deterministic code rather than
instructions to a model, and that claim is worth exactly as much as this file.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from unblocked.agent.beliefs import BuyerBeliefs
from unblocked.agent.guardrails import GateConfig, Guardrails
from unblocked.agent.view import BuyerLedger, InvoiceView
from unblocked.domain.enums import Channel, Intervention
from unblocked.domain.models import Buyer, Dispute, Invoice, OutboundMessage, Promise

TODAY = date(2026, 6, 10)  # a Wednesday
ALL = list(Intervention)


def make_ledger(
    *,
    dpd: int = 40,
    amount: int = 250000_00,
    revenue_share: float = 0.02,
    msmed_eligible: bool = True,
    acceptance_offset: int = 0,
    channels: list[Channel] | None = None,
    contacts: list[date] | None = None,
) -> BuyerLedger:
    buyer = Buyer(
        buyer_id="buy_test",
        legal_name="Test Buyer Pvt Ltd",
        city="Pune",
        state="MH",
        revenue_share=revenue_share,
        agreed_terms_days=30,
        tenure_months=40,
        reachable_channels=channels if channels is not None else [Channel.EMAIL],
        msmed_eligible=msmed_eligible,
    )
    due = TODAY - timedelta(days=dpd)
    issue = due - timedelta(days=30)
    inv = Invoice(
        invoice_id="inv_test",
        invoice_number="T/26-27/0001",
        buyer_id=buyer.buyer_id,
        amount=amount,
        issue_date=issue,
        due_date=due,
        acceptance_date=issue + timedelta(days=acceptance_offset),
    )
    lg = BuyerLedger(buyer=buyer, invoices=[InvoiceView(invoice=inv, outstanding=amount, paid=0)])
    for d in contacts or []:
        lg.sent.append(
            OutboundMessage(
                buyer_id=buyer.buyer_id,
                invoice_ids=["inv_test"],
                intervention=Intervention.SOFT_NUDGE,
                channel=Channel.EMAIL,
                sent_at=datetime.combine(d, datetime.min.time()),
                body="x",
                decision_id="d",
            )
        )
    return lg


def gate(results, name):
    return next(r for r in results if r.gate == name)


@pytest.fixture
def g():
    return Guardrails()


# --- promise freeze: the headline stopping rule -----------------------------


def test_open_promise_silences_everything(g):
    b = BuyerBeliefs(buyer_id="buy_test")
    b.promises.append(
        Promise(
            buyer_id="buy_test",
            invoice_ids=["inv_test"],
            made_on=TODAY - timedelta(days=4),
            promised_date=TODAY + timedelta(days=8),
            source_quote="month end tak ho jayega",
            source_message_id="m1",
            confidence=0.9,
        )
    )
    d = g.filter(ALL, make_ledger(), b, TODAY)
    assert d.allowed == [Intervention.HOLD]
    assert not gate(d.results, "promise_freeze").passed
    assert "month end tak" in gate(d.results, "promise_freeze").reason


def test_contact_resumes_after_promise_date_plus_grace(g):
    b = BuyerBeliefs(buyer_id="buy_test")
    b.promises.append(
        Promise(
            buyer_id="buy_test",
            invoice_ids=["inv_test"],
            made_on=TODAY - timedelta(days=20),
            promised_date=TODAY - timedelta(days=5),
            source_quote="15 tarikh tak",
            source_message_id="m1",
            confidence=0.9,
        )
    )
    d = g.filter(ALL, make_ledger(), b, TODAY)
    assert gate(d.results, "promise_freeze").passed
    assert len(d.allowed) > 1


def test_serial_promise_breakers_lose_the_deferral(g):
    """Otherwise promise-deferral is an infinite stall and the stopping rule
    becomes a way to never collect anything."""
    b = BuyerBeliefs(buyer_id="buy_test")
    for i in range(3):
        b.promises.append(
            Promise(
                buyer_id="buy_test",
                invoice_ids=["inv_test"],
                made_on=TODAY - timedelta(days=60 - i * 10),
                promised_date=TODAY - timedelta(days=50 - i * 10),
                source_quote="next week",
                source_message_id=f"m{i}",
                confidence=0.9,
                status="broken",
            )
        )
    b.promises.append(
        Promise(
            buyer_id="buy_test",
            invoice_ids=["inv_test"],
            made_on=TODAY,
            promised_date=TODAY + timedelta(days=10),
            source_quote="agle hafte",
            source_message_id="m9",
            confidence=0.9,
        )
    )
    d = g.filter(ALL, make_ledger(), b, TODAY)
    assert gate(d.results, "promise_freeze").passed
    assert "already broken" in gate(d.results, "promise_freeze").reason


# --- dispute freeze ---------------------------------------------------------


def test_open_dispute_permits_only_resolution_paths(g):
    b = BuyerBeliefs(buyer_id="buy_test")
    b.disputes.append(
        Dispute(
            buyer_id="buy_test",
            invoice_ids=["inv_test"],
            raised_on=TODAY - timedelta(days=3),
            kind="short_delivery",
            source_quote="2 boxes damaged the",
        )
    )
    d = g.filter(ALL, make_ledger(), b, TODAY)
    assert set(d.allowed) <= {
        Intervention.DISPUTE_RESOLUTION,
        Intervention.DOCUMENT_RECONCILE,
        Intervention.HOLD,
    }
    assert Intervention.FIRM_REMINDER not in d.allowed


# --- hardship shield --------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    [
        Intervention.FIRM_REMINDER,
        Intervention.OWNER_ESCALATION,
        Intervention.MSMED_NOTICE,
        Intervention.SAMADHAAN_FILING,
    ],
)
def test_hardship_blocks_all_pressure(g, action):
    """The gate that exists for human reasons rather than commercial ones."""
    b = BuyerBeliefs(
        buyer_id="buy_test", hardship_declared=True, hardship_declared_on=TODAY - timedelta(days=5)
    )
    d = g.filter([action], make_ledger(), b, TODAY)
    assert action not in d.allowed
    assert not gate(d.results, "hardship_shield").passed


def test_undated_hardship_fails_closed(g):
    """A shield with no recorded date cannot be shown to have expired. Failing
    open would mean applying pressure to someone who said they cannot pay."""
    b = BuyerBeliefs(buyer_id="buy_test", hardship_declared=True)
    d = g.filter([Intervention.FIRM_REMINDER], make_ledger(), b, TODAY)
    assert Intervention.FIRM_REMINDER not in d.allowed


def test_hardship_expires(g):
    """A declaration made two months ago is a statement about two months ago.
    Without expiry, one sentence permanently disarms every firm action."""
    b = BuyerBeliefs(
        buyer_id="buy_test", hardship_declared=True, hardship_declared_on=TODAY - timedelta(days=90)
    )
    d = g.filter([Intervention.FIRM_REMINDER], make_ledger(), b, TODAY)
    assert Intervention.FIRM_REMINDER in d.allowed


def test_hardship_clears_early_on_evidence_of_capacity(g):
    """Someone paying substantial amounts is demonstrably able to pay."""
    b = BuyerBeliefs(
        buyer_id="buy_test",
        hardship_declared=True,
        hardship_declared_on=TODAY - timedelta(days=5),
        paid_since_hardship=100000_00,
    )
    d = g.filter([Intervention.FIRM_REMINDER], make_ledger(amount=250000_00), b, TODAY)
    assert Intervention.FIRM_REMINDER in d.allowed


def test_partial_payment_does_not_clear_the_shield(g):
    """A token payment is not evidence of capacity."""
    b = BuyerBeliefs(
        buyer_id="buy_test",
        hardship_declared=True,
        hardship_declared_on=TODAY - timedelta(days=5),
        paid_since_hardship=5000_00,
    )
    d = g.filter([Intervention.FIRM_REMINDER], make_ledger(amount=250000_00), b, TODAY)
    assert Intervention.FIRM_REMINDER not in d.allowed


def test_hardship_still_permits_instalment_offer(g):
    b = BuyerBeliefs(
        buyer_id="buy_test", hardship_declared=True, hardship_declared_on=TODAY - timedelta(days=5)
    )
    d = g.filter([Intervention.INSTALMENT_OFFER], make_ledger(), b, TODAY)
    assert Intervention.INSTALMENT_OFFER in d.allowed


# --- MSMED ladder -----------------------------------------------------------


def test_msmed_notice_blocked_without_udyam_registration(g):
    """An unregistered supplier issuing an MSMED notice is bluffing, and the
    agent is not permitted to bluff."""
    b = BuyerBeliefs(buyer_id="buy_test")
    d = g.filter([Intervention.MSMED_NOTICE], make_ledger(dpd=120), b, TODAY, merchant_udyam=False)
    assert Intervention.MSMED_NOTICE not in d.allowed
    assert not gate(d.results, "msmed_eligibility").passed


def test_msmed_notice_blocked_before_45_days_from_acceptance(g):
    b = BuyerBeliefs(buyer_id="buy_test")
    # 10 days past due on 30-day terms, accepted at issue => 40 days elapsed.
    d = g.filter([Intervention.MSMED_NOTICE], make_ledger(dpd=10), b, TODAY)
    assert Intervention.MSMED_NOTICE not in d.allowed
    assert not gate(d.results, "msmed_clock").passed


def test_msmed_notice_allowed_once_clock_has_run(g):
    b = BuyerBeliefs(buyer_id="buy_test")
    d = g.filter([Intervention.MSMED_NOTICE], make_ledger(dpd=90), b, TODAY)
    assert Intervention.MSMED_NOTICE in d.allowed
    assert d.requires_approval


def test_msmed_clock_runs_from_acceptance_not_issue(g):
    """s.15 runs from acceptance. An invoice accepted late is not yet eligible
    even though it looks old on the aging report."""
    b = BuyerBeliefs(buyer_id="buy_test")
    late = make_ledger(dpd=50, acceptance_offset=45)
    d = g.filter([Intervention.MSMED_NOTICE], late, b, TODAY)
    assert Intervention.MSMED_NOTICE not in d.allowed


# --- irreversibility and concentration --------------------------------------


def test_samadhaan_always_requires_human_approval(g):
    b = BuyerBeliefs(buyer_id="buy_test")
    d = g.filter([Intervention.SAMADHAAN_FILING], make_ledger(dpd=200), b, TODAY)
    assert d.requires_approval


def test_concentration_guard_blocks_escalation_on_a_major_account(g):
    """Losing an account worth a fifth of the business is the owner's call."""
    b = BuyerBeliefs(buyer_id="buy_test")
    big = make_ledger(dpd=120, revenue_share=0.35)
    d = g.filter([Intervention.OWNER_ESCALATION, Intervention.MSMED_NOTICE], big, b, TODAY)
    assert Intervention.OWNER_ESCALATION not in d.allowed
    assert not gate(d.results, "concentration_guard").passed


# --- cadence ----------------------------------------------------------------


def test_no_contact_on_sunday(g):
    d = g.filter(ALL, make_ledger(), BuyerBeliefs(buyer_id="buy_test"), date(2026, 6, 14))
    assert d.allowed == [Intervention.HOLD]
    assert not gate(d.results, "quiet_day").passed


def test_no_contact_on_public_holiday(g):
    d = g.filter(ALL, make_ledger(), BuyerBeliefs(buyer_id="buy_test"), date(2026, 8, 15))
    assert d.allowed == [Intervention.HOLD]


def test_contact_spacing_enforced(g):
    lg = make_ledger(contacts=[TODAY - timedelta(days=2)])
    d = g.filter(ALL, lg, BuyerBeliefs(buyer_id="buy_test"), TODAY)
    assert d.allowed == [Intervention.HOLD]
    assert not gate(d.results, "contact_spacing").passed


def test_frequency_cap_enforced(g):
    lg = make_ledger(contacts=[TODAY - timedelta(days=d) for d in (7, 13, 19, 25)])
    d = g.filter(ALL, lg, BuyerBeliefs(buyer_id="buy_test"), TODAY)
    assert d.allowed == [Intervention.HOLD]
    assert not gate(d.results, "frequency_cap").passed


def test_nothing_sent_before_due_date(g):
    d = g.filter(ALL, make_ledger(dpd=-5), BuyerBeliefs(buyer_id="buy_test"), TODAY)
    assert d.allowed == [Intervention.HOLD]
    assert not gate(d.results, "not_yet_due").passed


def test_de_minimis_amounts_are_left_alone(g):
    d = g.filter(ALL, make_ledger(amount=50_00), BuyerBeliefs(buyer_id="buy_test"), TODAY)
    assert d.allowed == [Intervention.HOLD]


def test_unreachable_buyer_is_not_contacted(g):
    d = g.filter(ALL, make_ledger(channels=[]), BuyerBeliefs(buyer_id="buy_test"), TODAY)
    assert d.allowed == [Intervention.HOLD]


# --- structural properties --------------------------------------------------


def test_hold_is_always_available(g):
    """There is no state in which the agent has no legal action."""
    for lg, b, day in [
        (make_ledger(dpd=-100), BuyerBeliefs(buyer_id="buy_test"), TODAY),
        (make_ledger(), BuyerBeliefs(buyer_id="buy_test", hardship_declared=True), TODAY),
        (make_ledger(channels=[]), BuyerBeliefs(buyer_id="buy_test"), date(2026, 6, 14)),
    ]:
        assert Intervention.HOLD in g.filter(ALL, lg, b, day).allowed


def test_all_gates_are_evaluated_not_short_circuited(g):
    """The audit must show everything that would have stopped an action, not
    only the first thing that did."""
    lg = make_ledger(dpd=-5, amount=10_00, channels=[])
    d = g.filter(ALL, lg, BuyerBeliefs(buyer_id="buy_test"), date(2026, 6, 14))
    failed = {r.gate for r in d.blocked()}
    assert {"quiet_day", "not_yet_due", "de_minimis", "reachable"} <= failed


def test_every_result_carries_a_human_readable_reason(g):
    d = g.filter(ALL, make_ledger(), BuyerBeliefs(buyer_id="buy_test"), TODAY)
    assert all(r.reason and len(r.reason) > 10 for r in d.results)


def test_gates_are_pure(g):
    """Same inputs, same verdict. A gate that depends on hidden state cannot be
    audited."""
    lg, b = make_ledger(), BuyerBeliefs(buyer_id="buy_test")
    a = g.filter(ALL, lg, b, TODAY)
    c = g.filter(ALL, lg, b, TODAY)
    assert a.allowed == c.allowed
    assert [(r.gate, r.passed) for r in a.results] == [(r.gate, r.passed) for r in c.results]


def test_config_is_respected(g):
    strict = Guardrails(GateConfig(min_days_between_contacts=30))
    lg = make_ledger(contacts=[TODAY - timedelta(days=10)])
    assert strict.filter(ALL, lg, BuyerBeliefs(buyer_id="buy_test"), TODAY).allowed == [
        Intervention.HOLD
    ]


def test_very_long_deferral_is_not_honoured_in_full(g):
    """"Diwali ke baad" said in June resolves correctly to November. Honouring
    it literally would buy five months of silence from one sentence."""
    b = BuyerBeliefs(buyer_id="buy_test")
    b.promises.append(
        Promise(
            buyer_id="buy_test",
            invoice_ids=["inv_test"],
            made_on=TODAY,
            promised_date=TODAY + timedelta(days=150),
            source_quote="diwali ke baad dekhte hain",
            source_message_id="m1",
            confidence=0.8,
            date_was_relative=True,
        )
    )
    d = g.filter(ALL, make_ledger(), b, TODAY)
    assert gate(d.results, "promise_freeze").passed
    assert "beyond the" in gate(d.results, "promise_freeze").reason


def test_ordinary_deferral_is_honoured(g):
    b = BuyerBeliefs(buyer_id="buy_test")
    b.promises.append(
        Promise(
            buyer_id="buy_test",
            invoice_ids=["inv_test"],
            made_on=TODAY,
            promised_date=TODAY + timedelta(days=20),
            source_quote="month end tak",
            source_message_id="m1",
            confidence=0.9,
        )
    )
    d = g.filter(ALL, make_ledger(), b, TODAY)
    assert d.allowed == [Intervention.HOLD]


def test_approval_requirement_does_not_leak_between_actions(g):
    """An irreversible candidate surviving gating must not make every other
    action need sign-off. A routine document chase was being rendered as
    requiring the owner's signature because an MSMED notice was also allowed."""
    b = BuyerBeliefs(buyer_id="buy_test")
    d = g.filter(
        [Intervention.DOCUMENT_RECONCILE, Intervention.MSMED_NOTICE],
        make_ledger(dpd=120),
        b,
        TODAY,
    )
    assert Intervention.MSMED_NOTICE in d.allowed
    assert d.needs_approval(Intervention.MSMED_NOTICE)
    assert not d.needs_approval(Intervention.DOCUMENT_RECONCILE)
    assert not d.needs_approval(Intervention.HOLD)
