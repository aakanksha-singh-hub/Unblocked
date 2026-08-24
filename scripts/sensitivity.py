"""Which assumption is actually carrying the result?

The fatigue sweep found no crossing anywhere in its range, which means our
headline finding does not depend on the parameter we assumed was load-bearing.
That is a useful negative result and it points at the obvious follow-up: sweep
the parameters that might be.

Scope is three parameters, per the twelve-day budget - chosen because each one,
if wrong, breaks a different load-bearing claim:

  PORTAL_REPAIR_SUCCESS        the agent's largest single segment win
  DISPUTE_RESOLUTION_SUCCESS   the mechanism behind the disputer result
  ARCHETYPE_MIX.process_bound  whether the population shape carries it

    python scripts/sensitivity.py
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vasooli.agent.inference import ArchetypeModel  # noqa: E402
from vasooli.eval.breakeven import sweep_parameter  # noqa: E402
from vasooli.sim.world import generate  # noqa: E402

SWEEPS: list[tuple[str, tuple[float, ...], str]] = [
    (
        "PORTAL_REPAIR_SUCCESS",
        (0.0, 0.15, 0.30, 0.50, 0.70, 0.90),
        "If chasing paperwork rarely works, the process-bound win evaporates.",
    ),
    (
        "DISPUTE_RESOLUTION_SUCCESS",
        (0.0, 0.15, 0.30, 0.45, 0.62, 0.85),
        "If disputes are hard to settle, resolving them is not a strategy.",
    ),
    (
        "ARCHETYPE_MIX.process_bound",
        (0.05, 0.12, 0.20, 0.26, 0.35),
        "If few buyers are cyclic payers, cause-matching has less to find. "
        "Generation-time: the population is rebuilt at each point.",
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260824)
    ap.add_argument("--merchants", type=int, default=6)
    ap.add_argument("--buyers", type=int, default=52)
    ap.add_argument("--rival", default="never-chase")
    ap.add_argument("--metric", default="recovered")
    args = ap.parse_args()

    world = generate(seed=args.seed, n_merchants=args.merchants, buyers_per_merchant=args.buyers)
    model = ArchetypeModel.load() if Path("artifacts/models/archetype.pkl").exists() else None
    print(f"world {world.fingerprint()}  {len(world.buyers)} buyers")
    print(f"rival {args.rival}   metric {args.metric}\n")

    out = []
    for param, values, why in SWEEPS:
        print(f"--- {param} ---")
        print(f"    {why}")
        r = sweep_parameter(
            world, param, values, model=model, rival=args.rival, metric=args.metric
        )
        print("\n" + r.summary() + "\n")
        out.append(
            {
                "parameter": param,
                "rationale": why,
                "chosen": r.chosen_retention,
                "crossing": r.crossing,
                "holds_at_chosen": r.holds_at_chosen(),
                "points": [asdict(p) | {"margin": p.margin} for p in r.points],
            }
        )

    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/sensitivity.json").write_text(
        json.dumps({"world_fingerprint": world.fingerprint(), "sweeps": out}, indent=2)
    )
    print("artifacts/sensitivity.json written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
