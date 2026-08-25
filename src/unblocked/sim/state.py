"""Mutable run state. Separated from dynamics so the state shape can be read
without wading through the hazard arithmetic."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ..domain.enums import Intervention
from ..domain.models import AuditEntry, Dispute, InboundMessage, OutboundMessage, Payment, Promise
from ..domain.money import Paise


@dataclass
class InstalmentPlan:
    """An agreed schedule. Created when a buyer accepts an INSTALMENT_OFFER.

    Its existence changes the physics: a DISTRESSED buyer capped at 30% of
    balance in one go can clear the whole thing across four instalments. This is
    the mechanism by which the right intervention converts a bad debt into a
    slow one, and it is why INSTALMENT_OFFER is not merely a softer nudge.
    """

    plan_id: str
    buyer_id: str
    invoice_ids: list[str]
    instalment_amount: Paise
    due_dates: list[date]
    paid_count: int = 0

    def next_due(self, as_of: date) -> date | None:
        for d in self.due_dates[self.paid_count :]:
            if d >= as_of - timedelta(days=7):
                return d
        return None


@dataclass
class InvoiceRuntime:
    invoice_id: str
    outstanding: Paise
    #: Kept for capacity limits, which are a fraction of the original ask rather
    #: than of whatever happens to be left.
    original: Paise

    #: Intake state, copied from the Invoice at run start and mutable *per run*.
    #: These live here rather than on the Invoice because `World` is shared
    #: across every policy run in a comparison - mutating it would let one
    #: policy's document chase silently fix the book for the next policy, and
    #: the paired comparison would quietly stop being a comparison.
    portal_submitted: bool = True
    has_po: bool = True

    #: Value forgiven via credit note to settle a dispute. Tracked separately
    #: because writing off a disputed amount unblocks the remainder but is not
    #: money recovered, and reporting it inside recovery would let the agent
    #: "collect" by forgiving debt.
    written_off: Paise = 0

    @property
    def is_open(self) -> bool:
        return self.outstanding > 0


@dataclass
class BuyerRuntime:
    buyer_id: str
    contacts: list[tuple[date, Intervention]] = field(default_factory=list)
    promises: list[Promise] = field(default_factory=list)
    disputes: list[Dispute] = field(default_factory=list)
    plan: InstalmentPlan | None = None

    relationship_spent: int = 0
    human_minutes: int = 0
    churned: bool = False
    churned_on: date | None = None

    #: Multiplier on promise reliability, decayed by each broken promise. A
    #: buyer who has broken two promises is materially less likely to keep the
    #: third, which is what stops promise-deferral being an infinite stall.
    trust: float = 1.0

    #: Set once the buyer has told us they cannot pay. The agent is expected to
    #: read this and stop escalating; whether it does is measured.
    hardship_declared: bool = False

    def contacts_within(self, as_of: date, days: int) -> int:
        cutoff = as_of - timedelta(days=days)
        return sum(1 for d, _ in self.contacts if cutoff < d <= as_of)

    def last_contact(self, as_of: date) -> date | None:
        past = [d for d, _ in self.contacts if d <= as_of]
        return max(past) if past else None

    def open_promise(self, as_of: date, grace: int) -> Promise | None:
        active = [p for p in self.promises if p.is_active(as_of, grace)]
        return max(active, key=lambda p: p.made_on) if active else None

    def open_disputes(self) -> list[Dispute]:
        return [d for d in self.disputes if d.status == "open"]


@dataclass
class RunState:
    """Everything that changes as the simulation advances."""

    seed: int
    day: date
    invoices: dict[str, InvoiceRuntime]
    buyers: dict[str, BuyerRuntime]

    payments: list[Payment] = field(default_factory=list)
    outbound: list[OutboundMessage] = field(default_factory=list)
    inbound: list[InboundMessage] = field(default_factory=list)
    audit: list[AuditEntry] = field(default_factory=list)

    #: Disputes settled by writing off the disputed portion, and intake defects
    #: repaired by a document chase. Both are reported in the run summary.
    write_offs: Paise = 0
    intake_repairs: int = 0
    #: Messages that actually changed state, used to judge whether a contact was
    #: wasted by what it did rather than by who received it.
    repair_messages: set[str] = field(default_factory=set)

    #: Outbound indexed by send date, and the set of messages already replied
    #: to. Both are pure indices over `outbound`/`inbound`, kept because
    #: rescanning every message every day made run cost quadratic in horizon.
    outbound_by_day: dict[date, list[OutboundMessage]] = field(default_factory=dict)
    replied_to: set[str] = field(default_factory=set)

    #: Per-buyer indices over the flat event lists, appended on write. build_view
    #: runs once per simulated day, and scanning every payment and every message
    #: on each of those days made view construction the dominant cost of the
    #: whole evaluation.
    #: Invoice ids grouped by buyer, built once at run start. open_invoice_ids
    #: previously scanned every invoice in the book for every buyer on every
    #: simulated day - 472 million comparisons on a full run, and by far the
    #: dominant cost of the entire evaluation.
    invoices_by_buyer: dict[str, list[str]] = field(default_factory=dict)

    payments_by_buyer: dict[str, list[Payment]] = field(default_factory=dict)
    outbound_by_buyer: dict[str, list[OutboundMessage]] = field(default_factory=dict)
    inbound_by_buyer: dict[str, list[InboundMessage]] = field(default_factory=dict)

    #: Invoices not yet issued at the current day. Released by dynamics as the
    #: calendar reaches them, so the agent never sees future work.
    pending_issue: dict[str, date] = field(default_factory=dict)

    #: Simulator-side promise outcomes, rolled at creation and hidden from the
    #: agent. Held here rather than on Promise so the agent cannot read it even
    #: by accident.
    promise_will_keep: dict[str, bool] = field(default_factory=dict)

    def open_invoice_ids(self, buyer_id: str, world) -> list[str]:
        pending = self.pending_issue
        return [
            iid
            for iid in self.invoices_by_buyer.get(buyer_id, ())
            if self.invoices[iid].is_open and iid not in pending
        ]

    def total_outstanding(self) -> Paise:
        return sum(rt.outstanding for rt in self.invoices.values())

    def total_collected(self) -> Paise:
        return sum(p.amount for p in self.payments)
