"""Assembles one ShipmentReportRow from a shipment's engine outputs."""
from tracking_control_tower.comparison.models import SPSDiff
from tracking_control_tower.exceptions.models import RiskException
from tracking_control_tower.orchestration.worklist import WorkItem
from tracking_control_tower.reporting.models import ShipmentReportRow, risk_level_from_exceptions
from tracking_control_tower.shipment_state.models import ShipmentState
from tracking_control_tower.utils.vessel_names import normalize_vessel_name


def build_report_row(
    item: WorkItem,
    carrier_name: str,
    state: ShipmentState,
    sps_diff: SPSDiff,
    exceptions: list[RiskException],
) -> ShipmentReportRow:
    recommended_fields = {r.field for r in sps_diff.recommendations}
    port_eta_needs_update = "port_eta" in recommended_fields
    vessel_needs_update = "vessel" in recommended_fields

    return ShipmentReportRow(
        sipl=item.sipl,
        container=state.container,
        carrier=carrier_name,
        sipl_status=item.sipl_status,
        ship_to_location=item.ship_to_location,
        # normalize_vessel_name() strips the voyage-code suffix (not
        # meaningful to a business reader) and turns a container-state
        # marker like "LADEN" (MSC's scraped vessel field sometimes
        # holds this instead of an actual vessel name - see
        # utils/vessel_names.py) into a blank rather than displaying it
        # as if it were a real ship name. Applied to both sps_vessel and
        # current_vessel so they're a fair, directly comparable pair in
        # the report - comparison logic elsewhere (sps_diff.py,
        # exceptions/evaluator.py) already normalizes independently for
        # its own purposes; this only affects what a human reader sees.
        sps_vessel=normalize_vessel_name(item.vessel),
        sps_port_eta=item.port_eta,
        sps_location_eta=item.location_eta,
        current_status=state.current_phase,
        current_location=state.current_location,
        departure_port=state.departure_port,
        arrival_port=state.arrival_port,
        current_vessel=normalize_vessel_name(state.current_vessel),
        estimated_dock_date=state.current_eta,
        previous_event=state.previous_event,
        next_expected_event=state.next_expected_event,
        port_eta_needs_update=port_eta_needs_update,
        vessel_needs_update=vessel_needs_update,
        port_eta_or_vessel_needs_update=port_eta_needs_update or vessel_needs_update,
        risk_level=risk_level_from_exceptions(exceptions),
        tracking_confidence=state.confidence_score,
        data_quality_notes="; ".join(state.data_quality_issues),
        exceptions=exceptions,
    )
