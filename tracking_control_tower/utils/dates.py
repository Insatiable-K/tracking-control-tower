"""Date comparison at day-level granularity (FEASIBILITY.md §06)."""
from datetime import date, datetime


def _to_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def same_day(a, b) -> bool:
    da, db = _to_date(a), _to_date(b)
    if da is None or db is None:
        return da is db
    return da == db
