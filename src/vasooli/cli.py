"""Command line entry point.

    vasooli evaluate            compare policies on the held-out book
    vasooli train               fit the archetype model
    vasooli breakeven           find where the headline finding stops holding
    vasooli trail <buyer>       one buyer's full decision history
    vasooli restraint           the moments the agent chose not to send
    vasooli prove               end-to-end recovery against Razorpay test mode
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .agent.inference import ArchetypeModel
from .agent.policy import CauseMatchedPolicy
from .domain.enums import Intervention
from .domain.money import fmt
from .eval import runner
from .sim.world import generate

app = typer.Typer(add_completion=False, help="A restrained B2B receivables recovery agent.")
console = Console()

ROOT = Path(__file__).resolve().parents[2]


def _script(name: str, *args: str) -> int:
    return subprocess.call([sys.executable, str(ROOT / "scripts" / name), *args])


@app.command()
def evaluate(
    merchants: int = 14, buyers: int = 52, seed: int = 20260824
) -> None:
    """Compare every policy on the held-out book."""
    raise typer.Exit(
        _script("evaluate.py", "--merchants", str(merchants), "--buyers", str(buyers), "--seed", str(seed))
    )


@app.command()
def train(drop_structural: bool = False) -> None:
    """Fit the archetype model and report hold-out performance."""
    args = ["--drop-structural"] if drop_structural else []
    raise typer.Exit(_script("train_inference.py", *args))


@app.command()
def breakeven(metric: str = "net_value", merchants: int = 8) -> None:
    """Find the value at which our own headline finding stops being true."""
    raise typer.Exit(_script("breakeven.py", "--metric", metric, "--merchants", str(merchants)))


@app.command()
def sensitivity(merchants: int = 6) -> None:
    """Sweep the assumptions that might be carrying the result."""
    raise typer.Exit(_script("sensitivity.py", "--merchants", str(merchants)))


@app.command()
def prove(amount: float = 2500.0, invoice: str = "PKG/26-27/0412") -> None:
    """Recover one real payment through Razorpay test mode."""
    raise typer.Exit(_script("prove_recovery.py", "--amount", str(amount), "--invoice", invoice))


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


def _run_agent(merchants: int, buyers: int, seed: int):
    world = generate(seed=seed, n_merchants=merchants, buyers_per_merchant=buyers)
    udyam = {
        b: next(m.udyam_registered for m in world.merchants if m.merchant_id == world.buyer_merchant[b])
        for b in world.buyers
    }
    model = ArchetypeModel.load() if (ROOT / "artifacts/models/archetype.pkl").exists() else None
    policy = CauseMatchedPolicy(model=model, merchant_udyam=udyam)
    policy.name = "cause-matched"
    return world, runner.run(world, policy), policy


@app.command()
def trail(
    buyer: str = typer.Argument("", help="Buyer id, or blank for the most eventful one"),
    merchants: int = 2,
    buyers: int = 40,
    seed: int = 20260824,
) -> None:
    """Show every decision made about one buyer, with the reasoning.

    This is the audit trail the track asks for: not a log of what was sent, but
    of what was considered, what was blocked, by which rule, and why the
    survivor won.
    """
    world, result, _ = _run_agent(merchants, buyers, seed)

    if not buyer:
        counts: dict[str, int] = {}
        for d in result.decisions:
            if d.chosen is not Intervention.HOLD:
                counts[d.buyer_id] = counts.get(d.buyer_id, 0) + 1
        if not counts:
            console.print("[yellow]No actions taken in this run.[/yellow]")
            raise typer.Exit(1)
        buyer = max(counts, key=counts.get)

    b = world.buyers.get(buyer)
    if b is None:
        console.print(f"[red]No such buyer: {buyer}[/red]")
        raise typer.Exit(1)

    truth = world.truth[buyer]
    console.print(f"\n[bold]{b.legal_name}[/bold]  ({buyer})")
    console.print(f"{b.city}, {b.state}   terms {b.agreed_terms_days}d   "
                  f"{b.revenue_share:.1%} of revenue   tenure {b.tenure_months}mo")
    console.print(f"[dim]ground truth (hidden from the agent): {truth.archetype} "
                  f"| effective terms {truth.effective_terms_days}d[/dim]\n")

    table = Table(show_lines=False, header_style="bold")
    table.add_column("date", style="dim", width=11)
    table.add_column("action", width=21)
    table.add_column("belief", width=22)
    table.add_column("why")

    for d in result.decisions:
        if d.buyer_id != buyer:
            continue
        belief = (
            f"{d.inferred_archetype} {d.archetype_confidence:.0%}"
            if d.inferred_archetype
            else "[dim]cold start[/dim]"
        )
        style = "yellow" if d.chosen is Intervention.HOLD else "green"
        action = d.chosen.value + (" [red](needs sign-off)[/red]" if d.requires_human_approval else "")
        table.add_row(d.as_of.isoformat(), f"[{style}]{action}[/{style}]", belief, d.rationale)

    console.print(table)

    paid = [p for p in result.state.payments if p.buyer_id == buyer]
    total = sum(p.amount for p in paid)
    owed = sum(world.invoices[i].amount for i in world.invoices if world.invoices[i].buyer_id == buyer)
    console.print(f"\nrecovered {fmt(total)} of {fmt(owed)}  ({len(paid)} payments)")


@app.command()
def restraint(merchants: int = 2, buyers: int = 40, seed: int = 20260824, limit: int = 20) -> None:
    """The moments the agent decided not to send, and the rule that stopped it.

    Anyone can build a bot that chases. The interesting output is the silence,
    and this is where it is legible.
    """
    world, result, _ = _run_agent(merchants, buyers, seed)

    blocked: dict[str, list] = {}
    for d in result.decisions:
        if d.chosen is not Intervention.HOLD:
            continue
        for g in d.gates:
            if not g.passed:
                blocked.setdefault(g.gate, []).append((d, g))
                break

    table = Table(title="Why the agent stayed quiet", header_style="bold")
    table.add_column("gate", style="cyan")
    table.add_column("times", justify="right")
    table.add_column("example")
    for gate, rows in sorted(blocked.items(), key=lambda kv: -len(kv[1])):
        table.add_row(gate, str(len(rows)), rows[0][1].reason[:88])
    console.print(table)

    console.print("\n[bold]Promise freezes in detail[/bold] (the agent going silent on its own word):")
    shown = 0
    for d, g in blocked.get("promise_freeze", []):
        console.print(f"  {d.as_of.isoformat()}  {d.buyer_id[-8:]}  [dim]{g.reason}[/dim]")
        shown += 1
        if shown >= limit:
            break
    if not shown:
        console.print("  [dim]none in this run[/dim]")


if __name__ == "__main__":
    app()
