"""What the agent is allowed to see.

The counterpart to the Buyer/BuyerTruth split in the domain model. `World`
contains ground truth, so no policy ever receives one; it receives a `LedgerView`
assembled for a specific day, containing only what a real merchant's system
would actually hold: issued invoices, received payments, messages sent, replies
received.

Two things are deliberately absent and must be *earned* by the agent:

- **Promises and disputes.** These exist in the simulator as consequences of
  buyer replies, but the agent only learns of them by reading the reply text.
  Handing them over as structured fields would make the extraction layer
  decorative and would let the stopping rules look far better than they are.
- **Anything about the future.** Invoices dated after `as_of` are filtered out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ..domain.models import Buyer, InboundMessage, Invoice, OutboundMessage, Payment
from ..domain.money import Paise


@dataclass(frozen=True)
class InvoiceView:
    invoice: Invoice
    outstanding: Paise
    paid: Paise

    def days_past_due(self, as_of: date) -> int:
        return self.invoice.days_past_due(as_of)


@dataclass
class BuyerLedger:
    """One buyer's position, as visible from the merchant's own records."""

    buyer: Buyer
    invoices: list[InvoiceView] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    sent: list[OutboundMessage] = field(default_factory=list)
    received: list[InboundMessage] = field(default_factory=list)

    @property
    def outstanding(self) -> Paise:
        return Paise(sum(iv.outstanding for iv in self.invoices))

    @property
    def open_invoices(self) -> list[InvoiceView]:
        return [iv for iv in self.invoices if iv.outstanding > 0]

    def oldest_dpd(self, as_of: date) -> int:
        open_ = self.open_invoices
        return max((iv.days_past_due(as_of) for iv in open_), default=-999)

    def overdue_amount(self, as_of: date) -> Paise:
        return Paise(sum(iv.outstanding for iv in self.open_invoices if iv.days_past_due(as_of) > 0))

    def contacts_within(self, as_of: date, days: int) -> int:
        cutoff = as_of - timedelta(days=days)
        return sum(1 for m in self.sent if cutoff < m.sent_at.date() <= as_of)

    def last_contact(self, as_of: date) -> date | None:
        past = [m.sent_at.date() for m in self.sent if m.sent_at.date() <= as_of]
        return max(past) if past else None

    def unread_replies(self, since: date | None = None) -> list[InboundMessage]:
        if since is None:
            return list(self.received)
        return [m for m in self.received if m.received_at.date() >= since]

    def payment_history_days(self) -> list[int]:
        """Days from due date to payment, for every settled invoice.

        The primary behavioural feature: a buyer that consistently pays on day
        62 regardless of 30-day terms is telling you what it is, and this is the
        signal that says so.
        """
        out: list[int] = []
        by_inv = {iv.invoice.invoice_id: iv.invoice for iv in self.invoices}
        for p in self.payments:
            inv = by_inv.get(p.invoice_id)
            if inv is not None:
                out.append((p.received_on - inv.due_date).days)
        return out


@dataclass
class LedgerView:
    """The whole book as of a given day. No ground truth reachable from here."""

    as_of: date
    ledgers: dict[str, BuyerLedger]

    def buyers_with_open(self) -> list[BuyerLedger]:
        return [lg for lg in self.ledgers.values() if lg.outstanding > 0]

    @property
    def total_outstanding(self) -> Paise:
        return Paise(sum(lg.outstanding for lg in self.ledgers.values()))


def build_view(world, st, day: date, *, buyer_ids: list[str] | None = None) -> LedgerView:
    """Assemble the agent-visible view. The only place world and state are read
    together for agent consumption, and it copies rather than aliasing so a
    policy cannot mutate the simulation by accident."""
    ids = buyer_ids if buyer_ids is not None else list(world.buyers)
    ledgers: dict[str, BuyerLedger] = {}

    paid_by_inv: dict[str, Paise] = {}
    for p in st.payments:
        if p.received_on <= day:
            paid_by_inv[p.invoice_id] = Paise(paid_by_inv.get(p.invoice_id, 0) + p.amount)

    for bid in ids:
        lg = BuyerLedger(buyer=world.buyers[bid])
        for iid, inv in world.invoices.items():
            if inv.buyer_id != bid or inv.issue_date > day:
                continue
            rt = st.invoices[iid]
            lg.invoices.append(
                InvoiceView(invoice=inv, outstanding=rt.outstanding, paid=paid_by_inv.get(iid, Paise(0)))
            )
        lg.payments = [p for p in st.payments if p.buyer_id == bid and p.received_on <= day]
        lg.sent = [m for m in st.outbound if m.buyer_id == bid and m.sent_at.date() <= day]
        lg.received = [m for m in st.inbound if m.buyer_id == bid and m.received_at.date() <= day]
        ledgers[bid] = lg

    return LedgerView(as_of=day, ledgers=ledgers)
