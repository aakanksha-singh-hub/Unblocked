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

from unblocked.eval.provenance import audit  # noqa: E402

#: Both elicitation formats land under data/corpus. Scanning only the long-form
#: directory meant `unblocked corpus` reported "no replies found" while a full set
#: of WhatsApp replies sat in the sibling folder.
SHEET_DIRS = (
    Path("data/corpus/hinglish"),
    Path("data/corpus/round2"),
    Path("data/corpus/sheets"),
    Path("data/corpus/whatsapp"),
)
OUT = Path("data/corpus/replies.jsonl")


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-frac", type=float, default=0.55)
    ap.add_argument("--seed", type=int, default=20260824)
    ap.add_argument(
        "--sheets", type=Path, default=None,
        help="a single sheet directory; by default every known one is scanned",
    )
    ap.add_argument(
        "--allow-pilot",
        action="store_true",
        help="build even when the provenance audit says the corpus cannot carry "
             "evidential weight. The tier is written into the corpus either way.",
    )
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    items: list[dict] = []
    seen: set[str] = set()
    empty = dupes = 0

    sheet_dirs = [args.sheets] if args.sheets else [d for d in SHEET_DIRS if d.exists()]
    for path in sorted(p for d in sheet_dirs for p in d.glob("*.json")):
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
        looked = ", ".join(str(d) for d in sheet_dirs) or "(no sheet directory exists)"
        print(f"No replies found. Looked in: {looked}")
        print("Contributors fill the 'reply' field of each item. Nothing to build yet.")
        return 1

    # Provenance audit BEFORE anything else. A corpus that does not look like
    # several people writing naturally cannot carry the weight the protocol
    # assigns to it, and the tier travels with the data rather than living in
    # someone's memory of a conversation.
    report = audit([(i["contributor"], i["item_id"], i["reply"]) for i in items])
    print(report.summary())
    print()
    tier = "pilot" if report.verdict.startswith("PILOT") else "evidence"
    if tier == "pilot" and not args.allow_pilot:
        print("Refusing to build. This corpus is PILOT quality: it can prove the")
        print("pipeline runs, and it cannot be quoted as a measurement.")
        print("Re-run with --allow-pilot to build it as a labelled pilot set.")
        return 2

    # Existing split assignments are honoured; only NEW contributors are drawn.
    #
    # A corpus that grows is normal - more people reply - but redrawing the whole
    # split each time would quietly move items between dev and test, which is how
    # a "test opened once" claim becomes untrue without anyone deciding to make
    # it untrue. Contributors already assigned keep their side. New ones are
    # drawn against the same seed, and the lock records that the corpus grew and
    # how many times.
    prior_split: dict[str, str] = {}
    prior_rounds = 0
    if args.out.exists():
        for line in args.out.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            prior_split[rec["contributor"]] = rec["split"]
    lock = args.out.parent / "CORPUS_LOCK.txt"
    if lock.exists():
        for line in lock.read_text(encoding="utf-8").splitlines():
            if line.startswith("build rounds"):
                prior_rounds = int(line.split("=")[1].strip())

    # Split by CONTRIBUTOR, not by item. Two replies from the same person share
    # their idiom and their habits; splitting by item would leak that across the
    # boundary and quietly inflate the test number.
    contributors = sorted({i["contributor"] for i in items})
    fresh = [c for c in contributors if c not in prior_split]

    test_group = {c for c, sp in prior_split.items() if sp == "test"}
    if fresh:
        rng = random.Random(args.seed + prior_rounds)
        rng.shuffle(fresh)
        want = round(len(contributors) * args.test_frac) - len(test_group)
        test_group |= set(fresh[: max(0, want)])

    for it in items:
        it["split"] = "test" if it["contributor"] in test_group else "dev"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for it in sorted(items, key=lambda x: x["item_id"]):
            f.write(json.dumps({**it, "tier": tier}, ensure_ascii=False) + "\n")

    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()[:16]
    rounds = prior_rounds + 1
    (args.out.parent / "CORPUS_LOCK.txt").write_text(
        f"TIER               = {tier.upper()}\n"
        f"build rounds       = {rounds}\n"
        + ("" if tier == "evidence" else
           "  This corpus did NOT pass the provenance audit. It proves the\n"
           "  pipeline runs end to end. It is not evidence, is not quoted as a\n"
           "  measurement anywhere, and does not appear in the README results.\n\n")
        + f"corpus sha256[:16] = {digest}\n"
        f"items              = {len(items)}\n"
        f"contributors       = {len(contributors)}\n"
        f"test contributors  = {sorted(test_group)}\n"
        f"split seed         = {args.seed}\n"
        f"\nSplit drawn at build time, before any model output was inspected.\n"
        f"Contributors keep the side they were first assigned; only new ones are\n"
        f"drawn. If this hash changes, the corpus changed.\n"
        + ("" if rounds == 1 else
           f"\nThis corpus has been built {rounds} times. The test split has therefore\n"
           f"been looked at more than once, and any report using it must say so:\n"
           f"a second scoring is a second look, however the items were added.\n"),
        encoding="utf-8",
    )

    n_dev = sum(1 for i in items if i["split"] == "dev")
    print(f"[{tier.upper()}] {len(items)} replies from {len(contributors)} contributors")
    print(f"  skipped: {empty} empty, {dupes} duplicate")
    print(f"  dev  {n_dev}   test {len(items) - n_dev}")
    print(f"  -> {args.out}   hash {digest}")
    print(f"  -> {args.out.parent / 'CORPUS_LOCK.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
