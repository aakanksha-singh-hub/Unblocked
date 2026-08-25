"""Score reply understanding against the human labels.

Reports in a fixed order, and the order is the point:

  1. inter-annotator agreement
  2. the majority-class baseline
  3. model numbers, with intervals, against that baseline
  4. the hard subset the annotators disagreed on
  5. the confusion matrix, with hardship -> refusal called out

If kappa comes back below 0.4, or a model's accuracy interval does not clear
the baseline, the finding is that the layer is unsupported - and that is what
gets reported, rather than the slide quietly disappearing.

    python scripts/score_extraction.py --split dev      # while iterating
    python scripts/score_extraction.py --split test     # once, at the end
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vasooli.adapters.env import load_env  # noqa: E402
from vasooli.agent.extract import RuleExtractor  # noqa: E402
from vasooli.domain.enums import Channel, ReplyIntent  # noqa: E402
from vasooli.domain.models import InboundMessage  # noqa: E402
from vasooli.eval.extraction import agreement, score  # noqa: E402

CORPUS = Path("data/corpus/replies.jsonl")


def read_labels(path: Path) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """Returns (intent by item, promised date by item, ambiguous item ids)."""
    intents: dict[str, str] = {}
    dates: dict[str, str] = {}
    ambiguous: set[str] = set()
    if not path.exists():
        return intents, dates, ambiguous
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
    for row in csv.DictReader(lines):
        item = (row.get("item_id") or "").strip()
        intent = (row.get("intent") or "").strip().lower()
        if not item or not intent:
            continue
        intents[item] = intent
        if (row.get("promised_date_resolved") or "").strip():
            dates[item] = row["promised_date_resolved"].strip()
        if (row.get("confidence") or "").strip().lower() == "ambiguous":
            ambiguous.add(item)
    return intents, dates, ambiguous


def _pilot(items: dict, args) -> int:
    """Extractor-vs-extractor comparison when no gold labels exist.

    This is not an evaluation and is never reported as one. It answers a narrower
    question that does not need labels: on this text, how often does the model
    reach a different reading from the patterns, and what does it see that they
    miss? Disagreements are exactly the items worth putting in front of an
    annotator first.
    """
    from vasooli.eval.extraction import cohens_kappa

    load_env()
    extractors = [("rules", RuleExtractor())]
    try:
        from vasooli.agent.llm_extract import LLMExtractor

        extractors.append(("llm", LLMExtractor()))
    except Exception as e:  # noqa: BLE001
        print(f"LLM extractor unavailable ({e}); nothing to compare against.")
        return 1

    preds: dict[str, dict[str, object]] = {name: {} for name, _ in extractors}
    spans: dict[str, dict[str, str]] = {name: {} for name, _ in extractors}
    dates: dict[str, dict[str, str]] = {name: {} for name, _ in extractors}

    for item_id in sorted(items):
        msg = InboundMessage(
            message_id=item_id, buyer_id="corpus", channel=Channel.WHATSAPP,
            received_at=datetime(2026, 6, 10, 12, 0), body=items[item_id]["reply"],
        )
        for name, ex in extractors:
            r = ex.extract(msg, date(2026, 6, 10))
            preds[name][item_id] = r.intent.value
            spans[name][item_id] = r.evidence_span or ""
            if r.promised_date:
                dates[name][item_id] = r.promised_date.isoformat()

    ids = sorted(items)
    a = [preds["rules"][i] for i in ids]
    b = [preds["llm"][i] for i in ids]
    same = sum(1 for x, y in zip(a, b) if x == y)

    print("=" * 70)
    print(f"PILOT: rules vs model   (n={len(ids)}, no gold labels)")
    print("=" * 70)
    print(f"  agree on intent   {same}/{len(ids)} ({same / len(ids):.0%})")
    print(f"  Cohen's kappa     {cohens_kappa(a, b):.3f}")
    print(f"  rules abstained   {sum(1 for x in a if x == 'unclear')}")
    print(f"  model abstained   {sum(1 for x in b if x == 'unclear')}")
    print(f"  dates: rules {len(dates['rules'])}, model {len(dates['llm'])}")

    print("\n  where they diverge (the items to annotate first):")
    shown = 0
    for i in ids:
        if preds["rules"][i] == preds["llm"][i]:
            continue
        shown += 1
        if shown > 12:
            continue
        print(f"    [{i}] {items[i]['reply'][:78]}")
        print(f"          rules={preds['rules'][i]:<20} model={preds['llm'][i]}")
    if shown > 12:
        print(f"    ... and {shown - 12} more")

    print("\n  This is a pilot on a corpus that did not pass the provenance audit.")
    print("  It shows the pipeline runs. It is not a measurement and is not")
    print("  reported as one.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    ap.add_argument("--a", type=Path, default=Path("data/corpus/annotate_a.csv"))
    ap.add_argument("--b", type=Path, default=Path("data/corpus/annotate_b.csv"))
    ap.add_argument("--adjudicated", type=Path, default=Path("data/corpus/adjudicated.csv"))
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

    if not args.corpus.exists():
        print(f"{args.corpus} not found.")
        print("Pipeline:  build_corpus.py -> make_annotation_sheets.py -> annotate -> this")
        return 1

    items = {
        it["item_id"]: it
        for it in (json.loads(ln) for ln in args.corpus.read_text(encoding="utf-8").splitlines())
        if args.split == "all" or it["split"] == args.split
    }
    if not items:
        print(f"No items in the {args.split} split.")
        return 1

    la, da, amb_a = read_labels(args.a)
    lb, db, amb_b = read_labels(args.b)
    la = {k: v for k, v in la.items() if k in items}
    lb = {k: v for k, v in lb.items() if k in items}

    print(f"corpus {args.corpus}   split={args.split}   items={len(items)}")
    print(f"labels: annotator A {len(la)}   annotator B {len(lb)}\n")

    if not la or not lb:
        print("No annotator labels yet - running the PILOT comparison instead.")
        print("Accuracy cannot be computed without gold labels. What can be")
        print("computed is where the rule baseline and the model disagree, which")
        print("is a real signal about what the model buys, on text neither wrote.\n")
        return _pilot(items, args)

    # 1. Agreement, first and unconditionally.
    ag = agreement(la, lb)
    print("=" * 70)
    print("1. INTER-ANNOTATOR AGREEMENT")
    print("=" * 70)
    print(f"  n={ag.n}   raw agreement {ag.raw_agreement:.3f}   Cohen's kappa {ag.kappa:.3f}")
    print(f"  verdict: {ag.verdict}\n")
    print("  per-class kappa (weakest first):")
    for label, k in sorted(ag.per_class.items(), key=lambda kv: kv[1]):
        print(f"    {label:24s} {k:.3f}")
    print(f"\n  {len(ag.disagreements)} disagreements -> the 'hard' subset")

    if ag.kappa < 0.4:
        print("\n  Kappa is below 0.4. The taxonomy is underspecified, and that is")
        print("  the finding. Model numbers below are reported but should not be")
        print("  quoted without this caveat.")

    # Gold: adjudicated where available, else the items both agreed on.
    adj, adj_dates, adj_amb = read_labels(args.adjudicated)
    gold = {k: la[k] for k in la if k in lb and la[k] == lb[k]}
    gold.update({k: v for k, v in adj.items() if k in items})
    ambiguous = (amb_a | amb_b | adj_amb) | {d[0] for d in ag.disagreements}
    gold_dates = {**da, **db, **adj_dates}

    unresolved = [i for i, _, _ in ag.disagreements if i not in adj]
    if unresolved:
        out = args.corpus.parent / "to_adjudicate.csv"
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["item_id", "reply", "annotator_a", "annotator_b", "intent", "confidence"])
            for i, x, y in ag.disagreements:
                if i in adj:
                    continue
                w.writerow([i, items[i]["reply"], x, y, "", ""])
        print(f"\n  {len(unresolved)} disagreements still unadjudicated -> {out}")
        print("  Resolve them together, save as adjudicated.csv, and re-run.")

    print(f"\n  gold labels available: {len(gold)}\n")
    if not gold:
        return 1

    # 2-5. Models.
    extractors = [("rules", RuleExtractor())]
    if not args.no_llm:
        load_env()
        try:
            from vasooli.agent.llm_extract import LLMExtractor

            llm = LLMExtractor()
            extractors.append((llm.name, llm))
        except Exception as e:  # noqa: BLE001
            print(f"  (LLM extractor unavailable: {e})\n")

    reports = []
    for name, ex in extractors:
        preds: dict[str, ReplyIntent] = {}
        abstained: set[str] = set()
        pred_dates: dict[str, str] = {}
        for item_id in sorted(gold):
            it = items[item_id]
            msg = InboundMessage(
                message_id=item_id,
                buyer_id="corpus",
                channel=Channel.WHATSAPP,
                received_at=datetime(2026, 6, 10, 12, 0),
                body=it["reply"],
            )
            r = ex.extract(msg, date(2026, 6, 10))
            preds[item_id] = r.intent
            if r.abstained:
                abstained.add(item_id)
            if r.promised_date:
                pred_dates[item_id] = r.promised_date.isoformat()

        rep = score(
            name,
            gold,
            preds,
            split=args.split,
            ambiguous=ambiguous,
            abstained=abstained,
            gold_dates=gold_dates,
            pred_dates=pred_dates,
        )
        reports.append(rep)
        print("=" * 70)
        print(rep.summary())
        print()

        confusion: dict[tuple[str, str], int] = {}
        for i in sorted(gold):
            confusion[(gold[i], preds[i].value)] = confusion.get((gold[i], preds[i].value), 0) + 1
        harm = confusion.get(("hardship", "refusal"), 0)
        n_hard = sum(1 for i in gold if gold[i] == "hardship")
        print(
            f"  hardship read as refusal: {harm}/{n_hard} "
            "- reading someone who cannot pay as someone who will not"
        )
        print()

    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/extraction_report.json").write_text(
        json.dumps(
            {
                "split": args.split,
                "n_items": len(items),
                "kappa": ag.kappa,
                "raw_agreement": ag.raw_agreement,
                "per_class_kappa": ag.per_class,
                "n_disagreements": len(ag.disagreements),
                "gold_labels": len(gold),
                "reports": [
                    {
                        "extractor": r.extractor,
                        "n": r.n,
                        "accuracy": r.accuracy,
                        "accuracy_ci": list(r.accuracy_ci),
                        "macro_f1": r.macro_f1,
                        "baseline_accuracy": r.baseline_accuracy,
                        "beats_baseline": r.beats_baseline(),
                        "abstentions": r.abstentions,
                        "abstention_precision": r.abstention_precision,
                        "hard_subset_f1": r.hard_subset_f1,
                        "per_label": r.per_label,
                    }
                    for r in reports
                ],
            },
            indent=2,
        )
    )
    print("artifacts/extraction_report.json written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
