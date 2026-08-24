"""The cause-matched policy.

One decision per overdue buyer per day, made in four steps:

1. **Look for a structural block first.** An invoice that never reached the
   buyer's AP portal is not a collections problem, and no amount of asking
   fixes it. Checking this before anything else is the single highest-yield
   habit in the whole policy, and it costs nothing.
2. **Infer the cause**, as a distribution rather than a label.
3. **Score every action against that distribution**, charging relationship
   capital and human time in the same units as the money at stake. Expected
   value under uncertainty, not a decision tree over the argmax - because acting
   on a 0.4/0.38 posterior as though it were certain is how a confident agent
   does damage.
4. **Submit to the guardrails**, which can veto anything and frequently do.

The policy never reads `sim/calibration`. Its beliefs live in `playbook.py` and
are wrong in places, on purpose.
"""

from __future__ import annotations

from datetime import date

from ..domain.enums import HUMAN_MINUTES, RELATIONSHIP_COST, Intervention
from ..domain.models import Decision
from ..sim.calibration import archetype_mix
from .beliefs import Beliefs
from .extract import ReplyExtractor, RuleExtractor
from .features import extract as extract_features
from .guardrails import Guardrails
from .inference import ArchetypeModel, Prediction, PriorOnlyModel  # noqa: F401
from .observer import BeliefUpdater
from .playbook import (
    AT_RISK_FRACTION,
    BELIEVED_UPLIFT,
    PAISE_PER_HUMAN_MINUTE,
    PAISE_PER_RELATIONSHIP_POINT,
)
from .view import BuyerLedger, LedgerView

#: Below this top-two margin the posterior is not informative enough to justify
#: an action whose value depends on which archetype is right. The agent falls
#: back to actions that are safe under every hypothesis.
MIN_MARGIN_FOR_TARGETED_ACTION = 0.18

#: How much the believed value of an action decays each time it has already been
#: tried on this buyer. The agent's own conviction that saying the same thing
#: again works less well than saying it the first time - which is ordinary
#: domain sense, not a reading of the simulator. Without it the policy finds the
#: single cheapest positive-value action and repeats it forever: an early run
#: sent 3,091 messages that were 100% document chases, including to buyers whose
#: paperwork it had already fixed.
REPEAT_DECAY = 0.40

#: Days before a buyer's cause is re-inferred in the absence of new evidence.
#: A new reply forces re-inference immediately regardless.
REINFER_AFTER_DAYS = 7

#: Actions worth taking regardless of which archetype is correct: cheap,
#: reversible, and informative. What a careful person does when unsure.
SAFE_UNDER_UNCERTAINTY = (
    Intervention.STATEMENT_OF_ACCOUNT,
    Intervention.DOCUMENT_RECONCILE,
    Intervention.SOFT_NUDGE,
    Intervention.PAYMENT_LINK,
)


class CauseMatchedPolicy:
    name = "cause-matched"

    def __init__(
        self,
        *,
        model: ArchetypeModel | PriorOnlyModel | None = None,
        extractor: ReplyExtractor | None = None,
        guardrails: Guardrails | None = None,
        merchant_udyam: dict[str, bool] | None = None,
    ) -> None:
        self.model = model or PriorOnlyModel()
        self.extractor = extractor or RuleExtractor()
        self.guardrails = guardrails or Guardrails()
        self.updater = BeliefUpdater(self.extractor)
        self.beliefs = Beliefs()
        self.merchant_udyam = merchant_udyam or {}
        #: Cached inference per buyer: (prediction, day inferred, replies seen).
        #: A buyer's cause does not change daily, and re-running the classifier
        #: every day for every buyer was 131k model calls per evaluation run for
        #: an answer that had not moved. Re-inference is triggered by elapsed
        #: time or by new evidence arriving, which is also how a real system
        #: would be built.
        self._pred_cache: dict[str, tuple[Prediction, date, int]] = {}

    # -- observation ------------------------------------------------------

    def observe(self, view: LedgerView, day: date) -> None:
        self.updater.update(self.beliefs, view, day)

    # -- decision ---------------------------------------------------------

    def decide(self, view: LedgerView, day: date) -> list[Decision]:
        # Only buyers with something actually overdue are candidates. This is the
        # denominator the restraint rate is reported against, so it has to be
        # the honest one: buyers we looked at and could have contacted.
        candidates = [lg for lg in view.ledgers.values() if lg.overdue_amount(day) > 0]
        self._refresh_predictions(candidates, day)
        return [self._decide_one(lg, day) for lg in candidates]

    def _refresh_predictions(self, ledgers: list[BuyerLedger], day: date) -> None:
        """Re-infer, in one batched call, every buyer whose belief is stale."""
        stale: list[BuyerLedger] = []
        for lg in ledgers:
            bid = lg.buyer.buyer_id
            cached = self._pred_cache.get(bid)
            if cached is None:
                stale.append(lg)
                continue
            _, inferred_on, seen = cached
            if (day - inferred_on).days >= REINFER_AFTER_DAYS or len(lg.received) != seen:
                stale.append(lg)
        if not stale:
            return
        fvs = [extract_features(lg, self.beliefs.get(lg.buyer.buyer_id), day) for lg in stale]
        if hasattr(self.model, "predict_many"):
            preds = self.model.predict_many(fvs)
        else:
            preds = [self.model.predict(fv) for fv in fvs]
        for lg, pred in zip(stale, preds):
            self._pred_cache[lg.buyer.buyer_id] = (pred, day, len(lg.received))

    def _decide_one(self, ledger: BuyerLedger, day: date) -> Decision:
        buyer_id = ledger.buyer.buyer_id
        bb = self.beliefs.get(buyer_id)

        pred = self._infer(ledger, bb, day)
        bb.archetype, bb.confidence = pred.archetype, pred.confidence

        scored = self._score_actions(ledger, pred, day)
        ranked = [a for a, _ in sorted(scored.items(), key=lambda kv: -kv[1])]

        gates = self.guardrails.filter(
            ranked,
            ledger,
            bb,
            day,
            merchant_udyam=self.merchant_udyam.get(buyer_id, True),
        )
        allowed = set(gates.allowed)

        chosen = Intervention.HOLD
        for action in ranked:
            if action in allowed and scored[action] > 0:
                chosen = action
                break

        return Decision(
            buyer_id=buyer_id,
            as_of=day,
            chosen=chosen,
            rationale=self._explain(chosen, ledger, pred, scored, gates, day),
            considered=ranked[:5],
            gates=gates.results,
            inferred_archetype=None if pred.cold_start else pred.archetype,
            archetype_confidence=pred.confidence,
            requires_human_approval=gates.requires_approval and chosen is not Intervention.HOLD,
            decided_by="guardrail" if (chosen is Intervention.HOLD and gates.blocked()) else "policy",
        )

    def _infer(self, ledger: BuyerLedger, bb, day: date) -> Prediction:
        cached = self._pred_cache.get(ledger.buyer.buyer_id)
        if cached is not None:
            return cached[0]
        pred = self.model.predict(extract_features(ledger, bb, day))
        self._pred_cache[ledger.buyer.buyer_id] = (pred, day, len(ledger.received))
        return pred

    # -- scoring ----------------------------------------------------------

    def _score_actions(
        self, ledger: BuyerLedger, pred: Prediction, day: date
    ) -> dict[Intervention, float]:
        outstanding = float(ledger.overdue_amount(day))
        at_risk = outstanding * AT_RISK_FRACTION

        posterior = pred.posterior if not pred.cold_start else archetype_mix()
        confident = (not pred.cold_start) and pred.top_two_margin() >= MIN_MARGIN_FOR_TARGETED_ACTION

        blocked = ledger.intake_blocked()
        blocked_value = float(sum(iv.outstanding for iv in blocked))

        scores: dict[Intervention, float] = {}
        for action in Intervention:
            if action is Intervention.HOLD:
                scores[action] = 0.0
                continue

            # Expected gain, marginalised over what the buyer might be.
            gain = sum(p * (BELIEVED_UPLIFT[action][a] - 1.0) for a, p in posterior.items()) * at_risk

            # A document chase on a buyer whose invoices are demonstrably stuck
            # at intake is not a guess about archetype - it is a fact about our
            # own filing, and it is scored against the blocked value directly.
            if action is Intervention.DOCUMENT_RECONCILE:
                if blocked:
                    gain += blocked_value * 0.35
                else:
                    # Nothing is stuck. Chasing paperwork that is already in
                    # order is pure noise.
                    gain *= 0.15

            # Diminishing returns on repetition.
            tried = sum(1 for m in ledger.sent if m.intervention is action)
            if tried:
                gain *= REPEAT_DECAY**tried

            cost = (
                RELATIONSHIP_COST[action] * PAISE_PER_RELATIONSHIP_POINT
                + HUMAN_MINUTES[action] * PAISE_PER_HUMAN_MINUTE
            )

            # Under an uninformative posterior, only act where the action is
            # sound whichever hypothesis is true.
            if not confident and action not in SAFE_UNDER_UNCERTAINTY:
                gain *= 0.25

            scores[action] = gain - cost

        return scores

    # -- explanation ------------------------------------------------------

    def _explain(
        self,
        chosen: Intervention,
        ledger: BuyerLedger,
        pred: Prediction,
        scored: dict[Intervention, float],
        gates,
        day: date,
    ) -> str:
        dpd = ledger.oldest_dpd(day)
        blocked = ledger.intake_blocked()

        if chosen is Intervention.HOLD:
            failed = gates.blocked()
            if failed:
                # Name the rule that produced the silence. "The agent chose not
                # to send" is only evidence if it says why.
                first = failed[0]
                return f"Holding - {first.gate}: {first.reason}"
            best = max(scored.items(), key=lambda kv: kv[1])
            return (
                f"Holding - no action clears its own cost "
                f"(best was {best[0].value} at {best[1] / 100:,.0f} rupees expected)."
            )

        who = (
            "cause unknown (cold start)"
            if pred.cold_start
            else f"{pred.archetype.value} at {pred.confidence:.0%} (margin {pred.top_two_margin():.0%})"
        )
        why = f"{chosen.value}: {who}; oldest invoice {dpd}d overdue"
        if chosen is Intervention.DOCUMENT_RECONCILE and blocked:
            why += (
                f"; {len(blocked)} invoice(s) blocked at intake, not unpaid by choice"
            )
        return why + "."
