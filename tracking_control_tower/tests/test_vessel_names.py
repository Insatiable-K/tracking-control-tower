"""
Tests for vessel name normalization, built from real SPS/scraped vessel
strings found across MSC and HL historical data.
"""
import unittest

from tracking_control_tower.utils.vessel_names import normalize_vessel_name, vessels_effectively_match


class TestVesselNormalization(unittest.TestCase):
    REAL_EXAMPLES = [
        ("MSK-CLEMENTINE MAERSK / 621W", "CLEMENTINE MAERSK"),
        ("MSK-CLEMENTINE MAERSK 621W", "CLEMENTINE MAERSK"),
        ("MSK-FRANKFURT EXPRESS / 626E", "FRANKFURT EXPRESS"),
        ("MAERSK DENVER 627W", "MAERSK DENVER"),
        ("TORRENTE 5137", "TORRENTE"),
        ("MAERSK SERANGOON 537E", "MAERSK SERANGOON"),
        ("HL-CLEMENTINE MAERSK", "CLEMENTINE MAERSK"),
        ("MSC ATHOS MC528R", "MSC ATHOS"),
        ("MSC URSULA VI UA529R", "MSC URSULA VI"),
        ("MED BEYKOZ AX540R", "MED BEYKOZ"),
        ("LOG-IN RESILIENTE 635S", "LOG-IN RESILIENTE"),
    ]

    def test_real_examples_normalize_correctly(self):
        for raw, expected in self.REAL_EXAMPLES:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_vessel_name(raw), expected)

    def test_hyphen_in_the_vessel_name_itself_is_preserved(self):
        """
        'X-Press Carina' is a real vessel (X-Press Feeders line) seen in
        HL history - a naive "strip anything before the first hyphen"
        rule would wrongly eat the 'X' as if it were a carrier prefix.
        """
        self.assertEqual(normalize_vessel_name("X-PRESS CARINA 536E"), "X-PRESS CARINA")

    def test_none_and_empty_are_handled(self):
        self.assertIsNone(normalize_vessel_name(None))
        self.assertIsNone(normalize_vessel_name(""))
        self.assertIsNone(normalize_vessel_name("nan"))

    def test_container_load_state_words_are_not_treated_as_vessels(self):
        """
        Real bug caught by run_sample_report.py: MSC's scraped
        'Vessel Info' field sometimes holds 'LADEN' instead of an
        actual vessel name, which silently triggered a bogus SPS
        vessel-update recommendation.
        """
        self.assertIsNone(normalize_vessel_name("LADEN"))
        self.assertIsNone(normalize_vessel_name("EMPTY"))
        self.assertIsNone(normalize_vessel_name("laden"))

    def test_same_vessel_different_voyage_numbers_match(self):
        a = normalize_vessel_name("MAERSK SERANGOON 537E")
        b = normalize_vessel_name("MAERSK SERANGOON 541W")
        self.assertEqual(a, b)

    def test_spaced_hyphen_prefix_is_stripped(self):
        """Real SPS data: 'MSC - MSC FLORA MC622A' (spaces around the
        hyphen), not just 'MSC-MSC FLORA MC622A'."""
        self.assertEqual(normalize_vessel_name("MSC - MSC FLORA MC622A"), "MSC FLORA")


class TestVesselsEffectivelyMatch(unittest.TestCase):
    """
    Real bug caught via run_tracking.py's first production run: the SPS
    export's vessel field sometimes has the carrier code glued on twice
    ('MSC-MSC CAPE TAINARO MC621A' normalizes to 'MSC CAPE TAINARO',
    but that vessel's own tracked name has no 'MSC' in it at all -
    'CAPE TAINARO'), which was silently triggering a bogus SPS
    vessel-update recommendation despite the vessel not actually having
    changed. normalize_vessel_name() can't safely resolve this alone
    (stripping a repeated leading word there would also break a
    genuinely MSC-branded vessel like 'MSC Flora'), so this comparison
    only strips the extra word when doing so is the ONLY way the two
    sides agree.
    """

    def test_duplicated_carrier_prefix_is_recognized_as_same_vessel(self):
        sps = normalize_vessel_name("MSC-MSC CAPE TAINARO MC621A")
        tracked = normalize_vessel_name("CAPE TAINARO MC621A")
        self.assertTrue(vessels_effectively_match(sps, tracked))

    def test_genuinely_msc_branded_vessel_is_not_over_stripped(self):
        sps = normalize_vessel_name("MSC - MSC FLORA MC622A")
        tracked = normalize_vessel_name("MSC FLORA MC622A")
        self.assertTrue(vessels_effectively_match(sps, tracked))

    def test_real_vessel_change_still_detected(self):
        sps = normalize_vessel_name("MSK-CLEMENTINE MAERSK / 621W")
        tracked = normalize_vessel_name("MAERSK DENVER 627W")
        self.assertFalse(vessels_effectively_match(sps, tracked))

    def test_none_values_do_not_match(self):
        self.assertFalse(vessels_effectively_match(None, "CAPE TAINARO"))
        self.assertFalse(vessels_effectively_match("CAPE TAINARO", None))


if __name__ == "__main__":
    unittest.main()
