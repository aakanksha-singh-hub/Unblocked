"""The contract every policy implements. Deliberately tiny.

A policy sees a LedgerView and returns at most one Decision per buyer per day.
It does not send anything itself - the runner applies decisions, charges their
costs and records them - so a policy cannot bypass accounting, and the audit
trail is produced by the harness rather than trusted from the agent.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from ..agent.view import LedgerView
from ..domain.models import Decision


@runtime_checkable
class Policy(Protocol):
    name: str

    def decide(self, view: LedgerView, day: date) -> list[Decision]:
        """At most one decision per buyer. Omitting a buyer is equivalent to HOLD
        but is recorded as an omission rather than a considered hold, and the
        report distinguishes them - deliberate restraint and simply not looking
        are different things."""
        ...

    def observe(self, view: LedgerView, day: date) -> None:
        """Called before decide(), for policies that maintain belief state.

        Split from decide() so that stateful agents update from new replies even
        on days they choose to act on nobody.
        """
        ...
