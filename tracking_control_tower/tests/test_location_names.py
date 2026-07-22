"""
Tests for location normalization, built from real port strings found
in the first production Tracking_Report_*.xlsx (Container Tracking
sheet's Current Location/Departure Port/Arrival Port columns).
"""
import unittest

from tracking_control_tower.utils.location_names import normalize_location


class TestLocationNormalization(unittest.TestCase):
    def test_real_duplicate_pairs_now_match(self):
        """These pairs are the actual real-data duplicates that showed
        up as separate categories before normalization - the direct
        bug report this module exists to fix."""
        pairs = [
            ("Houston, US", "HOUSTON, TX"),
            ("Genoa, IT", "GENOA"),
            ("Norfolk, US", "NORFOLK, VA"),
        ]
        for a, b in pairs:
            with self.subTest(a=a, b=b):
                self.assertEqual(normalize_location(a), normalize_location(b))

    def test_comma_separated_country_code_form(self):
        self.assertEqual(normalize_location("La Spezia, IT"), "La Spezia")
        self.assertEqual(normalize_location("Rio De Janeiro, BR"), "Rio De Janeiro")

    def test_comma_separated_state_code_form(self):
        self.assertEqual(normalize_location("HOUSTON, TX"), "Houston")

    def test_slash_separated_terminal_form(self):
        self.assertEqual(normalize_location("JAIPUR / JAIPUR RAIL TERMINAL"), "Jaipur")
        self.assertEqual(normalize_location("SOHAR / OMAN INTERNATIONAL CONT. TERMINAL"), "Sohar")

    def test_bare_city_name_with_no_separator(self):
        self.assertEqual(normalize_location("GENOA"), "Genoa")
        self.assertEqual(normalize_location("NHAVA SHEVA"), "Nhava Sheva")

    def test_ambiguous_region_code_is_not_misresolved(self):
        """'PA' means Panama here, not Pennsylvania - Rodman/Colon/
        Cristobal are all real Panama Canal ports. Not attempting to
        resolve the region code at all is what keeps this correct."""
        self.assertEqual(normalize_location("Rodman, PA"), "Rodman")
        self.assertEqual(normalize_location("Colon, PA"), "Colon")

    def test_none_and_empty_are_handled(self):
        self.assertIsNone(normalize_location(None))
        self.assertIsNone(normalize_location(""))
        self.assertIsNone(normalize_location("nan"))


if __name__ == "__main__":
    unittest.main()
