"""Provenance checks on a reply corpus.

The extraction study is the only measurement in this project whose numbers would
be about the world rather than about our own generator. That property is worth
exactly as much as the corpus is real, so the corpus gets audited before it is
used, and the audit lives in the repository rather than in someone's judgement.

None of these checks proves text was machine-written. What they do is measure
whether a set of replies looks like **many people writing naturally** or like
**one voice producing variations**, and report it. A corpus that fails them is
not thereby fake - it may be a small sample of unusually formal writers - but it
cannot carry the evidential weight the protocol assigns to it, and the report
says so instead of quietly scoring it anyway.

Written after a first batch came back with the same thirty-word sentence
appearing verbatim under three different contributors.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

#: Common Devanagari-in-Latin tokens. Presence is expected in a corpus elicited
#: from Indian business contacts; total absence in a set that was asked for
#: Hinglish is itself a signal.
HINDI = re.compile(
    r"\b(hai|hoga|hogi|karo|kijiye|kijiyega|bhejo|bhejiye|jayega|jaayega|nahi|nahin"
    r"|tak|bhai|thoda|abhi|kal|aaj|paisa|paise|tarikh|taarikh|kar|diya|dijiye"
    r"|karenge|karunga|dunga|denge|raha|rahe|hoga|mila|milega|dekh|dekhta|dekhte"
    r"|sir|ji|acha|accha|theek|thik|matlab|kitna|kyun|kya|wala|walla|se|ko|ka|ki)\b",
    re.I,
)

NORM = lambda s: re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s.lower())).strip()  # noqa: E731


@dataclass
class Finding:
    check: str
    passed: bool
    detail: str
    severity: str = "warn"  # "warn" | "fail"


@dataclass
class ProvenanceReport:
    n: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def failures(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed and f.severity == "fail"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed and f.severity == "warn"]

    @property
    def verdict(self) -> str:
        if self.failures:
            return "PILOT ONLY - cannot carry evidential weight"
        if len(self.warnings) >= 3:
            return "PILOT ONLY - too many register warnings"
        if self.warnings:
            return "usable with caveats"
        return "consistent with independent human authorship"

    def summary(self) -> str:
        lines = [f"CORPUS PROVENANCE  (n={self.n})", ""]
        for f in self.findings:
            mark = "ok  " if f.passed else ("FAIL" if f.severity == "fail" else "warn")
            lines.append(f"  [{mark}] {f.check:<26} {f.detail}")
        lines += ["", f"  verdict: {self.verdict}"]
        return "\n".join(lines)


def audit(rows: list[tuple[str, str, str]]) -> ProvenanceReport:
    """rows are (contributor, item_id, reply)."""
    rep = ProvenanceReport(n=len(rows))
    if not rows:
        return rep

    texts = [r for _, _, r in rows]
    words = [len(t.split()) for t in texts]

    # 1. The same sentence under two contributors. Two people do not
    #    independently produce identical thirty-word sentences.
    by_text: dict[str, list[str]] = defaultdict(list)
    for c, _, t in rows:
        by_text[NORM(t)].append(c)
    cross = [t for t, cs in by_text.items() if len(set(cs)) > 1]
    rep.findings.append(
        Finding(
            "cross-contributor dupes",
            not cross,
            f"{len(cross)} text(s) appear verbatim under more than one contributor",
            severity="fail",
        )
    )

    # 2. Register. A corpus elicited as Hinglish that contains no Hindi at all
    #    is not the thing the protocol describes.
    hindi = sum(1 for t in texts if HINDI.search(t))
    rep.findings.append(
        Finding("code-switching", hindi > 0, f"{hindi}/{len(texts)} contain any Hindi token")
    )

    # 3. Real informal writing is ragged. Uniform capitalisation and punctuation
    #    across every single reply is not how a group of people writes.
    lower = sum(1 for t in texts if t[:1].islower())
    rep.findings.append(
        Finding("casing variation", lower > 0, f"{lower}/{len(texts)} start lowercase")
    )
    nostop = sum(1 for t in texts if "." not in t)
    rep.findings.append(
        Finding("punctuation variation", nostop > 0, f"{nostop}/{len(texts)} have no full stop")
    )

    # 4. Length spread. Genuine replies range from "ok" to a paragraph.
    short = sum(1 for w in words if w <= 6)
    rep.findings.append(
        Finding(
            "has short replies",
            short > 0,
            f"{short}/{len(texts)} are <= 6 words (mean {statistics.fmean(words):.0f})",
        )
    )

    # 5. Voice. Different people write at different lengths; near-identical
    #    per-contributor means across a whole panel is the strongest single tell
    #    that one hand wrote all of it.
    per: dict[str, list[int]] = defaultdict(list)
    for c, _, t in rows:
        per[c].append(len(t.split()))
    means = [statistics.fmean(v) for v in per.values() if v]
    if len(means) >= 3:
        spread = statistics.pstdev(means) / (statistics.fmean(means) or 1)
        rep.findings.append(
            Finding(
                "distinct voices",
                spread >= 0.18,
                f"per-contributor mean length varies by {spread:.0%} "
                f"(expect >=18% across real people)",
            )
        )

    return rep
