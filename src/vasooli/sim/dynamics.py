"""The day-stepper: how money actually moves, and why.

The whole model is one daily payment hazard per open invoice, assembled
multiplicatively:

    hazard = base(archetype, days_past_effective_terms)
             x structural_blockers        (dispute / portal / missing PO)
             x promise_state              (suppressed before, spiked on/after)
             x intervention_effect        (decayed, best-recent-wins)
             x contact_fatigue            (the punishing term)
             x churn_penalty

Multiplicative because the causes are conjunctive: an invoice that never reached
the buyer's AP portal does not get paid *however* responsive the buyer is and
*however* well the message is written. That is the structural point the project
is making, and it needs to be true of the arithmetic and not only of the prose.

Every draw is keyed by (seed, entity, day, stream) via sim.rng, so two policies
run on the same seed face identical dice. See sim/rng.py.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta

from ..domain.enums import CONTACT_INSENSITIVE, BuyerArchetype, Intervention, RELATIONSHIP_COST
from ..domain.enums import HUMAN_MINUTES
from ..domain.models import AuditEntry, Decision, Dispute, InboundMessage, OutboundMessage, Payment
from ..domain.money import Paise
from . import calibration as cal
from . import rng
from .state import BuyerRuntime, InstalmentPlan, InvoiceRuntime, RunState
from .world import World

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def new_run(world: World, *, seed: int | None = None) -> RunState:
    """Initial state at world.start_date.

    Invoices dated after the start are held in `pending_issue` and released as
    the calendar reaches them. The agent is never handed work that has not yet
    been delivered.
    """
    seed = world.seed if seed is None else seed
    invoices = {
        iid: InvoiceRuntime(
            invoice_id=iid,
            outstanding=inv.amount,
            original=inv.amount,
            portal_submitted=inv.portal_submitted,
            has_po=inv.po_number is not None,
        )
        for iid, inv in world.invoices.items()
    }
    pending = {
        iid: inv.issue_date
        for iid, inv in world.invoices.items()
        if inv.issue_date > world.start_date
    }
    buyers = {bid: BuyerRuntime(buyer_id=bid) for bid in world.buyers}
    _seed_latent_disputes(world, buyers, invoices, seed)
    by_buyer: dict[str, list[str]] = {}
    for iid, inv in world.invoices.items():
        by_buyer.setdefault(inv.buyer_id, []).append(iid)
    return RunState(
        seed=seed,
        day=world.start_date,
        invoices=invoices,
        buyers=buyers,
        pending_issue=pending,
        invoices_by_buyer=by_buyer,
    )


# ---------------------------------------------------------------------------
# Hazard components
# ---------------------------------------------------------------------------


def _seed_latent_disputes(world: World, buyers, invoices, seed: int) -> None:
    """Create disputes that already exist at t0, unseen.

    A short delivery is a fact about goods that were delivered wrong. It does
    not come into being because a supplier sent a reminder - it was true all
    along, and the reminder is merely when anyone said so out loud.

    Modelling disputes as *created* by contact made never-chase the best policy
    on disputers, for the entirely spurious reason that a supplier who never
    asks never hears about the problem. Under that model the optimal way to
    handle a damaged consignment is to not mention it, which is the opposite of
    true: the invoice sits unpaid either way, and the silent version simply
    takes longer to find out why.

    These disputes block payment from day one and are invisible to the agent
    until the buyer states them in a reply.
    """
    for bid, br in buyers.items():
        if world.truth[bid].archetype is not BuyerArchetype.DISPUTER:
            continue
        for iid in (i for i, inv in world.invoices.items() if inv.buyer_id == bid):
            if not rng.bernoulli(seed, 0.55, iid, "latent_dispute"):
                continue
            inv = world.invoices[iid]
            full = rng.bernoulli(seed, 0.45, iid, "latent_full")
            br.disputes.append(
                Dispute(
                    dispute_id=f"dsp_latent_{iid[-8:]}",
                    buyer_id=bid,
                    invoice_ids=[iid],
                    raised_on=inv.issue_date,
                    kind=rng.choice(
                        seed,
                        ["short_delivery", "damage", "rate_mismatch", "quality", "gst_mismatch"],
                        iid,
                        "latent_kind",
                    ),
                    disputed_amount=None if full else Paise(int(inv.amount * 0.35)),
                    source_quote="(not yet stated by the buyer)",
                )
            )


def _base_hazard(arch: BuyerArchetype, days_past_effective: float) -> float:
    """Gaussian bump around the archetype's characteristic pay point, plus a tail.

    The tail only applies once the invoice is actually past its effective terms.
    Without that gate a freshly issued invoice would carry a standing daily
    chance of payment, which over a month is a large and entirely spurious
    recovery rate.
    """
    shape = cal.HAZARD[arch]

    # A cyclic payer needs a different functional form entirely. A gaussian in
    # days-past-due encodes 'pays around a characteristic date, then the chance
    # decays' - true of most archetypes, and badly wrong for a buyer whose AP
    # runs a batch every month forever. Under the gaussian, a process-bound
    # invoice 145 days overdue had effectively zero hazard, which said it was
    # delinquent when the truth is that it is merely slow. Measured across a
    # 180-day run, these invoices were getting a mean of 0.8 days with any
    # meaningful chance of payment at all.
    #
    # Once eligible, the hazard is flat per cycle: the invoice is in the batch or
    # it is not. It decays only over a long horizon, because an invoice that has
    # survived many cycles untouched usually has an intake problem rather than a
    # timing one - and finding those is the agent's actual job on this segment.
    if arch is BuyerArchetype.PROCESS_BOUND:
        if days_past_effective < -3:
            return 0.0
        aged = max(0.0, days_past_effective - 30.0)
        return shape.peak_hazard * math.exp(-aged / 240.0)

    z = (days_past_effective - shape.peak_offset_days) / shape.spread_days
    bump = (shape.peak_hazard - shape.tail_hazard) * math.exp(-0.5 * z * z)
    tail = shape.tail_hazard if days_past_effective > 0 else 0.0
    return max(0.0, bump + tail)


def _blockers(world: World, st: RunState, buyer_id: str, invoice_id: str) -> tuple[float, Paise]:
    """Structural multiplier, and the ceiling on what is collectable today.

    Returns (multiplier, collectable_cap). The cap matters for partial disputes:
    a buyer withholding 40k against a 300k invoice can still pay 260k, and the
    single most underused move in B2B collections is asking for exactly that.
    """
    inv = world.invoices[invoice_id]
    buyer = world.buyers[buyer_id]
    rt = st.invoices[invoice_id]
    br = st.buyers[buyer_id]

    mult = 1.0
    cap: Paise = rt.outstanding

    if buyer.uses_ap_portal and not rt.portal_submitted:
        # Invisible on an aging report, fatal in reality: the invoice does not
        # exist as far as AP is concerned.
        mult *= float(cal.BLOCKER_PORTAL_NOT_SUBMITTED.value)

    if not rt.has_po:
        mult *= float(cal.BLOCKER_MISSING_PO.value)

    for d in br.open_disputes():
        if invoice_id in d.invoice_ids:
            if d.disputed_amount is None or d.disputed_amount >= rt.outstanding:
                mult *= float(cal.BLOCKER_OPEN_DISPUTE.value)
            else:
                cap = min(cap, rt.outstanding - d.disputed_amount)

    return mult, cap


def _promise_factor(st: RunState, buyer_id: str, day: date) -> float:
    """Suppressed while a promise is pending, spiked when it comes due.

    A buyer who said 'the 15th' does not pay on the 9th. Modelling that is what
    makes the agent's stopping rule worth anything: if promises did not actually
    suppress payment, going quiet would cost nothing and restraint would be free.
    """
    br = st.buyers[buyer_id]
    p = br.open_promise(day, int(cal.PROMISE_GRACE_DAYS.value))
    if p is None:
        return 1.0
    if day < p.promised_date:
        # A promise mostly REVEALS a plan, it does not create one.
        #
        # This is the same causality error as disputes being created by contact.
        # A buyer who intends to pay at month end intends that whether or not a
        # supplier asked; saying it out loud does not push the date back. By
        # letting contact produce a promise which then suppressed the hazard,
        # contact was made to *cause* delay - which is why a cash-stressed buyer
        # did worse when chased than when ignored, in flat contradiction of the
        # effect matrix that says nudging them helps.
        #
        # What remains is the small genuine effect of having named a date:
        # commitment anchors behaviour slightly, so payment before the stated
        # date becomes a little less likely, not dramatically so.
        #
        # The fully correct treatment is a latent intended pay-date that the
        # promise merely reports, with the hazard concentrated there for every
        # buyer whether or not they were asked. That is a larger change to the
        # generator than the remaining time allows, and it is recorded as a
        # known limitation in docs/EVALUATION.md rather than quietly ignored.
        return 0.85
    if st.promise_will_keep.get(p.promise_id, False):
        return float(cal.PROMISE_HAZARD_SPIKE.value)
    return 0.60


def _intervention_factor(world: World, st: RunState, buyer_id: str, day: date) -> float:
    """Best recent intervention, linearly decayed.

    Deliberately max-not-product. If effects multiplied, sending four messages
    would compound to a large boost and the optimal policy would be to spam,
    which is the opposite of what contact fatigue is modelling. Taking the best
    recent action means a second message adds nothing but fatigue - which is
    precisely the claim under test.
    """
    br = st.buyers[buyer_id]
    arch = world.truth[buyer_id].archetype
    window = float(cal.EFFECT_DECAY_DAYS.value)
    best_help = 1.0
    worst_harm = 1.0
    for sent_on, iv in br.contacts:
        age = (day - sent_on).days
        if age < 0 or age > window:
            continue
        raw = cal.EFFECT[iv][arch]
        decayed = 1.0 + (raw - 1.0) * (1.0 - age / window)
        if raw >= 1.0:
            best_help = max(best_help, decayed)
        else:
            worst_harm = min(worst_harm, decayed)
    # Order-independent by construction. Folding both directions into a single
    # running max/min made the result depend on the order contacts happened to
    # sit in the list, which is a silent reproducibility hazard: the same history
    # could score differently depending on insertion order.
    return best_help * worst_harm


def _fatigue(st: RunState, buyer_id: str, day: date) -> float:
    """Responsiveness decay from over-contact.

    This is the load-bearing invented parameter of the entire project. The
    breakeven analysis in eval/breakeven.py exists because our headline finding
    depends on it, and reporting the threshold at which we would be wrong is
    more useful than defending the value we picked.
    """
    n = st.buyers[buyer_id].contacts_within(day, 30)
    excess = max(0, n - int(cal.FATIGUE_FREE_CONTACTS.value))
    if excess == 0:
        return 1.0
    decayed = (1.0 - float(cal.FATIGUE_PER_EXCESS_CONTACT.value)) ** excess
    return max(float(cal.FATIGUE_FLOOR.value), decayed)


def hazard(world: World, st: RunState, buyer_id: str, invoice_id: str, day: date) -> tuple[float, Paise]:
    """Daily probability this invoice sees a payment, and the collectable ceiling."""
    truth = world.truth[buyer_id]
    inv = world.invoices[invoice_id]
    br = st.buyers[buyer_id]

    effective_due = inv.issue_date + timedelta(days=truth.effective_terms_days)
    dpe = (day - effective_due).days

    base = _base_hazard(truth.archetype, dpe)

    # A process-bound buyer pays on its AP run date or not at all. Suppressing
    # every other day is what makes chasing them between cycles measurably
    # futile rather than merely unrewarding.
    if truth.archetype is BuyerArchetype.PROCESS_BOUND:
        if truth.ap_cycle_day is None or day.day != truth.ap_cycle_day or dpe < -3:
            base *= 0.01

    block_mult, cap = _blockers(world, st, buyer_id, invoice_id)
    if block_mult <= 0.0 or cap <= 0:
        return 0.0, Paise(0)

    # Responsiveness scales how much interventions move the buyer, not the
    # baseline. A contact-insensitive buyer still pays; it just does not pay
    # *because you asked*.
    raw_iv = _intervention_factor(world, st, buyer_id, day)
    scaled_iv = 1.0 + (raw_iv - 1.0) * truth.contact_responsiveness * _fatigue(st, buyer_id, day)

    h = base * block_mult * _promise_factor(st, buyer_id, day) * scaled_iv

    if br.plan is not None:
        nd = br.plan.next_due(day)
        # Under an agreed plan the buyer pays on plan dates, and mostly not
        # otherwise.
        h = h * 4.0 if (nd is not None and day >= nd) else h * 0.10

    # Churn deliberately does NOT touch the hazard. A buyer whose relationship
    # has been destroyed still owes for goods already delivered; what is lost is
    # the *future* business, and that is accounted as a separate cost line in
    # eval/metrics.py rather than smuggled into the recovery figure.
    #
    # An earlier version applied a 0.5 hazard penalty on churn. It made the
    # headline finding - that high-frequency chasing loses money - come out of
    # an invented churn penalty rather than out of contact fatigue, while
    # appearing to come from fatigue. Charging the cost where it actually falls
    # keeps the breakeven analysis meaningful.

    return min(0.95, max(0.0, h)), cap


# ---------------------------------------------------------------------------
# Applying agent actions
# ---------------------------------------------------------------------------


def apply_decision(
    world: World, st: RunState, decision: Decision, *, body: str = "", channel=None
) -> OutboundMessage | None:
    """Charge the cost of an action and record it. HOLD costs nothing and sends
    nothing, but is still audited - a decision not to act is a decision."""
    bid = decision.buyer_id
    br = st.buyers[bid]
    day = decision.as_of

    st.audit.append(
        AuditEntry(
            at=datetime.combine(day, time(9, 0)),
            buyer_id=bid,
            kind="decision",
            summary=f"{decision.chosen}: {decision.rationale}",
            payload={
                "considered": [c.value for c in decision.considered],
                "gates": [g.model_dump() for g in decision.gates],
                "inferred": decision.inferred_archetype,
                "confidence": round(decision.archetype_confidence, 3),
                "decided_by": decision.decided_by,
            },
            decision_id=decision.decision_id,
        )
    )

    if decision.chosen is Intervention.HOLD:
        return None

    br.contacts.append((day, decision.chosen))
    br.relationship_spent += RELATIONSHIP_COST[decision.chosen]
    br.human_minutes += HUMAN_MINUTES[decision.chosen]

    truth = world.truth[bid]
    if not br.churned and br.relationship_spent > truth.relationship_budget:
        br.churned = True
        br.churned_on = day
        st.audit.append(
            AuditEntry(
                at=datetime.combine(day, time(9, 0)),
                buyer_id=bid,
                kind="churn",
                summary=(
                    f"Relationship budget exhausted: spent {br.relationship_spent} "
                    f"against tolerance {truth.relationship_budget}"
                ),
                payload={"revenue_share": world.buyers[bid].revenue_share},
            )
        )

    open_ids = st.open_invoice_ids(bid, world)
    # Deterministic message id. The uuid4 default is right for a live system and
    # fatal here: promise ids derive from the message id and are used as RNG
    # keys, so a random message id silently randomises which promises get kept.
    # Two identical runs then diverge, which test_run_is_deterministic caught.
    seq = sum(1 for m in st.outbound if m.buyer_id == bid)
    msg = OutboundMessage(
        message_id=f"out_{bid[-8:]}_{seq:04d}",
        buyer_id=bid,
        invoice_ids=open_ids,
        intervention=decision.chosen,
        channel=channel or world.buyers[bid].reachable_channels[0],
        sent_at=datetime.combine(day, time(10, 30)),
        body=body or f"[{decision.chosen}]",
        decision_id=decision.decision_id,
    )
    st.outbound.append(msg)
    st.outbound_by_day.setdefault(day, []).append(msg)
    st.outbound_by_buyer.setdefault(bid, []).append(msg)

    # Three interventions are not merely persuasive - they change the state of
    # the world. Modelling them as hazard multipliers alone was wrong: a
    # portal-blocked invoice has hazard exactly zero, so multiplying it by 1.6
    # leaves it at zero and the single highest-value discovery in the book was
    # unreachable by any action.
    if decision.chosen is Intervention.DOCUMENT_RECONCILE:
        if _repair_intake(world, st, bid, day, open_ids):
            st.repair_messages.add(msg.message_id)
    elif decision.chosen is Intervention.DISPUTE_RESOLUTION:
        if _resolve_disputes(world, st, bid, day):
            st.repair_messages.add(msg.message_id)
    elif decision.chosen is Intervention.INSTALMENT_OFFER and br.plan is None:
        _maybe_accept_plan(world, st, bid, day, open_ids)

    return msg


def _repair_intake(
    world: World, st: RunState, buyer_id: str, day: date, invoice_ids: list[str]
) -> bool:
    """Chase the paperwork that stops an invoice entering the buyer's system.

    This is the action that converts an invoice nobody at the buyer can see into
    one that is merely unpaid. On an aging report both look identical - "90 days
    overdue" - which is exactly why it goes unfound.
    """
    any_repaired = False
    for iid in invoice_ids:
        rt = st.invoices[iid]
        repaired = False
        if world.buyers[buyer_id].uses_ap_portal and not rt.portal_submitted:
            if rng.bernoulli(st.seed, float(cal.PORTAL_REPAIR_SUCCESS.value), iid, day, "portal_fix"):
                rt.portal_submitted = True
                repaired = True
        if not rt.has_po and rng.bernoulli(
            st.seed, float(cal.PO_REPAIR_SUCCESS.value), iid, day, "po_fix"
        ):
            rt.has_po = True
            repaired = True
        if repaired:
            any_repaired = True
            st.intake_repairs += 1
            st.audit.append(
                AuditEntry(
                    at=datetime.combine(day, time(12, 0)),
                    buyer_id=buyer_id,
                    kind="intake_repaired",
                    summary=(
                        f"{world.invoices[iid].invoice_number} was blocked at intake, "
                        f"not unpaid by choice; paperwork resolved"
                    ),
                    payload={"invoice_id": iid, "outstanding": rt.outstanding},
                )
            )
    return any_repaired


def _resolve_disputes(world: World, st: RunState, buyer_id: str, day: date) -> bool:
    """Settle open disputes, either by credit note or by the buyer dropping it.

    A credit note is a real cost, not a recovery. It is booked to
    `st.write_offs` and never counted as money collected - otherwise the agent
    could 'recover' any amount by forgiving it.
    """
    br = st.buyers[buyer_id]
    any_resolved = False
    for d in br.open_disputes():
        if not rng.bernoulli(
            st.seed, float(cal.DISPUTE_RESOLUTION_SUCCESS.value), d.dispute_id, day, "dispute_resolve"
        ):
            continue
        any_resolved = True
        if rng.bernoulli(
            st.seed, float(cal.DISPUTE_CREDIT_NOTE_SHARE.value), d.dispute_id, "credit_note"
        ):
            d.status = "credit_note_issued"
            for iid in d.invoice_ids:
                rt = st.invoices[iid]
                amount = Paise(min(rt.outstanding, d.disputed_amount or rt.outstanding))
                rt.outstanding = Paise(rt.outstanding - amount)
                rt.written_off = Paise(rt.written_off + amount)
                st.write_offs = Paise(st.write_offs + amount)
        else:
            d.status = "rejected"
        d.resolved_on = day
        st.audit.append(
            AuditEntry(
                at=datetime.combine(day, time(12, 30)),
                buyer_id=buyer_id,
                kind="dispute_resolved",
                summary=f"{d.kind} dispute settled as {d.status}",
                payload={"dispute_id": d.dispute_id, "disputed": d.disputed_amount},
            )
        )
    return any_resolved


def _maybe_accept_plan(
    world: World, st: RunState, buyer_id: str, day: date, invoice_ids: list[str]
) -> None:
    truth = world.truth[buyer_id]
    accept_p = {
        BuyerArchetype.DISTRESSED: 0.72,
        BuyerArchetype.CASHFLOW_STRESSED: 0.45,
        BuyerArchetype.AVOIDER: 0.10,
        BuyerArchetype.DISPUTER: 0.12,
        BuyerArchetype.PROCESS_BOUND: 0.05,
        BuyerArchetype.PROMPT: 0.05,
    }[truth.archetype]
    if not rng.bernoulli(st.seed, accept_p, buyer_id, day, "plan_accept"):
        return

    total = sum(st.invoices[i].outstanding for i in invoice_ids)
    if total <= 0:
        return
    n = 4 if truth.archetype is BuyerArchetype.DISTRESSED else 3
    br = st.buyers[buyer_id]
    br.plan = InstalmentPlan(
        plan_id=f"plan_{buyer_id[-6:]}_{day.isoformat()}",
        buyer_id=buyer_id,
        invoice_ids=list(invoice_ids),
        instalment_amount=Paise(total // n),
        due_dates=[day + timedelta(days=30 * (k + 1)) for k in range(n)],
    )
    st.audit.append(
        AuditEntry(
            at=datetime.combine(day, time(11, 0)),
            buyer_id=buyer_id,
            kind="plan_agreed",
            summary=f"{n} instalments accepted",
            payload={"instalment_paise": br.plan.instalment_amount, "n": n},
        )
    )


# ---------------------------------------------------------------------------
# Advancing a day
# ---------------------------------------------------------------------------


def advance(world: World, st: RunState, day: date) -> tuple[list[Payment], list[InboundMessage]]:
    """Release new invoices, settle promises, roll payments, generate replies."""
    from .replies import generate_reply  # local: replies import dynamics types

    st.day = day
    for iid, issue_on in list(st.pending_issue.items()):
        if issue_on <= day:
            del st.pending_issue[iid]

    _settle_promises(world, st, day)

    new_payments: list[Payment] = []
    for bid, br in st.buyers.items():
        for iid in st.open_invoice_ids(bid, world):
            h, cap = hazard(world, st, bid, iid, day)
            if h <= 0.0 or cap <= 0:
                continue
            if not rng.bernoulli(st.seed, h, bid, iid, day, "pay"):
                continue
            new_payments.append(_make_payment(world, st, bid, iid, day, cap))

    inbound = _collect_replies(world, st, day, generate_reply)
    return new_payments, inbound


def _make_payment(
    world: World, st: RunState, buyer_id: str, invoice_id: str, day: date, cap: Paise
) -> Payment:
    truth = world.truth[buyer_id]
    rt = st.invoices[invoice_id]
    br = st.buyers[buyer_id]

    amount = cap

    # Capacity ceiling: a distressed buyer cannot clear the balance in one go
    # however forcefully it is asked, which is what makes restructuring the ask
    # the only move that works.
    if truth.lump_sum_capacity < 1.0 and br.plan is None:
        amount = min(amount, Paise(int(rt.original * truth.lump_sum_capacity)))

    if br.plan is not None:
        amount = min(amount, br.plan.instalment_amount)
        br.plan.paid_count += 1

    if rng.bernoulli(st.seed, float(cal.PARTIAL_PAYMENT_PROB.value), buyer_id, invoice_id, day, "partial"):
        frac = rng.uniform(st.seed, 0.30, 0.85, buyer_id, invoice_id, day, "partial_frac")
        amount = Paise(max(1, int(amount * frac)))

    amount = Paise(min(amount, rt.outstanding))
    rt.outstanding = Paise(rt.outstanding - amount)

    pay = Payment(
        payment_id=f"pay_{invoice_id[-8:]}_{day.isoformat()}",
        invoice_id=invoice_id,
        buyer_id=buyer_id,
        amount=amount,
        received_on=day,
        utr=f"UTR{rng.u01(st.seed, invoice_id, day, 'utr') * 1e12:.0f}"[:16],
        method=rng.choice(st.seed, ["neft", "neft", "rtgs", "imps", "upi"], buyer_id, day, "method"),
    )
    st.payments.append(pay)
    st.payments_by_buyer.setdefault(buyer_id, []).append(pay)
    st.audit.append(
        AuditEntry(
            at=datetime.combine(day, time(14, 0)),
            buyer_id=buyer_id,
            kind="payment",
            summary=f"Received {amount} paise against {world.invoices[invoice_id].invoice_number}",
            payload={"invoice_id": invoice_id, "utr": pay.utr, "remaining": rt.outstanding},
        )
    )
    return pay


def _settle_promises(world: World, st: RunState, day: date) -> None:
    """Mark promises kept or broken once their date plus grace has passed."""
    grace = int(cal.PROMISE_GRACE_DAYS.value)
    for bid, br in st.buyers.items():
        for p in br.promises:
            if p.status != "open" or day <= p.promised_date + timedelta(days=grace):
                continue
            paid_since = sum(
                pay.amount
                for pay in st.payments
                if pay.buyer_id == bid and p.made_on <= pay.received_on <= day
            )
            target = p.promised_amount or 1
            if paid_since >= target:
                p.status = "kept"
            elif paid_since > 0:
                p.status = "partially_kept"
            else:
                p.status = "broken"
                # Serial promisers become progressively less credible, which is
                # what stops promise-deferral being an infinite stall.
                br.trust *= float(cal.PROMISE_BREAK_TRUST_PENALTY.value)
            st.audit.append(
                AuditEntry(
                    at=datetime.combine(day, time(8, 0)),
                    buyer_id=bid,
                    kind="promise_settled",
                    summary=f"Promise {p.promise_id} {p.status}",
                    payload={"promised": p.promised_amount, "received": paid_since},
                )
            )


def _collect_replies(world: World, st: RunState, day: date, generate_reply) -> list[InboundMessage]:
    """Buyers reply to yesterday's contacts, with archetype-conditioned latency."""
    out: list[InboundMessage] = []
    replied = st.replied_to
    for lag in range(1, 7):
        for msg in st.outbound_by_day.get(day - timedelta(days=lag), ()):
            if msg.message_id in replied:
                continue
            bid = msg.buyer_id
            truth = world.truth[bid]
            p_reply = _reply_probability(truth.archetype, msg.intervention)
            # Spread the reply over the plausible window rather than always day+1.
            if not rng.bernoulli(st.seed, p_reply / 3.0, bid, msg.message_id, day, "reply"):
                continue
            inb = generate_reply(world, st, bid, msg, day)
            if inb is not None:
                st.inbound.append(inb)
                st.inbound_by_buyer.setdefault(bid, []).append(inb)
                replied.add(msg.message_id)
                out.append(inb)
    return out


def _reply_probability(arch: BuyerArchetype, iv: Intervention) -> float:
    base = {
        BuyerArchetype.PROMPT: 0.35,
        BuyerArchetype.PROCESS_BOUND: 0.55,
        BuyerArchetype.CASHFLOW_STRESSED: 0.60,
        BuyerArchetype.DISPUTER: 0.72,
        BuyerArchetype.AVOIDER: 0.18,
        BuyerArchetype.DISTRESSED: 0.45,
    }[arch]
    if iv in (Intervention.FIRM_REMINDER, Intervention.MSMED_NOTICE, Intervention.PHONE_TASK):
        base = min(0.95, base * 1.5)
    if iv in (Intervention.STATEMENT_OF_ACCOUNT, Intervention.PAYMENT_LINK):
        base *= 0.7
    return base


def is_wasted_contact(world: World, msg: OutboundMessage, st: RunState | None = None) -> bool:
    """Whether this specific contact could have changed anything.

    The false-positive definition the evaluation reports against, and it is
    knowable only inside the simulator - which is exactly why it lives here and
    not in the agent.

    Defined per *message*, not per buyer. An earlier version counted every
    contact with a contact-insensitive archetype as wasted, which over-counted
    badly in one direction: a document chase that unblocks a process-bound
    buyer's invoice at intake changes the world, and calling it waste would have
    understated the agent while flattering nothing. It also under-counted in the
    other direction, since a nudge to a cash-stressed buyer during a fatigue
    collapse is genuinely wasted and this catches it.

    A contact is wasted when the action could not raise the payment hazard for
    that archetype, and it did not repair state either.
    """
    arch = world.truth[msg.buyer_id].archetype
    if cal.EFFECT[msg.intervention][arch] > 1.0:
        return False
    if msg.intervention in (Intervention.DOCUMENT_RECONCILE, Intervention.DISPUTE_RESOLUTION):
        # State-changing actions are judged by whether they changed state.
        if st is not None and msg.message_id in st.repair_messages:
            return False
    return True
