"""Money is integer paise. Never a float.

Every rupee figure in this system - invoice amounts, partial payments, disputed
deductions, MSMED interest - is stored and arithmetic'd as an integer count of
paise. Floats are allowed exactly once, at the moment a number is rendered for a
human to read.
"""

from __future__ import annotations

from typing import NewType

Paise = NewType("Paise", int)

PAISE_PER_RUPEE = 100


def rupees(amount: float | int) -> Paise:
    """Build Paise from a rupee figure. Rounds half-away-from-zero, deliberately.

    Used by data generation and config parsing only. Runtime arithmetic should
    stay in Paise and never round-trip through this.
    """
    scaled = amount * PAISE_PER_RUPEE
    # Python's round() is banker's rounding; for money we want half-up on .5
    # so that generated fixtures are reproducible across platforms.
    if scaled >= 0:
        return Paise(int(scaled + 0.5))
    return Paise(int(scaled - 0.5))


def to_rupees(p: Paise) -> float:
    """For display and for report serialisation only."""
    return p / PAISE_PER_RUPEE


def fmt(p: Paise, *, compact: bool = False) -> str:
    """Indian-format a paise amount: 1234567890 -> '₹1,23,45,678.90'.

    compact=True gives the crore/lakh shorthand a founder actually speaks in,
    which is what goes on a slide.
    """
    if compact:
        r = abs(to_rupees(p))
        sign = "-" if p < 0 else ""
        if r >= 1_00_00_000:
            return f"{sign}\u20b9{r / 1_00_00_000:.2f}Cr"
        if r >= 1_00_000:
            return f"{sign}\u20b9{r / 1_00_000:.2f}L"
        if r >= 1_000:
            return f"{sign}\u20b9{r / 1_000:.1f}K"
        return f"{sign}\u20b9{r:,.2f}".rstrip("0").rstrip(".")

    neg = p < 0
    whole, frac = divmod(abs(int(p)), PAISE_PER_RUPEE)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return f"{'-' if neg else ''}₹{s}.{frac:02d}"
