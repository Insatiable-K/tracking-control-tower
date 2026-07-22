"""
Tests for MSCAdapter.parse() - pure text processing, no browser needed.
search() needs a live Selenium session against the real MSC site and is
exercised separately (see the module docstring in carriers/msc.py and
this session's earlier live-check precedent for Maersk/HL); it is not
part of this automated suite.

Fixture data reconstructed from TEMU3632568's real, complete event
history (OLD/merged_validation_output_12-31-2025_22-10-54.xlsx) into
the raw 5-line-per-event block shape the MSC tracking page actually
produces, with unpadded D-M-YYYY dates (e.g. "5-11-2025") - MSC_INC.py's
pad_date_str exists specifically because the site's raw dates aren't
zero-padded, so the fixture exercises that, not a convenience shortcut.
"""
import unittest
from datetime import datetime

from tracking_control_tower.carriers.base import RawPage
from tracking_control_tower.carriers.msc import MSCAdapter

REAL_TEMU3632568_BLOCK = "\n".join([
    "5-11-2025", "La Spezia, IT", "Empty to Shipper", "EMPTY", "Lsct - La Spezia Container Terminal",
    "6-11-2025", "La Spezia, IT", "Export received at CY", "LADEN", "Lsct - La Spezia Container Terminal",
    "13-11-2025", "La Spezia, IT", "Export Loaded on Vessel", "CAPE TAINARO MC545A", "Lsct - La Spezia Container Terminal",
    "14-11-2025", "Oakland, US", "Carrier release", "CAPE TAINARO 545A", "N.A",
    "22-12-2025", "Oakland, US", "Import Discharged from Vessel", "CAPE TAINARO 545A", "Trapac Oakland",
    "29-12-2025", "Oakland, US", "Import to consignee", "LADEN", "Trapac Oakland",
    "29-12-2025", "Oakland, US", "Full Available for Delivery", "LADEN", "Trapac Oakland",
])


class TestParseRealHistory(unittest.TestCase):
    def test_full_real_history_parses_into_seven_events_in_order(self):
        raw = RawPage(container="TEMU3632568", text=REAL_TEMU3632568_BLOCK)
        events = MSCAdapter().parse(raw)

        self.assertEqual(len(events), 7)
        self.assertEqual([e.raw_text for e in events], [
            "Empty to Shipper", "Export received at CY", "Export Loaded on Vessel",
            "Carrier release", "Import Discharged from Vessel",
            "Import to consignee", "Full Available for Delivery",
        ])

    def test_unpadded_dates_are_parsed_correctly(self):
        raw = RawPage(container="TEMU3632568", text=REAL_TEMU3632568_BLOCK)
        events = MSCAdapter().parse(raw)
        self.assertEqual(events[0].date, datetime(2025, 11, 5))
        self.assertEqual(events[2].date, datetime(2025, 11, 13))

    def test_location_vessel_info_facility_carried_through(self):
        raw = RawPage(container="TEMU3632568", text=REAL_TEMU3632568_BLOCK)
        events = MSCAdapter().parse(raw)
        loaded_event = events[2]
        self.assertEqual(loaded_event.location, "La Spezia, IT")
        self.assertEqual(loaded_event.vessel_info, "CAPE TAINARO MC545A")
        self.assertEqual(loaded_event.facility, "Lsct - La Spezia Container Terminal")

    def test_container_and_source_are_set(self):
        raw = RawPage(container="TEMU3632568", text=REAL_TEMU3632568_BLOCK)
        events = MSCAdapter().parse(raw)
        self.assertTrue(all(e.container == "TEMU3632568" for e in events))
        self.assertTrue(all(e.source == "MSC" for e in events))


class TestParsePodEta(unittest.TestCase):
    def test_pod_eta_becomes_a_synthetic_estimated_arrival_event(self):
        raw = RawPage(container="TEMU3632568", text=REAL_TEMU3632568_BLOCK, pod_eta_text="15-1-2026")
        events = MSCAdapter().parse(raw)
        eta_events = [e for e in events if e.raw_text == "Estimated Time of Arrival"]
        self.assertEqual(len(eta_events), 1)
        self.assertEqual(eta_events[0].date, datetime(2026, 1, 15))

    def test_no_pod_eta_text_adds_nothing(self):
        raw = RawPage(container="TEMU3632568", text=REAL_TEMU3632568_BLOCK, pod_eta_text=None)
        events = MSCAdapter().parse(raw)
        self.assertEqual(len(events), 7)

    def test_unparseable_pod_eta_is_silently_skipped_not_a_crash(self):
        raw = RawPage(container="TEMU3632568", text=REAL_TEMU3632568_BLOCK, pod_eta_text="not a date")
        events = MSCAdapter().parse(raw)
        self.assertEqual(len(events), 7)


# Captured verbatim via a live search() run against real container
# MEDU5655981 (2026-07-13) - includes the literal column-header row and
# the "Show all*" pagination toggle exactly as MSC's page renders them.
# This is the real trigger for FEASIBILITY.md's ~8.5% historical
# parsing-artifact finding; see carriers/msc.py's module docstring.
LIVE_CAPTURED_RAW_TEXT = (
    "Date\nLocation\nDescription\nEmpty/Laden/Vessel/Voyage\nEquipment handling facility name\n"
    "13/08/2026\nOakland, US\nEstimated Time of Arrival\nMSC CARLOTTA MC627A\nTrapac Oakland\n"
    "Show all*\n"
    "11/07/2026\nLa Spezia, IT\nExport Loaded on Vessel\nMSC CARLOTTA MC627A\nLsct - La Spezia Container Terminal\n"
    "10/07/2026\nOakland, US\nCarrier release\nMSC CARLOTTA MC627A\nN.A\n"
    "02/07/2026\nLa Spezia, IT\nExport received at CY\nLADEN\nLsct - La Spezia Container Terminal\n"
    "02/07/2026\nLa Spezia, IT\nEmpty to Shipper\nEMPTY\nLsct - La Spezia Container Terminal"
)


class TestLiveCapturedHeaderAndShowAllArtifacts(unittest.TestCase):
    def test_header_row_and_show_all_do_not_corrupt_alignment(self):
        raw = RawPage(container="MEDU5655981", text=LIVE_CAPTURED_RAW_TEXT, pod_eta_text="13/08/2026")
        events = MSCAdapter().parse(raw)

        # 5 real events + 1 synthetic pod_eta event, NOT a header-garbage
        # event and NOT 4 misaligned events with fields shifted by one.
        self.assertEqual(len(events), 6)
        real_events = [e for e in events if e.location is not None]
        self.assertEqual([e.raw_text for e in real_events], [
            "Estimated Time of Arrival", "Export Loaded on Vessel", "Carrier release",
            "Export received at CY", "Empty to Shipper",
        ])
        self.assertEqual([e.location for e in real_events], [
            "Oakland, US", "La Spezia, IT", "Oakland, US", "La Spezia, IT", "La Spezia, IT",
        ])
        # Before the fix, this would have been 'La Spezia, IT' (a place
        # name shifted into the description field) and vessel_info would
        # have held 'Export Loaded on Vessel' - exactly the class of bug
        # found in the historical archive.
        self.assertEqual(real_events[1].raw_text, "Export Loaded on Vessel")
        self.assertEqual(real_events[1].vessel_info, "MSC CARLOTTA MC627A")

    def test_no_header_or_show_all_leaks_into_any_field(self):
        raw = RawPage(container="MEDU5655981", text=LIVE_CAPTURED_RAW_TEXT)
        events = MSCAdapter().parse(raw)
        junk = {"Date", "Location", "Description", "Empty/Laden/Vessel/Voyage",
                "Equipment handling facility name", "Show all*"}
        for e in events:
            self.assertNotIn(e.raw_text, junk)
            self.assertNotIn(e.location, junk)
            self.assertNotIn(e.vessel_info, junk)
            self.assertNotIn(e.facility, junk)


# Real live scrape of CRSU1397223, caught while investigating why the
# Exceptions sheet showed unclassified_events_present for it: "Carrier
# release" here has NO facility line at all in the real DOM (not a
# blank one - genuinely absent), which the old rigid-5-lines-per-block
# parser turned into eating the next event's date as this event's
# facility, corrupting every subsequent event's fields for the rest of
# the container's history. Real vessel names ("MSC URSULA VI UA622R",
# "LOG-IN DISCOVERY 723S") ended up unclassified as if they were event
# descriptions - the actual, concrete version of that failure.
REAL_CRSU1397223_BLOCK_MISSING_FACILITY = "\n".join([
    "16/07/2026", "Long Beach, US", "Estimated Time of Arrival", "MSC NITYA B MC623A", "Long Beach Pier T Terminal",
    "05/07/2026", "Rodman, PA", "Full Transshipment Loaded", "MSC NITYA B MC623A", "Panama Singapur International Terminal",
    "30/06/2026", "Rodman, PA", "Full Transshipment Positioned In", "LADEN", "Panama Singapur International Terminal",
    "30/06/2026", "Colon, PA", "Full Transshipment Positioned Out", "LADEN", "Colon Container Terminal",
    "25/06/2026", "Long Beach, US", "Carrier release", "N.A",
    "24/06/2026", "Colon, PA", "Full Transshipment Discharged", "MSC URSULA VI UA622R", "Colon Container Terminal",
    "09/06/2026", "Rio De Janeiro, BR", "Full Transshipment Loaded", "MSC URSULA VI UA622R", "Multiterminais Rio De Janeiro",
])


class TestMissingFacilityLineDoesNotMisalignSubsequentEvents(unittest.TestCase):
    def test_event_with_no_facility_line_is_parsed_with_facility_none(self):
        raw = RawPage(container="CRSU1397223", text=REAL_CRSU1397223_BLOCK_MISSING_FACILITY)
        events = MSCAdapter().parse(raw)
        carrier_release = next(e for e in events if e.raw_text == "Carrier release")
        self.assertIsNone(carrier_release.facility)
        self.assertEqual(carrier_release.vessel_info, "N.A")

    def test_events_after_the_missing_facility_line_are_not_shifted(self):
        raw = RawPage(container="CRSU1397223", text=REAL_CRSU1397223_BLOCK_MISSING_FACILITY)
        events = MSCAdapter().parse(raw)
        # Before the fix: the next event's date ("24/06/2026") would have
        # been consumed as Carrier release's facility, and every field
        # from here on would be shifted by one - "MSC URSULA VI UA622R"
        # would show up as a raw_text (description) instead of vessel_info.
        discharged = next(e for e in events if e.raw_text == "Full Transshipment Discharged")
        self.assertEqual(discharged.date, datetime(2026, 6, 24))
        self.assertEqual(discharged.location, "Colon, PA")
        self.assertEqual(discharged.vessel_info, "MSC URSULA VI UA622R")
        self.assertEqual(discharged.facility, "Colon Container Terminal")
        self.assertEqual(len(events), 7)


class TestParseEdgeCases(unittest.TestCase):
    def test_search_error_produces_no_events_not_a_crash(self):
        raw = RawPage(container="BADU0000000", error="element not found")
        events = MSCAdapter().parse(raw)
        self.assertEqual(events, [])

    def test_incomplete_trailing_block_is_dropped(self):
        """Matches MSC_INC.py's exact behavior: only complete 5-line
        blocks become events; a trailing partial block (e.g. the page
        cut off mid-render) is silently dropped, not force-parsed."""
        incomplete = REAL_TEMU3632568_BLOCK + "\n30-12-2025\nOakland, US"
        raw = RawPage(container="TEMU3632568", text=incomplete)
        events = MSCAdapter().parse(raw)
        self.assertEqual(len(events), 7)  # not 8 - the trailing 2-line partial block is dropped

    def test_empty_text_produces_no_events(self):
        raw = RawPage(container="TEMU3632568", text="")
        events = MSCAdapter().parse(raw)
        self.assertEqual(events, [])


class TestDatePadding(unittest.TestCase):
    def test_single_digit_day_and_month_are_padded(self):
        from tracking_control_tower.carriers.msc import _pad_date_str
        self.assertEqual(_pad_date_str("5-6-2025"), "05-06-2025")
        self.assertEqual(_pad_date_str("15-6-2025"), "15-06-2025")
        self.assertEqual(_pad_date_str("5-11-2025"), "05-11-2025")

    def test_already_padded_is_unchanged(self):
        from tracking_control_tower.carriers.msc import _pad_date_str
        self.assertEqual(_pad_date_str("05-06-2025"), "05-06-2025")


class TestRouterIntegration(unittest.TestCase):
    def test_msc_vessel_routes_to_msc_adapter(self):
        from tracking_control_tower.carriers.router import adapter_for_vessel
        self.assertIs(adapter_for_vessel("MSC-CAPE TAINARO 545A"), MSCAdapter)
        self.assertIs(adapter_for_vessel("MSC ATHOS MC528R"), MSCAdapter)

    def test_other_carriers_do_not_route_to_msc(self):
        from tracking_control_tower.carriers.router import adapter_for_vessel
        from tracking_control_tower.carriers.maersk import MaerskAdapter
        self.assertIs(adapter_for_vessel("MAERSK DENVER 627W"), MaerskAdapter)
        self.assertIsNone(adapter_for_vessel("SOME OTHER LINE 123X"))
        self.assertIsNone(adapter_for_vessel(None))


if __name__ == "__main__":
    unittest.main()
