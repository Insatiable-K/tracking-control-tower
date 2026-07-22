"""
Computes every aggregate the operations dashboard needs from the most
recent Tracking_Report_*.xlsx and writes it as one JSON file the
dashboard HTML embeds directly (Artifacts must be self-contained - no
fetch of local files at view time).

Run: python -m tracking_control_tower.tests.build_dashboard_data
"""
import glob
import json
from pathlib import Path

import pandas as pd

from tracking_control_tower.utils.location_names import normalize_location

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Canonical phase order (shipment_state/timeline.py's PHASE_LABELS) -
# charting "Current Status" in lifecycle order, not alphabetical or
# by frequency, is what makes the funnel/stage shape readable.
PHASE_ORDER = [
    "Export", "Loaded on vessel", "Departed", "Transshipment", "Ocean transit",
    "Arrived at port", "Discharged", "Customs", "Rail", "Destination terminal",
    "Delivery", "Delivered",
]

# risk_level -> status-palette role (none/low/medium/high maps cleanly
# onto the 4-slot status palette: good/warning/serious/critical).
RISK_TO_STATUS = {"none": "good", "low": "warning", "medium": "serious", "high": "critical"}


def _latest_report() -> Path:
    files = sorted(PROJECT_ROOT.glob("Tracking_Report_*.xlsx"))
    if not files:
        raise FileNotFoundError("No Tracking_Report_*.xlsx found - run run_tracking.py first.")
    return files[-1]


def _top_n_locations(series: pd.Series, n: int = 8) -> list[dict]:
    cleaned = series.dropna().map(normalize_location).dropna()
    counts = cleaned.value_counts().head(n)
    return [{"name": name, "count": int(count)} for name, count in counts.items()]


def main() -> None:
    source = _latest_report()
    print(f"Source: {source}")

    tracking = pd.read_excel(source, sheet_name="Container Tracking")
    other = pd.read_excel(source, sheet_name="Other Carriers")
    exceptions = pd.read_excel(source, sheet_name="Exceptions")

    total = len(tracking)
    needs_update = tracking[tracking["Port ETA Needs Update?"] | tracking["Vessel Needs Update?"]]

    carrier_counts = tracking["Carrier"].value_counts().to_dict()

    status_counts_raw = tracking["Current Status"].value_counts().to_dict()
    status_counts = [
        {"name": phase, "count": int(status_counts_raw.get(phase, 0))}
        for phase in PHASE_ORDER
        if status_counts_raw.get(phase, 0) > 0
    ]

    risk_counts_raw = tracking["Risk Level"].value_counts().to_dict()
    risk_counts = [
        {"level": level, "status": RISK_TO_STATUS[level], "count": int(risk_counts_raw.get(level, 0))}
        for level in ["high", "medium", "low", "none"]
        if risk_counts_raw.get(level, 0) > 0
    ]

    # "Other Carriers" real composition: a source row with NO vessel
    # assigned yet at all (not a routing gap) vs. a real vessel prefix
    # this system doesn't have an adapter for yet (a genuine gap worth
    # surfacing, not silently lumped in with the blank-vessel majority).
    other_vessel = other["Vessel"].dropna().astype(str).str.strip()
    other_vessel = other_vessel[other_vessel != ""]
    blank_vessel_count = len(other) - len(other_vessel)
    unmatched_prefixes = (
        other_vessel.str.extract(r"^([A-Za-z]+)")[0].str.upper().value_counts().to_dict()
    )

    data = {
        "generated_from": source.name,
        "summary": {
            "total_tracked": total,
            "other_carriers_total": len(other),
            "needs_update_count": len(needs_update),
            "port_eta_needs_update": int(tracking["Port ETA Needs Update?"].sum()),
            "vessel_needs_update": int(tracking["Vessel Needs Update?"].sum()),
            "avg_confidence": round(float(tracking["Tracking Confidence"].mean()), 3),
            "data_quality_flagged": int(tracking["Data Quality Notes"].notna().sum()),
            "exceptions_total": len(exceptions),
        },
        "carrier_counts": [{"name": k, "count": int(v)} for k, v in carrier_counts.items()],
        "status_counts": status_counts,
        "risk_counts": risk_counts,
        "top_departure_ports": _top_n_locations(tracking["Departure Port"]),
        "top_arrival_ports": _top_n_locations(tracking["Arrival Port"]),
        "other_carriers": {
            "blank_vessel_count": int(blank_vessel_count),
            "unmatched_prefixes": [{"prefix": k, "count": int(v)} for k, v in unmatched_prefixes.items()],
        },
        "rows": tracking.where(pd.notna(tracking), None).to_dict(orient="records"),
    }

    # datetime -> ISO date strings, JSON can't serialize Timestamps.
    # NaT has a strftime method that raises rather than being falsy, so
    # pd.notna() must gate this before the hasattr check runs.
    for row in data["rows"]:
        for key, value in row.items():
            if pd.notna(value) and hasattr(value, "strftime"):
                row[key] = value.strftime("%Y-%m-%d")
            elif not pd.notna(value):
                row[key] = None

    output_path = Path(__file__).parent / "dashboard_data.json"
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Written: {output_path}")
    print(f"Summary: {data['summary']}")


if __name__ == "__main__":
    main()
