"""The extraction pipeline, exercised end to end on fixtures.

Deliberately uses tmp_path rather than data/corpus: putting invented replies
anywhere near the real corpus directory is exactly the contamination
docs/EXTRACTION_PROTOCOL.md forbids, and a test that did it would be undermining
the thing it exists to protect.

The point is that the day real sheets come back, the pipeline is known to work
and the only new variable is the data.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from unblocked.eval.extraction import (
    agreement,
    cohens_kappa,
    macro_f1,
    majority_baseline,
    score,
    wilson,
)
from unblocked.domain.enums import ReplyIntent

ROOT = Path(__file__).resolve().parents[1]


# --- statistics -------------------------------------------------------------


def test_wilson_interval_contains_the_estimate():
    lo, hi = wilson(140, 180)
    assert lo < 140 / 180 < hi
    assert 0.0 <= lo and hi <= 1.0


def test_wilson_handles_degenerate_cases():
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(10, 10)
    assert hi == 1.0 and lo < 1.0  # never claims certainty from ten items


def test_wilson_is_wider_at_small_n():
    small = wilson(9, 10)
    large = wilson(900, 1000)
    assert (small[1] - small[0]) > (large[1] - large[0]) * 5


def test_kappa_is_one_for_identical_labels():
    a = ["promise", "dispute", "ack"] * 10
    assert cohens_kappa(a, a) == pytest.approx(1.0)


def test_kappa_is_near_zero_for_independent_labels():
    import random

    r = random.Random(0)
    a = [r.choice(["a", "b", "c"]) for _ in range(600)]
    b = [r.choice(["a", "b", "c"]) for _ in range(600)]
    assert abs(cohens_kappa(a, b)) < 0.1


def test_kappa_punishes_agreement_that_is_only_prevalence():
    """Two annotators who both label almost everything the same common class
    agree constantly and have learned nothing. Raw agreement misses this.

    The construction matters: the disagreements have to fall on *different*
    items. Two annotators who use the same rare label on the same five items do
    genuinely agree about those items, and kappa is right to credit them - an
    earlier version of this test asserted otherwise and was simply wrong about
    the arithmetic.
    """
    a = ["promise"] * 95 + ["dispute"] * 5
    b = ["dispute"] * 5 + ["promise"] * 95
    raw = sum(1 for x, y in zip(a, b) if x == y) / len(a)
    assert raw >= 0.90, "raw agreement looks excellent"
    assert abs(cohens_kappa(a, b)) < 0.1, "and yet there is no agreement beyond chance"


def test_majority_baseline_macro_f1_is_low_even_when_accuracy_is_high():
    """The reason macro-F1 is the headline and accuracy is not."""
    gold = ["promise"] * 80 + ["dispute"] * 10 + ["ack"] * 10
    label, acc, mf1 = majority_baseline(gold)
    assert label == "promise" and acc == pytest.approx(0.8)
    assert mf1 < 0.35


def test_macro_f1_weights_rare_classes_equally():
    gold = ["a"] * 90 + ["b"] * 10
    perfect_on_common = ["a"] * 100
    mf1, detail = macro_f1(gold, perfect_on_common)
    assert detail["b"]["recall"] == 0.0
    assert mf1 < 0.55


# --- agreement report -------------------------------------------------------


def test_agreement_report_lists_disagreements():
    a = {"i1": "promise", "i2": "dispute", "i3": "ack"}
    b = {"i1": "promise", "i2": "hardship", "i3": "ack"}
    ag = agreement(a, b)
    assert ag.n == 3
    assert [d[0] for d in ag.disagreements] == ["i2"]


def test_agreement_verdict_flags_poor_kappa():
    import random

    r = random.Random(1)
    a = {f"i{i}": r.choice(["a", "b", "c", "d"]) for i in range(200)}
    b = {f"i{i}": r.choice(["a", "b", "c", "d"]) for i in range(200)}
    assert "POOR" in agreement(a, b).verdict


# --- scoring ----------------------------------------------------------------


def test_beats_baseline_requires_clearing_the_interval():
    """A model whose interval overlaps the baseline has demonstrated nothing,
    however good the point estimate looks."""
    gold = {f"i{i}": ("promise" if i < 12 else "dispute") for i in range(20)}
    pred = {k: ReplyIntent.PROMISE_TO_PAY for k in gold}
    rep = score("dummy", gold, pred, split="dev", ambiguous=set(), abstained=set())
    assert not rep.beats_baseline()


def test_abstention_precision_rewards_declining_on_ambiguous_items():
    gold = {f"i{i}": "promise" for i in range(10)}
    pred = {k: ReplyIntent.UNCLEAR for k in gold}
    ambiguous = {"i0", "i1", "i2", "i3", "i4", "i5", "i6", "i7"}
    rep = score(
        "dummy", gold, pred, split="dev", ambiguous=ambiguous, abstained=set(gold)
    )
    assert rep.abstentions == 10
    assert rep.abstention_precision == pytest.approx(0.8)


def test_date_accuracy_counts_only_attempted_items():
    gold = {"i1": "promise", "i2": "ack"}
    pred = {"i1": ReplyIntent.PROMISE_TO_PAY, "i2": ReplyIntent.ACKNOWLEDGEMENT}
    rep = score(
        "dummy",
        gold,
        pred,
        split="dev",
        ambiguous=set(),
        abstained=set(),
        gold_dates={"i1": "2026-06-30"},
        pred_dates={"i1": "2026-06-30"},
    )
    assert rep.date_attempted == 1 and rep.date_exact == 1


# --- pipeline ---------------------------------------------------------------


@pytest.fixture
def fake_sheets(tmp_path: Path) -> Path:
    """Four contributors' worth of returned sheets. Invented for this test only
    and never written near data/corpus."""
    sheets = tmp_path / "sheets"
    sheets.mkdir()
    replies = [
        "month end tak ho jayega sir",
        "2 boxes damaged the credit note bhejo",
        "payment cycle me hai 10 tarikh ko",
        "noted will check",
        "cash nahi hai abhi thoda time do",
        "kal transfer kiya tha UTR 401512345678",
        "PO copy bhej dijiye",
        "abhi payment nahi hoga",
    ]
    for c in range(4):
        items = [
            {"item_id": f"c{c:02d}_i{k:02d}", "scenario": "s", "reply": replies[k]}
            for k in range(len(replies))
        ]
        (sheets / f"c{c:02d}.json").write_text(
            json.dumps({"contributor": f"c{c:02d}", "items": items}), encoding="utf-8"
        )
    return sheets


def test_build_corpus_splits_by_contributor_not_item(fake_sheets: Path, tmp_path: Path):
    """Two replies from one person share their idiom. Splitting by item would
    leak that across the boundary and inflate the test number."""
    out = tmp_path / "replies.jsonl"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_corpus.py"),
         "--sheets", str(fake_sheets), "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    items = [json.loads(ln) for ln in out.read_text(encoding="utf-8").splitlines()]
    assert items

    by_contributor: dict[str, set[str]] = {}
    for it in items:
        by_contributor.setdefault(it["contributor"], set()).add(it["split"])
    for contributor, splits in by_contributor.items():
        assert len(splits) == 1, f"{contributor} spans both splits"


def test_build_corpus_drops_duplicates_and_writes_a_lock(fake_sheets: Path, tmp_path: Path):
    out = tmp_path / "replies.jsonl"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_corpus.py"),
         "--sheets", str(fake_sheets), "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT, check=True,
    )
    items = [json.loads(ln) for ln in out.read_text(encoding="utf-8").splitlines()]
    # Every contributor sent the same eight replies; only one copy survives.
    assert len(items) == 8
    lock = (out.parent / "CORPUS_LOCK.txt").read_text(encoding="utf-8")
    assert "sha256" in lock
    assert "before any model output was inspected" in lock
    assert "keep the side they were first assigned" in lock


def test_annotation_sheets_contain_no_labels(fake_sheets: Path, tmp_path: Path):
    out = tmp_path / "replies.jsonl"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_corpus.py"),
         "--sheets", str(fake_sheets), "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT, check=True,
    )
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/make_annotation_sheets.py"), "--corpus", str(out)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    for name in ("a", "b"):
        path = out.parent / f"TO_LABEL_annotator_{name}_round1.csv"
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
        rows = list(csv.DictReader(lines))
        assert rows
        assert all(not row["intent"] and not row["confidence"] for row in rows)


def test_annotators_get_different_orderings(fake_sheets: Path, tmp_path: Path):
    out = tmp_path / "replies.jsonl"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_corpus.py"),
         "--sheets", str(fake_sheets), "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT, check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/make_annotation_sheets.py"), "--corpus", str(out)],
        capture_output=True, text=True, cwd=ROOT, check=True,
    )

    def order(name: str) -> list[str]:
        path = out.parent / f"TO_LABEL_annotator_{name}_round1.csv"
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
        return [r["item_id"] for r in csv.DictReader(lines)]

    a, b = order("a"), order("b")
    assert sorted(a) == sorted(b)
    assert a != b


def _run_build(sheets: Path, out: Path, extra: list[str] | None = None):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_corpus.py"),
         "--sheets", str(sheets), "--out", str(out), *(extra or [])],
        capture_output=True, text=True, cwd=ROOT,
    )


def _write_sheet(sheets: Path, name: str, replies: list[str]) -> None:
    sheets.mkdir(parents=True, exist_ok=True)
    (sheets / f"{name}.json").write_text(
        json.dumps({
            "contributor": name,
            "items": [{"item_id": f"{name}_i{k:02d}", "scenario": "s", "reply": r}
                      for k, r in enumerate(replies)],
        }), encoding="utf-8")


def test_growing_the_corpus_does_not_redraw_the_existing_split(tmp_path: Path):
    """A corpus grows as more people reply. Redrawing the whole split each time
    would move items between dev and test without anyone deciding to - which is
    how a 'test scored once' claim becomes untrue by accident."""
    sheets, out = tmp_path / "sheets", tmp_path / "replies.jsonl"
    for i in range(4):
        _write_sheet(sheets, f"a{i:02d}",
                     [f"reply {i} {k} kal tak ho jayega bhai" for k in range(6)])
    assert _run_build(sheets, out, ["--allow-pilot"]).returncode == 0

    before = {json.loads(l)["contributor"]: json.loads(l)["split"]
              for l in out.read_text(encoding="utf-8").splitlines()}

    for i in range(4, 8):
        _write_sheet(sheets, f"a{i:02d}",
                     [f"new {i} {k} thoda time do please" for k in range(6)])
    assert _run_build(sheets, out, ["--allow-pilot"]).returncode == 0

    after = {json.loads(l)["contributor"]: json.loads(l)["split"]
             for l in out.read_text(encoding="utf-8").splitlines()}

    for c, side in before.items():
        assert after[c] == side, f"{c} moved from {side} to {after[c]} when the corpus grew"
    assert len(after) == 8


def test_second_build_is_recorded_as_a_second_look(tmp_path: Path):
    """Scoring a test split twice is a second look however the items arrived, and
    the lock file has to say so rather than leaving it to be remembered."""
    sheets, out = tmp_path / "sheets", tmp_path / "replies.jsonl"
    for i in range(3):
        _write_sheet(sheets, f"b{i:02d}", [f"reply {i} {k} nahi hua abhi" for k in range(6)])
    _run_build(sheets, out, ["--allow-pilot"])
    lock = (out.parent / "CORPUS_LOCK.txt").read_text(encoding="utf-8")
    assert "build rounds       = 1" in lock
    assert "second look" not in lock

    _write_sheet(sheets, "b99", ["another one kal dekhta hoon"] * 6)
    _run_build(sheets, out, ["--allow-pilot"])
    lock = (out.parent / "CORPUS_LOCK.txt").read_text(encoding="utf-8")
    assert "build rounds       = 2" in lock
    assert "second look" in lock


def test_second_round_sheets_exclude_already_labelled_items(tmp_path: Path):
    """A second annotation round must not re-ask for judgements already made. It
    wastes an hour of a volunteer's time and invites them to contradict their own
    earlier call on the same item."""
    corpus = tmp_path / "replies.jsonl"
    corpus.write_text("\n".join(
        json.dumps({"item_id": f"x{i:02d}", "contributor": "c1", "scenario": "s",
                    "reply": f"reply {i}", "split": "dev"})
        for i in range(6)
    ), encoding="utf-8")
    (tmp_path / "LABELLED_annotator_a_round1.csv").write_text(
        "item_id,scenario,reply,intent,promised_date_raw,promised_date_resolved,"
        "disputed_amount,claimed_utr,documents_requested,confidence\n"
        "x00,s,r,promise_to_pay,,,,,,clear\n"
        "x01,s,r,dispute,,,,,,clear\n", encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/make_annotation_sheets.py"),
         "--corpus", str(corpus)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert r.returncode == 0, r.stdout + r.stderr

    lines = [l for l in (tmp_path / "TO_LABEL_annotator_a_round2.csv").read_text(encoding="utf-8").splitlines()
             if not l.startswith("#")]
    ids = {row["item_id"] for row in csv.DictReader(lines)}
    assert ids == {"x02", "x03", "x04", "x05"}, ids


def test_sheet_names_cannot_be_confused_with_completed_work(tmp_path: Path):
    """A round produced annotate_a.csv beside annotate_a_filled.csv. The filled
    one - being the one that looked finished - was copied and handed back as the
    next round's work, so 72 items went unlabelled while appearing done. Files to
    fill in and files already filled in must not differ by a suffix."""
    sheets, out = tmp_path / "sheets", tmp_path / "replies.jsonl"
    _write_sheet(sheets, "c01", [f"reply {k} kal tak ho jayega" for k in range(6)])
    _run_build(sheets, out, ["--allow-pilot"])
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/make_annotation_sheets.py"), "--corpus", str(out)],
        capture_output=True, text=True, cwd=ROOT, check=True,
    )
    names = {p.name for p in tmp_path.glob("*.csv")}
    todo = {n for n in names if n.startswith("TO_LABEL_")}
    assert todo, names
    for n in todo:
        # The instruction is inside the file, not only in a chat message.
        head = (tmp_path / n).read_text(encoding="utf-8").splitlines()[:2]
        assert "fill the" in head[0]
        assert "save this file as: LABELLED_" in head[1]


def test_label_files_are_read_with_their_own_columns(tmp_path: Path):
    """Merging annotation rounds must not impose the annotator header on files
    that have a different shape. adjudicated.csv is item_id,intent,confidence,note
    - reading it with the 10-column sheet header pulled `intent` out of the note
    column, and two sentences of prose appeared in a classification report as
    though they were class labels."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("sx", ROOT / "scripts/score_extraction.py")
    sx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sx)

    adj = tmp_path / "adjudicated.csv"
    adj.write_text(
        "item_id,intent,confidence,note\n"
        'x01,payment_claim,ambiguous,"Compound: a claim, and a promise for the rest."\n',
        encoding="utf-8")
    intents, _, ambiguous = sx.read_labels(adj)
    assert intents == {"x01": "payment_claim"}, intents
    assert ambiguous == {"x01"}
