"""
Tests for MaerskAdapter.parse() - pure JSON processing, no browser
needed. search() needs a live undetected-chromedriver session against
the real Maersk site and is exercised separately (see carriers/
maersk.py's module docstring and tests/run_maersk_live_check.py).

Fixture data captured verbatim via a live search() run against real
container MRKU7248456 (2026-07-13) - all 8 real milestones, already in
chronological order (unlike HL's site), including the location-shown-
once-per-group display convention exactly as Maersk's page renders it.
"""
import json
import unittest
from datetime import datetime

from tracking_control_tower.carriers.base import RawPage
from tracking_control_tower.carriers.maersk import MaerskAdapter
from tracking_control_tower.events.classifier import classify
from tracking_control_tower.exceptions.evaluator import evaluate_exceptions
from tracking_control_tower.shipment_state.engine import infer_state
from tracking_control_tower.shipment_state.models import ClassifiedEvent

LIVE_CAPTURED_MRKU7248456 = json.dumps([
    {"location": "JAIPUR / JAIPUR RAIL TERMINAL", "event": "Gate out Empty", "date": "12 May 2026 10:26"},
    {"location": None, "event": "Gate in", "date": "18 May 2026 15:38"},
    {"location": None, "event": "Gate out", "date": "20 May 2026 11:00"},
    {"location": "PIPAVAV / PIPAVAV TERMINAL", "event": "Gate in", "date": "25 May 2026 09:18"},
    {"location": None, "event": "Load on CLEMENTINE MAERSK / 621W", "date": "27 May 2026 02:45"},
    {"location": None, "event": "Vessel departure (CLEMENTINE MAERSK / 621W)", "date": "27 May 2026 07:19"},
    {"location": "HOUSTON / BAY PORT CONTAINER TERMINAL", "event": "Vessel arrival (CLEMENTINE MAERSK / 621W)", "date": "10 Jul 2026 16:54"},
    {"location": None, "event": "Discharge (CLEMENTINE MAERSK / 621W)", "date": "11 Jul 2026 03:45"},
])


class TestParseRealCapturedData(unittest.TestCase):
    def test_all_eight_milestones_parsed(self):
        raw = RawPage(container="MRKU7248456", text=LIVE_CAPTURED_MRKU7248456)
        events = MaerskAdapter().parse(raw)
        self.assertEqual(len(events), 8)

    def test_location_forward_filled_across_group(self):
        raw = RawPage(container="MRKU7248456", text=LIVE_CAPTURED_MRKU7248456)
        events = MaerskAdapter().parse(raw)
        # events[1] and [2] ("Gate in"/"Gate out") show no location of
        # their own in the raw data - both are still at JAIPUR, the
        # last location actually shown.
        self.assertEqual(events[0].location, "JAIPUR / JAIPUR RAIL TERMINAL")
        self.assertEqual(events[1].location, "JAIPUR / JAIPUR RAIL TERMINAL")
        self.assertEqual(events[2].location, "JAIPUR / JAIPUR RAIL TERMINAL")
        self.assertEqual(events[3].location, "PIPAVAV / PIPAVAV TERMINAL")
        self.assertEqual(events[6].location, "HOUSTON / BAY PORT CONTAINER TERMINAL")
        self.assertEqual(events[7].location, "HOUSTON / BAY PORT CONTAINER TERMINAL")

    def test_vessel_info_extracted_from_parens(self):
        raw = RawPage(container="MRKU7248456", text=LIVE_CAPTURED_MRKU7248456)
        events = MaerskAdapter().parse(raw)
        arrival = next(e for e in events if e.raw_text.startswith("Vessel arrival"))
        self.assertEqual(arrival.vessel_info, "CLEMENTINE MAERSK / 621W")

    def test_vessel_info_extracted_from_load_on(self):
        raw = RawPage(container="MRKU7248456", text=LIVE_CAPTURED_MRKU7248456)
        events = MaerskAdapter().parse(raw)
        loaded = next(e for e in events if e.raw_text.startswith("Load on"))
        self.assertEqual(loaded.vessel_info, "CLEMENTINE MAERSK / 621W")

    def test_gate_events_have_no_vessel_info(self):
        raw = RawPage(container="MRKU7248456", text=LIVE_CAPTURED_MRKU7248456)
        events = MaerskAdapter().parse(raw)
        gate_event = next(e for e in events if e.raw_text == "Gate out Empty")
        self.assertIsNone(gate_event.vessel_info)

    def test_date_parsed_correctly(self):
        raw = RawPage(container="MRKU7248456", text=LIVE_CAPTURED_MRKU7248456)
        events = MaerskAdapter().parse(raw)
        self.assertEqual(events[0].date, datetime(2026, 5, 12, 10, 26))

    def test_source_is_maersk(self):
        raw = RawPage(container="MRKU7248456", text=LIVE_CAPTURED_MRKU7248456)
        events = MaerskAdapter().parse(raw)
        self.assertTrue(all(e.source == "Maersk" for e in events))


class TestParseEdgeCases(unittest.TestCase):
    def test_search_error_produces_no_events(self):
        raw = RawPage(container="BADU0000000", error="timeout")
        self.assertEqual(MaerskAdapter().parse(raw), [])

    def test_empty_text_produces_no_events(self):
        raw = RawPage(container="MRKU7248456", text="")
        self.assertEqual(MaerskAdapter().parse(raw), [])

    def test_malformed_json_does_not_crash(self):
        raw = RawPage(container="MRKU7248456", text="not json")
        self.assertEqual(MaerskAdapter().parse(raw), [])


class TestFullPipelineOnRealCapturedData(unittest.TestCase):
    def test_no_unclassified_events(self):
        raw = RawPage(container="MRKU7248456", text=LIVE_CAPTURED_MRKU7248456)
        raw_events = MaerskAdapter().parse(raw)
        classified = [ClassifiedEvent(raw=e, classification=classify(e.raw_text)) for e in raw_events]
        self.assertTrue(all(c.category != "unclassified" for c in classified))

    def test_no_contradictions_and_correct_final_phase(self):
        raw = RawPage(container="MRKU7248456", text=LIVE_CAPTURED_MRKU7248456)
        raw_events = MaerskAdapter().parse(raw)
        classified = [ClassifiedEvent(raw=e, classification=classify(e.raw_text)) for e in raw_events]
        state = infer_state("MRKU7248456", classified)

        self.assertEqual(state.data_quality_issues, [])
        self.assertEqual(state.current_phase, "Discharged")
        self.assertEqual(state.current_vessel, "CLEMENTINE MAERSK / 621W")
        self.assertEqual(state.confidence_score, 1.0)

    def test_no_exceptions_raised(self):
        raw = RawPage(container="MRKU7248456", text=LIVE_CAPTURED_MRKU7248456)
        raw_events = MaerskAdapter().parse(raw)
        classified = [ClassifiedEvent(raw=e, classification=classify(e.raw_text)) for e in raw_events]
        state = infer_state("MRKU7248456", classified)
        exceptions = evaluate_exceptions(state, as_of=datetime(2026, 7, 12))
        self.assertEqual(exceptions, [])


class TestRouterIntegration(unittest.TestCase):
    def test_msk_and_maersk_prefixes_both_route_to_maersk_adapter(self):
        from tracking_control_tower.carriers.router import adapter_for_vessel
        self.assertIs(adapter_for_vessel("MSK-CLEMENTINE MAERSK / 621W"), MaerskAdapter)
        self.assertIs(adapter_for_vessel("MAERSK DENVER 627W"), MaerskAdapter)


if __name__ == "__main__":
    unittest.main()
