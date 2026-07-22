"""
Live check of MaerskAdapter.search() against the real Maersk site - not
part of the automated test suite. Run manually to confirm the adapter
still works.

Run: python -m tracking_control_tower.tests.run_maersk_live_check <container>
"""
import sys

from tracking_control_tower.carriers.maersk import MaerskAdapter
from tracking_control_tower.events.classifier import classify
from tracking_control_tower.exceptions.evaluator import evaluate_exceptions
from tracking_control_tower.shipment_state.engine import infer_state
from tracking_control_tower.shipment_state.models import ClassifiedEvent


def main() -> None:
    container = sys.argv[1] if len(sys.argv) > 1 else "MRKU7248456"
    print(f"Searching Maersk for container: {container}")

    with MaerskAdapter(headless=False) as adapter:
        raw = adapter.search(container)

    if raw.error:
        print(f"ERROR: {raw.error}")
        return

    raw_events = MaerskAdapter().parse(raw)
    print(f"Parsed {len(raw_events)} events:")
    for e in raw_events:
        print(f"  {e.date} | {e.raw_text!r} | loc={e.location!r} vessel={e.vessel_info!r}")

    classified = [ClassifiedEvent(raw=e, classification=classify(e.raw_text)) for e in raw_events]
    unclassified = [c for c in classified if c.category == "unclassified"]
    if unclassified:
        print(f"\nUNCLASSIFIED: {[c.raw.raw_text for c in unclassified]}")

    state = infer_state(container, classified)
    print(f"\ncurrent_phase={state.current_phase!r} vessel={state.current_vessel!r} "
          f"confidence={state.confidence_score} data_quality_issues={state.data_quality_issues}")

    exceptions = evaluate_exceptions(state)
    print(f"exceptions: {[e.rule for e in exceptions]}")


if __name__ == "__main__":
    main()
