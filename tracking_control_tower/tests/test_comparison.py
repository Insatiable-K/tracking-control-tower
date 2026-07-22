"""
Tests for the comparison engine, built from real container histories
where available, and honest about where a real limitation was found
rather than papered over.
"""
import unittest
from datetime import datetime

from tracking_control_tower.comparison.snapshot_diff import diff_snapshots
from tracking_control_tower.comparison.sps_diff import diff_against_sps
from tracking_control_tower.events.classifier import classify
from tracking_control_tower.shipment_state.engine import infer_state
from tracking_control_tower.shipment_state.models import ClassifiedEvent, RawEvent


def _events(container: str, rows: list[tuple[str, str]]) -> list[ClassifiedEvent]:
    out = []
    for date_str, text in rows:
        raw = RawEvent(container=container, date=datetime.fromisoformat(date_str), raw_text=text)
        out.append(ClassifiedEvent(raw=raw, classification=classify(text)))
    return out


class TestSnapshotDiffFirstSeen(unittest.TestCase):
    def test_no_previous_snapshot_reports_first_seen(self):
        rows = [("2025-09-01", "Export received at CY")]
        current = infer_state("TEST0000001", _events("TEST0000001", rows))
        diff = diff_snapshots(None, current)
        self.assertTrue(diff.is_first_seen)
        self.assertFalse(diff.state_changed)


class TestSnapshotDiffRealProgression(unittest.TestCase):
    """
    Real TEMU4439276 history: the earlier scrape is missing an explicit
    'Discharged HOUSTON' line for the final leg (a genuine data gap in
    the source, not synthetic), but both snapshots already knew about
    the same final "Arrival in DENVER, CO" milestone - so no state
    change is the CORRECT answer here, not a false negative.
    """

    EARLY = [
        ("2025-06-30", "Gate out empty JEBEL ALI"),
        ("2025-07-09", "Loaded JEBEL ALI"),
        ("2025-07-10", "Vessel departed JEBEL ALI"),
        ("2025-08-15", "Vessel arrived TANGER MED"),
        ("2025-08-16", "Discharged TANGER MED"),
        ("2025-08-17", "Loaded TANGER MED"),
        ("2025-08-17", "Vessel departed TANGER MED"),
        ("2025-08-19", "Vessel arrived TANGER MED"),
        ("2025-08-19", "Discharged TANGER MED"),
        ("2025-08-21", "Loaded TANGER MED"),
        ("2025-08-22", "Vessel departed TANGER MED"),
        ("2025-09-12", "Vessel arrival HOUSTON, TX"),
        # note: no explicit "Discharged HOUSTON" in this real scrape
        ("2025-09-15", "Departure from HOUSTON, TX"),
        ("2025-09-23", "Arrival in DENVER, CO"),
    ]
    LATE = EARLY[:-3] + [
        ("2025-09-12", "Discharged HOUSTON, TX"),  # gap filled in on rescrape
        ("2025-09-18", "Departure from HOUSTON, TX"),
        ("2025-09-23", "Arrival in DENVER, CO"),
    ]

    def test_same_final_milestone_reports_no_state_change(self):
        early = infer_state("TEMU4439276", _events("TEMU4439276", self.EARLY))
        late = infer_state("TEMU4439276", _events("TEMU4439276", self.LATE))
        self.assertEqual(early.current_phase, "Destination terminal")
        self.assertEqual(late.current_phase, "Destination terminal")
        diff = diff_snapshots(early, late)
        self.assertFalse(diff.state_changed)
        self.assertFalse(diff.likely_new_cycle)


class TestContainerReuseKnownLimitation(unittest.TestCase):
    """
    Real HLXU3511177: two genuinely unrelated shipments, six weeks
    apart, sharing the same physical container number (confirmed - zero
    overlapping raw event text between the two scrapes). The new
    cycle's first event (2025-08-19) falls chronologically BEFORE the
    old cycle's last known event (2025-09-10, Denver rail arrival) -
    every real reuse pair in this dataset overlaps the same way. The
    date-based guard cannot catch this; documenting that honestly
    rather than asserting a heuristic result it doesn't achieve.
    """

    OLD_CYCLE = [
        ("2025-06-18", "Gate out empty JAIPUR"),
        ("2025-07-01", "Loaded MUNDRA"),
        ("2025-08-02", "Vessel arrived TANGER MED"),
        ("2025-08-02", "Discharged TANGER MED"),
        ("2025-08-29", "Discharged HOUSTON, TX"),
        ("2025-09-04", "Departure from HOUSTON, TX"),
        ("2025-09-10", "Arrival in DENVER, CO"),
    ]
    NEW_CYCLE = [
        ("2025-08-19", "Gate out empty JAIPUR"),
        ("2025-09-01", "Loaded MUNDRA"),
        ("2025-10-03", "Discharged TANGER MED"),
        ("2025-11-01", "Vessel arrival PORT EVERGLADES, FL"),
    ]

    def test_reuse_with_overlapping_dates_is_not_caught(self):
        old = infer_state("HLXU3511177", _events("HLXU3511177", self.OLD_CYCLE))
        new = infer_state("HLXU3511177", _events("HLXU3511177", self.NEW_CYCLE))
        diff = diff_snapshots(old, new)
        # Known, documented gap - not the desired behavior, but the
        # honest current one. Production must key by SIPL, not this
        # heuristic, to actually solve container reuse.
        self.assertFalse(diff.likely_new_cycle)
        self.assertTrue(diff.state_changed)


class TestSPSDiff(unittest.TestCase):
    def test_recommends_vessel_update_when_tracked_vessel_differs(self):
        rows = [("2025-09-01", "Vessel arrival HOUSTON, TX")]
        events = _events("TEST0000002", rows)
        events[0].raw.vessel_info = "MEXICO EXPRESS 541W"
        state = infer_state("TEST0000002", events)

        diff = diff_against_sps(state, sps_vessel="MSK-MAERSK DENVER 627W", sps_port_eta=None)
        self.assertTrue(diff.should_update)
        self.assertEqual(diff.recommendations[0].field, "vessel")

    def test_no_recommendation_when_vessel_already_matches(self):
        rows = [("2025-09-01", "Vessel arrival HOUSTON, TX")]
        events = _events("TEST0000003", rows)
        events[0].raw.vessel_info = "MAERSK DENVER 627W"
        state = infer_state("TEST0000003", events)

        diff = diff_against_sps(state, sps_vessel="MSK-MAERSK DENVER 621W", sps_port_eta=None)
        self.assertFalse(diff.should_update)

    def test_low_confidence_state_produces_no_recommendation(self):
        rows = [("2025-09-01", "Rio De Janeiro, BR")]  # real parsing-artifact value
        state = infer_state("TEST0000004", _events("TEST0000004", rows))
        diff = diff_against_sps(state, sps_vessel="anything", sps_port_eta=None)
        self.assertFalse(diff.should_update)


if __name__ == "__main__":
    unittest.main()
