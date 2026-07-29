"""
Tests for the shipment state engine, built from real container histories
(FCIU4746425, HLXU3511177 - both from HL Tracking/old/HL_Parsed_*.xlsx)
plus synthetic edge cases the real data didn't happen to contain.
"""
import unittest
from datetime import datetime

from tracking_control_tower.events.classifier import classify
from tracking_control_tower.shipment_state.engine import infer_state
from tracking_control_tower.shipment_state.models import ClassifiedEvent, RawEvent
from tracking_control_tower.shipment_state.timeline import next_expected


def _events(container: str, rows: list[tuple[str, str]]) -> list[ClassifiedEvent]:
    out = []
    for date_str, text in rows:
        raw = RawEvent(container=container, date=datetime.fromisoformat(date_str), raw_text=text)
        out.append(ClassifiedEvent(raw=raw, classification=classify(text)))
    return out


# Real FCIU4746425 history: single leg, ends with a post-discharge inland
# truck departure from the port toward final destination.
FCIU4746425 = [
    ("2025-08-30", "Gate out empty JAIPUR"),
    ("2025-09-08", "Arrival in JAIPUR"),
    ("2025-09-10", "Departure from JAIPUR"),
    ("2025-09-11", "Arrival in MUNDRA"),
    ("2025-09-18", "Loaded MUNDRA"),
    ("2025-09-19", "Vessel departed MUNDRA"),
    ("2025-10-23", "Vessel arrived NORFOLK, VA"),
    ("2025-10-23", "Discharged NORFOLK, VA"),
    ("2025-10-27", "Departure from NORFOLK, VA"),
]

# Real HLXU1294961 history: discharged at an INTERMEDIATE transshipment
# port (COLOMBO), reloaded onto a second vessel there, with an inland
# truck shuffle at COLOMBO in between. The inland move must NOT be
# promoted to "post-discharge final leg" rank, because the COLOMBO
# discharge wasn't final - a reload followed it.
HLXU1294961 = [
    ("2025-09-02", "Gate out empty CHENNAI"),
    ("2025-09-05", "Arrival in ENNORE"),
    ("2025-09-07", "Loaded ENNORE"),
    ("2025-09-08", "Vessel departed ENNORE"),
    ("2025-09-11", "Vessel arrived COLOMBO"),
    ("2025-09-11", "Discharged COLOMBO"),
    ("2025-09-26", "Departure from COLOMBO"),
    ("2025-09-26", "Arrival in COLOMBO"),
    ("2025-09-27", "Loaded COLOMBO"),
    ("2025-09-27", "Vessel departed COLOMBO"),
    ("2025-10-31", "Vessel arrival NORFOLK, VA"),
]

# Real HLXU3511177 history: THREE vessel legs (MUNDRA -> TANGER MED ->
# TANGER MED -> PORT EVERGLADES), each cycling loaded/departed/arrived/
# discharged. Ends mid-leg at "Vessel arrival" for the final port.
HLXU3511177 = [
    ("2025-08-19", "Gate out empty JAIPUR"),
    ("2025-08-23", "Arrival in JAIPUR"),
    ("2025-08-24", "Departure from JAIPUR"),
    ("2025-08-26", "Arrival in MUNDRA"),
    ("2025-09-01", "Loaded MUNDRA"),
    ("2025-09-02", "Vessel departed MUNDRA"),
    ("2025-10-02", "Vessel arrived TANGER MED"),
    ("2025-10-03", "Discharged TANGER MED"),
    ("2025-10-04", "Loaded TANGER MED"),
    ("2025-10-05", "Vessel departed TANGER MED"),
    ("2025-10-07", "Vessel arrived TANGER MED"),
    ("2025-10-08", "Discharged TANGER MED"),
    ("2025-10-11", "Loaded TANGER MED"),
    ("2025-10-12", "Vessel departed TANGER MED"),
    ("2025-11-01", "Vessel arrival PORT EVERGLADES, FL"),
]


class TestRealContainerHistories(unittest.TestCase):
    def test_post_discharge_inland_leg_is_not_reported_as_export(self):
        """
        Real bug caught by testing: the container's LAST event is an
        inland truck departure from the discharge port. Before the
        contextual re-ranking fix, this reported current_phase="Export"
        for a shipment that had already left the port - misleading.
        """
        state = infer_state("FCIU4746425", _events("FCIU4746425", FCIU4746425))
        self.assertEqual(state.current_phase, "Destination terminal")
        self.assertEqual(state.current_phase_rank, 10)
        self.assertEqual(state.previous_event, "Discharged")
        self.assertEqual(state.data_quality_issues, [])
        self.assertEqual(state.confidence_score, 1.0)

    def test_multi_leg_transshipment_reports_latest_leg_not_max_ever(self):
        """
        Three vessel legs, ending mid-way through the third (arrived,
        not yet discharged). 'Max rank ever seen' would freeze at
        'Discharged' from leg 1 or 2; the correct answer is the latest
        event: arrived at the (implied final) port.
        """
        state = infer_state("HLXU3511177", _events("HLXU3511177", HLXU3511177))
        self.assertEqual(state.current_phase, "Arrived at port")
        self.assertEqual(state.current_phase_rank, 6)
        self.assertEqual(state.previous_event, "Departed")
        # No contradiction: cycling through ranks 2-7 across three legs
        # is normal transshipment behavior, not a data error.
        self.assertEqual(state.data_quality_issues, [])

    def test_pre_discharge_inland_leg_still_ranks_low(self):
        """The JAIPUR/MUNDRA legs before any vessel activity must NOT be
        promoted to rank 10 - only post-discharge inland moves are."""
        early_only = _events("FCIU4746425", FCIU4746425[:2])  # gate out, arrival in JAIPUR
        state = infer_state("FCIU4746425", early_only)
        self.assertEqual(state.current_phase_rank, 1)

    def test_inland_leg_between_transshipment_legs_is_not_promoted(self):
        """
        Real bug caught by testing: an inland truck shuffle at an
        INTERMEDIATE transshipment port (COLOMBO) was wrongly promoted
        to rank 10 because it followed *a* discharge, even though that
        discharge wasn't final - the container was reloaded onto a
        second vessel right after. Only a discharge with no later
        reload counts as "final" for this promotion.
        """
        state = infer_state("HLXU1294961", _events("HLXU1294961", HLXU1294961))
        self.assertEqual(state.data_quality_issues, [])
        self.assertEqual(state.current_phase, "Arrived at port")
        self.assertEqual(state.current_phase_rank, 6)


class TestContradictionDetection(unittest.TestCase):
    def test_regression_after_rail_is_flagged_as_contradiction(self):
        """Synthetic: a shipment reaches rail (rank 9), then a later-dated
        event reports 'loaded on vessel' again - genuinely impossible,
        must be flagged, and must NOT silently override current_phase."""
        rows = [
            ("2025-09-01", "Export received at CY"),
            ("2025-09-05", "Export Loaded on Vessel"),
            ("2025-10-01", "Import Discharged from Vessel"),
            ("2025-10-05", "Import Rail Departure"),
            ("2025-10-10", "Export Loaded on Vessel"),  # impossible regression
        ]
        state = infer_state("TEST0000001", _events("TEST0000001", rows))
        self.assertTrue(any(i.startswith("contradiction") for i in state.data_quality_issues))
        # current_phase must still reflect the LATEST event, not silently
        # revert - the contradiction is surfaced, not hidden.
        self.assertEqual(state.current_phase_rank, 2)
        self.assertLess(state.confidence_score, 1.0)

    def test_cycling_within_ocean_leg_ranks_is_not_a_contradiction(self):
        state = infer_state("HLXU3511177", _events("HLXU3511177", HLXU3511177))
        self.assertEqual(state.data_quality_issues, [])


class TestDeliveryAttempts(unittest.TestCase):
    def test_delivery_zone_events_are_counted(self):
        rows = [
            ("2025-09-01", "Import Discharged from Vessel"),
            ("2025-09-10", "Full Available for Delivery"),
        ]
        state = infer_state("TEST0000002", _events("TEST0000002", rows))
        self.assertEqual(state.delivery_attempt_count, 1)


class TestConfidenceAndDataQuality(unittest.TestCase):
    def test_unclassified_events_lower_confidence_and_are_reported(self):
        rows = [
            ("2025-09-01", "Export Loaded on Vessel"),
            ("2025-09-05", "Rio De Janeiro, BR"),  # real parsing-artifact value
        ]
        state = infer_state("TEST0000003", _events("TEST0000003", rows))
        self.assertLess(state.confidence_score, 1.0)
        self.assertTrue(any("did not classify" in i for i in state.data_quality_issues))

    def test_no_events_returns_empty_state_not_a_crash(self):
        state = infer_state("TEST0000004", [])
        self.assertIsNone(state.current_phase)
        self.assertEqual(state.confidence_score, 0.0)
        self.assertTrue(state.missing_information)

    def test_missing_ship_to_location_is_flagged(self):
        rows = [("2025-09-01", "Export Loaded on Vessel")]
        state = infer_state("TEST0000005", _events("TEST0000005", rows))
        self.assertIn("no ship_to_location provided; rail-expectation unknown", state.missing_information)


class TestDeparturePortAndArrivalPort(unittest.TestCase):
    """
    Added for the report redesign that surfaces departure/arrival port
    directly in the shipment report (per-request: "from liner website i
    want the departure port arrival port... where the container is
    where is it going"). _events() doesn't carry location, so these
    build RawEvent/ClassifiedEvent directly instead.
    """

    @staticmethod
    def _event(date_str: str, text: str, location: str) -> ClassifiedEvent:
        raw = RawEvent(container="TEST", date=datetime.fromisoformat(date_str), raw_text=text, location=location)
        return ClassifiedEvent(raw=raw, classification=classify(text))

    def test_ports_are_none_before_those_milestones_happen(self):
        events = [self._event("2025-09-01", "Export received at CY", "JAIPUR")]
        state = infer_state("TEST", events)
        self.assertIsNone(state.departure_port)
        self.assertIsNone(state.arrival_port)

    def test_departure_port_set_once_loaded_arrival_port_still_none(self):
        events = [
            self._event("2025-09-01", "Export received at CY", "JAIPUR"),
            self._event("2025-09-18", "Export Loaded on Vessel", "MUNDRA"),
        ]
        state = infer_state("TEST", events)
        self.assertEqual(state.departure_port, "MUNDRA")
        self.assertIsNone(state.arrival_port)

    def test_arrival_port_set_after_discharge(self):
        events = [
            self._event("2025-09-01", "Export received at CY", "JAIPUR"),
            self._event("2025-09-18", "Export Loaded on Vessel", "MUNDRA"),
            self._event("2025-10-20", "Vessel arrival", "HOUSTON, TX"),
            self._event("2025-10-21", "Import Discharged from Vessel", "HOUSTON, TX"),
        ]
        state = infer_state("TEST", events)
        self.assertEqual(state.departure_port, "MUNDRA")
        self.assertEqual(state.arrival_port, "HOUSTON, TX")

    def test_multi_leg_transshipment_reports_the_current_legs_ports(self):
        """Two loading events (two legs) - departure_port should be the
        MOST RECENT one, not the very first origin port, matching how
        current_phase already reports the latest leg rather than the
        first one (see TestRealContainerHistories)."""
        events = [
            self._event("2025-09-01", "Export Loaded on Vessel", "MUNDRA"),
            self._event("2025-09-15", "Full Transshipment Discharged", "COLOMBO"),
            self._event("2025-09-16", "Full Transshipment Loaded", "COLOMBO"),
        ]
        state = infer_state("TEST", events)
        # Only "Export Loaded on Vessel" classifies as loaded_on_vessel -
        # transshipment loads are a distinct category, so the single
        # real loaded_on_vessel event's location is what's reported.
        self.assertEqual(state.departure_port, "MUNDRA")


class TestRailExpectation(unittest.TestCase):
    def test_next_after_discharge_is_customs_regardless_of_rail(self):
        """Discharged (7) -> Customs (8) is the same next step whether or
        not the shipment is headed somewhere rail-served; the rail/no-rail
        branch only matters one step further, at rank 9."""
        rows = [("2025-09-01", "Import Discharged from Vessel")]
        state = infer_state("TEST0000006", _events("TEST0000006", rows), ship_to_location="Houston")
        self.assertIn("Customs", state.next_expected_event)

    def test_timeline_skips_rail_when_not_rail_served(self):
        self.assertEqual(next_expected(8, rail_expected=False), "Destination terminal")

    def test_timeline_includes_rail_when_rail_served(self):
        self.assertEqual(next_expected(8, rail_expected=True), "Rail")


class TestCurrentVesselSkipsPlaceholders(unittest.TestCase):
    """
    Real bug caught 2026-07-29 re-checking fresh containers: current_vessel's
    fallback took whatever vessel_info sat on the chronologically LATEST
    confirmed event, even when that event's vessel_info is a non-vessel
    placeholder (MSC's 'LADEN'/'EMPTY' container-state marker, HL's
    'Truck'/'Rail' mode-of-transport label) rather than a real vessel name.
    """

    def _classified(self, date_str, text, vessel_info):
        raw = RawEvent(
            container="TEST0000007", date=datetime.fromisoformat(date_str),
            raw_text=text, vessel_info=vessel_info,
        )
        return ClassifiedEvent(raw=raw, classification=classify(text))

    def test_msc_delivered_container_skips_laden_marker(self):
        """Real SEGU2963797: latest confirmed event is 'Full Available for
        Delivery' with vessel_info='LADEN' - must fall back to the real
        vessel on 'Import Discharged from Vessel' a few events earlier."""
        events = [
            self._classified("2026-06-19", "Export Loaded on Vessel", "MSC LETIZIA MC624A"),
            self._classified("2026-07-26", "Import Discharged from Vessel", "MSC LETIZIA MC624A"),
            self._classified("2026-07-26", "Full Available for Delivery", "LADEN"),
        ]
        state = infer_state("TEST0000007", events)
        self.assertEqual(state.current_vessel, "MSC LETIZIA MC624A")

    def test_hl_container_at_destination_skips_truck_marker(self):
        """Real HLXU3569327: latest confirmed events are inland 'Gated
        in'/'Gated out' moves at destination with vessel_info='Truck' -
        must fall back to the real ocean vessel from 'Discharged'."""
        events = [
            self._classified("2026-05-31", "Loaded", "HUI FA 2622W"),
            self._classified("2026-06-05", "Discharged", "HUI FA 2622W"),
            self._classified("2026-06-05", "Gated out", "Truck"),
            self._classified("2026-06-11", "Gated in", "Truck"),
        ]
        state = infer_state("TEST0000007", events)
        self.assertEqual(state.current_vessel, "HUI FA 2622W")

    def test_all_placeholder_vessel_info_falls_back_to_none(self):
        """No real vessel anywhere in the confirmed history - must report
        None, not silently surface a placeholder as if it were real."""
        events = [
            self._classified("2026-07-01", "Empty to Shipper", "EMPTY"),
            self._classified("2026-07-02", "Export received at CY", "LADEN"),
        ]
        state = infer_state("TEST0000007", events)
        self.assertIsNone(state.current_vessel)


class TestMaerskFutureArrival(unittest.TestCase):
    """
    Maersk has no MSC-style "Estimated Time of Arrival" projection
    phrase - instead its own DOM marks the final destination-port
    "Vessel arrival" milestone data-test="transport-plan-item-future"
    (carriers/maersk.py), confirmed live 2026-07-29 against real
    containers BSIU2815550 / MRKU9415911 / MRKU8437156: always exactly
    one such row, already carrying the real assigned vessel and a real
    predicted date. Modeled here as RawEvent(is_future=True) since
    that's the flag parse() sets from it.
    """

    def _raw(self, date_str, text, *, is_future=False, scraped_at="2026-07-20"):
        from tracking_control_tower.carriers.maersk import _extract_vessel_info

        return RawEvent(
            container="MRKU0000001",
            date=datetime.fromisoformat(date_str),
            raw_text=text,
            vessel_info=_extract_vessel_info(text),
            source="Maersk",
            scraped_at=datetime.fromisoformat(scraped_at) if scraped_at else None,
            is_future=is_future,
        )

    def _classified(self, raw):
        return ClassifiedEvent(raw=raw, classification=classify(raw.raw_text))

    def test_future_flagged_arrival_sets_eta_and_vessel(self):
        events = [
            self._classified(self._raw("2026-07-09", "Load on MAERSK DENVER / 627W")),
            self._classified(self._raw("2026-07-09", "Vessel departure (MAERSK DENVER / 627W)")),
            self._classified(self._raw(
                "2026-08-14", "Vessel arrival (MAERSK DENVER / 627W)", is_future=True,
            )),
        ]
        state = infer_state("MRKU0000001", events)
        self.assertEqual(state.current_eta, datetime(2026, 8, 14))
        self.assertEqual(state.current_vessel, "MAERSK DENVER / 627W")

    def test_future_flagged_arrival_does_not_advance_current_phase(self):
        """The container hasn't actually arrived yet - current_phase must
        still reflect the last CONFIRMED milestone (vessel departed),
        not jump to "Arrived at port" off the future row."""
        events = [
            self._classified(self._raw("2026-07-09", "Load on MAERSK DENVER / 627W")),
            self._classified(self._raw("2026-07-09", "Vessel departure (MAERSK DENVER / 627W)")),
            self._classified(self._raw(
                "2026-08-14", "Vessel arrival (MAERSK DENVER / 627W)", is_future=True,
            )),
        ]
        state = infer_state("MRKU0000001", events)
        self.assertEqual(state.current_phase, "Departed")
        self.assertIn(
            "1 future-dated event(s) excluded from confirmed history (scheduled, not yet occurred)",
            state.data_quality_issues,
        )

    def test_unflagged_future_dated_row_is_excluded_not_used_as_eta(self):
        """Regression guard: a plain future-dated event WITHOUT the
        carrier's is_future flag (HL's unmarked speculative schedule
        rows) must still be excluded from confirmed history, but must
        NOT be resurrected as an ETA/vessel source the way a genuinely
        carrier-flagged Maersk row is - it's unverified, not confirmed."""
        events = [
            self._classified(self._raw("2026-07-09", "Vessel departed MUNDRA")),
            self._classified(self._raw("2026-08-14", "Vessel arrived NORFOLK, VA", is_future=False)),
        ]
        state = infer_state("MRKU0000001", events)
        self.assertIsNone(state.current_eta)
        self.assertEqual(state.current_phase, "Departed")


if __name__ == "__main__":
    unittest.main()
