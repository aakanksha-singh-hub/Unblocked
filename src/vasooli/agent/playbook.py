"""The agent's own beliefs about what works, and what it costs.

This table is deliberately **not** `sim/calibration.EFFECT`.

Importing the simulator's effect matrix into the policy would be the agent
reading the answer key. It would score beautifully and would prove only that a
lookup table can invert itself. The evaluation's whole value depends on the
agent holding an *independent and imperfect* model of the world and having to
act under that imperfection.

So these numbers are authored separately, from what an experienced collections
manager would believe about Indian B2B: resolve grievances before asking again,
paperwork problems are commoner than unwillingness, pressure works on the
unwilling and backfires on the unable. The ordering broadly agrees with the
simulator's - a manager who was wrong about everything would be a strange
straw man - but the magnitudes differ, some entries are wrong in both
directions, and `eval/divergence.py` measures and reports the gap.

Reporting that gap is the point: "the agent's model of what works is off by this
much on average, and it still beats the baselines" is a far stronger claim than
any score obtained by consulting the generator.
"""

from __future__ import annotations

from ..domain.enums import BuyerArchetype, Intervention

#: Believed multiplier on the chance of collecting, by action and by the
#: archetype the agent thinks it is facing. 1.0 means "believed to change
#: nothing but the relationship".
BELIEVED_UPLIFT: dict[Intervention, dict[BuyerArchetype, float]] = {
    Intervention.HOLD: {a: 1.0 for a in BuyerArchetype},
    Intervention.STATEMENT_OF_ACCOUNT: {
        BuyerArchetype.PROMPT: 1.05,
        BuyerArchetype.PROCESS_BOUND: 1.45,
        BuyerArchetype.CASHFLOW_STRESSED: 1.15,
        BuyerArchetype.DISPUTER: 1.10,
        BuyerArchetype.AVOIDER: 1.10,
        BuyerArchetype.DISTRESSED: 1.05,
    },
    Intervention.DOCUMENT_RECONCILE: {
        BuyerArchetype.PROMPT: 1.05,
        # The manager's strongest conviction, and close to right: on a portal
        # buyer, paperwork is the commonest silent cause of non-payment.
        BuyerArchetype.PROCESS_BOUND: 1.75,
        BuyerArchetype.CASHFLOW_STRESSED: 1.05,
        BuyerArchetype.DISPUTER: 1.35,
        BuyerArchetype.AVOIDER: 1.15,
        BuyerArchetype.DISTRESSED: 1.0,
    },
    Intervention.SOFT_NUDGE: {
        BuyerArchetype.PROMPT: 1.05,
        # Believed mildly useful on a cyclic payer. It is not - this entry is
        # wrong, and deliberately left wrong.
        BuyerArchetype.PROCESS_BOUND: 1.10,
        BuyerArchetype.CASHFLOW_STRESSED: 1.50,
        # "A gentle reminder can't hurt." It can: to someone waiting on a credit
        # note, a nudge that ignores the grievance reads as not listening. The
        # agent has the sign wrong here, which is the commonest real-world
        # misconception in collections and is left in on purpose.
        BuyerArchetype.DISPUTER: 1.05,
        BuyerArchetype.AVOIDER: 1.05,
        BuyerArchetype.DISTRESSED: 1.05,
    },
    Intervention.PAYMENT_LINK: {
        BuyerArchetype.PROMPT: 1.10,
        BuyerArchetype.PROCESS_BOUND: 1.0,
        BuyerArchetype.CASHFLOW_STRESSED: 1.55,
        # "Making it easier to pay always helps." Not when the reason for not
        # paying is a dispute; friction was never the obstacle. Sign wrong.
        BuyerArchetype.DISPUTER: 1.10,
        BuyerArchetype.AVOIDER: 1.15,
        BuyerArchetype.DISTRESSED: 1.15,
    },
    Intervention.FIRM_REMINDER: {
        BuyerArchetype.PROMPT: 1.0,
        # Overestimates what firmness does to a large buyer's AP calendar. It
        # does approximately nothing; the calendar is not listening.
        BuyerArchetype.PROCESS_BOUND: 1.25,
        BuyerArchetype.CASHFLOW_STRESSED: 1.30,
        BuyerArchetype.DISPUTER: 0.80,
        BuyerArchetype.AVOIDER: 1.70,
        BuyerArchetype.DISTRESSED: 0.85,
    },
    Intervention.DISPUTE_RESOLUTION: {
        BuyerArchetype.PROMPT: 1.0,
        BuyerArchetype.PROCESS_BOUND: 1.10,
        BuyerArchetype.CASHFLOW_STRESSED: 1.10,
        # Believed decisive, and it is - though the agent underestimates how
        # decisive.
        BuyerArchetype.DISPUTER: 2.60,
        BuyerArchetype.AVOIDER: 1.05,
        BuyerArchetype.DISTRESSED: 1.0,
    },
    Intervention.INSTALMENT_OFFER: {
        BuyerArchetype.PROMPT: 1.0,
        BuyerArchetype.PROCESS_BOUND: 1.0,
        BuyerArchetype.CASHFLOW_STRESSED: 1.40,
        BuyerArchetype.DISPUTER: 1.0,
        # Underestimates restructuring - the agent will offer instalments less
        # often than it should.
        BuyerArchetype.DISTRESSED: 2.20,
        BuyerArchetype.AVOIDER: 1.10,
    },
    Intervention.PHONE_TASK: {
        BuyerArchetype.PROMPT: 1.05,
        BuyerArchetype.PROCESS_BOUND: 1.20,
        BuyerArchetype.CASHFLOW_STRESSED: 1.75,
        BuyerArchetype.DISPUTER: 1.70,
        BuyerArchetype.AVOIDER: 1.40,
        BuyerArchetype.DISTRESSED: 1.55,
    },
    Intervention.OWNER_ESCALATION: {
        BuyerArchetype.PROMPT: 1.0,
        BuyerArchetype.PROCESS_BOUND: 1.25,
        BuyerArchetype.CASHFLOW_STRESSED: 1.60,
        BuyerArchetype.DISPUTER: 1.45,
        BuyerArchetype.AVOIDER: 2.20,
        BuyerArchetype.DISTRESSED: 1.20,
    },
    Intervention.MSMED_NOTICE: {
        BuyerArchetype.PROMPT: 1.0,
        BuyerArchetype.PROCESS_BOUND: 1.30,
        BuyerArchetype.CASHFLOW_STRESSED: 1.45,
        BuyerArchetype.DISPUTER: 1.15,
        BuyerArchetype.AVOIDER: 2.60,
        BuyerArchetype.DISTRESSED: 1.05,
    },
    Intervention.SAMADHAAN_FILING: {
        BuyerArchetype.PROMPT: 1.0,
        BuyerArchetype.PROCESS_BOUND: 1.40,
        BuyerArchetype.CASHFLOW_STRESSED: 1.30,
        BuyerArchetype.DISPUTER: 1.20,
        BuyerArchetype.AVOIDER: 2.40,
        BuyerArchetype.DISTRESSED: 1.05,
    },
}

#: Rupees (in paise) the agent charges itself per unit of relationship capital.
#: This is the dial that decides how aggressive the agent is, and exposing it as
#: one number rather than burying it in thresholds is deliberate: a merchant with
#: nothing to lose would set it near zero, and Priya would not.
PAISE_PER_RELATIONSHIP_POINT = 900_00

#: Rupees (in paise) per minute of the owner's time.
PAISE_PER_HUMAN_MINUTE = 500

#: Fraction of the outstanding balance the agent treats as genuinely at risk on
#: any single decision. Without this the expected value of every action scales
#: with the whole balance and even a tiny believed uplift justifies escalation.
AT_RISK_FRACTION = 0.06
