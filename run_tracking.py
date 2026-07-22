"""
Production entry point for the tracking control tower - the
replacement for MSC_INC.py's single-carrier flow, now covering MSC,
Hapag-Lloyd, and Maersk through one carrier-agnostic pipeline (see
ARCHITECTURE.md and FEASIBILITY.md for the full design and validation
history).

Run: python run_tracking.py

Requirements: same as MSC_INC.py - Google Chrome installed locally,
1RAW.xlsx present in this directory with the expected columns. Flip
HEADLESS to True for unattended runs once you've watched it work
visibly a few times; every real validation trial in FEASIBILITY.md was
run with it False.

Output: a timestamped Tracking_Report_<date>_<time>.xlsx in this same
directory (sheets: Container Tracking, Other Carriers, Exceptions) -
one per run, same accumulate-in-place convention as the old script's
output files. tracking_control_tower/data/ holds the persistent
snapshots.db and checkpoints.db - these are NOT per-run output, they
carry shipment history and resume state forward across every run and
should not be deleted between runs.

The same report is also copied to the shared weekly-tracking drive
(EXPORT_BASE_DIR below) under <year>/<month name>/<today's date
folder>, since that's where the team actually looks for it, not this
working directory. The date folder format is mm-dd-yy (month first,
then day) - _resolve_export_dir() reuses whatever mm-dd-yy folder
already exists for today (padded or unpadded) rather than creating a
duplicate, and only falls back to creating a new zero-padded mm-dd-yy
folder when none exists yet. A handful of folders already in this
share (e.g. today's, at the time this was written) are named
dd-mm-yy - those are pre-existing anomalies, not the convention, so
they're deliberately not matched here.
"""
import shutil
from datetime import datetime
from pathlib import Path

from tracking_control_tower.orchestration.run_daily import run_daily_batch

PROJECT_ROOT = Path(__file__).parent
RAW_EXPORT_PATH = PROJECT_ROOT / "1RAW.xlsx"
DATA_DIR = PROJECT_ROOT / "tracking_control_tower" / "data"
SNAPSHOT_DB_PATH = DATA_DIR / "snapshots.db"
CHECKPOINT_DB_PATH = DATA_DIR / "checkpoints.db"

EXPORT_BASE_DIR = Path(
    r"C:\Users\Abhay\Architectural Surfaces\Mohan - Logistics\Container Tracking"
    r"\Weekly Tracked SIPL Data"
)

HEADLESS = False


def _resolve_export_dir(today: datetime) -> Path:
    month_dir = EXPORT_BASE_DIR / str(today.year) / today.strftime("%B")
    month_dir.mkdir(parents=True, exist_ok=True)

    day, month, yy = today.day, today.month, today.strftime("%y")
    # mm-dd-yy only (month first, then day) - not dd-mm-yy. Padded and
    # unpadded both because the existing folders in this share are
    # unpadded (e.g. "7-1-26" for July 1), but new folders are created
    # zero-padded below.
    existing_variants = {
        f"{month}-{day}-{yy}",
        f"{month:02d}-{day:02d}-{yy}",
    }
    for candidate in month_dir.iterdir():
        if candidate.is_dir() and candidate.name in existing_variants:
            return candidate

    new_dir = month_dir / f"{month:02d}-{day:02d}-{yy}"
    new_dir.mkdir()
    return new_dir


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    output_path = PROJECT_ROOT / f"Tracking_Report_{timestamp}.xlsx"

    rows, stats, other_carrier_rows = run_daily_batch(
        raw_export_path=str(RAW_EXPORT_PATH),
        output_path=str(output_path),
        snapshot_db_path=str(SNAPSHOT_DB_PATH),
        checkpoint_db_path=str(CHECKPOINT_DB_PATH),
        headless=HEADLESS,
    )

    export_dir = _resolve_export_dir(now)
    export_copy_path = export_dir / output_path.name
    shutil.copy2(output_path, export_copy_path)

    print(f"\nReport: {output_path}")
    print(f"Also saved to: {export_copy_path}")
    print(f"Shipments in Container Tracking sheet: {len(rows)}")
    print(f"Shipments in Other Carriers sheet: {len(other_carrier_rows)}")
    print(f"Stats: {stats}")


if __name__ == "__main__":
    main()
