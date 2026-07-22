"""
The shape every renderer consumes. Built once per shipment from
ShipmentState + SnapshotDiff + SPSDiff + exceptions - renderers never
see a raw scraped string (ARCHITECTURE.md §08).

Redesigned per a direct ask: the report needs every SPS field a data
entry associate already recognizes (sipl, container, port_eta,
location_eta, ship_to_location, sipl_status) sitting right next to
what the carrier's own tracking site says right now (carrier,
departure/arrival port, current status/location, vessel, estimated
dock date), with plain field names and no engineering jargon exposed
as the primary view - built to be pivotable into a dashboard, not just
readable top to bottom.
"""
from dataclasses import dataclass, field
from datetime import datetime

from tracking_control_tower.exceptions.models import RiskException

_SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}


@dataclass
class ShipmentReportRow:
    sipl: str
    container: str
    carrier: str

    # --- from the SPS export, unchanged (what a data entry associate
    # already has on file) ---
    sipl_status: str | None
    ship_to_location: str | None
    sps_vessel: str | None
    sps_port_eta: datetime | None
    sps_location_eta: datetime | None

    # --- from the carrier's own tracking site, right now ---
    current_status: str | None
    current_location: str | None
    departure_port: str | None
    arrival_port: str | None
    current_vessel: str | None
    estimated_dock_date: datetime | None
    previous_event: str | None
    next_expected_event: str | None

    # --- does SPS need updating - each field's old/new value is
    # already sitting side by side above (sps_vessel/current_vessel,
    # sps_port_eta/estimated_dock_date); these are just the "does it
    # differ" flags, not a re-statement of the values in text form -
    # a dashboard can filter/aggregate on a boolean, not on a sentence.
    port_eta_needs_update: bool
    vessel_needs_update: bool
    # Same combined flag MSC_INC.py computed as 'eta_or_vessel_changed'
    # (Y if either eta_changed or vessel_changed was Y) - one column to
    # filter on for "does this shipment need ANY SPS update", instead of
    # checking two columns every time.
    port_eta_or_vessel_needs_update: bool

    # --- data quality / triage ---
    risk_level: str  # "none" | "low" | "medium" | "high"
    tracking_confidence: float  # 0.0-1.0 - low it means treat the row's tracked fields with caution
    data_quality_notes: str

    exceptions: list[RiskException] = field(default_factory=list)


def risk_level_from_exceptions(exceptions) -> str:
    if not exceptions:
        return "none"
    return max((e.severity for e in exceptions), key=lambda s: _SEVERITY_RANK.get(s, 0))


@dataclass
class OtherCarrierRow:
    """
    A container whose vessel isn't MSC/Hapag-Lloyd/Maersk - no adapter
    exists yet, so there's no live tracking data to show, only what SPS
    already has on file. Kept on its own sheet rather than mixed into
    the main tracking report or silently dropped.
    """

    sipl: str
    container: str
    vessel: str | None
    sipl_status: str | None
    ship_to_location: str | None
    sps_port_eta: datetime | None
    sps_location_eta: datetime | None
