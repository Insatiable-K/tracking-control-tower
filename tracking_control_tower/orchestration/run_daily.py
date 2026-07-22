"""
Daily batch runner (ARCHITECTURE.md orchestration/). Ties every layer
together: clean -> route by carrier -> scrape -> classify -> infer
state -> diff -> exceptions -> report.

Two FEASIBILITY.md §10 performance techniques are load-bearing here,
not optional extras:
  - Checkpointing: a killed run resumes from the last completed
    shipment on re-run with the same run_id, instead of re-scraping
    everything from scratch.
  - Change-aware scheduling: a shipment already at rank 12 (Delivered)
    as of its last snapshot is skipped without a network call at all -
    there's nothing left for it to tell us.

One adapter instance per carrier, reused across every shipment that
carrier owns (grouped via carriers/router.py) - not one browser launch
per container, which would be needlessly slow.
"""
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from tracking_control_tower.carriers.router import adapter_for_vessel
from tracking_control_tower.cleaning.shipment_cleaner import clean_sps_export
from tracking_control_tower.comparison.snapshot_diff import diff_snapshots
from tracking_control_tower.comparison.sps_diff import diff_against_sps
from tracking_control_tower.events.classifier import classify
from tracking_control_tower.exceptions.evaluator import evaluate_exceptions
from tracking_control_tower.orchestration.checkpoint import Checkpoint
from tracking_control_tower.orchestration.worklist import WorkItem, build_worklist
from tracking_control_tower.reporting.excel_renderer import ExcelRenderer
from tracking_control_tower.reporting.models import OtherCarrierRow, ShipmentReportRow
from tracking_control_tower.reporting.report_builder import build_report_row
from tracking_control_tower.shipment_state.engine import infer_state
from tracking_control_tower.shipment_state.models import ClassifiedEvent
from tracking_control_tower.storage.snapshot_store import SnapshotStore

DELIVERED_RANK = 12


def _process_item(
    item: WorkItem, carrier_name: str, adapter, store: SnapshotStore, as_of: datetime
) -> tuple[ShipmentReportRow | None, str | None]:
    """Returns (row, error). Checking raw.error directly here matters:
    infer_state([]) produces current_phase=None with an EMPTY
    data_quality_issues (that message goes to missing_information
    instead), so trying to detect a search failure from the resulting
    ShipmentState after the fact would silently miss it."""
    previous = store.get_latest(item.sipl, item.container)

    raw = adapter.search(item.container)
    if raw.error:
        return None, raw.error

    raw_events = adapter.parse(raw)
    classified = [ClassifiedEvent(raw=e, classification=classify(e.raw_text)) for e in raw_events]
    state = infer_state(item.container, classified, ship_to_location=item.ship_to_location)

    snapshot_diff = diff_snapshots(previous, state)
    sps_diff = diff_against_sps(state, sps_vessel=item.vessel, sps_port_eta=item.port_eta)
    exceptions = evaluate_exceptions(
        state, snapshot_diff=snapshot_diff, ship_to_location=item.ship_to_location, as_of=as_of,
    )

    store.save(item.sipl, item.container, state, run_at=as_of)
    return build_report_row(item, carrier_name, state, sps_diff, exceptions), None


def run_daily_batch(
    raw_export_path: str,
    output_path: str,
    snapshot_db_path: str,
    checkpoint_db_path: str,
    run_id: str | None = None,
    as_of: datetime | None = None,
    headless: bool = False,
    route_vessel=adapter_for_vessel,
) -> tuple[list[ShipmentReportRow], dict[str, int], list[OtherCarrierRow]]:
    """route_vessel defaults to the real carrier router; tests inject a
    substitute so they can exercise the full orchestration flow with
    fake adapters instead of launching real browsers."""
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    as_of = as_of or datetime.now()

    cleaning_result = clean_sps_export(raw_export_path)
    worklist = build_worklist(cleaning_result)

    grouped: dict[type, list[WorkItem]] = defaultdict(list)
    stats = {
        "processed": 0, "skipped_delivered": 0, "skipped_checkpoint": 0,
        "errors": 0, "unrouted": 0, "recovered_on_retry": 0, "carrier_crashed": 0,
    }
    other_carrier_rows: list[OtherCarrierRow] = []

    for item in worklist:
        adapter_cls = route_vessel(item.vessel)
        if adapter_cls is None:
            stats["unrouted"] += 1
            other_carrier_rows.append(OtherCarrierRow(
                sipl=item.sipl, container=item.container, vessel=item.vessel,
                sipl_status=item.sipl_status, ship_to_location=item.ship_to_location,
                sps_port_eta=item.port_eta, sps_location_eta=item.location_eta,
            ))
            continue
        grouped[adapter_cls].append(item)

    report_rows: list[ShipmentReportRow] = []

    with SnapshotStore(snapshot_db_path) as store, Checkpoint(checkpoint_db_path) as checkpoint:
        for adapter_cls, items in grouped.items():
            try:
                with adapter_cls(headless=headless) as adapter:
                    retry_items: list[WorkItem] = []
                    for item in items:
                        if checkpoint.is_done(run_id, item.sipl, item.container):
                            stats["skipped_checkpoint"] += 1
                            continue

                        previous = store.get_latest(item.sipl, item.container)
                        if previous is not None and previous.current_phase_rank == DELIVERED_RANK:
                            checkpoint.mark_done(run_id, item.sipl, item.container, status="skipped_delivered")
                            stats["skipped_delivered"] += 1
                            continue

                        row, error = _process_item(item, adapter_cls.carrier_name, adapter, store, as_of)
                        if error:
                            # Don't mark checkpoint/stats yet - a first-pass
                            # failure might be transient (a slow page, a
                            # momentary block) rather than a real
                            # per-container problem. Retried once, at the end
                            # of this carrier's whole batch, before being
                            # accepted as a final error.
                            retry_items.append(item)
                            continue

                        report_rows.append(row)
                        checkpoint.mark_done(run_id, item.sipl, item.container, status="done")
                        stats["processed"] += 1

                    for item in retry_items:
                        row, error = _process_item(item, adapter_cls.carrier_name, adapter, store, as_of)
                        if error:
                            checkpoint.mark_done(run_id, item.sipl, item.container, status="error")
                            stats["errors"] += 1
                            continue

                        report_rows.append(row)
                        checkpoint.mark_done(run_id, item.sipl, item.container, status="done")
                        stats["processed"] += 1
                        stats["recovered_on_retry"] += 1
            except Exception as e:
                # A real run crashed here (a browser launch failure that
                # had nowhere to land as a normal per-container error at
                # the time) and took the ENTIRE batch down with it -
                # including MSC/HL work already done, since the Excel
                # report only gets written at the end. Adapters now
                # convert their own launch failures into per-container
                # errors instead (see carriers/*.py), but this stays as
                # defense in depth: whatever's genuinely unexpected here
                # must not cost every other carrier's already-collected
                # results, or the report never getting written at all.
                stats["carrier_crashed"] += 1
                print(f"Carrier {adapter_cls.carrier_name} crashed and was skipped for the rest of this run: {e}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    ExcelRenderer().render(report_rows, output_path, other_carrier_rows)

    print(f"Run {run_id} complete: {stats}")
    return report_rows, stats, other_carrier_rows
