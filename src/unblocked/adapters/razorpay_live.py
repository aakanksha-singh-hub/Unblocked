"""Razorpay test-mode adapter.

Test mode only, and it refuses to run otherwise. Razorpay test keys are prefixed
`rzp_test_`; a `rzp_live_` key raises at construction rather than at request
time. A collections agent that can issue real payment demands by configuration
accident is not a thing that should exist, and the check costs one line.

What this buys the project: the claim "recovered" stops being our own
bookkeeping. A captured payment here is attested by Razorpay's dashboard.
"""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256

import httpx

from ..domain.money import Paise
from .rail import CapturedPayment, PaymentLink

API_BASE = "https://api.razorpay.com/v1"


class RazorpayConfigError(RuntimeError):
    pass


@dataclass
class RazorpayRail:
    key_id: str
    key_secret: str
    name: str = "razorpay-test"
    timeout: float = 20.0
    _client: httpx.Client | None = None

    def __post_init__(self) -> None:
        if not self.key_id or not self.key_secret:
            raise RazorpayConfigError(
                "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set. "
                "Get them from dashboard.razorpay.com in Test Mode."
            )
        if not self.key_id.startswith("rzp_test_"):
            raise RazorpayConfigError(
                f"Refusing to start with key id {self.key_id[:12]!r}. This project "
                "runs against test mode only - a live key here would issue real "
                "payment demands to real people."
            )

    @classmethod
    def from_env(cls) -> RazorpayRail:
        return cls(
            key_id=os.environ.get("RAZORPAY_KEY_ID", ""),
            key_secret=os.environ.get("RAZORPAY_KEY_SECRET", ""),
        )

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=API_BASE,
                auth=(self.key_id, self.key_secret),
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )
        return self._client

    # -- links ------------------------------------------------------------

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
        payload: dict = {
            # Razorpay takes paise, which is why the whole system stores paise.
            # No conversion happens here, and that is the point.
            "amount": int(amount),
            "currency": "INR",
            "description": description[:2048],
            "reference_id": reference_id,
            "customer": {"name": customer_name},
            # Reminders are Razorpay's own nagging. We disable it: the agent
            # decides when to contact someone, under stopping rules the rail
            # knows nothing about, and a second uncoordinated reminder stream
            # would violate them silently.
            "reminder_enable": False,
            "notify": {"sms": False, "email": False},
            "notes": notes or {},
        }
        if customer_email:
            payload["customer"]["email"] = customer_email
        if customer_phone:
            payload["customer"]["contact"] = customer_phone
        if expire_by:
            payload["expire_by"] = int(
                datetime.combine(expire_by, datetime.min.time(), tzinfo=timezone.utc).timestamp()
            )

        r = self.client.post("/payment_links", json=payload)
        self._raise_for_status(r)
        return self._to_link(r.json())

    def fetch_link(self, link_id: str) -> PaymentLink:
        r = self.client.get(f"/payment_links/{link_id}")
        self._raise_for_status(r)
        return self._to_link(r.json())

    def cancel_link(self, link_id: str) -> PaymentLink:
        r = self.client.post(f"/payment_links/{link_id}/cancel")
        self._raise_for_status(r)
        return self._to_link(r.json())

    def _to_link(self, d: dict) -> PaymentLink:
        created = d.get("created_at")
        return PaymentLink(
            link_id=d["id"],
            short_url=d.get("short_url", ""),
            amount=Paise(int(d.get("amount", 0))),
            reference_id=d.get("reference_id") or "",
            status=d.get("status", "unknown"),
            created_on=(
                datetime.fromtimestamp(created, tz=timezone.utc).date() if created else date.today()
            ),
        )

    @staticmethod
    def _raise_for_status(r: httpx.Response) -> None:
        if r.is_success:
            return
        try:
            err = r.json().get("error", {})
            detail = f"{err.get('code')}: {err.get('description')}"
        except Exception:
            detail = r.text[:400]
        raise RuntimeError(f"Razorpay {r.status_code} on {r.request.url.path} - {detail}")


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


def verify_webhook(raw_body: bytes, signature: str, secret: str) -> bool:
    """Constant-time HMAC-SHA256 check on the *raw* request body.

    Two things that are easy to get wrong and both silently accept forgeries:
    the digest must be over the exact bytes received - re-serialising the parsed
    JSON changes whitespace and key order and breaks the comparison - and the
    comparison must be constant-time. `==` on an hmac digest leaks timing.
    """
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_capture(raw_body: bytes) -> CapturedPayment | None:
    """Read a `payment_link.paid` webhook into a CapturedPayment.

    Verify the signature before calling this. Returns None for any other event,
    so an unrecognised webhook is ignored rather than misread.
    """
    event = json.loads(raw_body)
    if event.get("event") != "payment_link.paid":
        return None

    payload = event.get("payload", {})
    link = payload.get("payment_link", {}).get("entity", {})
    pay = payload.get("payment", {}).get("entity", {})

    return CapturedPayment(
        payment_id=pay.get("id", ""),
        link_id=link.get("id"),
        amount=Paise(int(pay.get("amount", link.get("amount", 0)))),
        # Our own invoice number, set when the link was created. Reconciliation
        # keys off this rather than off anything the payer controls.
        reference_id=link.get("reference_id") or "",
        method=pay.get("method", "unknown"),
        acquirer_reference=(pay.get("acquirer_data") or {}).get("rrn"),
    )
