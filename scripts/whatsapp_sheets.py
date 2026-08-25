"""Short, paste-into-WhatsApp version of the elicitation sheets.

The full sheets ask for 14 replies and open with a consent paragraph. That is
correct for a form and too heavy for a chat: the realistic failure mode of this
whole study is not bad data, it is nobody replying because the ask looked like
homework.

This emits 8 scenarios per contributor as a single message someone can paste
into WhatsApp, plus a one-line preamble. Same scenarios, same rule that none of
them names an intent - only the packaging changes.

    python scripts/whatsapp_sheets.py --contributors 8
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Sibling script, not a package: add its own directory rather than relying on
# the caller to set PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from elicit import CONTEXT_VARIANTS, SCENARIOS  # noqa: E402

PREAMBLE = (
    "Hi! Doing a student project on how businesses reply to payment reminders. "
    "Can you help - 5 mins?\n\n"
    "Below are {n} situations. For each, just type what you'd ACTUALLY reply if "
    "you were the one who owes the money. Short is fine. Hinglish, typos, "
    "WhatsApp style - please don't make it formal, that's the whole point.\n\n"
    "Please make everything up - no real company names, amounts or transaction "
    "numbers. Your replies go into an open dataset used to test whether AI can "
    "read messages like these. Skip any you don't want to answer."
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contributors", type=int, default=8)
    ap.add_argument("--per-contributor", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20260824)
    ap.add_argument("--out", type=Path, default=Path("data/corpus/whatsapp"))
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    for c in range(args.contributors):
        pool = SCENARIOS[:]
        rng.shuffle(pool)
        lines = [PREAMBLE.format(n=args.per_contributor), ""]
        items = []
        for k in range(args.per_contributor):
            text = (pool[k % len(pool)] + " " + rng.choice(CONTEXT_VARIANTS)).strip()
            lines.append(f"{k + 1}. {text}")
            lines.append("")
            items.append(
                {"item_id": f"w{c + 1:02d}_i{k + 1:02d}", "scenario": text, "reply": ""}
            )

        stem = args.out / f"w{c + 1:02d}"
        stem.with_suffix(".txt").write_text("\n".join(lines), encoding="utf-8")
        stem.with_suffix(".json").write_text(
            json.dumps({"contributor": f"w{c + 1:02d}", "items": items}, indent=2,
                       ensure_ascii=False),
            encoding="utf-8",
        )

    print(f"{args.contributors} sheets x {args.per_contributor} items -> {args.out}")
    print(f"potential corpus: {args.contributors * args.per_contributor} replies\n")
    print("Send the .txt to each person. As replies come back, paste each one into")
    print("the matching .json, then:  unblocked corpus")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
