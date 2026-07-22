"""
Full pipeline, real data, one command: classify -> infer state -> diff
vs SPS -> evaluate exceptions -> render Excel.

Uses a real historical OLD/merged_validation_output_*.xlsx, which
already pairs each container's real SPS fields (sipl, vessel, port_eta,
ship_to_location) with its real scraped tracking events from the same
point in time - the one real dataset in this repo that has both halves
matched, so this is the first time the SPS-comparison half of the
pipeline runs against genuine SPS values rather than None/synthetic
ones in every other test this session.

Run: python -m tracking_control_tower.tests.run_sample_report
"""
import glob
import re
from pathlib import Path

import pandas as pd

from tracking_control_tower.comparison.snapshot_diff import diff_snapshots
from tracking_control_tower.comparison.sps_diff import diff_against_sps
from tracking_control_tower.events.classifier import classify
from tracking_control_tower.exceptions.evaluator import evaluate_exceptions
from tracking_control_tower.orchestration.worklist import WorkItem
from tracking_control_tower.reporting.excel_renderer import ExcelRenderer
from tracking_control_tower.reporting.report_builder import build_report_row
from tracking_control_tower.shipment_state.engine import infer_state
from tracking_control_tower.shipment_state.models import ClassifiedEvent, RawEvent

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _latest_dated_merged_file() -> str:
    files = [
        f for f in glob.glob(str(PROJECT_ROOT / "OLD" / "merged_validation_output_*.xlsx"))
        if re.search(r"\d{2}-\d{2}-\d{4}", f)
    ]
    return sorted(files)[-1]


def main() -> None:
    source_file = _latest_dated_merged_file()
    print(f"Source: {source_file}")
    d = pd.read_excel(source_file, sheet_name="Matched_Containers")
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["port_eta"] = pd.to_datetime(d["port_eta"], errors="coerce")
    d["scraped_at"] = pd.to_datetime(d["scraped_at"], errors="coerce")
    # NOT d["date"].max() - "date" mixes real event dates with future
    # estimated_arrival projections, so its max is a projected ETA, not
    # a real "when did we last check" timestamp. scraped_at is the
    # actual batch-run time and is what "stalled" should measure against.
    as_of = d["scraped_at"].max()

    rows = []
    for container, grp in d.groupby("container"):
        events = []
        for _, r in grp.iterrows():
            text = str(r.get("description", "")).strip()
            if not text:
                continue
            events.append(ClassifiedEvent(
                raw=RawEvent(
                    container=container, date=r["date"], raw_text=text,
                    location=r.get("location"), vessel_info=r.get("vessel_info"),
                ),
                classification=classify(text),
            ))

        sipl = str(grp.iloc[0]["sipl"])
        ship_to_location = grp.iloc[0]["ship_to_location"]
        sps_vessel = grp.iloc[0]["vessel"]
        sps_port_eta = grp.iloc[0]["port_eta"]

        state = infer_state(container, events, ship_to_location=ship_to_location)
        snapshot_diff = diff_snapshots(None, state)  # no prior run in this demo
        sps_diff = diff_against_sps(state, sps_vessel=sps_vessel, sps_port_eta=sps_port_eta)
        exceptions = evaluate_exceptions(
            state, snapshot_diff=snapshot_diff, ship_to_location=ship_to_location, as_of=as_of,
        )
        item = WorkItem(
            sipl=sipl, container=container, vessel=sps_vessel, port_eta=sps_port_eta,
            ship_to_location=ship_to_location,
        )
        rows.append(build_report_row(item, "MSC", state, sps_diff, exceptions))

    output_path = PROJECT_ROOT / "sample_shipment_report.xlsx"
    ExcelRenderer().render(rows, str(output_path))

    risk_counts = {}
    for r in rows:
        risk_counts[r.risk_level] = risk_counts.get(r.risk_level, 0) + 1
    sps_update_count = sum(1 for r in rows if r.port_eta_needs_update or r.vessel_needs_update)

    print(f"Shipments processed: {len(rows)}")
    print(f"Risk levels: {risk_counts}")
    print(f"SPS updates recommended: {sps_update_count}")
    print(f"Written: {output_path}")


if __name__ == "__main__":
    main()
