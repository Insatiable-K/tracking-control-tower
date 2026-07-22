"""
Cleaning stage — parity port of MSC_INC.py steps 1-6 and HL Tracking/cleaning.py.

Behavior is intentionally unchanged from the original scripts (see
FEASIBILITY.md §05): rename columns, parse dates, trim SIPL/container IDs,
drop completed-status rows, keep only blank-LFD rows, dedupe by container,
then segregate by vessel prefix. Carrier-agnostic — this runs once on the
full SPS export, upstream of any carrier-specific scraping.
"""
import re
from dataclasses import dataclass, field

import pandas as pd

from tracking_control_tower.config.settings import (
    DATE_COLUMNS,
    EXPECTED_COLUMNS,
    STATUSES_TO_REMOVE,
    VESSEL_PREFIXES,
)

# ISO 6346: 4 letters (owner code + category identifier) + 7 digits (6
# digits + check digit). A real row's raw container cell caught this
# not holding: "Freight 5 PO SEGU2963797-" (a note plus the real
# container number plus a trailing hyphen) - taking the LAST 11
# characters positionally grabbed "EGU2963797-" (drops the real leading
# "S", keeps the trailing "-"). Searching for the actual ISO-shaped
# substring instead of trusting position finds the genuine container
# number regardless of what surrounds it, and finds nothing (not a
# best-effort guess) when there isn't one.
_CONTAINER_NUMBER = re.compile(r"[A-Z]{4}\d{7}")


def _extract_container_number(raw) -> str | None:
    if pd.isna(raw):
        return None
    match = _CONTAINER_NUMBER.search(str(raw).strip().upper())
    return match.group() if match else None


@dataclass
class CleaningResult:
    cleaned: pd.DataFrame
    vessel_dfs: dict[str, pd.DataFrame]
    mismatched: pd.DataFrame
    counts: dict[str, int] = field(default_factory=dict)


def load_sps_export(path: str, sheet_name: str = "Sheet 1") -> pd.DataFrame:
    # Explicit context manager, not a bare pd.ExcelFile(path): an
    # unclosed handle left the source file locked on Windows until
    # garbage collection got around to it, which surfaced as a
    # PermissionError when tests tried to clean up a temp copy of
    # 1RAW.xlsx immediately afterward.
    with pd.ExcelFile(path) as xls:
        if sheet_name not in xls.sheet_names:
            raise ValueError(f"Sheet '{sheet_name}' not found. Sheets present: {xls.sheet_names}")
        df = xls.parse(sheet_name)

    if len(df.columns) != len(EXPECTED_COLUMNS):
        raise ValueError(
            f"Unexpected number of columns: {len(df.columns)} instead of "
            f"{len(EXPECTED_COLUMNS)}. Columns found: {list(df.columns)}"
        )
    df.columns = EXPECTED_COLUMNS
    return df


def clean_sps_export(path: str, sheet_name: str = "Sheet 1") -> CleaningResult:
    df = load_sps_export(path, sheet_name)
    counts: dict[str, int] = {"raw_rows": len(df)}

    for col in DATE_COLUMNS:
        df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)

    df["sipl"] = df["sipl"].astype(str).str.strip().str[:6]
    df["container"] = df["container"].apply(_extract_container_number)
    counts["container_extraction_failed"] = int(df["container"].isna().sum())

    df["sipl_status"] = df["sipl_status"].astype(str).str.strip()
    statuses_to_remove_lower = [s.lower() for s in STATUSES_TO_REMOVE]
    before = len(df)
    df = df[~df["sipl_status"].str.lower().isin(statuses_to_remove_lower)].copy()
    counts["removed_by_status"] = before - len(df)

    before = len(df)
    df = df[df["lfd"].isna()]
    counts["removed_by_lfd"] = before - len(df)

    before = len(df)
    # A row where container extraction found nothing isn't a duplicate
    # of every OTHER such row - pandas' drop_duplicates treats multiple
    # NaNs as equal to each other, which would silently collapse
    # distinct real rows down to one just because none of them had a
    # parseable container number. Falling back to the row's own index
    # (always unique) for the dedup key when container is missing keeps
    # every one of them instead of merging them away.
    dedup_key = df["container"].where(df["container"].notna(), "MISSING_" + df.index.astype(str))
    df = df[~dedup_key.duplicated(keep="first")]
    counts["removed_duplicates"] = before - len(df)

    df["vessel"] = df["vessel"].astype(str).str.strip().str.upper()

    vessel_dfs: dict[str, pd.DataFrame] = {}
    for prefix in VESSEL_PREFIXES:
        vessel_dfs[prefix] = df[df["vessel"].str.startswith(prefix)].copy()

    pattern = "^(" + "|".join(VESSEL_PREFIXES) + ")"
    mismatched = df[~df["vessel"].str.match(pattern)].copy()

    counts["final_rows"] = len(df)
    counts["mismatched_rows"] = len(mismatched)
    for prefix, vdf in vessel_dfs.items():
        counts[f"vessel_{prefix}"] = len(vdf)

    return CleaningResult(cleaned=df, vessel_dfs=vessel_dfs, mismatched=mismatched, counts=counts)
