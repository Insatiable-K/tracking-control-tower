"""
Persisted ShipmentState snapshots (ARCHITECTURE.md storage/ layer).

Keyed by (SIPL, container), not either one alone. Two real findings
drove this, both from actual 1RAW.xlsx data, not speculation:

1. Container numbers get reused for entirely unrelated shipments within
   weeks (comparison/snapshot_diff.py's docstring has the details) -
   ruling out keying by container alone.
2. One SIPL can legitimately span MULTIPLE containers - real example
   found via the orchestration layer's smoke test against 1RAW.xlsx:
   SIPL 168893 covers three different containers (MEDU3697078,
   MEDU2304983, MEDU6299740), a normal pattern for a purchase order or
   consolidated shipment split across containers. Keying by SIPL alone
   would have let one container's tracking history silently overwrite
   another's under the same SIPL - ruling that out too.

Each container within a shipment has its own independent physical
journey (different vessel, different discharge date, etc.), so the
composite key is the right granularity for both problems at once.

Append-only: every run's snapshot is kept, not overwritten, so
comparison/snapshot_diff.py always has real prior state to diff against
and a full per-shipment timeline can be reconstructed for review.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from tracking_control_tower.shipment_state.models import ShipmentState

_SCHEMA = """
CREATE TABLE IF NOT EXISTS shipment_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sipl TEXT NOT NULL,
    container TEXT NOT NULL,
    run_at TEXT NOT NULL,
    current_phase TEXT,
    current_phase_rank INTEGER,
    current_location TEXT,
    current_vessel TEXT,
    current_eta TEXT,
    previous_event TEXT,
    previous_event_date TEXT,
    first_event_date TEXT,
    latest_event_date TEXT,
    next_expected_event TEXT,
    confidence_score REAL NOT NULL,
    delivery_attempt_count INTEGER NOT NULL,
    data_quality_issues TEXT NOT NULL,
    missing_information TEXT NOT NULL,
    phases_visited TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_sipl_container_run_at
    ON shipment_snapshots (sipl, container, run_at);
"""

_STATE_COLUMNS = """
    current_phase, current_phase_rank, current_location,
    current_vessel, current_eta, previous_event, previous_event_date,
    first_event_date, latest_event_date, next_expected_event,
    confidence_score, delivery_attempt_count, data_quality_issues, missing_information,
    phases_visited
"""


def _dt_to_str(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _str_to_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row_to_state(container: str, row) -> ShipmentState:
    (
        current_phase, current_phase_rank, current_location,
        current_vessel, current_eta, previous_event, previous_event_date,
        first_event_date, latest_event_date, next_expected_event,
        confidence_score, delivery_attempt_count, data_quality_issues, missing_information,
        phases_visited,
    ) = row
    return ShipmentState(
        container=container,
        current_phase=current_phase,
        current_phase_rank=current_phase_rank,
        current_location=current_location,
        current_vessel=current_vessel,
        current_eta=_str_to_dt(current_eta),
        previous_event=previous_event,
        previous_event_date=_str_to_dt(previous_event_date),
        first_event_date=_str_to_dt(first_event_date),
        latest_event_date=_str_to_dt(latest_event_date),
        next_expected_event=next_expected_event,
        confidence_score=confidence_score,
        delivery_attempt_count=delivery_attempt_count,
        data_quality_issues=json.loads(data_quality_issues),
        missing_information=json.loads(missing_information),
        phases_visited=frozenset(json.loads(phases_visited)),
    )


class SnapshotStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SnapshotStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def save(self, sipl: str, container: str, state: ShipmentState, run_at: datetime | None = None) -> None:
        run_at = run_at or datetime.now()
        self._conn.execute(
            f"""
            INSERT INTO shipment_snapshots (sipl, container, run_at, {_STATE_COLUMNS})
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sipl, container, run_at.isoformat(),
                state.current_phase, state.current_phase_rank, state.current_location,
                state.current_vessel, _dt_to_str(state.current_eta),
                state.previous_event, _dt_to_str(state.previous_event_date),
                _dt_to_str(state.first_event_date), _dt_to_str(state.latest_event_date),
                state.next_expected_event, state.confidence_score, state.delivery_attempt_count,
                json.dumps(state.data_quality_issues), json.dumps(state.missing_information),
                json.dumps(sorted(state.phases_visited)),
            ),
        )
        self._conn.commit()

    def get_latest(self, sipl: str, container: str) -> ShipmentState | None:
        row = self._conn.execute(
            f"""SELECT {_STATE_COLUMNS} FROM shipment_snapshots
                WHERE sipl = ? AND container = ? ORDER BY run_at DESC LIMIT 1""",
            (sipl, container),
        ).fetchone()
        return _row_to_state(container, row) if row is not None else None

    def get_history(self, sipl: str, container: str) -> list[tuple[datetime, ShipmentState]]:
        rows = self._conn.execute(
            f"""SELECT run_at, {_STATE_COLUMNS} FROM shipment_snapshots
                WHERE sipl = ? AND container = ? ORDER BY run_at ASC""",
            (sipl, container),
        ).fetchall()
        return [(datetime.fromisoformat(r[0]), _row_to_state(container, r[1:])) for r in rows]
