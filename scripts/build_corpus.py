"""Turn returned contributor sheets into a locked, split corpus.

Run this once, when replies come back. It:

  - reads the filled-in sheets in data/corpus/sheets/*.json
  - drops empties and near-duplicates
  - assigns a dev/test split deterministically and writes it into the corpus
  - records a content hash

The split is drawn HERE, before anyone has looked at a model output, and the
hash is what makes that claim checkable rather than asserted. All prompt
iteration happens on dev. Test is scored once, at the end, and the number
reported is that number - not the best of several.

    python scripts/build_corpus.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

SHEETS = Path("data/corpus/sheets")
OUT = Path("data/corpus/replies.jsonl")


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-frac", type=float, default=0.55)
    ap.add_argument("--seed", type=int, default=20260824)
    ap.add_argument("--sheets", type=Path, default=SHEETS)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    items: list[dict] = []
    seen: set[str] = set()
    empty = dupes = 0

    for path in sorted(args.sheets.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        for it in blob.get("items", []):
            reply = (it.get("reply") or "").strip()
            if not reply:
                empty += 1
                continue
            key = normalise(reply)
            if not key or key in seen:
                dupes += 1
                continue
            seen.add(key)
            items.append(
                {
                    "item_id": it["item_id"],
                    "contributor": blob.get("contributor", path.stem),
                    "scenario": it.get("scenario", ""),
                    "reply": reply,
                }
            )

    if not items:
        print(f"No replies found in {args.sheets}/*.json")
        print("Contributors fill the 'reply' field of each item. Nothing to build yet.")
        return 1

    # Split by CONTRIBUTOR, not by item. Two replies from the same person share
    # their idiom and their habits; splitting by item would leak that across the
    # boundary and quietly inflate the test number.
    contributors = sorted({i["contributor"] for i in items})
    rng = random.Random(args.seed)
    rng.shuffle(contributors)
    n_test = max(1, round(len(contributors) * args.test_frac))
    test_group = set(contributors[:n_test])

    for it in items:
        it["split"] = "test" if it["contributor"] in test_group else "dev"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for it in sorted(items, key=lambda x: x["item_id"]):
            f.write(json.dumps(it, ensure_ascii=False) + "\n")

    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()[:16]
    (args.out.parent / "CORPUS_LOCK.txt").write_text(
        f"corpus sha256[:16] = {digest}\n"
        f"items              = {len(items)}\n"
        f"contributors       = {len(contributors)}\n"
        f"test contributors  = {sorted(test_group)}\n"
        f"split seed         = {args.seed}\n"
        f"\nSplit drawn at build time, before any model output was inspected.\n"
        f"Test is scored once. If this hash changes, the split changed too.\n",
        encoding="utf-8",
    )

    n_dev = sum(1 for i in items if i["split"] == "dev")
    print(f"{len(items)} replies from {len(contributors)} contributors")
    print(f"  skipped: {empty} empty, {dupes} duplicate")
    print(f"  dev  {n_dev}   test {len(items) - n_dev}")
    print(f"  -> {args.out}   hash {digest}")
    print(f"  -> {args.out.parent / 'CORPUS_LOCK.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
