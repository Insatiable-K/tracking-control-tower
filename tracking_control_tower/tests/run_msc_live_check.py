"""
Live check of MSCAdapter.search() against the real MSC site - not part
of the automated test suite (needs a real browser + live network), the
same category of check as this session's earlier live Maersk/HL
verification. Run manually to confirm the adapter still works.

Run: python -m tracking_control_tower.tests.run_msc_live_check <container>
"""
import sys

from tracking_control_tower.carriers.msc import MSCAdapter


def main() -> None:
    container = sys.argv[1] if len(sys.argv) > 1 else "MEDU5655981"
    print(f"Searching MSC for container: {container}")

    with MSCAdapter(headless=False) as adapter:
        raw = adapter.search(container)

    if raw.error:
        print(f"ERROR: {raw.error}")
        return

    print(f"Raw text length: {len(raw.text)} chars")
    print(f"POD ETA text: {raw.pod_eta_text!r}")
    print("--- raw text preview ---")
    print(raw.text[:500])

    events = MSCAdapter().parse(raw)
    print(f"\nParsed {len(events)} events:")
    for e in events:
        print(f"  {e.date} | {e.raw_text!r} | loc={e.location!r} vessel={e.vessel_info!r}")


if __name__ == "__main__":
    main()
