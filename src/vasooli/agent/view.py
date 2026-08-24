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

    #: Current intake state, from run state rather than from the original
    #: Invoice. The merchant genuinely knows whether it uploaded an invoice to
    #: the buyer's portal, so this is legitimately visible - but it must reflect
    #: repairs, or the agent would keep chasing paperwork it already fixed.
    portal_submitted: bool = True
    has_po: bool = True

    @property
    def blocked_at_intake(self) -> bool:
        """Not overdue by choice: nobody at the buyer can see this invoice."""
        return not self.portal_submitted or not self.has_po

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

    def intake_blocked(self) -> list[InvoiceView]:
        """Open invoices the buyer's system cannot act on. Indistinguishable
        from ordinary overdue on an aging report, and the highest-yield thing
        the agent can find."""
        return [iv for iv in self.open_invoices if iv.blocked_at_intake]

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


def _buyer_index(world) -> dict[str, list[str]]:
    """Invoice ids grouped by buyer, cached on the World.

    Rebuilding this per call made build_view O(buyers x invoices) - 2.6M
    comparisons on the full book - and the runner calls it once per simulated
    day. It was the dominant cost of the whole evaluation.
    """
    idx = getattr(world, "_invoice_index", None)
    if idx is None:
        idx = {}
        for iid, inv in world.invoices.items():
            idx.setdefault(inv.buyer_id, []).append(iid)
        object.__setattr__(world, "_invoice_index", idx)
    return idx


def build_view(world, st, day: date, *, buyer_ids: list[str] | None = None) -> LedgerView:
    """Assemble the agent-visible view. The only place world and state are read
    together for agent consumption, and it copies rather than aliasing so a
    policy cannot mutate the simulation by accident."""
    ids = buyer_ids if buyer_ids is not None else list(world.buyers)
    wanted = set(ids)
    ledgers: dict[str, BuyerLedger] = {bid: BuyerLedger(buyer=world.buyers[bid]) for bid in ids}

    paid_by_inv: dict[str, Paise] = {}
    index = _buyer_index(world)
    for bid in ids:
        lg = ledgers[bid]
        for p in st.payments_by_buyer.get(bid, ()):
            if p.received_on <= day:
                paid_by_inv[p.invoice_id] = Paise(paid_by_inv.get(p.invoice_id, 0) + p.amount)
                lg.payments.append(p)
        for iid in index.get(bid, ()):
            inv = world.invoices[iid]
            if inv.issue_date > day:
                continue
            rt = st.invoices[iid]
            lg.invoices.append(
                InvoiceView(
                    invoice=inv,
                    outstanding=rt.outstanding,
                    paid=paid_by_inv.get(iid, Paise(0)),
                    portal_submitted=rt.portal_submitted,
                    has_po=rt.has_po,
                )
            )

    for bid in ids:
        lg = ledgers[bid]
        lg.sent = [m for m in st.outbound_by_buyer.get(bid, ()) if m.sent_at.date() <= day]
        lg.received = [m for m in st.inbound_by_buyer.get(bid, ()) if m.received_at.date() <= day]

    return LedgerView(as_of=day, ledgers=ledgers)
