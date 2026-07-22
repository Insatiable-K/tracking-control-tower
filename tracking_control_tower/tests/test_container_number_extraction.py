"""
Tests for _extract_container_number, built from real 1RAW.xlsx raw
container-column values.
"""
import unittest

from tracking_control_tower.cleaning.shipment_cleaner import _extract_container_number


class TestContainerNumberExtraction(unittest.TestCase):
    def test_real_bug_note_prefix_and_trailing_hyphen(self):
        """The actual bug report: 'Freight 5 PO SEGU2963797-' - the old
        last-11-characters slice produced 'EGU2963797-' (drops the real
        leading 'S', keeps the trailing '-'). Searching for the ISO
        6346 shape instead of trusting position finds the genuine
        container number regardless of what surrounds it."""
        self.assertEqual(_extract_container_number("Freight 5 PO SEGU2963797-"), "SEGU2963797")

    def test_clean_container_number_extracts_unchanged(self):
        self.assertEqual(_extract_container_number("MEDU5655981"), "MEDU5655981")

    def test_lowercase_is_normalized(self):
        self.assertEqual(_extract_container_number("medu5655981"), "MEDU5655981")

    def test_domestic_trucking_tracking_numbers_are_not_containers(self):
        """Real rows: domestic truck/parcel movements (UPS/FedEx/XPO/
        ODFL tracking numbers), not ocean containers at all - these
        must extract to nothing, not a best-effort guess, since forcing
        a match here would silently invent a fake container number for
        a shipment that was never on a ship."""
        real_non_containers = [
            "TRUCK UPSGRND 1ZG6402X0309196863",
            "XPO 649540076",
            "TRUCK FEDEX 300322630136",
            "Daylight-159769892",
            "FedEX#870774907281",
            "TRUCK ODFL 36801628011",
        ]
        for raw in real_non_containers:
            with self.subTest(raw=raw):
                self.assertIsNone(_extract_container_number(raw))

    def test_malformed_rows_with_no_container_number_at_all(self):
        self.assertIsNone(_extract_container_number("3403- 4 POs"))
        self.assertIsNone(_extract_container_number("403 - 4 POs"))

    def test_none_and_nan_are_handled(self):
        import pandas as pd
        self.assertIsNone(_extract_container_number(None))
        self.assertIsNone(_extract_container_number(float("nan")))
        self.assertIsNone(_extract_container_number(pd.NA))


if __name__ == "__main__":
    unittest.main()
