"""Builds the list of shipments to process from cleaned SPS data."""
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from tracking_control_tower.cleaning.shipment_cleaner import CleaningResult


@dataclass
class WorkItem:
    sipl: str
    container: str
    vessel: str | None
    port_eta: datetime | None
    ship_to_location: str | None
    location_eta: datetime | None = None
    sipl_status: str | None = None


_NAN_TEXT = {"nan", "nat", "none"}


def _clean_value(value):
    """
    A real source row can have a genuinely blank cell for sipl/
    container/vessel/etc. - shipment_cleaner.py's astype(str) calls
    turn that missing value into the literal text "nan"/"NaN" (that's
    what str(float('nan')) produces) rather than leaving it blank, and
    by the time it reaches here pd.notna() no longer sees it as
    missing (it's just a normal-looking string now). Catching that
    text explicitly is what actually keeps a truly blank source cell
    blank in the report, instead of showing "nan" as if it were real
    data - a real row (SIPL 164687, blank container and vessel) is
    what surfaced this.
    """
    if pd.isna(value):
        return None
    if isinstance(value, str) and value.strip().lower() in _NAN_TEXT:
        return None
    return value


def build_worklist(cleaning_result: CleaningResult) -> list[WorkItem]:
    df = cleaning_result.cleaned
    items = []
    for _, row in df.iterrows():
        items.append(WorkItem(
            sipl=_clean_value(row["sipl"]) or "",
            container=_clean_value(row["container"]) or "",
            vessel=_clean_value(row.get("vessel")),
            port_eta=_clean_value(row.get("port_eta")),
            ship_to_location=_clean_value(row.get("ship_to_location")),
            location_eta=_clean_value(row.get("location_eta")),
            sipl_status=_clean_value(row.get("sipl_status")),
        ))
    return items
