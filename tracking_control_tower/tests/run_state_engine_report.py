"""
Real-scale validation of the shipment state engine: build each container's
full event history from the most recent historical snapshot per carrier
and run infer_state() on every one, reporting the current_phase
distribution, contradiction rate, and confidence distribution.

Run: python -m tracking_control_tower.tests.run_state_engine_report
"""
import collections
import glob
from pathlib import Path

import pandas as pd

from tracking_control_tower.events.classifier import classify
from tracking_control_tower.shipment_state.engine import infer_state
from tracking_control_tower.shipment_state.models import ClassifiedEvent, RawEvent

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _report_hl() -> None:
    files = sorted(glob.glob(str(PROJECT_ROOT / "HL Tracking" / "old" / "HL_Parsed_*.xlsx")))
    if not files:
        print("\n=== Hapag-Lloyd: no historical data found, skipping ===")
        return
    latest = files[-1]
    d = pd.read_excel(latest)
    d["Date"] = pd.to_datetime(d["Date"], errors="coerce")

    by_container: dict[str, list[ClassifiedEvent]] = collections.defaultdict(list)
    for _, row in d.iterrows():
        text = str(row.get("History Entry", "")).strip()
        if not text:
            continue
        raw = RawEvent(container=row["Container"], date=row["Date"], raw_text=text)
        by_container[row["Container"]].append(ClassifiedEvent(raw=raw, classification=classify(text)))

    _summarize(f"Hapag-Lloyd ({Path(latest).name}, {len(by_container)} containers)", by_container)


def _report_msc() -> None:
    files = sorted(glob.glob(str(PROJECT_ROOT / "OLD" / "msc_scraped_results_*.xlsx")))
    if not files:
        print("\n=== MSC: no historical data found, skipping ===")
        return
    latest = files[-1]
    d = pd.read_excel(latest, sheet_name="Clean Data")
    d["date"] = pd.to_datetime(d["date"], errors="coerce")

    by_container: dict[str, list[ClassifiedEvent]] = collections.defaultdict(list)
    for _, row in d.iterrows():
        text = str(row.get("description", "")).strip()
        if not text:
            continue
        raw = RawEvent(
            container=row["container"], date=row["date"], raw_text=text,
            location=row.get("location"), vessel_info=row.get("vessel_info"),
        )
        by_container[row["container"]].append(ClassifiedEvent(raw=raw, classification=classify(text)))

    _summarize(f"MSC ({Path(latest).name}, {len(by_container)} containers)", by_container)


def _summarize(label: str, by_container: dict[str, list[ClassifiedEvent]]) -> None:
    phase_counts: collections.Counter = collections.Counter()
    contradiction_containers = 0
    confidences: list[float] = []
    zero_confirmed = 0

    for container, events in by_container.items():
        state = infer_state(container, events)
        phase_counts[state.current_phase] += 1
        confidences.append(state.confidence_score)
        if any(i.startswith("contradiction") for i in state.data_quality_issues):
            contradiction_containers += 1
        if state.current_phase is None:
            zero_confirmed += 1

    print(f"\n=== {label} ===")
    print(f"  Current-phase distribution:")
    for phase, count in phase_counts.most_common():
        print(f"    {count:5d}  {phase}")
    print(f"  Containers with a detected contradiction: {contradiction_containers}")
    print(f"  Containers with no classifiable dated events: {zero_confirmed}")
    if confidences:
        print(f"  Confidence: min={min(confidences):.2f} avg={sum(confidences)/len(confidences):.2f} max={max(confidences):.2f}")


def main() -> None:
    _report_hl()
    _report_msc()


if __name__ == "__main__":
    main()
