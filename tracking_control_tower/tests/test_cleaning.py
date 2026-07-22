"""
Parity tests for the cleaning stage against the real 1RAW.xlsx export.

These check invariants that must hold if clean_sps_export() reproduces
MSC_INC.py's cleaning behavior exactly (see FEASIBILITY.md §05: every
rule here is preserved as-is, not reinterpreted).
"""
import unittest
from pathlib import Path

from tracking_control_tower.cleaning.shipment_cleaner import clean_sps_export
from tracking_control_tower.config.settings import STATUSES_TO_REMOVE, VESSEL_PREFIXES

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_FILE = PROJECT_ROOT / "1RAW.xlsx"


@unittest.skipUnless(RAW_FILE.exists(), f"{RAW_FILE} not present")
class TestCleaningParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = clean_sps_export(str(RAW_FILE))

    def test_columns_renamed(self):
        expected = {
            "sipl", "supplier", "port_eta", "rail_eta", "location_eta",
            "ship_to_location", "purchase_location", "container", "vessel",
            "lfd", "sipl_status", "status", "initiated_on", "eta_date",
            "fr_forwarder", "departure_port",
        }
        self.assertEqual(set(self.result.cleaned.columns), expected)

    def test_no_excluded_statuses_remain(self):
        remaining = set(self.result.cleaned["sipl_status"].str.lower().unique())
        excluded = {s.lower() for s in STATUSES_TO_REMOVE}
        self.assertEqual(remaining & excluded, set())

    def test_all_rows_have_blank_lfd(self):
        self.assertTrue(self.result.cleaned["lfd"].isna().all())

    def test_no_duplicate_containers(self):
        # A real row can genuinely have no extractable container number
        # (a domestic trucking movement using a UPS/FedEx/XPO tracking
        # number, not an ocean container at all - see
        # test_container_number_extraction.py) - multiple such rows
        # sharing a null container isn't a duplicate in the dedup sense,
        # just multiple rows this extraction correctly found nothing
        # for. Only real (non-null) container numbers must be unique.
        containers = self.result.cleaned["container"].dropna()
        self.assertEqual(containers.duplicated().sum(), 0)

    def test_container_ids_are_exactly_11_chars_when_present(self):
        lengths = self.result.cleaned["container"].dropna().str.len()
        self.assertTrue((lengths == 11).all())

    def test_vessel_prefix_partition_covers_every_row(self):
        accounted = sum(len(df) for df in self.result.vessel_dfs.values()) + len(self.result.mismatched)
        self.assertEqual(accounted, len(self.result.cleaned))

    def test_vessel_dfs_only_contain_matching_prefix(self):
        for prefix in VESSEL_PREFIXES:
            df = self.result.vessel_dfs[prefix]
            if df.empty:
                continue
            self.assertTrue(df["vessel"].str.startswith(prefix).all())

    def test_counts_are_internally_consistent(self):
        c = self.result.counts
        self.assertEqual(
            c["raw_rows"] - c["removed_by_status"] - c["removed_by_lfd"] - c["removed_duplicates"],
            c["final_rows"],
        )


if __name__ == "__main__":
    unittest.main()
