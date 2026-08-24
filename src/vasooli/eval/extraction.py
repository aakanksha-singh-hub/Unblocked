"""Scoring reply understanding against human labels.

This is the only measurement in the project whose numbers are about the world
rather than about our own generator, so the order things are reported in matters
as much as the numbers themselves:

1. **Inter-annotator agreement, first.** If two people cannot agree what a
   message means, model accuracy on those items is not measuring comprehension,
   and quoting it would be dishonest even if the number were high.
2. **The majority-class baseline, second.** Any model figure is quoted against
   it. A macro-F1 that sounds respectable but sits inside the baseline's
   interval has demonstrated nothing.
3. **Intervals, not point estimates.** At n=180 a Wilson interval is roughly
   +/-7pp, and reporting 0.81 without that is a precision claim the sample size
   does not support.
4. **Abstention as its own outcome.** A model that says "I am not sure" on a
   genuinely ambiguous item is behaving correctly. This is the one place in the
   system where declining to answer is rewarded, so it is measured separately
   rather than counted as an error.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from ..domain.enums import ReplyIntent


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion.

    Wilson rather than the normal approximation because at n=180, with several
    classes holding twenty-odd items each, the normal interval misbehaves badly
    near 0 and 1 - it happily reports bounds outside [0, 1] and is too narrow
    exactly where the per-class supports are thinnest.
    """
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def cohens_kappa(a: list[str], b: list[str]) -> float:
    """Chance-corrected agreement between two annotators.

    Raw agreement is misleading here: with one class holding a quarter of the
    corpus, two annotators guessing independently would agree a good fraction of
    the time. Kappa subtracts that.
    """
    if len(a) != len(b):
        raise ValueError("annotator label lists must be the same length")
    n = len(a)
    if n == 0:
        return float("nan")

    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum((ca[k] / n) * (cb[k] / n) for k in set(ca) | set(cb))
    if expected >= 1.0:
        return float("nan")
    return (observed - expected) / (1 - expected)


def per_class_kappa(a: list[str], b: list[str]) -> dict[str, float]:
    """One-vs-rest kappa per class, to find where the taxonomy is weak.

    An overall kappa of 0.7 can hide one class at 0.2, and that class is usually
    the one worth fixing.
    """
    out: dict[str, float] = {}
    for label in sorted(set(a) | set(b)):
        out[label] = cohens_kappa(
            [("y" if x == label else "n") for x in a],
            [("y" if y == label else "n") for y in b],
        )
    return out


def macro_f1(gold: list[str], pred: list[str]) -> tuple[float, dict[str, dict[str, float]]]:
    labels = sorted(set(gold) | set(pred))
    detail: dict[str, dict[str, float]] = {}
    f1s = []
    for label in labels:
        tp = sum(1 for g, p in zip(gold, pred) if g == label and p == label)
        fp = sum(1 for g, p in zip(gold, pred) if g != label and p == label)
        fn = sum(1 for g, p in zip(gold, pred) if g == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        detail[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": sum(1 for g in gold if g == label),
        }
        f1s.append(f1)
    return (sum(f1s) / len(f1s) if f1s else 0.0), detail


def majority_baseline(gold: list[str]) -> tuple[str, float, float]:
    """The label to beat, its accuracy, and its macro-F1.

    Macro-F1 for a constant predictor is near zero, which is why accuracy alone
    would flatter any model on this task: always answering the commonest class
    can look respectable on accuracy and is useless.
    """
    if not gold:
        return ("", 0.0, 0.0)
    label, count = Counter(gold).most_common(1)[0]
    acc = count / len(gold)
    mf1, _ = macro_f1(gold, [label] * len(gold))
    return (label, acc, mf1)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class AgreementReport:
    n: int
    raw_agreement: float
    kappa: float
    per_class: dict[str, float] = field(default_factory=dict)
    disagreements: list[tuple[str, str, str]] = field(default_factory=list)
    """(item_id, annotator_a_label, annotator_b_label)"""

    @property
    def verdict(self) -> str:
        if math.isnan(self.kappa):
            return "undefined"
        if self.kappa < 0.4:
            return "POOR - the taxonomy is underspecified; that is the finding"
        if self.kappa < 0.6:
            return "moderate - report model numbers with this caveat attached"
        if self.kappa < 0.8:
            return "substantial"
        return "near-perfect - check the annotators worked independently"


@dataclass
class ExtractionReport:
    extractor: str
    n: int
    split: str

    accuracy: float
    accuracy_ci: tuple[float, float]
    macro_f1: float
    per_label: dict[str, dict[str, float]]

    baseline_label: str
    baseline_accuracy: float
    baseline_macro_f1: float

    abstentions: int
    abstention_precision: float
    """Of the items where the model abstained, the share the annotators had
    flagged ambiguous. High is good: it means the model declines on the items
    humans also found hard, rather than at random."""

    date_exact: int
    date_attempted: int
    hard_subset_f1: float
    hard_subset_n: int

    def beats_baseline(self) -> bool:
        """Only if the accuracy interval clears the baseline point estimate."""
        return self.accuracy_ci[0] > self.baseline_accuracy

    def summary(self) -> str:
        lo, hi = self.accuracy_ci
        lines = [
            f"EXTRACTION  {self.extractor}   ({self.split} split, n={self.n})",
            "",
            f"  accuracy         {self.accuracy:.3f}  95% CI [{lo:.3f}, {hi:.3f}]",
            f"  macro-F1         {self.macro_f1:.3f}",
            f"  majority baseline{self.baseline_accuracy:>8.3f} acc "
            f"/ {self.baseline_macro_f1:.3f} macro-F1  (always '{self.baseline_label}')",
            f"  beats baseline   {'YES' if self.beats_baseline() else 'NO - within the interval'}",
            "",
            f"  abstained on     {self.abstentions} items"
            f"  ({self.abstention_precision:.0%} of those were annotator-flagged ambiguous)",
            f"  dates resolved   {self.date_exact}/{self.date_attempted} exact",
            f"  hard subset      macro-F1 {self.hard_subset_f1:.3f} (n={self.hard_subset_n})",
            "",
            f"  {'label':22}{'prec':>7}{'rec':>7}{'f1':>7}{'n':>6}",
        ]
        for label, d in sorted(self.per_label.items(), key=lambda kv: -kv[1]["support"]):
            lines.append(
                f"  {label:22}{d['precision']:>7.3f}{d['recall']:>7.3f}"
                f"{d['f1']:>7.3f}{int(d['support']):>6}"
            )
        return "\n".join(lines)


def agreement(
    labels_a: dict[str, str], labels_b: dict[str, str]
) -> AgreementReport:
    shared = sorted(set(labels_a) & set(labels_b))
    a = [labels_a[i] for i in shared]
    b = [labels_b[i] for i in shared]
    raw = sum(1 for x, y in zip(a, b) if x == y) / len(shared) if shared else 0.0
    return AgreementReport(
        n=len(shared),
        raw_agreement=raw,
        kappa=cohens_kappa(a, b),
        per_class=per_class_kappa(a, b),
        disagreements=[(i, labels_a[i], labels_b[i]) for i in shared if labels_a[i] != labels_b[i]],
    )


def score(
    extractor_name: str,
    gold: dict[str, str],
    predicted: dict[str, ReplyIntent],
    *,
    split: str,
    ambiguous: set[str],
    abstained: set[str],
    gold_dates: dict[str, str] | None = None,
    pred_dates: dict[str, str] | None = None,
) -> ExtractionReport:
    ids = sorted(set(gold) & set(predicted))
    g = [gold[i] for i in ids]
    p = [predicted[i].value for i in ids]

    correct = sum(1 for x, y in zip(g, p) if x == y)
    mf1, per_label = macro_f1(g, p)
    b_label, b_acc, b_f1 = majority_baseline(g)

    abst = [i for i in ids if i in abstained]
    abst_precision = (
        sum(1 for i in abst if i in ambiguous) / len(abst) if abst else 0.0
    )

    hard = [i for i in ids if i in ambiguous]
    hard_f1 = (
        macro_f1([gold[i] for i in hard], [predicted[i].value for i in hard])[0] if hard else 0.0
    )

    gd, pd = gold_dates or {}, pred_dates or {}
    attempted = [i for i in ids if gd.get(i)]
    exact = sum(1 for i in attempted if pd.get(i) and pd[i] == gd[i])

    return ExtractionReport(
        extractor=extractor_name,
        n=len(ids),
        split=split,
        accuracy=correct / len(ids) if ids else 0.0,
        accuracy_ci=wilson(correct, len(ids)),
        macro_f1=mf1,
        per_label=per_label,
        baseline_label=b_label,
        baseline_accuracy=b_acc,
        baseline_macro_f1=b_f1,
        abstentions=len(abst),
        abstention_precision=abst_precision,
        date_exact=exact,
        date_attempted=len(attempted),
        hard_subset_f1=hard_f1,
        hard_subset_n=len(hard),
    )
