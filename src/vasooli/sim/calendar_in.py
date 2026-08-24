"""Indian working calendar, approximate and deliberately conservative.

Fixed-date national holidays are exact. Festival dates move with lunar
calendars, so those listed here are approximations for the simulated year, and
where a date is uncertain the calendar errs towards marking it a holiday - the
cost of not sending a reminder on a working day is small, and the cost of
messaging someone during Diwali is not.
"""

from __future__ import annotations

from datetime import date

FIXED = {(1, 26), (8, 15), (10, 2), (5, 1)}
"""Republic Day, Independence Day, Gandhi Jayanti, Labour Day."""

APPROX_2026: set[date] = {
    date(2026, 3, 4),   # Holi (approx)
    date(2026, 3, 21),  # Eid al-Fitr (approx)
    date(2026, 3, 26),  # Ram Navami (approx)
    date(2026, 3, 31),  # Mahavir Jayanti (approx)
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 14),  # Ambedkar Jayanti
    date(2026, 5, 27),  # Eid al-Adha (approx)
    date(2026, 8, 26),  # Janmashtami (approx)
    date(2026, 9, 14),  # Ganesh Chaturthi (approx)
    date(2026, 10, 20), # Dussehra (approx)
    date(2026, 11, 8),  # Diwali (approx)
    date(2026, 12, 25), # Christmas
}

DIWALI_WINDOW_2026 = (date(2026, 11, 6), date(2026, 11, 12))
"""Businesses shut for several days around Diwali. Contact in this window is
not merely unwelcome; there is nobody at the AP desk to read it."""


def is_holiday(d: date) -> bool:
    if (d.month, d.day) in FIXED or d in APPROX_2026:
        return True
    lo, hi = DIWALI_WINDOW_2026
    return lo <= d <= hi


def is_sunday(d: date) -> bool:
    return d.weekday() == 6


def is_contactable_day(d: date) -> bool:
    return not is_sunday(d) and not is_holiday(d)
