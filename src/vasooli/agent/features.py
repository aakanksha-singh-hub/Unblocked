"""Behavioural features for archetype inference.

Everything here is computable from what a merchant's own system holds: its
invoices, the payments it received, the messages it sent, and the replies it got
back. Nothing reads simulator state.

A note on one feature that deserves suspicion. `uses_ap_portal` is a strong
predictor of PROCESS_BOUND, and it is strong partly because the generator draws
them together. It is also genuinely true of the world - large buyers run supplier
portals and large buyers pay on fixed cycles - but a reader should know that its
importance in the fitted model is inflated by our own construction. Feature
importances are printed in the training report for exactly this reason, and
`--drop-structural` refits without it so the behavioural signal can be read on
its own.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date

from ..domain.enums import ReplyIntent
from .beliefs import BuyerBeliefs
from .view import BuyerLedger

FEATURE_NAMES: list[str] = [
    # --- settled-payment behaviour: the primary signal ---
    "n_settled",
    "mean_days_late",
    "std_days_late",
    "max_days_late",
    "frac_on_time",
    "payment_dom_concentration",
    "partial_payment_rate",
    # --- current position ---
    "oldest_dpd",
    "log_outstanding",
    "n_open_invoices",
    "frac_overdue_value",
    # --- engagement ---
    "reply_rate",
    "n_contacts",
    # --- what they say ---
    "n_promises",
    "promise_keep_rate",
    "n_disputes",
    "hardship_flag",
    "n_process_deflections",
    "n_document_requests",
    "n_payment_claims",
    "n_acknowledgements",
    # --- structural ---
    "uses_ap_portal",
    "agreed_terms_days",
    "log_tenure_months",
    "revenue_share",
    "frac_portal_blocked",
    "frac_missing_po",
]


@dataclass(frozen=True)
class FeatureVector:
    values: list[float]

    def as_dict(self) -> dict[str, float]:
        return dict(zip(FEATURE_NAMES, self.values))


def _dom_concentration(days_of_month: list[int]) -> float:
    """Largest share of payments falling on a single day of the month.

    The cleanest tell for a fixed AP cycle: a buyer paying on the 10th every
    month scores near 1.0 however late those payments look against terms. It is
    the feature that separates 'slow by policy' from 'slow by neglect', which is
    the distinction the whole project turns on.
    """
    if not days_of_month:
        return 0.0
    # Adjacent days count together; an AP run does not always clear on the dot.
    buckets: dict[int, int] = {}
    for d in days_of_month:
        buckets[d // 3] = buckets.get(d // 3, 0) + 1
    return max(buckets.values()) / len(days_of_month)


def extract(ledger: BuyerLedger, beliefs: BuyerBeliefs, as_of: date) -> FeatureVector:
    lateness = ledger.payment_history_days()
    n_settled = len(lateness)

    mean_late = statistics.fmean(lateness) if lateness else 0.0
    std_late = statistics.pstdev(lateness) if n_settled > 1 else 0.0
    max_late = float(max(lateness)) if lateness else 0.0
    frac_on_time = (sum(1 for x in lateness if x <= 3) / n_settled) if n_settled else 0.0

    dom = _dom_concentration([p.received_on.day for p in ledger.payments])

    # A partial payment is a payment smaller than the invoice it settles.
    by_inv = {iv.invoice.invoice_id: iv.invoice.amount for iv in ledger.invoices}
    partials = sum(1 for p in ledger.payments if p.amount < by_inv.get(p.invoice_id, p.amount))
    partial_rate = partials / len(ledger.payments) if ledger.payments else 0.0

    outstanding = ledger.outstanding
    overdue = ledger.overdue_amount(as_of)
    n_sent = len(ledger.sent)
    reply_rate = (len(ledger.received) / n_sent) if n_sent else 0.0

    intents = [r.intent for r in beliefs.unverified_payment_claims]
    kept = sum(1 for p in beliefs.promises if p.status in ("kept", "partially_kept"))
    settled_promises = sum(1 for p in beliefs.promises if p.status != "open")

    open_invs = ledger.open_invoices
    portal_blocked = sum(1 for iv in open_invs if not iv.portal_submitted)
    missing_po = sum(1 for iv in open_invs if not iv.has_po)
    n_open = len(open_invs)

    return FeatureVector(
        [
            float(n_settled),
            mean_late,
            std_late,
            max_late,
            frac_on_time,
            dom,
            partial_rate,
            float(ledger.oldest_dpd(as_of)),
            math.log1p(outstanding / 100.0),
            float(n_open),
            (overdue / outstanding) if outstanding else 0.0,
            reply_rate,
            float(n_sent),
            float(len(beliefs.promises)),
            (kept / settled_promises) if settled_promises else 0.0,
            float(len(beliefs.disputes)),
            1.0 if beliefs.hardship_declared else 0.0,
            float(beliefs.intent_counts.get(ReplyIntent.PROCESS_DEFLECTION, 0)),
            float(beliefs.intent_counts.get(ReplyIntent.DOCUMENT_REQUEST, 0)),
            float(beliefs.intent_counts.get(ReplyIntent.PAYMENT_CLAIM, 0)),
            float(beliefs.intent_counts.get(ReplyIntent.ACKNOWLEDGEMENT, 0)),
            1.0 if ledger.buyer.uses_ap_portal else 0.0,
            float(ledger.buyer.agreed_terms_days),
            math.log1p(ledger.buyer.tenure_months),
            ledger.buyer.revenue_share,
            (portal_blocked / n_open) if n_open else 0.0,
            (missing_po / n_open) if n_open else 0.0,
        ]
    )


#: Features that encode how the buyer is *built* rather than how it *behaves*.
#: Refitting without these is how the behavioural signal gets read on its own.
STRUCTURAL: frozenset[str] = frozenset(
    {"uses_ap_portal", "agreed_terms_days", "log_tenure_months", "revenue_share"}
)
