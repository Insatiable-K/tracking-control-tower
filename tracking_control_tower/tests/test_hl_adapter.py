"""
Tests for HLAdapter.parse() - pure JSON processing, no browser needed.
search() needs a live undetected-chromedriver session against the real
HL SPA and is exercised separately (see carriers/hl.py's module
docstring and tests/run_hl_live_check.py).

Fixture data captured verbatim via a live search() run against real
container FCIU4746425 (2026-07-13) - all 9 real events, in the site's
own (non-chronological) display order, exactly as returned by the
.hal-event-tracking .hal-event elements.
"""
import json
import unittest
from datetime import datetime

from tracking_control_tower.carriers.base import RawPage
from tracking_control_tower.carriers.hl import HLAdapter
from tracking_control_tower.events.classifier import classify
from tracking_control_tower.exceptions.evaluator import evaluate_exceptions
from tracking_control_tower.shipment_state.engine import infer_state
from tracking_control_tower.shipment_state.models import ClassifiedEvent

LIVE_CAPTURED_FCIU4746425 = json.dumps([
    {"event": "Gated in", "location": "FOREST VIEW, IL", "date": "2026-02-18", "time": "18:04", "transport": "Truck", "voyage": ""},
    {"event": "Gated out", "location": "NORFOLK, VA", "date": "2026-02-11", "time": "22:50", "transport": "Rail", "voyage": ""},
    {"event": "Discharged", "location": "NORFOLK, VA", "date": "2026-02-11", "time": "11:56", "transport": "BREMEN EXPRESS", "voyage": "6101"},
    {"event": "Gated in", "location": "NHAVA SHEVA", "date": "2026-01-01", "time": "15:11", "transport": "Truck", "voyage": ""},
    {"event": "Loaded", "location": "NHAVA SHEVA", "date": "2026-01-04", "time": "09:21", "transport": "BREMEN EXPRESS", "voyage": "6101"},
    {"event": "Gated out", "location": "NHAVA SHEVA", "date": "2025-12-30", "time": "21:12", "transport": "Truck", "voyage": ""},
    {"event": "Discharged", "location": "CHICAGO, IL", "date": "2026-02-15", "time": "00:00", "transport": "Rail", "voyage": ""},
    {"event": "Gated out", "location": "CHICAGO, IL", "date": "2026-02-18", "time": "18:04", "transport": "Truck", "voyage": ""},
    {"event": "Gated in", "location": "CHICAGO, IL", "date": "2026-02-16", "time": "09:05", "transport": "Rail", "voyage": ""},
])


class TestParseRealCapturedData(unittest.TestCase):
    def test_all_nine_events_parsed(self):
        raw = RawPage(container="FCIU4746425", text=LIVE_CAPTURED_FCIU4746425)
        events = HLAdapter().parse(raw)
        self.assertEqual(len(events), 9)

    def test_date_and_time_combined_correctly(self):
        raw = RawPage(container="FCIU4746425", text=LIVE_CAPTURED_FCIU4746425)
        events = HLAdapter().parse(raw)
        loaded = next(e for e in events if e.raw_text == "Loaded")
        self.assertEqual(loaded.date, datetime(2026, 1, 4, 9, 21))

    def test_vessel_and_voyage_joined_when_present(self):
        raw = RawPage(container="FCIU4746425", text=LIVE_CAPTURED_FCIU4746425)
        events = HLAdapter().parse(raw)
        discharged_norfolk = next(e for e in events if e.raw_text == "Discharged" and e.location == "NORFOLK, VA")
        self.assertEqual(discharged_norfolk.vessel_info, "BREMEN EXPRESS 6101")

    def test_transport_only_when_no_voyage(self):
        raw = RawPage(container="FCIU4746425", text=LIVE_CAPTURED_FCIU4746425)
        events = HLAdapter().parse(raw)
        gate_event = next(e for e in events if e.raw_text == "Gated in" and e.location == "NHAVA SHEVA")
        self.assertEqual(gate_event.vessel_info, "Truck")

    def test_source_is_hl(self):
        raw = RawPage(container="FCIU4746425", text=LIVE_CAPTURED_FCIU4746425)
        events = HLAdapter().parse(raw)
        self.assertTrue(all(e.source == "HL" for e in events))


class TestParseEdgeCases(unittest.TestCase):
    def test_search_error_produces_no_events(self):
        raw = RawPage(container="BADU0000000", error="timeout")
        self.assertEqual(HLAdapter().parse(raw), [])

    def test_empty_text_produces_no_events(self):
        raw = RawPage(container="FCIU4746425", text="")
        self.assertEqual(HLAdapter().parse(raw), [])

    def test_malformed_json_does_not_crash(self):
        raw = RawPage(container="FCIU4746425", text="not json")
        self.assertEqual(HLAdapter().parse(raw), [])


class TestFullPipelineOnRealCapturedData(unittest.TestCase):
    """
    The real end-to-end validation: parse -> classify -> infer_state ->
    exceptions, on the exact live-captured event set, checking the new
    "Gated in"/"Gated out" taxonomy phrases and the repeated-"Discharged"
    handling actually work together, not just in isolation.
    """

    def test_no_unclassified_events(self):
        raw = RawPage(container="FCIU4746425", text=LIVE_CAPTURED_FCIU4746425)
        raw_events = HLAdapter().parse(raw)
        classified = [ClassifiedEvent(raw=e, classification=classify(e.raw_text)) for e in raw_events]
        self.assertTrue(all(c.category != "unclassified" for c in classified))

    def test_no_contradictions_and_correct_final_phase(self):
        raw = RawPage(container="FCIU4746425", text=LIVE_CAPTURED_FCIU4746425)
        raw_events = HLAdapter().parse(raw)
        classified = [ClassifiedEvent(raw=e, classification=classify(e.raw_text)) for e in raw_events]
        state = infer_state("FCIU4746425", classified)

        self.assertEqual(state.data_quality_issues, [])
        # Latest by date is "Gated in FOREST VIEW, IL" 2026-02-18 18:04 -
        # a post-discharge inland move, correctly promoted to rank 10.
        self.assertEqual(state.current_phase, "Destination terminal")
        self.assertEqual(state.confidence_score, 1.0)

    def test_no_exceptions_raised(self):
        raw = RawPage(container="FCIU4746425", text=LIVE_CAPTURED_FCIU4746425)
        raw_events = HLAdapter().parse(raw)
        classified = [ClassifiedEvent(raw=e, classification=classify(e.raw_text)) for e in raw_events]
        state = infer_state("FCIU4746425", classified)
        exceptions = evaluate_exceptions(state, as_of=datetime(2026, 2, 19))
        self.assertEqual(exceptions, [])


class TestRouterIntegration(unittest.TestCase):
    def test_hl_vessel_routes_to_hl_adapter(self):
        from tracking_control_tower.carriers.router import adapter_for_vessel
        self.assertIs(adapter_for_vessel("HL-CLEMENTINE MAERSK"), HLAdapter)
        self.assertIs(adapter_for_vessel("HLBU1097348"[:2] + " SOME VESSEL"), HLAdapter)


if __name__ == "__main__":
    unittest.main()
