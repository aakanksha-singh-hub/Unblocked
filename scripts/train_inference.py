"""Fit and evaluate the archetype model.

Trains on the training split of buyers and reports on the held-out split. The
splits are stratified and assigned at buyer level in `sim/world.py`, so no buyer
appears in both.

Snapshots are taken at intervals through the run so the model sees buyers at
varying levels of evidence - including nearly none, which is the state the agent
is actually in for the first month of any relationship.

Training data is pooled across several policies because reply features only
exist where contact happened: a model trained on never-chase data would never
see a reply, and one trained only on blast-weekly would assume everyone answers.

    python scripts/train_inference.py
    python scripts/train_inference.py --drop-structural
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vasooli.agent.beliefs import Beliefs  # noqa: E402
from vasooli.agent.extract import RuleExtractor  # noqa: E402
from vasooli.agent.features import FEATURE_NAMES, extract  # noqa: E402
from vasooli.agent.inference import ArchetypeModel  # noqa: E402
from vasooli.agent.observer import BeliefUpdater  # noqa: E402
from vasooli.agent.view import build_view  # noqa: E402
from vasooli.eval import baselines, runner  # noqa: E402
from vasooli.sim.world import generate  # noqa: E402

SNAPSHOT_DAYS = (25, 50, 80, 110, 140, 170)


def collect(world, policy_factory, label: str) -> tuple[np.ndarray, list[str], list[str]]:
    """Run one policy and snapshot features for every buyer at fixed days."""
    result = runner.run(world, policy_factory())
    st = result.state

    beliefs = Beliefs()
    updater = BeliefUpdater(RuleExtractor())

    X: list[list[float]] = []
    y: list[str] = []
    split: list[str] = []

    for offset in SNAPSHOT_DAYS:
        day = world.start_date + timedelta(days=offset)
        view = build_view(world, st, day)
        updater.update(beliefs, view, day)
        for bid, ledger in view.ledgers.items():
            if not ledger.invoices:
                continue
            X.append(extract(ledger, beliefs.get(bid), day).values)
            y.append(world.truth[bid].archetype.value)
            split.append(world.split[bid])

    print(f"  {label:>16}: {len(X)} snapshots")
    return np.asarray(X, dtype=float), y, split


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260824)
    ap.add_argument("--merchants", type=int, default=14)
    ap.add_argument("--buyers", type=int, default=52)
    ap.add_argument("--drop-structural", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("artifacts/models/archetype.pkl"))
    args = ap.parse_args()

    world = generate(seed=args.seed, n_merchants=args.merchants, buyers_per_merchant=args.buyers)
    print(f"world {world.fingerprint()}  {len(world.buyers)} buyers\n")
    print("collecting snapshots across policies:")

    Xs, ys, ss = [], [], []
    for factory, label in (
        (baselines.NeverChase, "never-chase"),
        (baselines.BlastWeekly, "blast-weekly"),
        (baselines.StaticLadder, "static-ladder"),
    ):
        X, y, s = collect(world, factory, label)
        Xs.append(X); ys += y; ss += s

    X = np.vstack(Xs)
    y = np.asarray(ys)
    s = np.asarray(ss)

    tr, te = s == "train", s == "holdout"
    print(f"\ntrain {tr.sum()} snapshots / holdout {te.sum()} snapshots")

    model = ArchetypeModel.new(drop_structural=args.drop_structural, seed=args.seed)
    model.fit(X[tr], list(y[tr]))

    from sklearn.metrics import classification_report, confusion_matrix

    pred = model.predict_batch(X[te])
    labels = sorted(set(y))

    print("\n" + "=" * 74)
    print("HOLD-OUT PERFORMANCE")
    print("Macro-F1 on recovering a latent generator variable in simulation.")
    print("NOT a real-world buyer classification result. See docs/EVALUATION.md.")
    print("=" * 74)
    print(classification_report(y[te], pred, labels=labels, digits=3, zero_division=0))

    cm = confusion_matrix(y[te], pred, labels=labels)
    print(f"{'confusion':>20} " + " ".join(f"{l[:8]:>9}" for l in labels))
    for i, l in enumerate(labels):
        print(f"{l:>20} " + " ".join(f"{v:>9}" for v in cm[i]))

    di, ai = labels.index("distressed"), labels.index("avoider")
    n_dist = cm[di].sum()
    print(
        f"\nThe error that does human damage - distressed read as avoider: "
        f"{cm[di][ai]}/{n_dist} ({cm[di][ai] / max(1, n_dist):.1%})"
    )

    print("\ntop features:")
    for name, imp in model.importances()[:10]:
        print(f"   {name:26s} {imp:.4f}")

    path = model.save(args.out)
    from sklearn.metrics import f1_score

    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/inference_report.json").write_text(
        json.dumps(
            {
                "world_fingerprint": world.fingerprint(),
                "drop_structural": args.drop_structural,
                "n_train": int(tr.sum()),
                "n_holdout": int(te.sum()),
                "macro_f1": float(f1_score(y[te], pred, average="macro", zero_division=0)),
                "distressed_as_avoider": int(cm[di][ai]),
                "distressed_support": int(n_dist),
                "importances": dict(model.importances()),
                "caveat": (
                    "Macro-F1 on recovering a latent generator variable in simulation. "
                    "Not a real-world classification result."
                ),
            },
            indent=2,
        )
    )
    print(f"\nmodel -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
