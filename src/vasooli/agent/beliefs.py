"""What the agent believes about a buyer, and how sure it is.

Kept separate from the simulator's truth *and* from the raw ledger, because the
distinction carries weight in the evaluation: a promise in `Beliefs` is one the
agent extracted from a reply and may have got wrong, while a promise in
simulator state is one the buyer actually made. The promise-respect metric scores
against the latter, so failing to notice a promise counts as breaking it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ..domain.enums import BuyerArchetype, ReplyIntent
from ..domain.models import Dispute, ExtractedReply, Promise


@dataclass
class BuyerBeliefs:
    buyer_id: str

    promises: list[Promise] = field(default_factory=list)
    disputes: list[Dispute] = field(default_factory=list)
    hardship_declared: bool = False
    hardship_declared_on: date | None = None

    #: Money received since hardship was declared. A buyer who said "cash nahi
    #: hai" in March and has since cleared two invoices is not in hardship any
    #: more, and continuing to shield them is not compassion - it is the agent
    #: refusing to look.
    paid_since_hardship: int = 0

    #: Unverified claims of payment. Held as claims, never as payments, until
    #: reconciled against the ledger. Believing a UTR the buyer typed is how a
    #: collections system stops chasing money that never arrived.
    unverified_payment_claims: list[ExtractedReply] = field(default_factory=list)

    documents_requested: list[str] = field(default_factory=list)

    #: Current archetype belief and confidence. Populated by inference, compared
    #: against truth only inside eval/.
    archetype: BuyerArchetype | None = None
    confidence: float = 0.0

    #: Replies the extractor declined to interpret. These are the queue a human
    #: should work, and their size is a headline operational number: an agent
    #: that abstains on everything has not automated anything.
    needs_human: list[str] = field(default_factory=list)

    #: Running count of what this buyer has said, by intent. The behavioural
    #: half of the feature vector: a buyer who has deflected to a payment cycle
    #: four times is telling you what it is.
    intent_counts: dict = field(default_factory=dict)

    #: Message ids already folded into these beliefs, so observe() is idempotent
    #: and re-reading the ledger cannot duplicate a promise.
    processed: set[str] = field(default_factory=set)

    def active_promise(self, as_of: date, grace: int = 3) -> Promise | None:
        live = [
            p
            for p in self.promises
            if p.status == "open" and as_of <= p.promised_date + timedelta(days=grace)
        ]
        return max(live, key=lambda p: p.made_on) if live else None

    def hardship_active(self, as_of: date, *, expiry_days: int = 60, clear_ratio: float = 0.25,
                        outstanding: int = 0) -> bool:
        """Whether the hardship shield still applies.

        Two ways it lifts. It expires, because a declaration made two months ago
        is a statement about two months ago; and it clears early on evidence of
        capacity, because someone paying substantial amounts is demonstrably able
        to pay. Both matter: without them a single sentence permanently disarms
        every firm action the agent has, which is how a well-meaning shield turns
        into a way of never collecting.
        """
        if not self.hardship_declared:
            return False
        if self.hardship_declared_on is None:
            # Declared but undated. A shield must fail closed: an unknown date
            # cannot be shown to have expired, and the cost of wrongly shielding
            # is a delayed reminder while the cost of wrongly un-shielding is
            # pressure on someone who has said they cannot pay.
            return True
        if (as_of - self.hardship_declared_on).days > expiry_days:
            return False
        if outstanding > 0 and self.paid_since_hardship >= outstanding * clear_ratio:
            return False
        return True

    def open_disputes(self) -> list[Dispute]:
        return [d for d in self.disputes if d.status == "open"]

    def note_intent(self, intent: ReplyIntent) -> None:
        self.intent_counts[intent] = self.intent_counts.get(intent, 0) + 1

    def broken_promises(self) -> int:
        return sum(1 for p in self.promises if p.status == "broken")


@dataclass
class Beliefs:
    buyers: dict[str, BuyerBeliefs] = field(default_factory=dict)

    def get(self, buyer_id: str) -> BuyerBeliefs:
        if buyer_id not in self.buyers:
            self.buyers[buyer_id] = BuyerBeliefs(buyer_id=buyer_id)
        return self.buyers[buyer_id]
