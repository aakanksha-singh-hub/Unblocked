"""Archetype inference.

What this is: a classifier fitted on the training split of buyers, predicting a
latent variable the simulator drew. What it measures, stated once more because
it is easy to overclaim: **how invertible our own generator is.** A model that
scored well here would not thereby be shown to classify real buyers. See
docs/EVALUATION.md.

Two design choices worth defending.

**Trained on pooled data from several policies.** Features include reply
behaviour, and replies only exist where contact happened - so a model trained on
never-chase data would never see a reply, and a model trained only on
blast-weekly data would assume everyone replies constantly. Pooling across
never-chase, blast-weekly and static-ladder gives coverage of both regimes. This
does not eliminate the distribution shift between training policies and the
agent's own behaviour; it reduces it, and the residual is a stated limitation.

**Cold start is explicit, not implicit.** A buyer with no settled invoices and no
replies carries almost no signal, and the model will still emit a confident-
looking distribution over six classes. Rather than let the policy act on that,
`predict` returns the population prior with a confidence of zero, and the policy
treats near-zero confidence as a reason to prefer cheap, reversible actions.
Knowing that you do not know is the part most classifiers skip.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..domain.enums import BuyerArchetype
from ..sim.calibration import archetype_mix
from .features import FEATURE_NAMES, STRUCTURAL, FeatureVector

DEFAULT_MODEL_PATH = Path("artifacts/models/archetype.pkl")


@dataclass(frozen=True)
class Prediction:
    archetype: BuyerArchetype
    confidence: float
    posterior: dict[BuyerArchetype, float]
    cold_start: bool = False

    def top_two_margin(self) -> float:
        """Gap between the best and second-best class.

        A better guide to whether to act than raw confidence: a 0.4/0.38 split
        across two archetypes that want opposite interventions is a coin flip
        dressed as a decision.
        """
        ranked = sorted(self.posterior.values(), reverse=True)
        return ranked[0] - ranked[1] if len(ranked) > 1 else ranked[0]


def _prior() -> dict[BuyerArchetype, float]:
    return archetype_mix()


class ArchetypeModel:
    def __init__(self, clf=None, feature_names: list[str] | None = None) -> None:
        self.clf = clf
        self.feature_names = feature_names or FEATURE_NAMES
        self._idx = [FEATURE_NAMES.index(n) for n in self.feature_names]

    # -- training ---------------------------------------------------------

    @staticmethod
    def new(*, drop_structural: bool = False, seed: int = 20260824) -> ArchetypeModel:
        from sklearn.ensemble import RandomForestClassifier

        names = [n for n in FEATURE_NAMES if not (drop_structural and n in STRUCTURAL)]
        clf = RandomForestClassifier(
            n_estimators=400,
            max_depth=12,
            min_samples_leaf=8,
            # The rare archetypes are the expensive ones to miss. Without this,
            # the model happily ignores DISTRESSED entirely and still looks good
            # on accuracy.
            class_weight="balanced_subsample",
            random_state=seed,
            n_jobs=-1,
        )
        return ArchetypeModel(clf, names)

    def fit(self, X: np.ndarray, y: list[str]) -> ArchetypeModel:
        self.clf.fit(X[:, self._idx], y)
        return self

    # -- prediction -------------------------------------------------------

    def predict(self, fv: FeatureVector) -> Prediction:
        f = fv.as_dict()

        # Cold start: nothing settled, nothing said. Any posterior here is the
        # model reading structural fields and pretending they are behaviour.
        if f["n_settled"] == 0 and f["n_contacts"] == 0:
            prior = _prior()
            return Prediction(
                archetype=max(prior, key=prior.get),
                confidence=0.0,
                posterior=prior,
                cold_start=True,
            )

        row = np.asarray([fv.values], dtype=float)[:, self._idx]
        probs = self.clf.predict_proba(row)[0]
        posterior = {BuyerArchetype(c): float(p) for c, p in zip(self.clf.classes_, probs)}
        best = max(posterior, key=posterior.get)
        return Prediction(archetype=best, confidence=posterior[best], posterior=posterior)

    def predict_batch(self, X: np.ndarray) -> list[str]:
        return list(self.clf.predict(X[:, self._idx]))

    def predict_many(self, fvs: list[FeatureVector]) -> list[Prediction]:
        """Predict a whole day's buyers in one call.

        A 400-tree forest costs roughly the same for one row as for a thousand,
        because the cost is dominated by traversing the trees rather than by the
        rows. Predicting buyer-by-buyer made the evaluation spend most of its
        time inside sklearn's call overhead.
        """
        if not fvs:
            return []
        prior = _prior()
        cold = [
            i
            for i, fv in enumerate(fvs)
            if fv.as_dict()["n_settled"] == 0 and fv.as_dict()["n_contacts"] == 0
        ]
        cold_set = set(cold)
        warm = [i for i in range(len(fvs)) if i not in cold_set]

        out: list[Prediction | None] = [None] * len(fvs)
        for i in cold:
            out[i] = Prediction(
                archetype=max(prior, key=prior.get),
                confidence=0.0,
                posterior=prior,
                cold_start=True,
            )
        if warm:
            X = np.asarray([fvs[i].values for i in warm], dtype=float)[:, self._idx]
            probs = self.clf.predict_proba(X)
            classes = [BuyerArchetype(c) for c in self.clf.classes_]
            for row, i in zip(probs, warm):
                posterior = {c: float(pp) for c, pp in zip(classes, row)}
                best = max(posterior, key=posterior.get)
                out[i] = Prediction(
                    archetype=best, confidence=posterior[best], posterior=posterior
                )
        return [o for o in out if o is not None]

    # -- importances ------------------------------------------------------

    def importances(self) -> list[tuple[str, float]]:
        imp = getattr(self.clf, "feature_importances_", None)
        if imp is None:
            return []
        return sorted(zip(self.feature_names, imp), key=lambda kv: -kv[1])

    # -- persistence ------------------------------------------------------

    def save(self, path: Path = DEFAULT_MODEL_PATH) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump({"clf": self.clf, "feature_names": self.feature_names}, f)
        return path

    @staticmethod
    def load(path: Path = DEFAULT_MODEL_PATH) -> ArchetypeModel:
        with path.open("rb") as f:
            blob = pickle.load(f)
        return ArchetypeModel(blob["clf"], blob["feature_names"])


class PriorOnlyModel:
    """Fallback when no fitted model is available.

    Always returns the population prior at zero confidence, which drives the
    policy into its cautious branch. Used so the agent runs end to end before
    training, and so a missing model file degrades to timid rather than to wrong.
    """

    feature_names = FEATURE_NAMES

    def predict(self, fv: FeatureVector) -> Prediction:
        prior = _prior()
        return Prediction(
            archetype=max(prior, key=prior.get), confidence=0.0, posterior=prior, cold_start=True
        )

    def importances(self) -> list[tuple[str, float]]:
        return []
