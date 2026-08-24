"""Every parameter the simulated world runs on, with its provenance stated.

Read this before you believe any number this project reports.

The honest position: this is a *designer's prior*, not a model fitted to real
receivables data. No public dataset of Indian MSME invoice-level payment
behaviour exists, and inventing one and calling it empirical would be worse than
inventing one and saying so. What follows is a set of parameters chosen to be
individually plausible and jointly capable of producing an aging profile that
resembles published aggregates.

Each parameter carries a `Provenance`:

  STATUTE   - fixed by law. Not a modelling choice; getting it wrong is a bug.
  AGGREGATE - anchored to a published summary statistic. The shape is inferred;
              only the anchor is external.
  PRIOR     - a designer's judgement. Defensible, unverified, and the first
              thing to replace when real data arrives.
  MECHANICAL - a structural constant of the simulation with no real-world
              referent (grid resolution, horizon length).

What this buys: the evaluation is a *relative* comparison between policies on
one fixed environment. That comparison is sound even where the environment's
absolute realism is not - the same way a chess engine's Elo is meaningful
without the board being a real war. What it does not buy: the right to quote
'rupees recovered' as a forecast of production performance. Section 'Threats to
validity' in docs/EVALUATION.md says so at greater length.

SENSITIVITY: `eval/sensitivity.py` re-runs the full comparison across perturbed
parameter sets. If a policy ranking survives only at one parameter choice, the
report says that, because a conclusion that fragile is not a conclusion.
"""

from __future__ import annotations

from contextlib import contextmanager
from enum import StrEnum
from typing import NamedTuple

from ..domain.enums import BuyerArchetype, Intervention


class Provenance(StrEnum):
    STATUTE = "statute"
    AGGREGATE = "aggregate"
    PRIOR = "prior"
    MECHANICAL = "mechanical"


class Param(NamedTuple):
    value: float
    provenance: Provenance
    note: str

    def __float__(self) -> float:
        return float(self.value)


# ---------------------------------------------------------------------------
# Statutory constants. These are law, not modelling.
# ---------------------------------------------------------------------------

MSMED_MAX_PAYMENT_DAYS = Param(
    45,
    Provenance.STATUTE,
    "MSMED Act 2006 s.15: where no period is agreed, payment is due within 15 "
    "days of acceptance; where agreed in writing, the agreed period applies but "
    "may not exceed 45 days from the day of acceptance or deemed acceptance. "
    "The clock therefore runs from acceptance, not from invoice date - which is "
    "why Invoice.msmed_clock_start() exists and why acceptance_date is captured.",
)

MSMED_INTEREST_MULTIPLE = Param(
    3.0,
    Provenance.STATUTE,
    "MSMED Act 2006 s.16: compound interest with monthly rests at three times "
    "the bank rate notified by RBI, running from the appointed day. Computed in "
    "agent/msmed.py and quoted in the notice; it is a real liability, which is "
    "what gives a correctly-issued notice its force.",
)

MSMED_REQUIRES_UDYAM = Param(
    1.0,
    Provenance.STATUTE,
    "Benefits under Chapter V attach to enterprises registered as micro or small "
    "at the time of supply. Buyer.msmed_eligible gates the entire legal ladder; "
    "an unregistered supplier issuing an MSMED notice is bluffing, and the agent "
    "is not permitted to bluff.",
)

# ---------------------------------------------------------------------------
# Self-imposed contact conduct.
#
# Worth being precise, because it is easy to overclaim here: RBI's recovery-agent
# conduct norms bind regulated entities and the agents they engage for *loan*
# recovery. A manufacturer chasing its own trade receivables is not a regulated
# entity and these rules do not legally apply to Priya.
#
# We adopt them anyway, as a self-imposed floor. Partly because the underlying
# judgement is sound regardless of who is bound by it, and partly because a
# collections agent that reasons 'no rule forbids this' about a 10pm message has
# the wrong disposition to be automating contact with anyone.
# ---------------------------------------------------------------------------

CONTACT_WINDOW_START_HOUR = Param(
    9, Provenance.PRIOR, "Self-imposed. RBI's norm for regulated recovery is 0800; "
    "0900 is tightened further because these are business-hours B2B contacts and "
    "nothing is gained by arriving before the AP desk is staffed."
)
CONTACT_WINDOW_END_HOUR = Param(
    19, Provenance.PRIOR, "Self-imposed, matching RBI's 1900 bound for regulated recovery."
)
CONTACT_ON_SUNDAY = Param(0.0, Provenance.PRIOR, "Self-imposed. No Sunday contact.")
CONTACT_ON_PUBLIC_HOLIDAY = Param(
    0.0, Provenance.PRIOR, "Self-imposed. Holiday calendar in sim/calendar_in.py."
)

# ---------------------------------------------------------------------------
# Population shape.
# ---------------------------------------------------------------------------

ARCHETYPE_MIX: dict[BuyerArchetype, Param] = {
    BuyerArchetype.PROMPT: Param(
        0.30, Provenance.PRIOR,
        "The majority of a healthy book pays without intervention. Setting this "
        "high is deliberately unfavourable to the agent: it means most buyer-days "
        "have HOLD as the correct action, so a chase-everything baseline is "
        "punished and an agent that cannot tell the difference cannot win.",
    ),
    BuyerArchetype.PROCESS_BOUND: Param(
        0.26, Provenance.AGGREGATE,
        "Anchored on the widely-reported gap between contracted and realised "
        "terms in Indian B2B - a large share of 'overdue' is a large buyer's "
        "payment cycle behaving exactly as it always does. This is the archetype "
        "that makes wasted-contact measurable.",
    ),
    BuyerArchetype.CASHFLOW_STRESSED: Param(
        0.20, Provenance.PRIOR,
        "The archetype where intervention genuinely creates money. Kept below "
        "PROCESS_BOUND so the agent cannot win by assuming everyone is winnable.",
    ),
    BuyerArchetype.DISPUTER: Param(
        0.12, Provenance.PRIOR,
        "Unresolved commercial issues as a blocker. Plausibly understated versus "
        "reality, where a good share of aged debt turns out to be an unraised "
        "credit note nobody chased down.",
    ),
    BuyerArchetype.AVOIDER: Param(
        0.07, Provenance.PRIOR,
        "Deliberately the second-rarest. The temptation in collections software "
        "is to model everyone as an avoider, which is how products end up "
        "harassing people who were going to pay anyway.",
    ),
    BuyerArchetype.DISTRESSED: Param(
        0.05, Provenance.PRIOR,
        "Rare but disproportionately costly to misread; the DISTRESSED-as-AVOIDER "
        "confusion is reported as its own line in the evaluation.",
    ),
}

# ---------------------------------------------------------------------------
# Payment hazard.
#
# Model: each open invoice has a daily probability of being paid. The archetype
# sets the shape of that hazard against days-past-due; blockers multiply it to
# zero; interventions scale it. Compounding daily hazards is what produces an
# aging curve rather than a single pay date, and it is what lets an intervention
# on day 40 have a different value than the same intervention on day 90.
# ---------------------------------------------------------------------------


class HazardShape(NamedTuple):
    """Daily pay-probability profile for one archetype, before modifiers."""

    peak_offset_days: float
    """Days past *effective* terms at which the hazard peaks."""
    peak_hazard: float
    """Daily probability at the peak, for the full open balance."""
    spread_days: float
    """Width of the peak. Larger = a more diffuse, less predictable payer."""
    tail_hazard: float
    """Floor the hazard decays to. The reason very old debt is not quite dead."""


HAZARD: dict[BuyerArchetype, HazardShape] = {
    # Pays near terms, tight spread, negligible tail - once a PROMPT buyer is
    # 90 days late something has changed and it is no longer a PROMPT buyer.
    BuyerArchetype.PROMPT: HazardShape(-2.0, 0.22, 6.0, 0.001),
    # Handled specially: the cycle-day gate in buyer_model.py suppresses the
    # hazard entirely except on the AP run date, so this shape describes the
    # envelope, not the realised pattern.
    BuyerArchetype.PROCESS_BOUND: HazardShape(4.0, 0.55, 14.0, 0.010),
    # Broad and late: they intend to pay, the date keeps moving.
    BuyerArchetype.CASHFLOW_STRESSED: HazardShape(22.0, 0.055, 30.0, 0.006),
    # Near zero while the dispute is open; the shape only applies post-resolution.
    BuyerArchetype.DISPUTER: HazardShape(6.0, 0.30, 12.0, 0.002),
    # Flat and low. Time alone does not move an avoider; credible escalation does.
    BuyerArchetype.AVOIDER: HazardShape(60.0, 0.020, 90.0, 0.004),
    # Low lump-sum hazard by construction - capped by lump_sum_capacity, so the
    # only way to collect materially is to restructure the ask.
    BuyerArchetype.DISTRESSED: HazardShape(45.0, 0.018, 60.0, 0.003),
}

# ---------------------------------------------------------------------------
# Intervention effects.
#
# The matrix that encodes the project's central claim. Read down a column: the
# same action has wildly different value depending on the cause of non-payment.
# A SOFT_NUDGE is worth 1.6x on a CASHFLOW_STRESSED buyer and 1.0x - literally
# nothing but relationship cost - on a PROCESS_BOUND one.
#
# These multipliers apply to the daily hazard for a decay window after contact.
# 1.0 means 'no effect on when the money arrives'.
# ---------------------------------------------------------------------------

EFFECT: dict[Intervention, dict[BuyerArchetype, float]] = {
    Intervention.HOLD: {a: 1.0 for a in BuyerArchetype},
    Intervention.STATEMENT_OF_ACCOUNT: {
        BuyerArchetype.PROMPT: 1.0,
        BuyerArchetype.PROCESS_BOUND: 1.35,  # surfaces invoices AP never ingested
        BuyerArchetype.CASHFLOW_STRESSED: 1.10,
        BuyerArchetype.DISPUTER: 1.05,
        BuyerArchetype.AVOIDER: 1.05,
        BuyerArchetype.DISTRESSED: 1.05,
    },
    Intervention.DOCUMENT_RECONCILE: {
        BuyerArchetype.PROMPT: 1.0,
        BuyerArchetype.PROCESS_BOUND: 1.60,  # the highest-yield action in the book
        BuyerArchetype.CASHFLOW_STRESSED: 1.05,
        BuyerArchetype.DISPUTER: 1.25,
        BuyerArchetype.AVOIDER: 1.10,
        BuyerArchetype.DISTRESSED: 1.0,
    },
    Intervention.SOFT_NUDGE: {
        BuyerArchetype.PROMPT: 1.02,
        BuyerArchetype.PROCESS_BOUND: 1.0,
        BuyerArchetype.CASHFLOW_STRESSED: 1.60,
        BuyerArchetype.DISPUTER: 0.95,  # reads as not listening; mildly negative
        BuyerArchetype.AVOIDER: 1.02,
        BuyerArchetype.DISTRESSED: 1.05,
    },
    Intervention.PAYMENT_LINK: {
        BuyerArchetype.PROMPT: 1.05,
        BuyerArchetype.PROCESS_BOUND: 0.98,  # AP cannot pay outside its rails
        BuyerArchetype.CASHFLOW_STRESSED: 1.75,  # friction removal, best single lever here
        BuyerArchetype.DISPUTER: 0.95,
        BuyerArchetype.AVOIDER: 1.08,
        BuyerArchetype.DISTRESSED: 1.10,
    },
    Intervention.FIRM_REMINDER: {
        BuyerArchetype.PROMPT: 1.0,
        BuyerArchetype.PROCESS_BOUND: 1.02,
        BuyerArchetype.CASHFLOW_STRESSED: 1.40,
        BuyerArchetype.DISPUTER: 0.85,  # actively counterproductive
        BuyerArchetype.AVOIDER: 1.55,
        BuyerArchetype.DISTRESSED: 0.90,  # pressure on someone who cannot pay
    },
    Intervention.DISPUTE_RESOLUTION: {
        BuyerArchetype.PROMPT: 1.0,
        BuyerArchetype.PROCESS_BOUND: 1.05,
        BuyerArchetype.CASHFLOW_STRESSED: 1.10,
        BuyerArchetype.DISPUTER: 3.20,  # unblocks; the largest multiplier in the matrix
        BuyerArchetype.AVOIDER: 1.05,
        BuyerArchetype.DISTRESSED: 1.0,
    },
    Intervention.INSTALMENT_OFFER: {
        BuyerArchetype.PROMPT: 1.0,
        BuyerArchetype.PROCESS_BOUND: 1.0,
        BuyerArchetype.CASHFLOW_STRESSED: 1.30,
        BuyerArchetype.DISPUTER: 1.0,
        BuyerArchetype.AVOIDER: 1.05,
        BuyerArchetype.DISTRESSED: 2.60,  # and lifts lump_sum_capacity; see buyer_model
    },
    Intervention.PHONE_TASK: {
        BuyerArchetype.PROMPT: 1.02,
        BuyerArchetype.PROCESS_BOUND: 1.15,
        BuyerArchetype.CASHFLOW_STRESSED: 1.85,
        BuyerArchetype.DISPUTER: 1.60,
        BuyerArchetype.AVOIDER: 1.45,
        BuyerArchetype.DISTRESSED: 1.50,
    },
    Intervention.OWNER_ESCALATION: {
        BuyerArchetype.PROMPT: 1.0,
        BuyerArchetype.PROCESS_BOUND: 1.30,
        BuyerArchetype.CASHFLOW_STRESSED: 1.70,
        BuyerArchetype.DISPUTER: 1.50,
        BuyerArchetype.AVOIDER: 2.10,
        BuyerArchetype.DISTRESSED: 1.30,
    },
    Intervention.MSMED_NOTICE: {
        BuyerArchetype.PROMPT: 1.0,
        BuyerArchetype.PROCESS_BOUND: 1.40,
        BuyerArchetype.CASHFLOW_STRESSED: 1.60,
        BuyerArchetype.DISPUTER: 1.20,
        BuyerArchetype.AVOIDER: 3.00,  # the one thing an avoider responds to
        BuyerArchetype.DISTRESSED: 1.10,
    },
    Intervention.SAMADHAAN_FILING: {
        BuyerArchetype.PROMPT: 1.0,
        BuyerArchetype.PROCESS_BOUND: 1.50,
        BuyerArchetype.CASHFLOW_STRESSED: 1.40,
        BuyerArchetype.DISPUTER: 1.30,
        BuyerArchetype.AVOIDER: 2.80,
        BuyerArchetype.DISTRESSED: 1.05,
    },
}

EFFECT_DECAY_DAYS = Param(
    7, Provenance.PRIOR,
    "An intervention's multiplier decays linearly to 1.0 over this many days. "
    "Without decay, one early nudge would pay forever and the optimal policy "
    "would be to contact everyone once on day one, which is not how anything "
    "works.",
)

# ---------------------------------------------------------------------------
# Contact fatigue. The mechanism that makes over-chasing genuinely costly rather
# than merely inelegant, and the reason a blast-weekly baseline loses money.
# ---------------------------------------------------------------------------

FATIGUE_FREE_CONTACTS = Param(
    3, Provenance.PRIOR, "Contacts in a rolling 30 days before fatigue begins."
)
FATIGUE_PER_EXCESS_CONTACT = Param(
    0.12, Provenance.PRIOR,
    "Each contact beyond the free allowance multiplies responsiveness by "
    "(1 - 0.12). Six excess contacts roughly halves the effect of everything "
    "you send afterwards - the buyer has started filtering you.",
)
FATIGUE_FLOOR = Param(
    0.35, Provenance.PRIOR, "Responsiveness never decays below this; even a "
    "filtered sender occasionally gets through."
)

# ---------------------------------------------------------------------------
# Promises.
# ---------------------------------------------------------------------------

PROMISE_HAZARD_SPIKE = Param(
    6.5, Provenance.PRIOR,
    "Hazard multiplier on and immediately after a promised date, for a buyer "
    "whose reliability roll succeeded. Large because a kept promise means the "
    "money moves on that day, not eventually.",
)
PROMISE_GRACE_DAYS = Param(
    3, Provenance.PRIOR,
    "Days after a promised date before the agent may resume contact. This is a "
    "policy constant as much as a world constant: it is the difference between "
    "following up and hovering.",
)
PROMISE_BREAK_TRUST_PENALTY = Param(
    0.75, Provenance.PRIOR,
    "Reliability multiplier applied after a broken promise. Serial promisers "
    "become progressively less credible, so a policy that keeps accepting "
    "promises indefinitely is punished - which is what forces a stopping rule "
    "on promise-based deferral rather than an infinite one.",
)

# ---------------------------------------------------------------------------
# Structural blockers. Multiplicative, and mostly zero - these are the causes
# no amount of chasing can overcome, which is the point.
# ---------------------------------------------------------------------------

BLOCKER_OPEN_DISPUTE = Param(
    0.0, Provenance.PRIOR,
    "A DISPUTER with an open dispute pays nothing on the disputed portion. The "
    "undisputed remainder stays collectable, which is why the agent is expected "
    "to split the ask.",
)
BLOCKER_PORTAL_NOT_SUBMITTED = Param(
    0.0, Provenance.PRIOR,
    "On a portal buyer, an invoice never uploaded does not exist as far as AP is "
    "concerned. Silent, extremely common, and invisible on an aging report - the "
    "aging report says 'overdue 90 days' and the truth is 'never submitted'.",
)
BLOCKER_MISSING_PO = Param(
    0.15, Provenance.PRIOR,
    "Missing PO reference does not fully block but severely throttles intake.",
)

# ---------------------------------------------------------------------------
# Repair probabilities.
#
# These lived as bare literals inside dynamics.py until the breakeven sweep went
# looking for the parameter that actually carries our headline result and could
# not reach them. That is worth stating plainly: the two numbers most likely to
# be load-bearing were not in the parameters file, which meant the sensitivity
# analysis could not have found them. A limitations section listing every
# parameter is worthless if the important ones are somewhere else.
# ---------------------------------------------------------------------------

PORTAL_REPAIR_SUCCESS = Param(
    0.70, Provenance.PRIOR,
    "Chance a document chase gets an invoice onto the buyer's AP portal. Drives "
    "the agent's single largest segment win - process-bound recovery moves ~20pp "
    "on this number - and is therefore swept explicitly.",
)
PO_REPAIR_SUCCESS = Param(
    0.55, Provenance.PRIOR,
    "Chance a document chase recovers a missing PO reference.",
)
DISPUTE_RESOLUTION_SUCCESS = Param(
    0.62, Provenance.PRIOR,
    "Chance one dispute-resolution contact settles an open dispute, either way.",
)
DISPUTE_CREDIT_NOTE_SHARE = Param(
    0.60, Provenance.PRIOR,
    "Share of settled disputes resolved by issuing a credit note rather than by "
    "the buyer dropping the claim. Higher values mean more of the 'recovery' is "
    "actually forgiveness, which is why write-offs are reported separately.",
)

# ---------------------------------------------------------------------------
# Mechanical.
# ---------------------------------------------------------------------------

SIM_HORIZON_DAYS = Param(180, Provenance.MECHANICAL, "Simulated days per run.")
PARTIAL_PAYMENT_PROB = Param(
    0.18, Provenance.PRIOR,
    "Probability a payment event settles part rather than all of the balance. "
    "Partial payments are what make reconciliation of a claimed UTR non-trivial.",
)


def archetype_mix() -> dict[BuyerArchetype, float]:
    total = sum(p.value for p in ARCHETYPE_MIX.values())
    return {a: p.value / total for a, p in ARCHETYPE_MIX.items()}


def provenance_report() -> dict[str, int]:
    """Counts by provenance, printed in the evaluation header.

    Stating 'this run rests on N designer priors' at the top of every report is
    a small thing that keeps the project honest about what it knows.
    """
    counts: dict[str, int] = {p.value: 0 for p in Provenance}
    for obj in globals().values():
        if isinstance(obj, Param):
            counts[obj.provenance.value] += 1
    for d in (ARCHETYPE_MIX,):
        for p in d.values():
            counts[p.provenance.value] += 1
    return counts


# ---------------------------------------------------------------------------
# Runtime overrides
# ---------------------------------------------------------------------------


@contextmanager
def overrides(**changes: float):
    """Temporarily replace parameter values, for sensitivity and breakeven runs.

    Exists so that "what would have to be true for our conclusion to flip" is a
    question the code can answer, rather than a paragraph in a limitations
    section. Values are restored on exit even if the body raises, so a failed
    sweep cannot leave the module in a perturbed state and silently poison every
    later run in the same process.

        with overrides(FATIGUE_PER_EXCESS_CONTACT=0.06):
            ...

    Nested parameters (the archetype mix) are addressed by name with a dotted
    suffix: `ARCHETYPE_MIX.avoider=0.12`.
    """
    saved: dict[str, object] = {}
    try:
        for key, value in changes.items():
            if "." in key:
                container, member = key.split(".", 1)
                table = globals()[container]
                saved[key] = table[BuyerArchetype(member)]
                old = table[BuyerArchetype(member)]
                table[BuyerArchetype(member)] = Param(value, old.provenance, old.note)
            else:
                old = globals()[key]
                saved[key] = old
                if isinstance(old, Param):
                    globals()[key] = Param(value, old.provenance, old.note)
                else:
                    globals()[key] = value
        yield
    finally:
        for key, old in saved.items():
            if "." in key:
                container, member = key.split(".", 1)
                globals()[container][BuyerArchetype(member)] = old
            else:
                globals()[key] = old
