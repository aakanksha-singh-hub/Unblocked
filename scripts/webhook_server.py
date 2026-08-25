"""Optional push path: a webhook receiver for `payment_link.paid`.

Not needed for the demo - scripts/prove_recovery.py polls instead, because a
webhook needs a public URL and a tunnel is one more thing to fail live. This
exists so the signature-verification path is exercised end to end rather than
only unit tested.

    python scripts/webhook_server.py --port 8787
    ngrok http 8787     # then point the Razorpay dashboard webhook at it

Every request is verified before it is read. An unverified body is never parsed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from unblocked.adapters.env import load_env  # noqa: E402
from unblocked.adapters.razorpay_live import parse_capture, verify_webhook  # noqa: E402
from unblocked.domain.money import fmt  # noqa: E402

SECRET = ""
LOG = Path("artifacts/proof/webhook_events.jsonl")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        sig = self.headers.get("X-Razorpay-Signature", "")

        if not verify_webhook(raw, sig, SECRET):
            # Reject before parsing. An unverified payload is attacker-controlled
            # and must not reach json.loads, let alone the ledger.
            print("  REJECTED  bad or missing signature")
            self.send_response(401)
            self.end_headers()
            return

        cap = parse_capture(raw)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

        if cap is None:
            print(f"  ignored   {json.loads(raw).get('event')}")
            return

        print(f"  CAPTURED  {fmt(cap.amount)} ref={cap.reference_id} via {cap.method}")
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "at": datetime.now(timezone.utc).isoformat(),
                        "payment_id": cap.payment_id,
                        "link_id": cap.link_id,
                        "reference_id": cap.reference_id,
                        "amount_paise": int(cap.amount),
                        "method": cap.method,
                        "acquirer_reference": cap.acquirer_reference,
                    }
                )
                + "\n"
            )

    def log_message(self, *a) -> None:
        pass


def main() -> int:
    global SECRET
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()

    load_env()
    import os

    SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not SECRET:
        print("RAZORPAY_WEBHOOK_SECRET is not set. Every request would be rejected.")
        return 2

    print(f"listening on :{args.port}  (POST /)  -> {LOG}")
    HTTPServer(("0.0.0.0", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
