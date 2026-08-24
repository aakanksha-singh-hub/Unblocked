"""Deterministic in-process rail. Used by every evaluation run.

Deterministic because the evaluation is: identical inputs must produce identical
link ids, or run artifacts stop being diffable. Nothing here touches the network.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

from ..domain.money import Paise
from .rail import CapturedPayment, PaymentLink


@dataclass
class MockRail:
    name: str = "mock"
    links: dict[str, PaymentLink] = field(default_factory=dict)
    captures: list[CapturedPayment] = field(default_factory=list)

    def _id(self, reference_id: str, amount: Paise) -> str:
        h = hashlib.blake2b(f"{reference_id}:{amount}".encode(), digest_size=7).hexdigest()
        return f"plink_mock{h}"

    def create_link(
        self,
        *,
        amount: Paise,
        reference_id: str,
        description: str,
        customer_name: str,
        customer_email: str | None = None,
        customer_phone: str | None = None,
        expire_by: date | None = None,
        notes: dict[str, str] | None = None,
    ) -> PaymentLink:
        link_id = self._id(reference_id, amount)
        link = PaymentLink(
            link_id=link_id,
            short_url=f"https://rzp.io/i/mock{link_id[-8:]}",
            amount=amount,
            reference_id=reference_id,
            status="created",
            created_on=expire_by or date.today(),
        )
        self.links[link_id] = link
        return link

    def fetch_link(self, link_id: str) -> PaymentLink:
        return self.links[link_id]

    def cancel_link(self, link_id: str) -> PaymentLink:
        cur = self.links[link_id]
        cancelled = PaymentLink(**{**cur.__dict__, "status": "cancelled"})
        self.links[link_id] = cancelled
        return cancelled

    def simulate_capture(self, link_id: str) -> CapturedPayment:
        """Test-only: mark a link paid. Not part of the PaymentRail protocol,
        because a real rail cannot pay itself."""
        link = self.links[link_id]
        self.links[link_id] = PaymentLink(**{**link.__dict__, "status": "paid"})
        cap = CapturedPayment(
            payment_id=f"pay_mock{link_id[-8:]}",
            link_id=link_id,
            amount=link.amount,
            reference_id=link.reference_id,
            method="upi",
        )
        self.captures.append(cap)
        return cap
