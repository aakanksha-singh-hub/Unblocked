"""Payment rail tests. The webhook path gets the most attention because it is
the only place in this project where attacker-controlled bytes reach us."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from vasooli.adapters.mock_rail import MockRail
from vasooli.adapters.rail import PaymentRail
from vasooli.adapters.razorpay_live import (
    RazorpayConfigError,
    RazorpayRail,
    parse_capture,
    verify_webhook,
)

SECRET = "whsec_test_only"


def _signed(payload: dict) -> tuple[bytes, str]:
    raw = json.dumps(payload).encode()
    return raw, hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()


def _paid_event(ref: str = "PKG/26-27/0412", amount: int = 24800000) -> dict:
    return {
        "event": "payment_link.paid",
        "payload": {
            "payment_link": {"entity": {"id": "plink_X1", "reference_id": ref, "amount": amount}},
            "payment": {
                "entity": {
                    "id": "pay_Y2",
                    "amount": amount,
                    "method": "upi",
                    "acquirer_data": {"rrn": "401512345678"},
                }
            },
        },
    }


# --- live-key refusal --------------------------------------------------------


def test_refuses_live_keys():
    """A collections agent that can issue real payment demands by configuration
    accident should not be constructible."""
    with pytest.raises(RazorpayConfigError, match="test mode only"):
        RazorpayRail(key_id="rzp_live_abc123", key_secret="s")


def test_refuses_empty_keys():
    with pytest.raises(RazorpayConfigError):
        RazorpayRail(key_id="", key_secret="")


def test_accepts_test_keys():
    assert RazorpayRail(key_id="rzp_test_abc123", key_secret="s").name == "razorpay-test"


# --- webhook verification ----------------------------------------------------


def test_valid_signature_accepted():
    raw, sig = _signed(_paid_event())
    assert verify_webhook(raw, sig, SECRET)


def test_tampered_body_rejected():
    raw, sig = _signed(_paid_event())
    assert not verify_webhook(raw + b" ", sig, SECRET)


def test_amount_tampering_rejected():
    """The attack that matters: inflate the captured amount so the agent marks a
    larger invoice settled than was actually paid."""
    raw, sig = _signed(_paid_event(amount=24800000))
    forged = json.dumps(_paid_event(amount=99900000)).encode()
    assert not verify_webhook(forged, sig, SECRET)


def test_wrong_secret_rejected():
    raw, sig = _signed(_paid_event())
    assert not verify_webhook(raw, sig, "some_other_secret")


def test_missing_signature_rejected():
    raw, _ = _signed(_paid_event())
    assert not verify_webhook(raw, "", SECRET)


def test_missing_secret_rejects_rather_than_accepts():
    """Fail closed. An unconfigured secret must never mean 'skip verification'."""
    raw, sig = _signed(_paid_event())
    assert not verify_webhook(raw, sig, "")


def test_signature_is_over_raw_bytes_not_reserialised_json():
    """Re-serialising the parsed body changes whitespace and key order, so a
    verifier that hashes the reparsed form rejects every genuine webhook."""
    event = _paid_event()
    raw = json.dumps(event, indent=2, sort_keys=True).encode()
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    assert verify_webhook(raw, sig, SECRET)
    assert not verify_webhook(json.dumps(event).encode(), sig, SECRET)


# --- capture parsing ---------------------------------------------------------


def test_parses_capture():
    raw, _ = _signed(_paid_event())
    cap = parse_capture(raw)
    assert cap is not None
    assert cap.payment_id == "pay_Y2"
    assert cap.reference_id == "PKG/26-27/0412"
    assert cap.amount == 24800000
    assert cap.acquirer_reference == "401512345678"


def test_ignores_unrelated_events():
    for event in ("payment.failed", "payment_link.cancelled", "order.paid"):
        assert parse_capture(json.dumps({"event": event}).encode()) is None


def test_reference_id_survives_roundtrip():
    """Reconciliation keys off reference_id because it is the one field we set
    ourselves. If it did not round-trip, we would be reconciling on payer data."""
    raw, _ = _signed(_paid_event(ref="ACME/26-27/9931"))
    assert parse_capture(raw).reference_id == "ACME/26-27/9931"


# --- mock rail ---------------------------------------------------------------


def test_mock_satisfies_protocol():
    assert isinstance(MockRail(), PaymentRail)


def test_mock_link_ids_are_deterministic():
    a, b = MockRail(), MockRail()
    kw = dict(amount=100000, reference_id="X/1", description="d", customer_name="C")
    assert a.create_link(**kw).link_id == b.create_link(**kw).link_id


def test_mock_capture_marks_link_paid():
    r = MockRail()
    link = r.create_link(amount=100000, reference_id="X/1", description="d", customer_name="C")
    assert r.fetch_link(link.link_id).status == "created"
    cap = r.simulate_capture(link.link_id)
    assert r.fetch_link(link.link_id).status == "paid"
    assert cap.amount == 100000


def test_cancel_link():
    r = MockRail()
    link = r.create_link(amount=100000, reference_id="X/1", description="d", customer_name="C")
    assert r.cancel_link(link.link_id).status == "cancelled"
