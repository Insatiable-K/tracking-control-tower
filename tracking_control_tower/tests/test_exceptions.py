"""
Tests for the exception engine, built from real vocabulary and the
thresholds derived from real historical dwell-time data (see
exceptions/rules.yaml).
"""
import unittest
from datetime import datetime

from tracking_control_tower.comparison.snapshot_diff import diff_snapshots
from tracking_control_tower.events.classifier import classify
from tracking_control_tower.exceptions.evaluator import evaluate_exceptions
from tracking_control_tower.shipment_state.engine import infer_state
from tracking_control_tower.shipment_state.models import ClassifiedEvent, RawEvent


def _events(container: str, rows: list[tuple[str, str]]) -> list[ClassifiedEvent]:
    out = []
    for date_str, text in rows:
        raw = RawEvent(container=container, date=datetime.fromisoformat(date_str), raw_text=text)
        out.append(ClassifiedEvent(raw=raw, classification=classify(text)))
    return out


class TestContainerNotFound(unittest.TestCase):
    def test_short_circuits_regardless_of_state(self):
        rows = [("2025-09-01", "Export received at CY")]
        state = infer_state("TEST0000001", _events("TEST0000001", rows))
        exceptions = evaluate_exceptions(state, container_not_found=True)
        self.assertEqual(len(exceptions), 1)
        self.assertEqual(exceptions[0].rule, "container_not_found")
        self.assertEqual(exceptions[0].severity, "high")
        self.assertEqual(exceptions[0].routed_to, "logistics")


class TestContradictionException(unittest.TestCase):
    def test_contradiction_in_state_becomes_high_severity_exception(self):
        rows = [
            ("2025-09-01", "Export received at CY"),
            ("2025-09-05", "Export Loaded on Vessel"),
            ("2025-10-01", "Import Discharged from Vessel"),
            ("2025-10-05", "Import Rail Departure"),
            ("2025-10-10", "Export Loaded on Vessel"),  # real impossible-regression pattern
        ]
        state = infer_state("TEST0000002", _events("TEST0000002", rows))
        exceptions = evaluate_exceptions(state)
        rules_fired = [e.rule for e in exceptions]
        self.assertIn("contradiction_detected", rules_fired)
        contradiction = next(e for e in exceptions if e.rule == "contradiction_detected")
        self.assertEqual(contradiction.severity, "high")
        self.assertEqual(contradiction.routed_to, "logistics")


class TestUnclassifiedException(unittest.TestCase):
    def test_unclassified_events_become_low_severity_exception(self):
        rows = [
            ("2025-09-01", "Export Loaded on Vessel"),
            ("2025-09-05", "Rio De Janeiro, BR"),  # real parsing-artifact value
        ]
        state = infer_state("TEST0000003", _events("TEST0000003", rows))
        exceptions = evaluate_exceptions(state)
        unclassified = next(e for e in exceptions if e.rule == "unclassified_events_present")
        self.assertEqual(unclassified.severity, "low")
        self.assertEqual(unclassified.routed_to, "data_quality_review")


def _events_with_vessel(container: str, rows: list[tuple[str, str]], vessel_info: str) -> list[ClassifiedEvent]:
    events = _events(container, rows)
    for event in events:
        event.raw.vessel_info = vessel_info
    return events


class TestVesselSwapException(unittest.TestCase):
    def test_vessel_change_at_ocean_transit_or_later_is_flagged(self):
        previous = infer_state(
            "TEST0000004",
            _events_with_vessel("TEST0000004", [("2025-09-01", "Vessel arrival HOUSTON, TX")], "MEXICO EXPRESS 541W"),
        )
        current = infer_state(
            "TEST0000004",
            _events_with_vessel("TEST0000004", [("2025-09-01", "Vessel arrival HOUSTON, TX")], "MAERSK DENVER 627W"),
        )

        diff = diff_snapshots(previous, current)
        self.assertTrue(diff.vessel_changed)

        exceptions = evaluate_exceptions(current, snapshot_diff=diff)
        swap = next(e for e in exceptions if e.rule == "vessel_swap_near_arrival")
        self.assertEqual(swap.severity, "high")
        self.assertIn("MEXICO EXPRESS", swap.reason)
        self.assertIn("MAERSK DENVER", swap.reason)

    def test_vessel_change_early_in_export_is_not_flagged(self):
        """A vessel swap while still at rank 1-4 (pre-ocean-transit) is
        routine re-booking, not an exception-worthy event."""
        previous = infer_state(
            "TEST0000005",
            _events_with_vessel("TEST0000005", [("2025-09-01", "Export Loaded on Vessel")], "SHIP A"),
        )
        current = infer_state(
            "TEST0000005",
            _events_with_vessel("TEST0000005", [("2025-09-01", "Export Loaded on Vessel")], "SHIP B"),
        )

        diff = diff_snapshots(previous, current)
        exceptions = evaluate_exceptions(current, snapshot_diff=diff)
        self.assertNotIn("vessel_swap_near_arrival", [e.rule for e in exceptions])


class TestRailExpectedMissingException(unittest.TestCase):
    def test_discharged_no_rail_past_grace_period_in_rail_served_corridor(self):
        rows = [
            ("2025-09-01", "Export Loaded on Vessel"),
            ("2025-09-20", "Import Discharged from Vessel"),
        ]
        state = infer_state("TEST0000006", _events("TEST0000006", rows))
        as_of = datetime(2025, 10, 15)  # 25 days after discharge, past the 10-day grace period
        exceptions = evaluate_exceptions(state, ship_to_location="Denver", as_of=as_of)
        rail_missing = next(e for e in exceptions if e.rule == "rail_expected_missing")
        self.assertEqual(rail_missing.severity, "medium")
        self.assertEqual(rail_missing.routed_to, "warehouse")

    def test_not_flagged_when_destination_is_not_rail_served(self):
        rows = [
            ("2025-09-01", "Export Loaded on Vessel"),
            ("2025-09-20", "Import Discharged from Vessel"),
        ]
        state = infer_state("TEST0000007", _events("TEST0000007", rows))
        exceptions = evaluate_exceptions(state, ship_to_location="Houston", as_of=datetime(2025, 10, 15))
        self.assertNotIn("rail_expected_missing", [e.rule for e in exceptions])

    def test_not_flagged_within_grace_period(self):
        rows = [
            ("2025-09-01", "Export Loaded on Vessel"),
            ("2025-09-20", "Import Discharged from Vessel"),
        ]
        state = infer_state("TEST0000008", _events("TEST0000008", rows))
        exceptions = evaluate_exceptions(state, ship_to_location="Denver", as_of=datetime(2025, 9, 22))
        self.assertNotIn("rail_expected_missing", [e.rule for e in exceptions])

    def test_not_flagged_when_rail_event_already_seen(self):
        rows = [
            ("2025-09-01", "Export Loaded on Vessel"),
            ("2025-09-20", "Import Discharged from Vessel"),
            ("2025-09-25", "Import Rail Departure"),
        ]
        state = infer_state("TEST0000009", _events("TEST0000009", rows))
        exceptions = evaluate_exceptions(state, ship_to_location="Denver", as_of=datetime(2025, 10, 15))
        self.assertNotIn("rail_expected_missing", [e.rule for e in exceptions])


class TestStalledException(unittest.TestCase):
    def test_no_advance_past_derived_threshold_is_flagged(self):
        rows = [("2025-09-01", "Export Loaded on Vessel")]
        state = infer_state("TEST0000010", _events("TEST0000010", rows))
        as_of = datetime(2025, 10, 10)  # 39 days later, past the 35-day threshold
        exceptions = evaluate_exceptions(state, as_of=as_of)
        stalled = next(e for e in exceptions if e.rule == "stalled")
        self.assertEqual(stalled.severity, "medium")
        self.assertEqual(stalled.routed_to, "logistics")

    def test_within_normal_ocean_transit_window_is_not_flagged(self):
        """20 days is within the real p90 gap observed for ocean-transit
        legs (~29-30 days) - must not false-trigger on a normal wait."""
        rows = [("2025-09-01", "Export Loaded on Vessel")]
        state = infer_state("TEST0000011", _events("TEST0000011", rows))
        exceptions = evaluate_exceptions(state, as_of=datetime(2025, 9, 21))
        self.assertNotIn("stalled", [e.rule for e in exceptions])

    def test_delivered_shipment_is_never_flagged_as_stalled(self):
        rows = [
            ("2025-09-01", "Export Loaded on Vessel"),
            ("2025-09-20", "Import Discharged from Vessel"),
            ("2025-09-25", "Import to consignee"),
        ]
        state = infer_state("TEST0000012", _events("TEST0000012", rows))
        exceptions = evaluate_exceptions(state, as_of=datetime(2026, 1, 1))
        self.assertNotIn("stalled", [e.rule for e in exceptions])


if __name__ == "__main__":
    unittest.main()
