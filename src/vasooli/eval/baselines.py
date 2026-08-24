"""The three baselines and the oracle ceiling.

Chosen to bracket the space rather than to be beaten. `never_chase` in
particular is a serious competitor on a book that is 30% prompt payers: an agent
that cannot beat doing nothing, once relationship and human cost are charged,
has not earned its existence.
"""

from __future__ import annotations

from datetime import date, timedelta

from ..agent.view import BuyerLedger, LedgerView
from ..domain.enums import Intervention
from ..domain.models import Decision


class NeverChase:
    """Send nothing. The floor, and the only policy with zero cost of any kind."""

    name = "never-chase"

    def observe(self, view: LedgerView, day: date) -> None:
        pass

    def decide(self, view: LedgerView, day: date) -> list[Decision]:
        return [
            Decision(
                buyer_id=lg.buyer.buyer_id,
                as_of=day,
                chosen=Intervention.HOLD,
                rationale="Policy sends nothing by construction.",
                decided_by="policy",
            )
            for lg in view.buyers_with_open()
            if lg.oldest_dpd(day) == 0  # log once, on the day each buyer first goes overdue
        ]


class BlastWeekly:
    """Contact every buyer with anything overdue, every seven days.

    The strategy contact fatigue is designed to punish. Its breakeven against
    the cause-matched policy is the first number in the report, because our
    headline finding is only as good as the fatigue constant that produces it.
    """

    name = "blast-weekly"

    #: A SOFT_NUDGE, not a FIRM_REMINDER. This is the charitable reading of
    #: "chase everyone": a naive operator being persistent, not an aggressive
    #: one. At relationship cost 2 rather than 8 it survives the full horizon
    #: without churning most of the book, which makes it a genuinely hard
    #: baseline to beat instead of a strawman that destroys itself.
    ACTION = Intervention.SOFT_NUDGE

    def observe(self, view: LedgerView, day: date) -> None:
        pass

    def decide(self, view: LedgerView, day: date) -> list[Decision]:
        out: list[Decision] = []
        for lg in view.buyers_with_open():
            if lg.overdue_amount(day) <= 0:
                continue
            last = lg.last_contact(day)
            if last is not None and (day - last).days < 7:
                continue
            out.append(
                Decision(
                    buyer_id=lg.buyer.buyer_id,
                    as_of=day,
                    chosen=self.ACTION,
                    rationale=f"{lg.oldest_dpd(day)}d overdue; weekly cadence.",
                    considered=[self.ACTION],
                    decided_by="policy",
                )
            )
        return out


class StaticLadder:
    """30/60/90 escalation. What most collections software actually does.

    Escalates on age alone, which is the assumption under test: age is a proxy
    for severity only if every buyer is late for the same reason.
    """

    name = "static-ladder"

    #: Age-based rungs. The assumption under test: age is a proxy for severity
    #: only if every buyer is late for the same reason.
    RUNGS: list[tuple[int, Intervention]] = [
        (7, Intervention.SOFT_NUDGE),
        (30, Intervention.STATEMENT_OF_ACCOUNT),
        (45, Intervention.FIRM_REMINDER),
        (60, Intervention.PHONE_TASK),
        (90, Intervention.OWNER_ESCALATION),
    ]

    name = "static-ladder"

    def __init__(self) -> None:
        #: Rungs already fired per buyer. Real dunning software escalates to a
        #: rung once and then holds; an earlier version re-sent OWNER_ESCALATION
        #: every fortnight for the rest of the horizon, which churned 85% of the
        #: book and made this a strawman rather than a baseline. Beating a
        #: strawman would have proved nothing.
        self._fired: dict[str, set[Intervention]] = {}

    def observe(self, view: LedgerView, day: date) -> None:
        pass

    def _rung(self, dpd: int) -> Intervention | None:
        chosen = None
        for threshold, iv in self.RUNGS:
            if dpd >= threshold:
                chosen = iv
        return chosen

    def decide(self, view: LedgerView, day: date) -> list[Decision]:
        out: list[Decision] = []
        for lg in view.buyers_with_open():
            bid = lg.buyer.buyer_id
            dpd = lg.oldest_dpd(day)
            iv = self._rung(dpd)
            if iv is None or iv in self._fired.get(bid, ()):
                continue
            last = lg.last_contact(day)
            if last is not None and (day - last).days < 14:
                continue
            self._fired.setdefault(bid, set()).add(iv)
            out.append(
                Decision(
                    buyer_id=bid,
                    as_of=day,
                    chosen=iv,
                    rationale=f"Ladder rung for {dpd}d overdue (fires once).",
                    considered=[iv],
                    decided_by="policy",
                )
            )
        return out
