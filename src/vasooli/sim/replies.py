"""Templated buyer replies, used to drive the simulation loop.

READ THIS BEFORE USING THESE FOR ANYTHING ELSE
----------------------------------------------
These strings are assembled from templates in this file. They exist so the
closed loop runs: a contact goes out, something comes back, state changes.

They must never be used to evaluate the reply-understanding model.

Scoring our extractor on text our own templates produced would measure whether
the extractor can invert this file - a number that would look excellent and mean
nothing. The extraction evaluation runs on the externally elicited corpus
described in docs/EXTRACTION_PROTOCOL.md, written by people who have never seen
our intent taxonomy and labelled by annotators who are not the author. That is
the only reply data in this project that carries evidential weight.

`eval/harness.py` enforces the separation: the extraction scorer refuses to run
against simulator-generated text, and `tests/test_no_template_leak.py` asserts
that no string in this module appears in the labelled corpus.

The templates below are nonetheless written in the register these messages
actually arrive in - code-switched Hinglish, minimal punctuation, WhatsApp
grammar - because a loop driven by tidy formal English would train our own
intuitions on the wrong thing.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from ..domain.enums import BuyerArchetype, Intervention, ReplyIntent
from ..domain.models import Dispute, InboundMessage, OutboundMessage, Promise
from ..domain.money import Paise
from . import rng
from .state import RunState
from .world import World

# ---------------------------------------------------------------------------
# Templates. {q} is a fuzzy date expression, {amt} a rupee figure.
# ---------------------------------------------------------------------------

TEMPLATES: dict[ReplyIntent, list[str]] = {
    ReplyIntent.PROMISE_TO_PAY: [
        "sir {q} tak payment ho jayega, thoda adjust kar lijiye",
        "{q} ko release kar denge, accounts ko bol diya hai",
        "payment {q} me process hoga, confirm",
        "dekhiye {q} tak clear kar dunga, abhi thoda tight hai",
        "ok noted. {q} tak transfer karwa deta hoon",
    ],
    ReplyIntent.PAYMENT_CLAIM: [
        "payment kal hi kar diya tha, UTR {utr} check karlo",
        "{amt} transfer ho chuka hai, ref {utr}",
        "already paid sir, NEFT ref {utr}, bank statement bhej dun?",
        "we have released {amt} on friday, utr {utr}",
    ],
    ReplyIntent.DISPUTE: [
        "2 boxes damaged the, credit note bhejo pehle",
        "rate mismatch hai, PO me {amt} kam tha. correct invoice bhejiye",
        "short delivery hui thi, {amt} ka material nahi aaya",
        "quality issue hai is lot me, hold kiya hai payment",
        "GST number galat hai invoice pe, revise karke bhejo",
    ],
    ReplyIntent.DOCUMENT_REQUEST: [
        "PO copy aur challan bhej dijiye, system me nahi mil raha",
        "e-way bill attach nahi hai, wo bhejiye",
        "invoice portal pe upload nahi hua hai, please upload karein",
        "GRN pending hai, stores se confirm karwa ke bhejta hoon",
    ],
    ReplyIntent.PROCESS_DEFLECTION: [
        "payment cycle me hai, {q} ki run me aa jayega",
        "approval management ke paas pending hai",
        "hamara payment {q} ko hota hai, us cycle me le lenge",
        "accounts dept dekh raha hai, unko follow up kar lijiye",
        "process me hai sir, ho jayega",
    ],
    ReplyIntent.HARDSHIP: [
        "sir abhi bilkul cash nahi hai, market bahut down hai. thoda time dijiye",
        "hamara bhi payment atka hua hai clients se, majboori hai",
        "ek saath nahi de paunga, part payment chalega kya?",
        "business bahut slow hai, {q} tak kuch arrange karta hoon",
    ],
    ReplyIntent.REFUSAL: [
        "abhi payment nahi ho payega",
        "iske baare me baad me baat karte hain",
    ],
    ReplyIntent.ACKNOWLEDGEMENT: [
        "noted",
        "ok sir dekhta hoon",
        "theek hai, check karta hoon",
        "received, will revert",
    ],
}

FUZZY_DATES = [
    ("month end tak", 12),
    ("next week", 7),
    ("agle hafte", 7),
    ("15 taarikh", 0),
    ("10-15 din me", 13),
    ("diwali ke baad", 21),
    ("GST filing ke baad", 9),
    ("is week", 4),
]


def _intent_mix(arch: BuyerArchetype, iv: Intervention) -> tuple[list[ReplyIntent], list[float]]:
    """What this archetype tends to say. The mapping is the generator's, not a
    finding: it encodes our assumptions about who says what."""
    table: dict[BuyerArchetype, dict[ReplyIntent, float]] = {
        BuyerArchetype.PROMPT: {
            ReplyIntent.PAYMENT_CLAIM: 0.45,
            ReplyIntent.ACKNOWLEDGEMENT: 0.35,
            ReplyIntent.PROMISE_TO_PAY: 0.20,
        },
        BuyerArchetype.PROCESS_BOUND: {
            ReplyIntent.PROCESS_DEFLECTION: 0.55,
            ReplyIntent.DOCUMENT_REQUEST: 0.28,
            ReplyIntent.ACKNOWLEDGEMENT: 0.17,
        },
        BuyerArchetype.CASHFLOW_STRESSED: {
            ReplyIntent.PROMISE_TO_PAY: 0.58,
            ReplyIntent.HARDSHIP: 0.18,
            ReplyIntent.ACKNOWLEDGEMENT: 0.14,
            ReplyIntent.PAYMENT_CLAIM: 0.10,
        },
        BuyerArchetype.DISPUTER: {
            ReplyIntent.DISPUTE: 0.62,
            ReplyIntent.DOCUMENT_REQUEST: 0.22,
            ReplyIntent.ACKNOWLEDGEMENT: 0.16,
        },
        BuyerArchetype.AVOIDER: {
            ReplyIntent.ACKNOWLEDGEMENT: 0.42,
            ReplyIntent.PROCESS_DEFLECTION: 0.33,
            ReplyIntent.REFUSAL: 0.15,
            ReplyIntent.PROMISE_TO_PAY: 0.10,
        },
        BuyerArchetype.DISTRESSED: {
            ReplyIntent.HARDSHIP: 0.52,
            ReplyIntent.PROMISE_TO_PAY: 0.30,
            ReplyIntent.ACKNOWLEDGEMENT: 0.18,
        },
    }[arch]

    # A dispute-resolution approach invites the dispute to be stated; a firm
    # reminder provokes either a commitment or a refusal.
    if iv is Intervention.DISPUTE_RESOLUTION:
        table = {**table, ReplyIntent.DISPUTE: table.get(ReplyIntent.DISPUTE, 0.0) + 0.35}
    if iv in (Intervention.FIRM_REMINDER, Intervention.MSMED_NOTICE):
        table = {**table, ReplyIntent.PROMISE_TO_PAY: table.get(ReplyIntent.PROMISE_TO_PAY, 0.0) + 0.25}
    if iv is Intervention.DOCUMENT_RECONCILE:
        table = {**table, ReplyIntent.DOCUMENT_REQUEST: table.get(ReplyIntent.DOCUMENT_REQUEST, 0.0) + 0.30}

    return list(table), list(table.values())


def generate_reply(
    world: World, st: RunState, buyer_id: str, msg: OutboundMessage, day: date
) -> InboundMessage | None:
    """Produce a reply and apply its side effects on world state.

    Side effects are the point: a promise suppresses the payment hazard until its
    date, a dispute blocks the disputed portion entirely, a hardship declaration
    is a signal the agent is expected to act on. The text is scenery; the state
    change is the mechanism.
    """
    truth = world.truth[buyer_id]
    br = st.buyers[buyer_id]
    key = (buyer_id, msg.message_id, "reply_body")

    intents, weights = _intent_mix(truth.archetype, msg.intervention)
    intent: ReplyIntent = rng.weighted(st.seed, intents, weights, *key, "intent")

    # A buyer with an agreed plan or a live promise does not open a fresh one.
    if intent is ReplyIntent.PROMISE_TO_PAY and (
        br.plan is not None or br.open_promise(day, 0) is not None
    ):
        intent = ReplyIntent.ACKNOWLEDGEMENT

    template = rng.choice(st.seed, TEMPLATES[intent], *key, "template")
    open_ids = st.open_invoice_ids(buyer_id, world)
    outstanding = sum(st.invoices[i].outstanding for i in open_ids)

    fuzzy, offset = rng.choice(st.seed, FUZZY_DATES, *key, "fuzzy")
    if fuzzy == "15 taarikh":
        nxt = day.replace(day=15)
        if nxt <= day:
            nxt = (day.replace(day=1) + timedelta(days=32)).replace(day=15)
        offset = (nxt - day).days
    elif fuzzy == "month end tak":
        nxt = (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        offset = max(1, (nxt - day).days)

    claim_amt = Paise(int(outstanding * rng.uniform(st.seed, 0.3, 0.9, *key, "amt")))
    body = template.format(
        q=fuzzy,
        amt=f"{claim_amt // 100:,}",
        utr=f"UTR{int(rng.u01(st.seed, *key, 'utr') * 1e12):012d}"[:15],
    )

    _apply_side_effects(world, st, buyer_id, intent, day, offset, claim_amt, open_ids, body, msg)

    return InboundMessage(
        message_id=f"in_{msg.message_id[-8:]}_{day.isoformat()}",
        buyer_id=buyer_id,
        channel=msg.channel,
        received_at=datetime.combine(day, time(16, 20)),
        body=body,
        in_reply_to=msg.message_id,
    )


def _apply_side_effects(
    world: World,
    st: RunState,
    buyer_id: str,
    intent: ReplyIntent,
    day: date,
    offset: int,
    claim_amt: Paise,
    open_ids: list[str],
    body: str,
    msg: OutboundMessage,
) -> None:
    br = st.buyers[buyer_id]
    truth = world.truth[buyer_id]

    if intent is ReplyIntent.PROMISE_TO_PAY and open_ids:
        promise = Promise(
            promise_id=f"prm_{msg.message_id[-8:]}",
            buyer_id=buyer_id,
            invoice_ids=list(open_ids),
            made_on=day,
            promised_date=day + timedelta(days=max(1, offset)),
            promised_amount=Paise(sum(st.invoices[i].outstanding for i in open_ids)),
            source_quote=body,
            source_message_id=msg.message_id,
            confidence=1.0,  # ground truth here; the extractor's confidence is separate
            date_was_relative=True,
        )
        br.promises.append(promise)
        # Rolled now, hidden from the agent, and degraded by past broken promises.
        st.promise_will_keep[promise.promise_id] = rng.bernoulli(
            st.seed, min(0.99, truth.promise_reliability * br.trust), promise.promise_id, "keep"
        )

    elif intent is ReplyIntent.DISPUTE and open_ids:
        # If a latent dispute already covers one of these invoices, the reply
        # states it rather than creating a second one. Contact reveals the
        # problem; it does not cause it.
        latent = next(
            (
                d
                for d in br.disputes
                if d.status == "open"
                and d.source_quote.startswith("(not yet stated")
                and set(d.invoice_ids) & set(open_ids)
            ),
            None,
        )
        if latent is not None:
            idx = br.disputes.index(latent)
            br.disputes[idx] = latent.model_copy(update={"source_quote": body, "raised_on": day})
            return

        target = rng.choice(st.seed, open_ids, buyer_id, day, "dispute_inv")
        full = rng.bernoulli(st.seed, 0.45, buyer_id, day, "dispute_full")
        br.disputes.append(
            Dispute(
                dispute_id=f"dsp_{msg.message_id[-8:]}",
                buyer_id=buyer_id,
                invoice_ids=[target],
                raised_on=day,
                kind=rng.choice(
                    st.seed,
                    ["short_delivery", "damage", "rate_mismatch", "quality", "gst_mismatch"],
                    buyer_id,
                    day,
                    "dispute_kind",
                ),
                # A partial dispute leaves the remainder collectable today.
                disputed_amount=None if full else Paise(int(st.invoices[target].outstanding * 0.35)),
                source_quote=body,
            )
        )

    elif intent is ReplyIntent.HARDSHIP:
        br.hardship_declared = True
