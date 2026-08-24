"""Folding replies and payments into beliefs.

Two behaviours here are worth more than the plumbing around them.

**A payment claim is a claim, not a payment.** When a buyer writes "kal hi kar
diya, UTR 401512345678", the agent records an unverified claim and reconciles it
against money that actually arrived. A collections system that believes a typed
reference stops chasing debts that were never paid - and does it politely, which
makes it worse, because nobody notices for months.

**A promise is settled by the ledger, not by the calendar.** The agent marks its
own promises kept or broken from observed payments, and that history feeds both
the guardrail deferral limit and the archetype model.
"""

from __future__ import annotations

from datetime import date, timedelta

from ..domain.enums import ReplyIntent
from ..domain.models import Dispute, ExtractedReply, Promise
from ..domain.money import Paise
from .beliefs import Beliefs, BuyerBeliefs
from .extract import ReplyExtractor
from .view import BuyerLedger, LedgerView

#: Days a payment claim is given to show up in the ledger before it is treated
#: as unsubstantiated. Bank credits are not instant; three working days is
#: generous without being credulous.
CLAIM_GRACE_DAYS = 4


class BeliefUpdater:
    def __init__(self, extractor: ReplyExtractor, *, confidence_floor: float = 0.35) -> None:
        self.extractor = extractor
        #: Below this, an extraction is not acted on - it goes to the human
        #: queue instead. Failing safe here means failing *quiet*: an
        #: uninterpretable reply must never license an escalation.
        self.confidence_floor = confidence_floor

    def update(self, beliefs: Beliefs, view: LedgerView, day: date) -> None:
        for buyer_id, ledger in view.ledgers.items():
            bb = beliefs.get(buyer_id)
            self._read_replies(bb, ledger, day)
            self._settle_promises(bb, ledger, day)
            self._reconcile_claims(bb, ledger, day)

    # -- replies ----------------------------------------------------------

    def _read_replies(self, bb: BuyerBeliefs, ledger: BuyerLedger, day: date) -> None:
        for msg in ledger.received:
            if msg.message_id in bb.processed:
                continue
            bb.processed.add(msg.message_id)

            r = self.extractor.extract(msg, msg.received_at.date())
            bb.note_intent(r.intent)

            if r.abstained or r.confidence < self.confidence_floor:
                bb.needs_human.append(msg.message_id)
                continue

            match r.intent:
                case ReplyIntent.PROMISE_TO_PAY:
                    self._record_promise(bb, ledger, r, msg.message_id, msg.received_at.date())
                case ReplyIntent.DISPUTE:
                    self._record_dispute(bb, ledger, r, msg.received_at.date())
                case ReplyIntent.HARDSHIP:
                    bb.hardship_declared = True
                    bb.hardship_declared_on = msg.received_at.date()
                    # A hardship message often carries a date too; it defers
                    # contact the same way a promise does.
                    if r.promised_date:
                        self._record_promise(bb, ledger, r, msg.message_id, msg.received_at.date())
                case ReplyIntent.PAYMENT_CLAIM:
                    bb.unverified_payment_claims.append(r)
                case ReplyIntent.DOCUMENT_REQUEST:
                    bb.documents_requested.extend(r.requested_documents)
                case ReplyIntent.PROCESS_DEFLECTION:
                    # Not a promise. A described process is not a commitment, and
                    # treating it as one is how an agent talks itself into
                    # silence on a buyer that never intended to pay.
                    pass

    def _record_promise(
        self, bb: BuyerBeliefs, ledger: BuyerLedger, r: ExtractedReply, msg_id: str, on: date
    ) -> None:
        if r.promised_date is None:
            # A commitment with no pinnable date. Recorded for the human queue,
            # not honoured as a stopping rule - otherwise "jaldi karenge" buys
            # indefinite silence.
            bb.needs_human.append(msg_id)
            return
        open_ids = [iv.invoice.invoice_id for iv in ledger.open_invoices]
        bb.promises.append(
            Promise(
                promise_id=f"prm_{msg_id}",
                buyer_id=bb.buyer_id,
                invoice_ids=open_ids,
                made_on=on,
                promised_date=r.promised_date,
                promised_amount=r.promised_amount or Paise(ledger.outstanding),
                source_quote=r.evidence_span or "",
                source_message_id=msg_id,
                confidence=r.confidence,
                date_was_relative=bool(r.promised_date_raw),
            )
        )

    def _record_dispute(
        self, bb: BuyerBeliefs, ledger: BuyerLedger, r: ExtractedReply, on: date
    ) -> None:
        open_ids = [iv.invoice.invoice_id for iv in ledger.open_invoices]
        kind = r.dispute_kind or "missing_docs"
        if any(d.status == "open" and d.kind == kind for d in bb.disputes):
            return
        bb.disputes.append(
            Dispute(
                buyer_id=bb.buyer_id,
                invoice_ids=open_ids[:1] or open_ids,
                raised_on=on,
                kind=kind,  # type: ignore[arg-type]
                disputed_amount=r.disputed_amount,
                source_quote=r.evidence_span or "",
            )
        )

    # -- settlement -------------------------------------------------------

    def _settle_promises(self, bb: BuyerBeliefs, ledger: BuyerLedger, day: date) -> None:
        for p in bb.promises:
            if p.status != "open" or day <= p.promised_date + timedelta(days=3):
                continue
            received = sum(
                pay.amount for pay in ledger.payments if p.made_on <= pay.received_on <= day
            )
            target = p.promised_amount or 1
            if received >= target:
                p.status = "kept"
            elif received > 0:
                p.status = "partially_kept"
            else:
                p.status = "broken"

    def _reconcile_claims(self, bb: BuyerBeliefs, ledger: BuyerLedger, day: date) -> None:
        """Match claimed payments against money that actually arrived.

        Matching is on amount within a window, not on the UTR string: our ledger
        holds the reference the *bank* gave us, and a buyer quoting a number from
        their side is not something we can join on. A claim that never
        materialises is dropped and the buyer is chased again - and the audit
        records that it was a claim, so the follow-up can say so politely.
        """
        if not bb.unverified_payment_claims:
            return
        still_open: list[ExtractedReply] = []
        for claim in bb.unverified_payment_claims:
            claim_day = next(
                (m.received_at.date() for m in ledger.received if m.message_id == claim.message_id),
                None,
            )
            if claim_day is None:
                continue
            window_end = claim_day + timedelta(days=CLAIM_GRACE_DAYS)
            arrived = [
                p for p in ledger.payments if claim_day - timedelta(days=7) <= p.received_on <= window_end
            ]
            if arrived:
                continue  # substantiated; drop the claim
            if day <= window_end:
                still_open.append(claim)  # still within grace
            # else: silently expires as unsubstantiated
        bb.unverified_payment_claims = still_open
