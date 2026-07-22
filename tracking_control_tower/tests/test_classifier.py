"""
Unit tests for the event classifier, built from real historical vocabulary
(see events/taxonomy.yaml header for source counts) rather than invented
examples.
"""
import unittest

from tracking_control_tower.events.classifier import UNCLASSIFIED, classify

# (raw_text, expected_category, expected_phase_rank) - drawn directly from
# OLD/msc_scraped_results_*.xlsx and HL Tracking/old/HL_Parsed_*.xlsx.
REAL_KNOWN_EVENTS = [
    ("Estimated Time of Arrival", "estimated_arrival", None),
    ("Empty to Shipper", "empty_released_to_shipper", 1),
    ("Export Loaded on Vessel", "loaded_on_vessel", 2),
    ("Export received at CY", "export_received", 1),
    ("Full Transshipment Discharged", "transshipment", 4),
    ("Full Transshipment Loaded", "transshipment", 4),
    ("Carrier release", "export_received", 1),
    ("Export Loaded on Rail", "export_received", 1),
    ("Export Unloaded from Rail", "export_received", 1),
    ("Import Discharged from Vessel", "discharged", 7),
    ("Import Rail Departure", "rail_departure", 9),
    ("Import Unloaded from Rail", "rail_arrival", 9),
    ("Full Available for Delivery", "available_for_delivery", 10),
    ("Import to consignee", "delivered_to_consignee", 12),
    ("Vessel arrival", "arrived_at_port", 6),
    ("Vessel arrived", "arrived_at_port", 6),
    ("Vessel departed", "vessel_departed", 3),
    ("Vessel departure", "vessel_departed", 3),
    ("Discharge", "discharged", 7),
    ("Discharged", "discharged", 7),
    ("Gate out empty", "gate_movement", 1),
    ("Gate in empty", "gate_movement", 1),
    ("Loaded", "loaded_on_vessel", 2),
    ("Loading", "loaded_on_vessel", 2),
    ("Arrival in", "inland_leg_arrival", 1),
    ("Departure from", "inland_leg_departure", 1),
    # HL's current SPA (solutions/tracking/#/), confirmed via the
    # FEASIBILITY.md §09 Step 0 live batch trial 2026-07-13:
    ("Gated in", "inland_leg_arrival", 1),
    ("Gated out", "inland_leg_departure", 1),
    ("Stuffed", "export_received", 1),
    # Maersk's current site, confirmed via the same Step 0 trial:
    ("Gate in", "inland_leg_arrival", 1),
    ("Gate out", "inland_leg_departure", 1),
    ("Load on CLEMENTINE MAERSK / 621W", "loaded_on_vessel", 2),
    # Maersk's current site, confirmed via a real container (MRKU9596846)
    # showing "Feeder departure (MAERSK KENTUCKY / 623S)" as unclassified
    # in the Exceptions sheet 2026-07-15 - a feeder is a smaller
    # connecting vessel for a transshipment leg, same underlying meaning
    # as "Vessel departure"/"Vessel arrival".
    ("Feeder departure (MAERSK KENTUCKY / 623S)", "vessel_departed", 3),
    ("Feeder arrival (MAERSK KENTUCKY / 623S)", "arrived_at_port", 6),
    # MSC's current site, confirmed via 4 real containers flagged in the
    # Exceptions sheet 2026-07-16 (XHCU2466631, TGBU1344515, MSDU2447472,
    # MSDU1284560) - same "start of the export cycle" meaning as the
    # other export_received phrases, just a different first-event wording.
    ("Start Export Cycle", "export_received", 1),
]

# Full raw lines exactly as HL's history block presents them (place/date/
# vessel suffix included) - proves matching works on realistic, not just
# bare, phrases.
REAL_FULL_LINES = [
    ("Arrival in JAIPUR 2025-09-08 20:19 Truck", "inland_leg_arrival"),
    ("Loaded MUNDRA 2025-09-18 07:31 TORRENTE 5137", "loaded_on_vessel"),
    ("Vessel arrived NORFOLK, VA 2025-10-23 06:30 TORRENTE 5137", "arrived_at_port"),
    ("Discharged NORFOLK, VA 2025-10-23 19:36 TORRENTE 5137", "discharged"),
    ("Vessel arrival HOUSTON, TX 2025-11-07 15:00 MEXICO EXPRESS 541W", "arrived_at_port"),
]

# The exact historical parsing bug from FEASIBILITY.md §02: HL's old
# first-word-split parser turned this into status="Empty",
# place="Arrival in RIVOLI VERONESE". The classifier must recover the
# correct category via the container_state/text split instead.
KNOWN_BUG_CASE = "Empty Arrival in RIVOLI VERONESE 2025-09-25 08:42 Truck"

# Real values that leaked into MSC's "description" column from a
# misaligned scrape block (dates, vessel names, place names - see
# FEASIBILITY.md investigation). None of these are real events and all
# must land as unclassified, not be force-fit into a category.
REAL_PARSING_ARTIFACTS = [
    "07/05/2026",
    "LOG-IN RESILIENTE 635S",
    "EUROPE UA536R",
    "Vitoria, BR",
    "Rio De Janeiro, BR",
    "MSC ATHOS MC528R",
    "Sines Container Terminal",
]


class TestKnownEvents(unittest.TestCase):
    def test_bare_phrases_classify_correctly(self):
        for raw, expected_category, expected_rank in REAL_KNOWN_EVENTS:
            with self.subTest(raw=raw):
                result = classify(raw)
                self.assertEqual(result.category, expected_category, msg=f"{raw!r} -> {result}")
                self.assertEqual(result.phase_rank, expected_rank, msg=f"{raw!r} -> {result}")

    def test_full_history_lines_classify_correctly(self):
        for raw, expected_category in REAL_FULL_LINES:
            with self.subTest(raw=raw):
                result = classify(raw)
                self.assertEqual(result.category, expected_category, msg=f"{raw!r} -> {result}")

    def test_container_state_qualifier_is_stripped(self):
        result = classify("Full Transshipment Discharged")
        self.assertEqual(result.container_state, "full")
        self.assertEqual(result.category, "transshipment")

        result = classify("Empty to Shipper")
        self.assertEqual(result.container_state, "empty")
        self.assertEqual(result.category, "empty_released_to_shipper")


class TestHistoricalBugFix(unittest.TestCase):
    def test_empty_arrival_in_no_longer_mis_splits(self):
        """
        The historical bug: HL's parser treated 'Empty Arrival in RIVOLI
        VERONESE...' as one unrecognized token and mis-split it into
        status='Empty', place='Arrival in RIVOLI VERONESE'. The new
        classifier must instead recognize this as an inland arrival event
        with container_state='empty'.
        """
        result = classify(KNOWN_BUG_CASE)
        self.assertEqual(result.category, "inland_leg_arrival")
        self.assertEqual(result.container_state, "empty")
        self.assertNotEqual(result.category, UNCLASSIFIED)


class TestParsingArtifactsRejected(unittest.TestCase):
    def test_leaked_dates_and_vessel_names_are_unclassified(self):
        """
        These values are not real events - they leaked into the
        'description' column from a misaligned 5-line scrape block
        (FEASIBILITY.md investigation, ~8.5% of MSC's historical
        description values). The classifier must not force-fit them into
        a category; they belong in the review queue.
        """
        for raw in REAL_PARSING_ARTIFACTS:
            with self.subTest(raw=raw):
                result = classify(raw)
                self.assertEqual(result.category, UNCLASSIFIED, msg=f"{raw!r} -> {result}")
                self.assertEqual(result.confidence, 0.0)


class TestUnclassifiedNeverGuesses(unittest.TestCase):
    def test_empty_string_is_unclassified(self):
        result = classify("")
        self.assertEqual(result.category, UNCLASSIFIED)

    def test_genuinely_novel_wording_is_unclassified_not_guessed(self):
        result = classify("Container swapped onto barge XYZ at midnight")
        self.assertEqual(result.category, UNCLASSIFIED)


if __name__ == "__main__":
    unittest.main()
