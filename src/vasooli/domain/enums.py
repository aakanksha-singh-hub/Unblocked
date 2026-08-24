"""The two taxonomies the whole project rests on.

BuyerArchetype is the *cause* of non-payment. It is ground truth inside the
simulator and an inference target for the agent. The project's central claim is
that recovery comes from identifying it, not from chasing harder.

Intervention is the agent's action space. Every entry carries an explicit
relationship cost, because the reason Priya under-collects is not that she
lacks reminders - it is that reminders are not free.
"""

from __future__ import annotations

from enum import StrEnum


class BuyerArchetype(StrEnum):
    """Why this buyer has not paid. Mutually exclusive, jointly near-exhaustive.

    Deliberately behavioural rather than moral: 'AVOIDER' is the only one that
    implies bad faith, and it is the rarest in the generated population, which
    matches what actually shows up in MSME ledgers.
    """

    PROMPT = "prompt"
    """Pays on or near terms. Any chase here is pure annoyance cost."""

    PROCESS_BOUND = "process_bound"
    """A large buyer on a fixed AP cycle - payment run on the 10th, 60-day terms
    regardless of what the invoice says. Nudges do not move the date. What *does*
    move it: making sure the invoice cleared their intake (PO match, GRN, portal
    upload) before the cycle cut-off. Chasing between cycles is the single
    largest source of wasted messages in the population."""

    CASHFLOW_STRESSED = "cashflow_stressed"
    """Wants to pay, is juggling. Responsive to contact, makes promises, keeps
    some of them. This is the archetype where good chasing genuinely creates
    money - and where over-chasing burns the relationship for nothing."""

    DISPUTER = "disputer"
    """Payment is blocked behind an unresolved commercial issue - short delivery,
    damage, rate mismatch, missing credit note. Chasing without resolving the
    dispute cannot work, and reads as not listening. Resolution unblocks the
    whole amount, often immediately."""

    AVOIDER = "avoider"
    """Has the money, deprioritises the small supplier because there is no
    consequence. Responds only to credible escalation. The archetype that
    justifies the legal ladder existing at all."""

    DISTRESSED = "distressed"
    """Genuinely cannot pay the full amount now. A lump-sum demand returns
    nothing; a structured instalment returns most of it slowly. Mis-classifying
    DISTRESSED as AVOIDER is the most expensive error the agent can make, and is
    tracked separately in the evaluation."""


#: Archetypes for which contact frequency has essentially no effect on the pay
#: date. Used by the evaluation to compute 'wasted contact' honestly.
CONTACT_INSENSITIVE: frozenset[BuyerArchetype] = frozenset(
    {BuyerArchetype.PROMPT, BuyerArchetype.PROCESS_BOUND}
)


class Intervention(StrEnum):
    """What the agent may do on any given day, for any given buyer."""

    HOLD = "hold"
    """Deliberately do nothing today. A first-class action, not the absence of
    one: it is logged, it carries a reason, and it is the correct choice for the
    majority of buyer-days in the population."""

    STATEMENT_OF_ACCOUNT = "statement_of_account"
    """Consolidated ledger of what is open. Informational, near-zero relationship
    cost, and the right opener for PROCESS_BOUND buyers whose AP team simply
    never received the invoice."""

    DOCUMENT_RECONCILE = "document_reconcile"
    """Attach/request the paperwork that unblocks intake: PO number, delivery
    challan, e-way bill, GRN, portal acknowledgement. Answers the most common
    deflection in Indian B2B - 'PO not received' / 'not in our system'."""

    SOFT_NUDGE = "soft_nudge"
    """Relationship-safe reminder. Assumes good faith, offers help, does not
    mention terms or consequences."""

    PAYMENT_LINK = "payment_link"
    """Remove friction: a Razorpay payment link for the open amount. Converts
    'I'll ask accounts to process it' into a two-tap action."""

    FIRM_REMINDER = "firm_reminder"
    """Cites agreed terms and days overdue. Still cordial, but on the record.
    First action with a non-trivial relationship cost."""

    DISPUTE_RESOLUTION = "dispute_resolution"
    """Acknowledge the stated issue, request specifics, propose a credit note or
    a pay-the-undisputed-portion split. The only action that moves a DISPUTER."""

    INSTALMENT_OFFER = "instalment_offer"
    """Propose a structured schedule for the open amount. The only action that
    reliably moves DISTRESSED, and it converts a bad debt into a slow one."""

    PHONE_TASK = "phone_task"
    """Hand off to a human for a call, with a prepared brief. The agent knowing
    where it stops being the right instrument is part of the design."""

    OWNER_ESCALATION = "owner_escalation"
    """Owner-to-owner contact. Expensive: it spends relationship capital that
    took years to build, and it cannot be un-spent."""

    MSMED_NOTICE = "msmed_notice"
    """Formal notice citing the MSMED Act 2006 s.15-16 interest liability on
    payment beyond 45 days. Legally grounded, hard-gated, and never sent without
    the eligibility checks in guardrails.py passing."""

    SAMADHAAN_FILING = "samadhaan_filing"
    """Reference of the dispute to the MSEFC via the Samadhaan portal. Terminal.
    Requires explicit human approval every single time - the agent may recommend
    it and may never execute it."""


#: Relationship capital spent by each action, on an arbitrary but internally
#: consistent 0-100 scale. These numbers are the reason the agent cannot simply
#: escalate everyone: the evaluation charges them against recovered rupees.
RELATIONSHIP_COST: dict[Intervention, int] = {
    Intervention.HOLD: 0,
    Intervention.STATEMENT_OF_ACCOUNT: 1,
    Intervention.DOCUMENT_RECONCILE: 1,
    Intervention.SOFT_NUDGE: 2,
    Intervention.PAYMENT_LINK: 2,
    Intervention.DISPUTE_RESOLUTION: 2,
    Intervention.INSTALMENT_OFFER: 4,
    Intervention.FIRM_REMINDER: 8,
    Intervention.PHONE_TASK: 10,
    Intervention.OWNER_ESCALATION: 25,
    Intervention.MSMED_NOTICE: 45,
    Intervention.SAMADHAAN_FILING: 90,
}

#: Minutes of a human's time each action consumes. HOLD is free; PHONE_TASK is
#: not, which is precisely why an agent that recommends forty calls a day has
#: not solved Priya's problem.
HUMAN_MINUTES: dict[Intervention, int] = {
    Intervention.HOLD: 0,
    Intervention.STATEMENT_OF_ACCOUNT: 0,
    Intervention.DOCUMENT_RECONCILE: 0,
    Intervention.SOFT_NUDGE: 0,
    Intervention.PAYMENT_LINK: 0,
    Intervention.FIRM_REMINDER: 0,
    Intervention.DISPUTE_RESOLUTION: 3,
    Intervention.INSTALMENT_OFFER: 5,
    Intervention.PHONE_TASK: 12,
    Intervention.OWNER_ESCALATION: 20,
    Intervention.MSMED_NOTICE: 15,
    Intervention.SAMADHAAN_FILING: 120,
}

#: Actions that put something on the record in a way that cannot be walked back.
#: Every one of these is gated in guardrails.py and requires a human in the loop
#: at or above the configured approval threshold.
IRREVERSIBLE: frozenset[Intervention] = frozenset(
    {Intervention.OWNER_ESCALATION, Intervention.MSMED_NOTICE, Intervention.SAMADHAAN_FILING}
)


class Channel(StrEnum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    SMS = "sms"
    PHONE = "phone"
    POST = "post"
    """Registered post / courier - the channel MSMED notices actually go out on."""


class ReplyIntent(StrEnum):
    """What an inbound buyer message actually means.

    This is the LLM's primary extraction target. The set is derived from the
    reply corpus in sim/replies.py, which is written in the Hinglish these
    messages are genuinely composed in.
    """

    PROMISE_TO_PAY = "promise_to_pay"
    """Commits to a date, explicitly ('15th ko') or implicitly ('month end tak')."""

    PAYMENT_CLAIM = "payment_claim"
    """Asserts a payment already made. Carries a UTR/ref more often than not, and
    must be reconciled against the ledger rather than believed."""

    DISPUTE = "dispute"
    """Withholds against a commercial issue, usually with an amount attached."""

    DOCUMENT_REQUEST = "document_request"
    """Asks for PO / challan / e-invoice / GST detail before processing."""

    PROCESS_DEFLECTION = "process_deflection"
    """'It is in the payment cycle' / 'approval pending with management'. The
    hardest class: sometimes true (PROCESS_BOUND), sometimes a brush-off
    (AVOIDER), and telling them apart is what the history is for."""

    HARDSHIP = "hardship"
    """States inability to pay. The signal that should trigger INSTALMENT_OFFER
    and suppress escalation."""

    REFUSAL = "refusal"
    """Declines to pay without a stated commercial reason."""

    ACKNOWLEDGEMENT = "acknowledgement"
    """'Noted', 'will check'. Contentless; explicitly not a promise."""

    UNCLEAR = "unclear"
    """The extractor is not confident. Routes to a human rather than guessing -
    an abstention, and it is measured as one."""
