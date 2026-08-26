"""Emit one CSV per annotator from the built corpus.

Two files, identical content, shuffled differently so the annotators do not
drift into the same order-driven habits. Neither contains any label, any model
output, or the other annotator's file.

    python scripts/make_annotation_sheets.py
    # -> data/corpus/annotate_a.csv, annotate_b.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from unblocked.domain.enums import ReplyIntent  # noqa: E402

HEADER = [
    "item_id",
    "scenario",
    "reply",
    "intent",
    "promised_date_raw",
    "promised_date_resolved",
    "disputed_amount",
    "claimed_utr",
    "documents_requested",
    "confidence",
]

GUIDE = (
    f"intent must be one of: {', '.join(i.value for i in ReplyIntent)}  |  "
    "confidence must be 'clear' or 'ambiguous'  |  "
    "see docs/CODEBOOK.md  |  do NOT discuss items with the other annotator "
    "until both files are complete"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=Path("data/corpus/replies.jsonl"))
    ap.add_argument("--seed", type=int, default=20260824)
    ap.add_argument(
        "--all", action="store_true",
        help="include items that already carry a label. By default only new items "
             "are emitted, so a second round does not ask an annotator to re-judge "
             "work they have already done - which wastes their time and invites "
             "them to contradict their own earlier call.",
    )
    args = ap.parse_args()

    if not args.corpus.exists():
        print(f"{args.corpus} not found. Run scripts/build_corpus.py first.")
        return 1

    items = [json.loads(line) for line in args.corpus.read_text(encoding="utf-8").splitlines()]

    already: set[str] = set()
    if not args.all:
        for name in ("a", "b"):
            for prior in sorted(args.corpus.parent.glob(f"LABELLED_annotator_{name}_round*.csv")):
                lines = [l for l in prior.read_text(encoding="utf-8").splitlines()
                         if not l.startswith("#")]
                for row in csv.DictReader(lines):
                    if (row.get("intent") or "").strip():
                        already.add((row.get("item_id") or "").strip())
        if already:
            before = len(items)
            items = [i for i in items if i["item_id"] not in already]
            print(f"  {before - len(items)} already labelled, {len(items)} new")

    # Round number in the filename. An earlier round produced annotate_a.csv
    # beside annotate_a_filled.csv, and the filled one - being the one that
    # looked finished - got copied and returned as the new round's work. Two
    # files that differ only by a suffix are an invitation to hand back the
    # wrong one.
    rnd = 1
    while (args.corpus.parent / f"LABELLED_annotator_a_round{rnd}.csv").exists():
        rnd += 1

    for name, salt in (("a", 1), ("b", 2)):
        rows = items[:]
        random.Random(args.seed + salt).shuffle(rows)
        path = args.corpus.parent / f"TO_LABEL_annotator_{name}_round{rnd}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            f.write(f"# ROUND {rnd} — fill the 'intent' and 'confidence' columns below,\n")
            f.write(f"# then save this file as: LABELLED_annotator_{name}_round{rnd}.csv\n")
            f.write(f"# {GUIDE}\n")
            w = csv.DictWriter(f, fieldnames=HEADER, extrasaction="ignore")
            w.writeheader()
            for it in rows:
                w.writerow(
                    {
                        "item_id": it["item_id"],
                        "scenario": it["scenario"],
                        "reply": it["reply"],
                    }
                )
        print(f"  {path}  ({len(rows)} items)")

    print(f"\nSend one file to each annotator. They fill 'intent' and 'confidence'")
    print("at minimum; the other columns only where the reply states them.")
    print(f"They save their work as LABELLED_annotator_<a|b>_round{rnd}.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
