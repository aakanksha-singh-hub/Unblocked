"""Plain English for everything the interface shows.

The code needs stable identifiers - `process_bound`, `soft_nudge` - and a person
reading a screen needs a sentence. An earlier version of the dashboard showed the
identifiers directly and was, correctly, described as unreadable: nobody should
have to learn a taxonomy to find out why an invoice is unpaid.

The rule here is that every label answers a question a person would actually ask.
Not "what class is this buyer" but "why haven't they paid".
"""

from __future__ import annotations

from .enums import BuyerArchetype, Intervention

#: Why this buyer hasn't paid, in the words a person would use.
CAUSE: dict[BuyerArchetype, str] = {
    BuyerArchetype.PROMPT: "Pays on time",
    BuyerArchetype.PROCESS_BOUND: "Pays on a fixed monthly cycle",
    BuyerArchetype.CASHFLOW_STRESSED: "Short of cash right now",
    BuyerArchetype.DISPUTER: "Unhappy with the goods",
    BuyerArchetype.AVOIDER: "Ignoring you",
    BuyerArchetype.DISTRESSED: "Can't pay it in one go",
}

#: One line on what that means for the money.
CAUSE_MEANS: dict[BuyerArchetype, str] = {
    BuyerArchetype.PROMPT: "They were always going to pay. Any reminder is pure cost.",
    BuyerArchetype.PROCESS_BOUND: "Their accounts team runs payments once a month. "
                                  "Asking again does not move the date.",
    BuyerArchetype.CASHFLOW_STRESSED: "They intend to pay and keep juggling. "
                                      "This is where good chasing genuinely earns money.",
    BuyerArchetype.DISPUTER: "Something is wrong with the delivery or the bill. "
                             "Until that is settled, no amount of asking works.",
    BuyerArchetype.AVOIDER: "They have the money and no reason to hurry. "
                            "The only one where pressure is the right answer.",
    BuyerArchetype.DISTRESSED: "A lump-sum demand returns nothing. "
                               "A payment plan returns most of it, slowly.",
}

#: What the agent actually does, said as an action.
ACTION: dict[Intervention, str] = {
    Intervention.HOLD: "Do nothing today",
    Intervention.STATEMENT_OF_ACCOUNT: "Send a statement of what's open",
    Intervention.DOCUMENT_RECONCILE: "Chase the missing paperwork",
    Intervention.SOFT_NUDGE: "Send a gentle reminder",
    Intervention.PAYMENT_LINK: "Send a payment link",
    Intervention.FIRM_REMINDER: "Send a firm reminder citing terms",
    Intervention.DISPUTE_RESOLUTION: "Settle the dispute",
    Intervention.INSTALMENT_OFFER: "Offer to split it into instalments",
    Intervention.PHONE_TASK: "Hand it to a human to call",
    Intervention.OWNER_ESCALATION: "Owner calls their owner",
    Intervention.MSMED_NOTICE: "Formal notice under the MSMED Act",
    Intervention.SAMADHAAN_FILING: "Refer to the government dispute panel",
}

#: What each guardrail is protecting against, in one line.
GATE: dict[str, str] = {
    "promise_freeze": "They promised a date — stay quiet until then",
    "dispute_freeze": "They raised a complaint — settle it before asking again",
    "hardship_shield": "They said they can't pay — don't apply pressure",
    "contact_spacing": "Too soon after the last message",
    "frequency_cap": "Already contacted enough this month",
    "quiet_day": "Sunday or a public holiday",
    "not_yet_due": "Not actually overdue yet",
    "de_minimis": "Too small to be worth the goodwill",
    "msmed_clock": "The legal 45-day clock hasn't run yet",
    "msmed_eligibility": "Not registered, so the legal route doesn't apply",
    "concentration_guard": "This account is too big to risk without a human",
    "human_approval": "Needs a person to sign off",
    "reachable": "No working contact for this buyer",
    "no_positive_value": "Nothing worth doing today",
    "routine": "Routine spacing rules",
}


def cause(a: BuyerArchetype | str | None) -> str:
    if a is None:
        return "Not enough history yet"
    try:
        return CAUSE[BuyerArchetype(a)]
    except ValueError:
        return str(a).replace("_", " ")


def cause_means(a: BuyerArchetype | str | None) -> str:
    if a is None:
        return "Too few invoices settled to tell what kind of payer this is."
    try:
        return CAUSE_MEANS[BuyerArchetype(a)]
    except ValueError:
        return ""


def action(i: Intervention | str) -> str:
    try:
        return ACTION[Intervention(i)]
    except ValueError:
        return str(i).replace("_", " ")


def gate(name: str) -> str:
    return GATE.get(name, name.replace("_", " "))


def days_late(n: int) -> str:
    """Render days-past-due for a person.

    A negative number here means the invoice is not due yet, and printing
    "-11 days late" asks the reader to do the arithmetic and the inference.
    """
    if n < 0:
        return f"not due for {abs(n)}d"
    if n == 0:
        return "due today"
    return f"{n}d"


def humanise(rationale: str) -> str:
    """Turn a decision rationale into something a reader can take at face value.

    The rationale is written for the audit trail and opens with the action
    identifier - "owner_escalation: avoider at 45% (margin 12%)". On a page that
    otherwise speaks plain English, that reads as a different system talking.
    """
    import re

    text = rationale
    for key, label in ACTION.items():
        text = re.sub(rf"^{re.escape(key.value)}: ", "", text)
        text = text.replace(key.value, label.lower())
    for key, label in CAUSE.items():
        text = text.replace(key.value, label.lower())
    return text[:1].upper() + text[1:] if text else text


#: What each swept assumption means, in the words a person would use. The sweep
#: identifies parameters by their code name; nobody reading a page should have to
#: decode PORTAL_REPAIR_SUCCESS to find out what was tested.
PARAMETER: dict[str, str] = {
    "PORTAL_REPAIR_SUCCESS": "How often chasing paperwork actually unblocks an invoice",
    "PO_REPAIR_SUCCESS": "How often a missing PO number can be recovered",
    "DISPUTE_RESOLUTION_SUCCESS": "How often one conversation settles a complaint",
    "DISPUTE_CREDIT_NOTE_SHARE": "How often settling a complaint means writing part of it off",
    "FATIGUE_PER_EXCESS_CONTACT": "How much each extra message tires a buyer out",
    "ARCHETYPE_MIX.process_bound": "How many buyers pay on a fixed monthly cycle",
    "ARCHETYPE_MIX.cashflow_stressed": "How many buyers are short of cash",
    "ARCHETYPE_MIX.disputer": "How many buyers are unhappy with the goods",
    "ARCHETYPE_MIX.avoider": "How many buyers are simply ignoring you",
    "ARCHETYPE_MIX.distressed": "How many buyers cannot pay in one go",
    "ARCHETYPE_MIX.prompt": "How many buyers pay on time",
    "contact retention": "How much each extra message tires a buyer out",
}

#: What a buyer is complaining about.
DISPUTE: dict[str, str] = {
    "short_delivery": "short delivery",
    "damage": "damaged goods",
    "rate_mismatch": "the rate not matching the order",
    "quality": "quality",
    "gst_mismatch": "a wrong GST number on the bill",
    "missing_docs": "missing paperwork",
}


def parameter(name: str) -> str:
    return PARAMETER.get(name, name.replace("_", " ").replace(".", " — ").lower())


def dispute(kind: str) -> str:
    return DISPUTE.get(kind, kind.replace("_", " "))


#: Policies, as a reader would describe them rather than as the code names them.
POLICY: dict[str, str] = {
    "never-chase": "doing nothing",
    "blast-weekly": "chasing everyone weekly",
    "static-ladder": "a 30/60/90 ladder",
    "cause-matched": "working out the cause",
}


def policy(name: str) -> str:
    return POLICY.get(name, name.replace("-", " "))
