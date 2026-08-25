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
