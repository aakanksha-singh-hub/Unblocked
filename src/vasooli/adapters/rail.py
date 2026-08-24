"""Payment rail interface.

Two implementations sit behind this: a deterministic mock used by every
simulation run, and a live adapter that talks to Razorpay test mode.

The split matters for a specific reason. Money recovered inside a simulator we
wrote is a number our own code printed. One payment captured on Razorpay's
dashboard is a categorically different kind of claim - it is attested by a
system we do not control. The interface exists so the agent's decision logic is
byte-identical in both cases: the same policy that issues 4,800 mock links in an
evaluation issues the real one in the demo, with no separate demo path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from ..domain.money import Paise


@dataclass(frozen=True)
class PaymentLink:
    link_id: str
    short_url: str
    amount: Paise
    reference_id: str
    status: str
    created_on: date


@dataclass(frozen=True)
class CapturedPayment:
    """A payment the rail says actually happened."""

    payment_id: str
    link_id: str | None
    amount: Paise
    reference_id: str
    method: str
    #: Bank/UPI reference, where the rail exposes one.
    acquirer_reference: str | None = None


@runtime_checkable
class PaymentRail(Protocol):
    name: str

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
        """Issue a payment link for an outstanding amount.

        `reference_id` carries our invoice number so the webhook can be
        reconciled back to the ledger without trusting anything in the payload
        we did not set ourselves.
        """
        ...

    def fetch_link(self, link_id: str) -> PaymentLink: ...

    def cancel_link(self, link_id: str) -> PaymentLink:
        """Withdraw a link. Called when the invoice is settled another way -
        leaving a live link on a paid invoice is how duplicate payments happen."""
        ...
