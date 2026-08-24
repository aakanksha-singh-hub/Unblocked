"""Entities.

One structural decision worth stating up front: the agent's view of a buyer and
the simulator's ground truth about that buyer are *different types*. `Buyer`
carries no archetype field, so no amount of carelessness in policy code can read
the label - it is not reachable from the object the agent is handed. The
simulator holds `BuyerTruth` separately and the evaluation harness is the only
component that ever joins the two.

This costs a little ceremony and buys the single most important property in the
project: when the report says the archetype classifier scored 0.81 macro-F1,
that number is not contaminated.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import BuyerArchetype, Channel, Intervention, ReplyIntent
from .money import Paise


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Frozen(BaseModel):
    """Base for immutable records. Facts about the past do not get edited."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Mutable(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Counterparties
# ---------------------------------------------------------------------------


class Buyer(Mutable):
    """A buyer, exactly as the agent sees them. Note the absence of an archetype."""

    buyer_id: str = Field(default_factory=lambda: _id("buy"))
    legal_name: str
    trade_name: str | None = None
    gstin: str | None = None
    city: str
    state: str

    #: Share of the merchant's trailing-12m revenue, 0-1. The number behind
    #: 'I cannot afford to lose this account.' Drives the relationship budget.
    revenue_share: float = Field(ge=0.0, le=1.0)

    #: Contract terms as written on the PO, in days. The MSMED 45-day clock runs
    #: from acceptance regardless of what this says, which is the whole point of
    #: the statutory ladder.
    agreed_terms_days: int = Field(ge=0, le=180)

    #: Relationship tenure in months. Long tenure raises the cost of a misstep
    #: and lowers the prior on bad faith.
    tenure_months: int = Field(ge=0)

    ap_contact_name: str | None = None
    ap_contact_email: str | None = None
    ap_contact_phone: str | None = None
    owner_contact_name: str | None = None

    #: Channels this buyer has actually responded on before. Sending on a dead
    #: channel is a wasted contact that still costs relationship capital.
    reachable_channels: list[Channel] = Field(default_factory=lambda: [Channel.EMAIL])

    #: True where the buyer runs a supplier portal that invoices must be uploaded
    #: to before AP will look at them - endemic among large Indian buyers and a
    #: common silent cause of 'non-payment' that is really non-submission.
    uses_ap_portal: bool = False

    #: Whether the merchant is a registered Micro/Small enterprise vis-a-vis this
    #: buyer. Gates the entire MSMED ladder: without Udyam registration at the
    #: time of supply, s.15 interest and Samadhaan are simply not available.
    msmed_eligible: bool = True


class BuyerTruth(Frozen):
    """Simulator-only ground truth. Never handed to the agent.

    Held in `sim.world.World.truth`, keyed by buyer_id, and joined against agent
    output exclusively inside `eval/`.
    """

    buyer_id: str
    archetype: BuyerArchetype

    #: Day of month the buyer's AP runs its payment batch, for PROCESS_BOUND.
    #: None where the buyer has no fixed cycle.
    ap_cycle_day: int | None = None

    #: Effective terms the buyer actually pays on, which is frequently not the
    #: agreed terms. The gap between `Buyer.agreed_terms_days` and this is the
    #: quiet margin leak the aging report never explains.
    effective_terms_days: int

    #: Probability this buyer honours a promise it makes, 0-1.
    promise_reliability: float = Field(ge=0.0, le=1.0)

    #: Multiplier on baseline pay-hazard when contacted appropriately. Near 1.0
    #: for CONTACT_INSENSITIVE archetypes - which is what makes chasing them
    #: measurably wasteful rather than merely inelegant.
    contact_responsiveness: float = Field(ge=0.0)

    #: Ceiling on what this buyer can pay in one go, as a fraction of open
    #: balance. < 1.0 only for DISTRESSED.
    lump_sum_capacity: float = Field(default=1.0, ge=0.0, le=1.0)

    #: Relationship capital available before the account is at risk of being
    #: lost. Drawn down by RELATIONSHIP_COST; breaching it is a churn event.
    relationship_budget: int = Field(default=100, ge=0)


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


class Invoice(Mutable):
    invoice_id: str = Field(default_factory=lambda: _id("inv"))
    invoice_number: str
    buyer_id: str

    amount: Paise
    """Gross invoice value including GST."""

    issue_date: date
    due_date: date

    po_number: str | None = None
    delivery_challan_no: str | None = None
    eway_bill_no: str | None = None

    #: Date the buyer acknowledged receipt of goods/services. The MSMED 45-day
    #: clock runs from here, not from the invoice date - a distinction that
    #: decides whether a notice is enforceable or merely rude.
    acceptance_date: date | None = None

    #: Whether the invoice was successfully uploaded to the buyer's AP portal.
    #: False on a portal buyer is the single highest-yield thing to fix, and the
    #: agent is expected to find it before it sends anything at all.
    portal_submitted: bool = True

    @model_validator(mode="after")
    def _dates_coherent(self) -> Invoice:
        if self.due_date < self.issue_date:
            raise ValueError(f"{self.invoice_number}: due_date precedes issue_date")
        if self.acceptance_date and self.acceptance_date < self.issue_date:
            raise ValueError(f"{self.invoice_number}: acceptance precedes issue")
        return self

    def days_past_due(self, as_of: date) -> int:
        """Negative before the due date. Callers care about the sign."""
        return (as_of - self.due_date).days

    def msmed_clock_start(self) -> date:
        """Acceptance where recorded, else issue date - the conservative reading."""
        return self.acceptance_date or self.issue_date


class Payment(Frozen):
    payment_id: str = Field(default_factory=lambda: _id("pay"))
    invoice_id: str
    buyer_id: str
    amount: Paise
    received_on: date

    #: Bank reference. Present on real transfers, and the thing a PAYMENT_CLAIM
    #: reply has to be reconciled against before it is believed.
    utr: str | None = None

    method: Literal["neft", "rtgs", "imps", "upi", "cheque", "razorpay_link"] = "neft"

    #: Set when the payment arrived through a Razorpay payment link the agent
    #: issued, which is how recovery gets attested by something other than our
    #: own bookkeeping.
    razorpay_payment_id: str | None = None


class Promise(Mutable):
    """A commitment to pay, extracted from an inbound reply.

    The reason this is a first-class entity rather than a note: an open promise
    is the strongest stopping signal in the system. The agent goes quiet until
    the promised date plus a grace period, and the evaluation reports how often
    it respected that.
    """

    promise_id: str = Field(default_factory=lambda: _id("prm"))
    buyer_id: str
    invoice_ids: list[str]

    made_on: date
    promised_date: date
    promised_amount: Paise | None = None
    """None where the buyer committed to a date but not a figure."""

    #: Verbatim text the promise was extracted from. Every promise must be
    #: traceable to something the buyer actually said - no inferred promises.
    source_quote: str
    source_message_id: str

    #: Extractor confidence, 0-1. Low-confidence promises still suppress contact
    #: (failing safe means failing quiet) but are flagged for human review.
    confidence: float = Field(ge=0.0, le=1.0)

    #: True where the buyer gave a fuzzy date ('month end', 'next week') that the
    #: resolver had to pin to a calendar date. Tracked because resolution error
    #: is a real source of premature follow-up.
    date_was_relative: bool = False

    status: Literal["open", "kept", "partially_kept", "broken", "superseded"] = "open"

    def is_active(self, as_of: date, grace_days: int) -> bool:
        return self.status == "open" and as_of <= _add_days(self.promised_date, grace_days)


class Dispute(Mutable):
    dispute_id: str = Field(default_factory=lambda: _id("dsp"))
    buyer_id: str
    invoice_ids: list[str]
    raised_on: date

    kind: Literal[
        "short_delivery", "damage", "rate_mismatch", "quality", "gst_mismatch", "missing_docs"
    ]

    disputed_amount: Paise | None = None
    """The portion withheld. Where this is less than the invoice, the undisputed
    remainder is immediately collectable - and asking for it is the single most
    underused move in B2B collections."""

    source_quote: str
    status: Literal["open", "resolved", "rejected", "credit_note_issued"] = "open"
    resolved_on: date | None = None


# ---------------------------------------------------------------------------
# Communication
# ---------------------------------------------------------------------------


class OutboundMessage(Frozen):
    message_id: str = Field(default_factory=lambda: _id("out"))
    buyer_id: str
    invoice_ids: list[str]
    intervention: Intervention
    channel: Channel
    sent_at: datetime
    subject: str | None = None
    body: str

    #: Set for PAYMENT_LINK. The short URL the buyer taps.
    payment_link_url: str | None = None
    razorpay_link_id: str | None = None

    #: Which decision produced this. Joins a message back to its full reasoning
    #: chain in the audit log.
    decision_id: str


class InboundMessage(Frozen):
    message_id: str = Field(default_factory=lambda: _id("in"))
    buyer_id: str
    channel: Channel
    received_at: datetime
    body: str
    in_reply_to: str | None = None


class ExtractedReply(Frozen):
    """Structured reading of an InboundMessage. The LLM's actual output contract."""

    message_id: str
    intent: ReplyIntent
    confidence: float = Field(ge=0.0, le=1.0)

    promised_date_raw: str | None = None
    """The date expression exactly as written - 'month end tak', '15 taarikh'."""
    promised_date: date | None = None
    promised_amount: Paise | None = None

    dispute_kind: str | None = None
    disputed_amount: Paise | None = None

    claimed_utr: str | None = None
    claimed_amount: Paise | None = None

    requested_documents: list[str] = Field(default_factory=list)

    #: Free-text justification quoting the source. Shown to the human on review;
    #: an extraction that cannot point at a span is not trusted.
    evidence_span: str | None = None

    #: True when the extractor declined to commit. Abstention is a valid, and
    #: separately measured, outcome.
    abstained: bool = False


# ---------------------------------------------------------------------------
# Decisions and audit
# ---------------------------------------------------------------------------


class GateResult(Frozen):
    """One guardrail's verdict on one candidate action."""

    gate: str
    passed: bool
    reason: str


class Decision(Frozen):
    """A single buyer-day decision, with everything needed to defend it later.

    The audit trail is not a log of what was sent. It is a log of what was
    considered, what was blocked, by which rule, and why the survivor won.
    """

    decision_id: str = Field(default_factory=lambda: _id("dec"))
    buyer_id: str
    as_of: date

    chosen: Intervention
    rationale: str

    #: Actions the policy proposed, best-first, before gating.
    considered: list[Intervention] = Field(default_factory=list)

    #: Every gate that fired, on every candidate. This is what turns 'the agent
    #: chose not to send' from an anecdote into evidence.
    gates: list[GateResult] = Field(default_factory=list)

    #: The agent's current belief about the buyer, and how sure it is. Compared
    #: against BuyerTruth in evaluation, never before.
    inferred_archetype: BuyerArchetype | None = None
    archetype_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    #: Set where the action requires sign-off before execution.
    requires_human_approval: bool = False

    #: Which component produced the choice: deterministic policy, LLM, or a
    #: human override. Lets the report state exactly how much of the recovered
    #: money is attributable to the model.
    decided_by: Literal["policy", "llm", "human", "guardrail"] = "policy"


class AuditEntry(Frozen):
    """Append-only. Written by every state transition in the system."""

    entry_id: str = Field(default_factory=lambda: _id("aud"))
    at: datetime
    buyer_id: str | None = None
    kind: str
    summary: str
    payload: dict = Field(default_factory=dict)
    decision_id: str | None = None


def _add_days(d: date, n: int) -> date:
    from datetime import timedelta

    return d + timedelta(days=n)


PaiseField = Annotated[int, Field(ge=0)]
