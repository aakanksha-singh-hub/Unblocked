"""Full policy comparison on the held-out book.

Prints the comparison table, the paired differences with bootstrap intervals,
and the per-archetype breakdown. Writes artifacts/evaluation.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vasooli.agent.inference import ArchetypeModel  # noqa: E402
from vasooli.agent.policy import CauseMatchedPolicy  # noqa: E402
from vasooli.domain.money import fmt  # noqa: E402
from vasooli.eval import baselines, metrics, runner  # noqa: E402
from vasooli.sim import calibration as cal  # noqa: E402
from vasooli.sim.world import generate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260824)
    ap.add_argument("--merchants", type=int, default=14)
    ap.add_argument("--buyers", type=int, default=52)
    ap.add_argument("--split", default="holdout", choices=["holdout", "train", "all"])
    ap.add_argument("--model", type=Path, default=Path("artifacts/models/archetype.pkl"))
    args = ap.parse_args()

    world = generate(seed=args.seed, n_merchants=args.merchants, buyers_per_merchant=args.buyers)
    udyam = {
        b: next(m.udyam_registered for m in world.merchants if m.merchant_id == world.buyer_merchant[b])
        for b in world.buyers
    }

    print(f"world       {world.fingerprint()}")
    print(f"buyers      {len(world.buyers)}  ({args.split} split reported)")
    print(f"book        {fmt(sum(i.amount for i in world.invoices.values()), compact=True)}")
    print(f"provenance  {cal.provenance_report()}")
    print("\nThis measures policy quality conditional on the assumptions in")
    print("sim/calibration.py. It is not evidence those assumptions hold.")
    print("See docs/EVALUATION.md.\n")

    model = ArchetypeModel.load(args.model) if args.model.exists() else None
    policies = [
        ("never-chase", lambda: baselines.NeverChase()),
        ("blast-weekly", lambda: baselines.BlastWeekly()),
        ("static-ladder", lambda: baselines.StaticLadder()),
        ("cause-matched", lambda: CauseMatchedPolicy(model=model, merchant_udyam=udyam)),
    ]

    rows, runs = [], {}
    for name, factory in policies:
        p = factory()
        p.name = name
        t = time.time()
        r = runner.run(world, p)
        runs[name] = r
        rows.append(metrics.score(world, r))
        print(f"  ran {name:16s} {time.time() - t:5.1f}s")

    print("\n" + metrics.format_table(rows))

    print("\npaired differences vs never-chase (rupees per buyer, 95% bootstrap CI):")
    for name in ("blast-weekly", "static-ladder", "cause-matched"):
        for m in ("recovered", "net_value"):
            d = metrics.paired_bootstrap(world, runs[name], runs["never-chase"], metric=m)
            star = "*" if d.significant else " "
            print(
                f"  {name:16s} {m:10s} {d.mean_diff / 100:>11,.0f}  "
                f"[{d.ci_low / 100:>10,.0f}, {d.ci_high / 100:>10,.0f}] {star}"
            )

    print("\nrecovery by archetype (% of that segment's book):")
    seg: Counter = Counter()
    for i in world.invoices.values():
        seg[world.truth[i.buyer_id].archetype] += i.amount
    names = [n for n, _ in policies]
    segments: dict[str, dict[str, float]] = {}
    print(f"  {'archetype':20s}" + "".join(f"{n[:13]:>15s}" for n in names))
    for a in sorted(seg):
        cells = ""
        segments[a.value] = {}
        for n in names:
            got = sum(p.amount for p in runs[n].state.payments if world.truth[p.buyer_id].archetype == a)
            pct = 100 * got / seg[a]
            segments[a.value][n] = round(pct, 2)
            cells += f"{pct:>14.1f}%"
        print(f"  {a:20s}{cells}")

    best = runs["cause-matched"]
    print("\ncause-matched action mix:")
    for k, v in Counter(m.intervention.value for m in best.state.outbound).most_common():
        print(f"   {k:24s} {v:>5}")

    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/evaluation.json").write_text(
        json.dumps(
            {
                "world_fingerprint": world.fingerprint(),
                "seed": args.seed,
                "n_buyers": len(world.buyers),
                "provenance": cal.provenance_report(),
                "policies": [r.as_dict() for r in rows],
                "segments": segments,
                "caveat": (
                    "Policy quality conditional on the assumptions in sim/calibration.py. "
                    "Not evidence those assumptions hold."
                ),
            },
            indent=2,
            default=str,
        )
    )
    print("\nartifacts/evaluation.json written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
