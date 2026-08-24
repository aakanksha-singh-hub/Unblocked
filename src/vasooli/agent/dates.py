"""Resolving the date expressions people actually write.

Shared by both extractors. A promise is only a stopping rule if it resolves to a
calendar date - "month end tak" has to become a day the agent can stay silent
until, and getting it wrong by a week means either hovering or losing a fortnight.

Resolution is deliberately conservative: where an expression is genuinely
ambiguous the resolver returns the *later* reading. Waiting too long costs a few
days of float. Following up too early costs the thing the restraint was for.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

_NUM = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "panch": 5, "paanch": 5,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20,
}


def end_of_month(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def next_month_day(d: date, dom: int) -> date:
    """The next occurrence of a given day-of-month, strictly after d."""
    dom = max(1, min(31, dom))
    y, m = d.year, d.month
    for _ in range(3):
        last = calendar.monthrange(y, m)[1]
        cand = date(y, m, min(dom, last))
        if cand > d:
            return cand
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return d + timedelta(days=30)


def resolve(expression: str, as_of: date) -> tuple[date | None, bool]:
    """Resolve a date expression relative to `as_of`.

    Returns (resolved_date, was_relative). A None date means the expression could
    not be pinned, which is a valid outcome and is surfaced rather than guessed:
    an unpinnable promise still suppresses contact, but is flagged for a human.
    """
    if not expression:
        return None, False
    t = expression.lower().strip()

    # Explicit day-of-month: "15 taarikh", "on the 10th", "5 tarikh ko"
    m = re.search(r"\b(\d{1,2})\s*(taarikh|tarikh|tarik|th|st|nd|rd)\b", t)
    if m:
        return next_month_day(as_of, int(m.group(1))), True

    # Explicit dd/mm or dd-mm. Must fall *through* on an invalid month rather
    # than giving up: "10-15 din me" looks like a date to this pattern, parses
    # as month 15, and used to swallow the duration expression underneath it.
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", t)
    if m and 1 <= int(m.group(2)) <= 12:
        day, mon = int(m.group(1)), int(m.group(2))
        year = as_of.year
        if m.group(3):
            year = int(m.group(3))
            year += 2000 if year < 100 else 0
        try:
            cand = date(year, mon, day)
            if cand < as_of and not m.group(3):
                cand = date(year + 1, mon, day)
            return cand, False
        except ValueError:
            pass

    # Month end. The commonest expression in this domain by a wide margin.
    if re.search(r"month\s*end|mahine?\s*ke?\s*(end|akhir)|end\s*of\s*(the\s*)?month|eom", t):
        return end_of_month(as_of), True

    # "N din me", "N days", "N weeks", "N hafte"
    m = re.search(r"\b(\d{1,3})\s*[-–to]*\s*(\d{1,3})?\s*(din|days?|day)\b", t)
    if m:
        # A range like "10-15 din" resolves to its far end, deliberately.
        n = int(m.group(2) or m.group(1))
        return as_of + timedelta(days=n), True
    m = re.search(r"\b(\d{1,2})\s*(hafte|hafta|weeks?|week)\b", t)
    if m:
        return as_of + timedelta(weeks=int(m.group(1))), True

    for word, n in _NUM.items():
        if re.search(rf"\b{word}\s*(din|days?)\b", t):
            return as_of + timedelta(days=n), True
        if re.search(rf"\b{word}\s*(hafte|weeks?)\b", t):
            return as_of + timedelta(weeks=n), True

    if re.search(r"next\s*week|agle?\s*hafte|aane?\s*wale?\s*hafte", t):
        return as_of + timedelta(days=7), True
    if re.search(r"this\s*week|is{1,2}\s*(week|hafte)", t):
        # To the end of the working week, not to today.
        return as_of + timedelta(days=max(1, 5 - as_of.weekday())), True
    if re.search(r"next\s*month|agle?\s*mahine", t):
        return end_of_month(end_of_month(as_of) + timedelta(days=1)), True
    if re.search(r"tomorrow|kal\b", t):
        # 'kal' is both yesterday and tomorrow in Hindi. In a payment promise it
        # is nearly always tomorrow, but the ambiguity is real and is flagged.
        return as_of + timedelta(days=1), True
    if re.search(r"today|aaj\b", t):
        return as_of, True

    # Event anchors. Approximate by construction, and that is stated to the user
    # rather than hidden - the agent shows the resolved date in its rationale.
    if re.search(r"gst\s*(filing|return)", t):
        # GSTR-3B lands on the 20th; payments typically clear just after.
        return next_month_day(as_of, 22), True
    if re.search(r"diwali|deepavali|holi|dussehra|eid|christmas", t):
        # Anchor to the actual festival rather than to a fixed offset. A flat
        # +21d resolved "diwali ke baad" to July, which would have restarted
        # contact four months before the buyer meant.
        from ..sim.calendar_in import APPROX_2026, DIWALI_WINDOW_2026

        if re.search(r"diwali|deepavali", t):
            _, end = DIWALI_WINDOW_2026
            return (end + timedelta(days=2), True) if end >= as_of else (
                as_of + timedelta(days=21),
                True,
            )
        upcoming = sorted(d for d in APPROX_2026 if d >= as_of)
        return ((upcoming[0] + timedelta(days=2)) if upcoming else as_of + timedelta(days=21)), True
    if re.search(r"salary|payroll", t):
        return next_month_day(as_of, 7), True

    return None, True
