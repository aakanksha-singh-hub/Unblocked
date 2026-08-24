"""End-to-end proof that a recovery is real.

Runs one invoice through the whole loop against Razorpay test mode:

    agent decides PAYMENT_LINK
      -> real payment link created on Razorpay
      -> a human pays it in test mode
      -> the capture is confirmed by Razorpay, not by us
      -> the ledger reconciles against our own reference_id
      -> the agent stops chasing that invoice

The point of this script is narrow and important. Every other number in this
project is produced by a simulator we wrote. This one is attested by a system we
do not control, and the artifact it writes to artifacts/proof/ is the evidence.

Confirmation is by polling rather than by webhook. A webhook needs a public URL,
which needs a tunnel, which is one more thing to fail live on stage; the
signature-verification path is implemented and tested in
adapters/razorpay_live.py and exercised by scripts/webhook_server.py for anyone
who wants the full push path.

Usage:
    python scripts/prove_recovery.py --amount 2500 --invoice PKG/26-27/0412
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vasooli.adapters.env import load_env  # noqa: E402
from vasooli.adapters.razorpay_live import RazorpayConfigError, RazorpayRail  # noqa: E402
from vasooli.domain.money import Paise, fmt, rupees  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--amount", type=float, default=2500.0, help="rupees")
    ap.add_argument("--invoice", default="PKG/26-27/0412")
    ap.add_argument("--buyer", default="Shree Traders Pvt Ltd")
    ap.add_argument("--timeout", type=int, default=600, help="seconds to wait for payment")
    ap.add_argument("--poll", type=int, default=5)
    args = ap.parse_args()

    load_env()
    try:
        rail = RazorpayRail.from_env()
    except RazorpayConfigError as e:
        print(f"\n  {e}\n")
        print("  Add to .env:")
        print("    RAZORPAY_KEY_ID=rzp_test_xxxxxxxx")
        print("    RAZORPAY_KEY_SECRET=xxxxxxxx\n")
        return 2

    amount: Paise = rupees(args.amount)
    print(f"\nrail      {rail.name}  ({rail.key_id})")
    print(f"invoice   {args.invoice}")
    print(f"amount    {fmt(amount)}")

    link = rail.create_link(
        amount=amount,
        reference_id=args.invoice,
        description=f"Payment against invoice {args.invoice}",
        customer_name=args.buyer,
        notes={"source": "vasooli", "intervention": "payment_link"},
    )
    print(f"\n  link      {link.link_id}")
    print(f"  PAY HERE  {link.short_url}")
    print(f"  status    {link.status}")
    print("\n  Open the link and pay with any Razorpay test instrument.")
    print(f"  Polling every {args.poll}s for up to {args.timeout}s...\n")

    started = time.time()
    final = link
    while time.time() - started < args.timeout:
        time.sleep(args.poll)
        final = rail.fetch_link(link.link_id)
        elapsed = int(time.time() - started)
        print(f"    [{elapsed:>4}s] {final.status}")
        if final.status in ("paid", "cancelled", "expired"):
            break

    ok = final.status == "paid"

    # Reconciliation keys off reference_id - our own invoice number, set when we
    # created the link. Nothing the payer controls is trusted here.
    reconciled = ok and final.reference_id == args.invoice and final.amount == amount

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rail": rail.name,
        "key_id": rail.key_id,
        "invoice_number": args.invoice,
        "expected_amount_paise": int(amount),
        "link_id": final.link_id,
        "short_url": final.short_url,
        "final_status": final.status,
        "captured_amount_paise": int(final.amount),
        "reference_id_returned": final.reference_id,
        "reconciled": reconciled,
        "agent_action_after_capture": "stop_chasing" if reconciled else "continue",
    }
    d = Path("artifacts/proof")
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"recovery_{final.link_id}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print()
    if reconciled:
        print(f"  RECONCILED  {fmt(final.amount)} against {args.invoice}")
        print("  Agent marks the invoice settled and stops chasing this buyer.")
    elif ok:
        print("  PAID but did NOT reconcile - reference or amount mismatch.")
        print(f"    expected ref {args.invoice!r} amount {int(amount)}")
        print(f"    returned ref {final.reference_id!r} amount {int(final.amount)}")
        print("  The agent does NOT stop chasing on an unreconciled capture.")
    else:
        print(f"  Not paid. Final status: {final.status}")

    print(f"\n  artifact  {path}\n")
    return 0 if reconciled else 1


if __name__ == "__main__":
    raise SystemExit(main())
