"""
Replaces the four separate workbooks MSC_INC.py / HL Tracking produced
(filtered/scraped/merged/final) with one renderer, regardless of which
carrier a shipment came from.

Three sheets, aimed at three different real uses:
  - Container Tracking: one row per MSC/Hapag-Lloyd/Maersk shipment -
    every SPS field a data entry associate already has on file, sitting
    next to what the carrier's own site says right now. Plain,
    business-facing column headers (set explicitly below, not derived
    from the internal snake_case field names) so a non-technical reader
    never needs to know the underlying schema.
  - Other Carriers: containers on a vessel prefix without a live
    adapter yet (not MSC/HL/Maersk) - only the SPS fields are available
    for these, so they're kept separate rather than mixed into the main
    report with a wall of blank tracking columns.
  - Exceptions: one row per flagged issue, sorted worst-first, so
    logistics/warehouse/data-quality can each filter to their own rows.
"""
import pandas as pd

from tracking_control_tower.reporting.models import OtherCarrierRow, ShipmentReportRow
from tracking_control_tower.reporting.renderer_base import ReportRenderer

_SEVERITY_SORT = {"high": 0, "medium": 1, "low": 2}

# Business-facing header -> ShipmentReportRow field. Order here is the
# order columns appear in the sheet.
_TRACKING_COLUMNS = {
    "SIPL": "sipl",
    "Container Number": "container",
    "Carrier": "carrier",
    "SIPL Status": "sipl_status",
    "Ship To Location": "ship_to_location",
    "SPS Vessel": "sps_vessel",
    "SPS Port ETA": "sps_port_eta",
    "SPS Location ETA": "sps_location_eta",
    "Current Status": "current_status",
    "Current Location": "current_location",
    "Departure Port": "departure_port",
    "Arrival Port": "arrival_port",
    "Current Vessel": "current_vessel",
    "Estimated Dock Date": "estimated_dock_date",
    "Last Tracked Event": "previous_event",
    "Next Expected Event": "next_expected_event",
    "Port ETA Needs Update?": "port_eta_needs_update",
    "Vessel Needs Update?": "vessel_needs_update",
    "Port ETA or Vessel Update Needed?": "port_eta_or_vessel_needs_update",
    "Risk Level": "risk_level",
    "Tracking Confidence": "tracking_confidence",
    "Data Quality Notes": "data_quality_notes",
}

_OTHER_CARRIER_COLUMNS = {
    "SIPL": "sipl",
    "Container Number": "container",
    "Vessel": "vessel",
    "SIPL Status": "sipl_status",
    "Ship To Location": "ship_to_location",
    "SPS Port ETA": "sps_port_eta",
    "SPS Location ETA": "sps_location_eta",
}


class ExcelRenderer(ReportRenderer):
    def render(
        self,
        rows: list[ShipmentReportRow],
        output_path: str,
        other_carrier_rows: list[OtherCarrierRow] | None = None,
    ) -> None:
        # ETAs/dates in this codebase are always compared day-level (see
        # utils/dates.same_day) - every value is midnight, so xlsxwriter's
        # default datetime format ("yyyy-mm-dd hh:mm:ss") would show a
        # meaningless "00:00:00" on every date cell in the report.
        with pd.ExcelWriter(output_path, engine="xlsxwriter", datetime_format="yyyy-mm-dd") as writer:
            self._write_tracking_report(rows, writer)
            self._write_other_carriers(other_carrier_rows or [], writer)
            self._write_exceptions(rows, writer)

    @staticmethod
    def _write_tracking_report(rows: list[ShipmentReportRow], writer) -> None:
        df = pd.DataFrame([
            {
                header: (
                    # MSC_INC.py's eta_or_vessel_changed was 'Yes'/'No'
                    # text, not a raw boolean - matching that convention
                    # for this specific column since it's a direct port
                    # of that logic, not a new invention.
                    ("Yes" if getattr(r, field) else "No")
                    if field == "port_eta_or_vessel_needs_update"
                    else getattr(r, field)
                )
                for header, field in _TRACKING_COLUMNS.items()
            }
            for r in rows
        ], columns=list(_TRACKING_COLUMNS))
        df.to_excel(writer, sheet_name="Container Tracking", index=False)

    @staticmethod
    def _write_other_carriers(rows: list[OtherCarrierRow], writer) -> None:
        df = pd.DataFrame([
            {header: getattr(r, field) for header, field in _OTHER_CARRIER_COLUMNS.items()}
            for r in rows
        ], columns=list(_OTHER_CARRIER_COLUMNS))
        df.to_excel(writer, sheet_name="Other Carriers", index=False)

    @staticmethod
    def _write_exceptions(rows: list[ShipmentReportRow], writer) -> None:
        flat = [
            {
                "SIPL": r.sipl,
                "Container Number": r.container,
                "Carrier": r.carrier,
                "Severity": e.severity,
                "Rule": e.rule,
                "Reason": e.reason,
                "Routed To": e.routed_to,
            }
            for r in rows
            for e in r.exceptions
        ]
        df = pd.DataFrame(
            flat, columns=["SIPL", "Container Number", "Carrier", "Severity", "Rule", "Reason", "Routed To"]
        )
        if not df.empty:
            df["_sort"] = df["Severity"].map(_SEVERITY_SORT)
            df = df.sort_values("_sort").drop(columns="_sort")
        df.to_excel(writer, sheet_name="Exceptions", index=False)
