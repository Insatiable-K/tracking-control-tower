"""
Temporal comparison: this run's ShipmentState vs. the last persisted
snapshot for the same container (ARCHITECTURE.md §06 "Temporal" axis).

Compares canonical, normalized values (phase label, voyage-stripped
vessel name, day-level ETA) - not raw scraped text against raw text,
which is what made MSC_INC.py's compare_eta/compare_vessels brittle to
formatting differences (see FEASIBILITY.md §02/§06).

Container-reuse guard, and its real, tested limit: real historical data
caught container numbers being reassigned to an entirely unrelated
shipment weeks later (same physical container leased out again after
being emptied - a normal industry practice, not a data error). The
guard below catches the clean case, where the old cycle's last known
event predates the new cycle's first. Checked against every real reuse
pair actually present in HL's historical data (5 containers, same
before/after files): EVERY one has OVERLAPPING date ranges instead - the
new booking's "gate out empty" is scraped 4-7 weeks before the old
booking's final delivery leg finishes closing out in the source system.
This guard does NOT catch that pattern, and no reasonable heuristic
over ShipmentState summary fields alone reliably will, because the two
cycles' events are genuinely interleaved in time. It's kept as a
partial safety net for the cleaner case, not relied on as the fix.
The real fix is keying snapshot storage by (SIPL, container), not bare
container number alone - see storage/snapshot_store.py, which also
covers the other half of this: one SIPL can legitimately span multiple
containers (a real pattern found in 1RAW.xlsx), so SIPL alone isn't
sufficient either.
"""
from tracking_control_tower.comparison.models import FieldChange, SnapshotDiff
from tracking_control_tower.shipment_state.models import ShipmentState
from tracking_control_tower.utils.dates import same_day
from tracking_control_tower.utils.vessel_names import normalize_vessel_name


def _looks_like_container_reuse(previous: ShipmentState, current: ShipmentState) -> bool:
    if current.first_event_date is None or previous.latest_event_date is None:
        return False
    if current.current_phase_rank is None or previous.current_phase_rank is None:
        return False
    starts_after_everything_known = current.first_event_date > previous.latest_event_date
    reports_lower_phase = current.current_phase_rank < previous.current_phase_rank
    return starts_after_everything_known and reports_lower_phase


def diff_snapshots(previous: ShipmentState | None, current: ShipmentState) -> SnapshotDiff:
    if previous is None:
        return SnapshotDiff(
            container=current.container, is_first_seen=True,
            state_changed=False, vessel_changed=False, eta_changed=False,
        )

    if _looks_like_container_reuse(previous, current):
        return SnapshotDiff(
            container=current.container, is_first_seen=False,
            state_changed=False, vessel_changed=False, eta_changed=False,
            likely_new_cycle=True,
            changes=[FieldChange(
                "container_cycle",
                f"previous cycle ended at {previous.current_phase!r} ({previous.latest_event_date})",
                f"new cycle starting {current.first_event_date}",
            )],
        )

    changes: list[FieldChange] = []

    state_changed = previous.current_phase != current.current_phase
    if state_changed:
        changes.append(FieldChange("current_phase", previous.current_phase, current.current_phase))

    prev_vessel = normalize_vessel_name(previous.current_vessel)
    curr_vessel = normalize_vessel_name(current.current_vessel)
    vessel_changed = prev_vessel != curr_vessel
    if vessel_changed:
        changes.append(FieldChange("current_vessel", previous.current_vessel, current.current_vessel))

    eta_changed = not same_day(previous.current_eta, current.current_eta)
    if eta_changed:
        changes.append(FieldChange("current_eta", previous.current_eta, current.current_eta))

    return SnapshotDiff(
        container=current.container, is_first_seen=False,
        state_changed=state_changed, vessel_changed=vessel_changed, eta_changed=eta_changed,
        changes=changes,
    )
