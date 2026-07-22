"""
Checkpoint/resume tracking for a daily batch run (ARCHITECTURE.md
orchestration/; FEASIBILITY.md §10 "checkpoint recovery": persist
progress per batch so a killed run resumes from the last completed
shipment instead of restarting the whole list).

Keyed by (run_id, sipl, container) - matching storage/snapshot_store.py's
composite key exactly, and for the same two reasons: container numbers
get reused across unrelated shipments, and one SIPL can legitimately
span multiple containers (real example: SIPL 168893 covers three
distinct containers in 1RAW.xlsx). Either sipl-alone or container-alone
would let one shipment's checkpoint entry incorrectly mark a different
one as already done.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoint (
    run_id TEXT NOT NULL,
    sipl TEXT NOT NULL,
    container TEXT NOT NULL,
    status TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    PRIMARY KEY (run_id, sipl, container)
);
"""


class Checkpoint:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Checkpoint":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def is_done(self, run_id: str, sipl: str, container: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM checkpoint WHERE run_id = ? AND sipl = ? AND container = ?",
            (run_id, sipl, container),
        ).fetchone()
        return row is not None

    def mark_done(self, run_id: str, sipl: str, container: str, status: str = "done") -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO checkpoint (run_id, sipl, container, status, completed_at)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, sipl, container, status, datetime.now().isoformat()),
        )
        self._conn.commit()

    def summary(self, run_id: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) FROM checkpoint WHERE run_id = ? GROUP BY status", (run_id,)
        ).fetchall()
        return dict(rows)
