"""Finding the condition under which our own headline finding is wrong.

The project's central empirical claim - that high-frequency chasing loses money -
rests almost entirely on one number we invented: the per-message contact-fatigue
multiplier. We did not measure it. We chose it.

Rather than defend the choice, this module locates the threshold. It sweeps the
fatigue parameter and finds where blast-weekly stops losing to the cause-matched
policy, so the claim can be stated in the only form that is actually useful to
someone who does not share our priors:

    Cause-matched beats blast-weekly while per-message retention is below f*.
    Above f*, spamming wins and our thesis is wrong on this book.

A reader who believes buyers tolerate more contact than we assumed can then
check their own belief against f* and decide whether our conclusion survives it,
without taking our word for anything.

The sweep is reported as a curve rather than a single number, because the shape
matters: a conclusion that holds across a wide plateau is different from one
that holds in a narrow band, and the difference should be visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..agent.inference import ArchetypeModel, PriorOnlyModel
from ..agent.policy import CauseMatchedPolicy
from ..sim import calibration as cal
from ..sim.world import World, generate
from . import baselines, metrics, runner


@dataclass
class SweepPoint:
    """One parameter value, and how the two policies did under it."""

    retention: float
    """Per-message responsiveness retained past the free allowance. 1.0 means
    contact never fatigues; 0.80 means each excess message costs a fifth of the
    effect of everything sent afterwards."""

    agent_value: float
    rival_value: float
    agent_messages: int
    rival_messages: int

    @property
    def margin(self) -> float:
        """Agent minus rival. Positive means our thesis holds at this value."""
        return self.agent_value - self.rival_value


@dataclass
class BreakevenResult:
    metric: str
    points: list[SweepPoint] = field(default_factory=list)
    chosen_retention: float = 0.0
    crossing: float | None = None
    parameter: str = "contact retention"
    rival: str = "blast-weekly"
    regenerated: bool = False

    def collapse(self) -> tuple[float, float]:
        """Worst margin in the swept range, and its ratio to the margin at our
        chosen value.

        Reported because "no crossing" badly undersells what a sweep can show.
        A parameter whose worst case still wins but wipes out 88% of the margin
        is carrying the result; one whose worst case costs 17% is not. The
        crossing alone cannot tell those apart.
        """
        chosen_pt = min(self.points, key=lambda p: abs(p.retention - self.chosen_retention))
        worst = min(p.margin for p in self.points)
        base = chosen_pt.margin
        return worst, (worst / base if base else float("nan"))

    def holds_at_chosen(self) -> bool:
        pt = min(self.points, key=lambda p: abs(p.retention - self.chosen_retention))
        return pt.margin > 0

    def summary(self) -> str:
        lines = [
            f"BREAKEVEN on {self.parameter}  "
            f"(cause-matched vs {self.rival}, metric: {self.metric})",
            "",
            "Our headline finding rests on a parameter we invented. This is the",
            "value at which it stops being true.",
            "",
            f"{'value':>10}{'agent':>16}{self.rival[:14]:>16}{'margin':>16}{'msgs a/r':>16}",
            "-" * 74,
        ]
        for p in sorted(self.points, key=lambda x: -x.retention):
            mark = "  <- chosen" if abs(p.retention - self.chosen_retention) < 1e-9 else ""
            lines.append(
                f"{p.retention:>10.2f}"
                f"{p.agent_value / 100:>16,.0f}"
                f"{p.rival_value / 100:>16,.0f}"
                f"{p.margin / 100:>16,.0f}"
                f"{p.agent_messages:>8}/{p.rival_messages:<7}{mark}"
            )
        worst, ratio = self.collapse()
        lines.append(
            f"Worst case in range: margin {worst / 100:,.0f} "
            f"({ratio:.0%} of the margin at our chosen value)."
        )
        if ratio < 0.5:
            lines.append(
                "This parameter CARRIES the result: most of the advantage "
                "disappears at the unfavourable end of the range."
            )
        elif ratio < 0.85:
            lines.append("This parameter matters but does not carry the result.")
        else:
            lines.append("The result is largely insensitive to this parameter.")
        if self.regenerated:
            lines.append(
                "[generation-time parameter: population regenerated per point, so "
                "points are not paired with each other]"
            )
        lines.append("")
        if self.crossing is None:
            direction = "at every value swept" if self.holds_at_chosen() else "at no value swept"
            lines.append(f"No crossing found: the cause-matched policy wins {direction}.")
            lines.append("A conclusion that never flips inside the swept range is not thereby")
            lines.append("robust - it may mean the range was too narrow. The range is stated above.")
        else:
            lines.append(
                f"CROSSING at retention f* = {self.crossing:.3f}. "
                f"We chose {self.chosen_retention:.2f}."
            )
            if self.holds_at_chosen():
                slack = self.chosen_retention - self.crossing
                lines.append(
                    f"Our thesis holds while per-message retention stays below "
                    f"{self.crossing:.3f}; we assumed {self.chosen_retention:.2f}, "
                    f"a margin of {abs(slack):.3f}."
                )
                lines.append(
                    "If buyers in reality tolerate contact better than that, "
                    "blast-weekly wins and we are wrong."
                )
            else:
                lines.append("At our own chosen value the thesis does NOT hold. That is the finding.")
        return "\n".join(lines)


RIVALS = {
    "blast-weekly": baselines.BlastWeekly,
    "static-ladder": baselines.StaticLadder,
    "never-chase": baselines.NeverChase,
}


def _run_pair(
    world: World, model, udyam: dict[str, bool], metric: str, rival_name: str
) -> tuple[float, float, int, int]:
    agent = CauseMatchedPolicy(model=model, merchant_udyam=udyam)
    agent.name = "cause-matched"
    rival = RIVALS[rival_name]()

    ar = runner.run(world, agent)
    rr = runner.run(world, rival)
    am, rm = metrics.score(world, ar), metrics.score(world, rr)

    pick = {"recovered": lambda m: float(m.recovered), "net_value": lambda m: float(m.net_value)}[metric]
    return pick(am), pick(rm), am.messages, rm.messages


def _interpolate_crossing(points: list[SweepPoint]) -> float | None:
    """Linear interpolation of the retention at which the margin hits zero.

    Uses the first sign change encountered scanning from harsh fatigue towards
    gentle. Linear is honest here: the sweep is coarse, and fitting anything
    smoother would imply a precision the eight sampled points do not support.
    """
    ordered = sorted(points, key=lambda p: p.retention)
    for a, b in zip(ordered, ordered[1:]):
        if a.margin == 0:
            return a.retention
        if (a.margin > 0) != (b.margin > 0):
            span = a.margin - b.margin
            if span == 0:
                return (a.retention + b.retention) / 2
            t = a.margin / span
            return a.retention + t * (b.retention - a.retention)
    return None


#: Parameters consumed at world-generation time. Overriding one of these after
#: the world exists changes nothing about the population - it only perturbs the
#: agent's prior, which happens to read the same table. An earlier version swept
#: ARCHETYPE_MIX against an already-generated world and reported the result as
#: "if few buyers are cyclic payers", when what it actually measured was "if the
#: agent's belief about the population is wrong". Both are worth knowing and
#: they are not the same question.
GENERATION_TIME = ("ARCHETYPE_MIX",)


def is_generation_time(parameter: str) -> bool:
    return parameter.split(".", 1)[0] in GENERATION_TIME


def sweep_parameter(
    world: World,
    parameter: str,
    values: tuple[float, ...],
    *,
    model: ArchetypeModel | PriorOnlyModel | None = None,
    rival: str = "blast-weekly",
    metric: str = "net_value",
    regenerate: bool | None = None,
    verbose: bool = True,
) -> BreakevenResult:
    """Sweep any calibration parameter and report where the ranking flips.

    Generalised after the fatigue sweep found no crossing anywhere in its range:
    if a conclusion does not depend on the parameter you assumed was carrying it,
    the useful next question is which parameter is - and that question needs a
    sweep that is not hard-wired to one constant.
    """
    if regenerate is None:
        regenerate = is_generation_time(parameter)

    chosen = _current_value(parameter)
    result = BreakevenResult(
        metric=metric,
        chosen_retention=chosen,
        parameter=parameter,
        rival=rival,
        regenerated=regenerate,
    )

    for v in values:
        with cal.overrides(**{parameter: v}):
            # A generation-time parameter needs a fresh population, or the sweep
            # is measuring something other than what it says. Each point is
            # still an internally paired comparison - both policies see the same
            # world - but points are no longer paired with each other, so the
            # curve is noisier than a runtime sweep and is labelled as such.
            w = (
                generate(
                    seed=world.seed,
                    n_merchants=len(world.merchants),
                    buyers_per_merchant=len(world.buyers) // len(world.merchants),
                )
                if regenerate
                else world
            )
            av, rv, am, rm = _run_pair(w, model, _udyam(w), metric, rival)
        result.points.append(
            SweepPoint(retention=v, agent_value=av, rival_value=rv, agent_messages=am, rival_messages=rm)
        )
        if verbose:
            print(f"    {parameter}={v:<6.3f}  margin {(av - rv) / 100:>14,.0f}")

    result.crossing = _interpolate_crossing(result.points)
    return result


def _current_value(parameter: str) -> float:
    if "." in parameter:
        container, member = parameter.split(".", 1)
        from ..domain.enums import BuyerArchetype

        return float(getattr(cal, container)[BuyerArchetype(member)].value)
    obj = getattr(cal, parameter)
    return float(obj.value if isinstance(obj, cal.Param) else obj)


def _udyam(world: World) -> dict[str, bool]:
    return {
        b: next(m.udyam_registered for m in world.merchants if m.merchant_id == world.buyer_merchant[b])
        for b in world.buyers
    }


def sweep(
    world: World,
    *,
    model: ArchetypeModel | PriorOnlyModel | None = None,
    metric: str = "net_value",
    retentions: tuple[float, ...] = (1.00, 0.97, 0.94, 0.91, 0.88, 0.84, 0.78, 0.70),
    verbose: bool = True,
) -> BreakevenResult:
    udyam = _udyam(world)
    chosen = 1.0 - float(cal.FATIGUE_PER_EXCESS_CONTACT.value)
    result = BreakevenResult(
        metric=metric, chosen_retention=chosen, parameter="contact retention", rival="blast-weekly"
    )

    for r in retentions:
        with cal.overrides(FATIGUE_PER_EXCESS_CONTACT=1.0 - r):
            av, rv, am, rm = _run_pair(world, model, udyam, metric, "blast-weekly")
        result.points.append(
            SweepPoint(retention=r, agent_value=av, rival_value=rv, agent_messages=am, rival_messages=rm)
        )
        if verbose:
            print(f"    retention {r:.2f}  margin {(av - rv) / 100:>14,.0f}")

    result.crossing = _interpolate_crossing(result.points)
    return result
