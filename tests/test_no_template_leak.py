"""The reply corpus must contain nothing our own templates produced.

docs/EXTRACTION_PROTOCOL.md commits to this: the extraction study is the only
part of the project whose numbers are about the world rather than about our
generator, and that holds only if no simulator text has leaked into it. Scoring
an extractor on text our templates wrote would measure template inversion and
would look excellent.

The test is skipped while no corpus exists, and becomes load-bearing the moment
one does.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from vasooli.sim.replies import FUZZY_DATES, TEMPLATES

CORPUS = Path("data/corpus")


def _corpus_replies() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for path in sorted(CORPUS.rglob("*.json")):
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for item in blob.get("items", []):
            reply = (item.get("reply") or "").strip()
            if reply:
                out.append((f"{path.name}:{item.get('item_id')}", reply))
    return out


def _template_skeletons() -> list[str]:
    """Templates with their placeholders removed, lowercased, punctuation
    stripped - so a match is on wording rather than on exact formatting."""
    out = []
    for variants in TEMPLATES.values():
        for t in variants:
            skel = re.sub(r"\{[a-z]+\}", " ", t).lower()
            skel = re.sub(r"[^a-z ]+", " ", skel)
            skel = re.sub(r"\s+", " ", skel).strip()
            if len(skel) > 12:
                out.append(skel)
    return out


def test_no_simulator_template_appears_in_the_corpus():
    replies = _corpus_replies()
    if not replies:
        pytest.skip("no collected replies yet; becomes load-bearing once they arrive")

    skeletons = _template_skeletons()
    offenders = []
    for item_id, reply in replies:
        norm = re.sub(r"[^a-z ]+", " ", reply.lower())
        norm = re.sub(r"\s+", " ", norm).strip()
        for skel in skeletons:
            if skel in norm or norm in skel:
                offenders.append((item_id, reply[:60]))
                break
    assert not offenders, f"simulator text found in the corpus: {offenders[:5]}"


def test_corpus_items_have_no_obvious_pii():
    """Contributors are asked not to include real references. Cheap check for
    the commonest slip: a long digit run that looks like a real UTR or GSTIN."""
    replies = _corpus_replies()
    if not replies:
        pytest.skip("no collected replies yet")
    suspicious = [
        (i, r) for i, r in replies if re.search(r"\b\d{15,}\b", r)
    ]
    assert not suspicious, f"possible real references in corpus: {suspicious[:3]}"


def test_fuzzy_date_expressions_are_not_reused_verbatim_as_a_set():
    """A corpus whose date expressions are exactly our list would suggest the
    contributor was shown our vocabulary."""
    replies = _corpus_replies()
    if len(replies) < 20:
        pytest.skip("too few replies to judge")
    ours = {f.lower() for f, _ in FUZZY_DATES}
    text = " ".join(r.lower() for _, r in replies)
    hits = sum(1 for f in ours if f in text)
    assert hits < len(ours), "every simulator date expression appears; check provenance"
