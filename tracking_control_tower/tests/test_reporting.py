"""Tests for the reporting layer, including a real end-to-end render."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from tracking_control_tower.comparison.sps_diff import diff_against_sps
from tracking_control_tower.events.classifier import classify
from tracking_control_tower.exceptions.evaluator import evaluate_exceptions
from tracking_control_tower.orchestration.worklist import WorkItem
from tracking_control_tower.reporting.excel_renderer import ExcelRenderer
from tracking_control_tower.reporting.models import OtherCarrierRow, ShipmentReportRow, risk_level_from_exceptions
from tracking_control_tower.reporting.report_builder import build_report_row
from tracking_control_tower.shipment_state.engine import infer_state
from tracking_control_tower.shipment_state.models import ClassifiedEvent, RawEvent


def _events(container: str, rows: list[tuple[str, str]]) -> list[ClassifiedEvent]:
    out = []
    for date_str, text in rows:
        raw = RawEvent(container=container, date=datetime.fromisoformat(date_str), raw_text=text)
        out.append(ClassifiedEvent(raw=raw, classification=classify(text)))
    return out


class TestRiskLevelDerivation(unittest.TestCase):
    def test_no_exceptions_is_none(self):
        self.assertEqual(risk_level_from_exceptions([]), "none")

    def test_takes_the_highest_severity_present(self):
        from tracking_control_tower.exceptions.models import RiskException
        exceptions = [
            RiskException("unclassified_events_present", "low", "x", "C1"),
            RiskException("stalled", "medium", "y", "C1"),
        ]
        self.assertEqual(risk_level_from_exceptions(exceptions), "medium")


class TestBuildReportRow(unittest.TestCase):
    def test_assembles_from_engine_outputs(self):
        rows = [("2025-09-01", "Export received at CY")]
        state = infer_state("TEMU1111111", _events("TEMU1111111", rows))
        item = WorkItem(
            sipl="SIPL001", container="TEMU1111111", vessel=None, port_eta=None,
            ship_to_location="Houston", location_eta=None, sipl_status="Active",
        )
        sps_diff = diff_against_sps(state, sps_vessel=None, sps_port_eta=None)
        # Fixed as_of close to the event date - evaluate_exceptions()
        # defaults to datetime.now(), and this test's 2025 event would
        # otherwise look "stalled" against today's real date.
        exceptions = evaluate_exceptions(state, as_of=datetime(2025, 9, 5))

        row = build_report_row(item, "MSC", state, sps_diff, exceptions)
        self.assertEqual(row.sipl, "SIPL001")
        self.assertEqual(row.container, "TEMU1111111")
        self.assertEqual(row.carrier, "MSC")
        self.assertEqual(row.sipl_status, "Active")
        self.assertEqual(row.ship_to_location, "Houston")
        self.assertEqual(row.risk_level, "none")


class TestCombinedUpdateFlag(unittest.TestCase):
    """
    port_eta_or_vessel_needs_update mirrors MSC_INC.py's
    eta_or_vessel_changed (Y if either eta_changed or vessel_changed
    was Y) - added per direct request to match that script's behavior
    without re-running a live batch to see it.
    """

    def _row_with(self, sps_vessel, sps_port_eta, tracked_vessel, tracked_eta):
        state = infer_state("TEMU1111111", _events("TEMU1111111", [("2025-09-01", "Export received at CY")]))
        state.current_vessel = tracked_vessel
        state.current_eta = tracked_eta
        state.confidence_score = 1.0
        item = WorkItem(
            sipl="SIPL001", container="TEMU1111111", vessel=sps_vessel, port_eta=sps_port_eta,
            ship_to_location="Houston",
        )
        sps_diff = diff_against_sps(state, sps_vessel=sps_vessel, sps_port_eta=sps_port_eta)
        return build_report_row(item, "MSC", state, sps_diff, [])

    def test_true_when_only_vessel_differs(self):
        row = self._row_with("MSC-OLD VESSEL", None, "NEW VESSEL", None)
        self.assertFalse(row.port_eta_needs_update)
        self.assertTrue(row.vessel_needs_update)
        self.assertTrue(row.port_eta_or_vessel_needs_update)

    def test_true_when_only_port_eta_differs(self):
        row = self._row_with(None, datetime(2025, 9, 1), None, datetime(2025, 9, 5))
        self.assertTrue(row.port_eta_needs_update)
        self.assertFalse(row.vessel_needs_update)
        self.assertTrue(row.port_eta_or_vessel_needs_update)

    def test_true_when_both_differ(self):
        row = self._row_with("MSC-OLD VESSEL", datetime(2025, 9, 1), "NEW VESSEL", datetime(2025, 9, 5))
        self.assertTrue(row.port_eta_needs_update)
        self.assertTrue(row.vessel_needs_update)
        self.assertTrue(row.port_eta_or_vessel_needs_update)

    def test_false_when_neither_differs(self):
        row = self._row_with("MSC-SAME VESSEL", datetime(2025, 9, 5), "SAME VESSEL", datetime(2025, 9, 5))
        self.assertFalse(row.port_eta_needs_update)
        self.assertFalse(row.vessel_needs_update)
        self.assertFalse(row.port_eta_or_vessel_needs_update)


class TestExcelRendererRealData(unittest.TestCase):
    """
    Builds real ShipmentReportRow objects from real HL historical
    container histories (the same containers used throughout this
    session's other tests) and renders them, then reads the workbook
    back to confirm the sheets are structurally correct.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.output_path = Path(self._tmpdir.name) / "report.xlsx"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _build_row(self, sipl: str, container: str, rows, ship_to_location=None) -> ShipmentReportRow:
        state = infer_state(container, _events(container, rows))
        item = WorkItem(
            sipl=sipl, container=container, vessel=None, port_eta=None,
            ship_to_location=ship_to_location, location_eta=None, sipl_status="Active",
        )
        sps_diff = diff_against_sps(state, sps_vessel=None, sps_port_eta=None)
        exceptions = evaluate_exceptions(state, ship_to_location=ship_to_location, as_of=datetime(2025, 12, 1))
        return build_report_row(item, "Hapag-Lloyd", state, sps_diff, exceptions)

    def test_renders_three_sheets_with_expected_content(self):
        clean_row = self._build_row("SIPL001", "TEMU1111111", [("2025-09-01", "Import to consignee")])
        contradiction_rows = [
            ("2025-09-01", "Export received at CY"),
            ("2025-09-05", "Export Loaded on Vessel"),
            ("2025-10-01", "Import Discharged from Vessel"),
            ("2025-10-05", "Import Rail Departure"),
            ("2025-10-10", "Export Loaded on Vessel"),
        ]
        risky_row = self._build_row("SIPL002", "TEMU2222222", contradiction_rows)

        other_carrier_row = OtherCarrierRow(
            sipl="SIPL003", container="ZIMU1234567", vessel="ZIM-SOME VESSEL",
            sipl_status="Active", ship_to_location="Chicago", sps_port_eta=None, sps_location_eta=None,
        )

        ExcelRenderer().render([clean_row, risky_row], str(self.output_path), [other_carrier_row])
        self.assertTrue(self.output_path.exists())

        with pd.ExcelFile(self.output_path) as xls:
            self.assertEqual(set(xls.sheet_names), {"Container Tracking", "Other Carriers", "Exceptions"})

            report_df = xls.parse("Container Tracking")
            self.assertEqual(len(report_df), 2)
            self.assertIn("SIPL001", report_df["SIPL"].tolist())
            self.assertIn("SIPL002", report_df["SIPL"].tolist())
            self.assertIn("Hapag-Lloyd", report_df["Carrier"].tolist())
            # MSC_INC.py's eta_or_vessel_changed was 'Yes'/'No' text, not
            # a raw boolean - this column matches that convention.
            self.assertIn("Port ETA or Vessel Update Needed?", report_df.columns)
            self.assertTrue(set(report_df["Port ETA or Vessel Update Needed?"]).issubset({"Yes", "No"}))

            other_df = xls.parse("Other Carriers")
            self.assertEqual(len(other_df), 1)
            self.assertEqual(other_df.iloc[0]["Container Number"], "ZIMU1234567")

            exceptions_df = xls.parse("Exceptions")
            self.assertGreaterEqual(len(exceptions_df), 1)
            self.assertEqual(exceptions_df.iloc[0]["Severity"], "high")  # sorted worst-first
            self.assertTrue((exceptions_df["SIPL"] == "SIPL002").all())  # only the risky shipment has exceptions


if __name__ == "__main__":
    unittest.main()
