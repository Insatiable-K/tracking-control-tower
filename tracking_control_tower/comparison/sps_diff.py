"""
Authoritative comparison: inferred ShipmentState vs. the SPS export's own
fields for this container (ARCHITECTURE.md §06 "Authoritative" axis) -
the direct answer to "should SPS be updated, and which fields."

Only recommends an update when the inferred value is both present and
meaningfully different (voyage-stripped vessel name, day-level ETA) -
never overwrites SPS with a blank or low-confidence inference.
"""
from datetime import datetime

from tracking_control_tower.comparison.models import SPSDiff, SPSFieldRecommendation
from tracking_control_tower.shipment_state.models import ShipmentState
from tracking_control_tower.utils.dates import same_day
from tracking_control_tower.utils.vessel_names import normalize_vessel_name, vessels_effectively_match

MIN_CONFIDENCE_TO_RECOMMEND = 0.5


def diff_against_sps(
    state: ShipmentState,
    sps_vessel: str | None,
    sps_port_eta: datetime | None,
) -> SPSDiff:
    recommendations: list[SPSFieldRecommendation] = []

    if state.confidence_score < MIN_CONFIDENCE_TO_RECOMMEND:
        return SPSDiff(container=state.container, recommendations=recommendations)

    inferred_vessel = normalize_vessel_name(state.current_vessel)
    sps_vessel_norm = normalize_vessel_name(sps_vessel)
    if inferred_vessel and not vessels_effectively_match(sps_vessel_norm, inferred_vessel):
        sps_display = repr(sps_vessel_norm) if sps_vessel_norm else "blank"
        recommendations.append(
            SPSFieldRecommendation(
                field="vessel",
                current_sps_value=sps_vessel,
                recommended_value=state.current_vessel,
                reason=(
                    f"Latest tracked vessel ({inferred_vessel!r}) differs from SPS ({sps_display})"
                ),
            )
        )

    if state.current_eta is not None and not same_day(state.current_eta, sps_port_eta):
        recommendations.append(
            SPSFieldRecommendation(
                field="port_eta",
                current_sps_value=sps_port_eta,
                recommended_value=state.current_eta,
                reason="Tracked ETA differs from SPS port_eta",
            )
        )

    return SPSDiff(container=state.container, recommendations=recommendations)
