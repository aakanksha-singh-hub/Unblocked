"""Run the contact-fatigue breakeven sweep.

    python scripts/breakeven.py
    python scripts/breakeven.py --metric recovered --merchants 14
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from unblocked.agent.inference import ArchetypeModel  # noqa: E402
from unblocked.eval.breakeven import sweep  # noqa: E402
from unblocked.sim.world import generate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260824)
    ap.add_argument("--merchants", type=int, default=8)
    ap.add_argument("--buyers", type=int, default=52)
    ap.add_argument("--metric", default="net_value", choices=["net_value", "recovered"])
    ap.add_argument("--model", type=Path, default=Path("artifacts/models/archetype.pkl"))
    args = ap.parse_args()

    world = generate(seed=args.seed, n_merchants=args.merchants, buyers_per_merchant=args.buyers)
    model = ArchetypeModel.load(args.model) if args.model.exists() else None

    print(f"world {world.fingerprint()}  {len(world.buyers)} buyers")
    print("sweeping contact fatigue...\n")

    result = sweep(world, model=model, metric=args.metric)
    print("\n" + "=" * 74)
    print(result.summary())
    print("=" * 74)

    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/breakeven.json").write_text(
        json.dumps(
            {
                "world_fingerprint": world.fingerprint(),
                "metric": args.metric,
                "chosen_retention": result.chosen_retention,
                "crossing": result.crossing,
                "holds_at_chosen": result.holds_at_chosen(),
                "points": [asdict(p) | {"margin": p.margin} for p in result.points],
            },
            indent=2,
        )
    )
    print("\nartifacts/breakeven.json written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
