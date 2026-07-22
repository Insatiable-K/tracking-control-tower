"""
Exception engine (ARCHITECTURE.md §07 / FEASIBILITY.md §07).

Rules read ShipmentState + the comparison diff - never raw scrape text -
so "stalled" or "vessel swap" mean the same thing for every carrier
without carrier-specific code. Every exception carries the rule name and
a specific reason back to whatever raised it, not just a severity level.
"""
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import yaml

from tracking_control_tower.comparison.models import SnapshotDiff
from tracking_control_tower.exceptions.models import RiskException
from tracking_control_tower.shipment_state.models import ShipmentState
from tracking_control_tower.shipment_state.timeline import is_rail_expected

RULES_PATH = Path(__file__).parent / "rules.yaml"
ROUTING_PATH = Path(__file__).parents[1] / "config" / "exception_routing.yaml"

DISCHARGED_RANK = 7
RAIL_RANK = 9
DELIVERED_RANK = 12
VESSEL_SWAP_MIN_RANK = 5  # ocean transit onward - a vessel change before this is routine


@lru_cache(maxsize=1)
def _load_rules() -> dict:
    with open(RULES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def _load_routing() -> dict:
    with open(ROUTING_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _route(rule: str, severity: str, reason: str, container: str) -> RiskException:
    return RiskException(
        rule=rule, severity=severity, reason=reason, container=container,
        routed_to=_load_routing().get(rule),
    )


def evaluate_exceptions(
    state: ShipmentState,
    *,
    snapshot_diff: SnapshotDiff | None = None,
    ship_to_location: str | None = None,
    container_not_found: bool = False,
    as_of: datetime | None = None,
) -> list[RiskException]:
    if container_not_found:
        return [_route(
            "container_not_found", "high",
            "Carrier adapter returned no tracking history at all", state.container,
        )]

    as_of = as_of or datetime.now()
    rules = _load_rules()
    exceptions: list[RiskException] = []

    for issue in state.data_quality_issues:
        if issue.startswith("contradiction"):
            exceptions.append(_route("contradiction_detected", "high", issue, state.container))
        elif "did not classify" in issue:
            exceptions.append(_route("unclassified_events_present", "low", issue, state.container))

    if snapshot_diff is not None and snapshot_diff.vessel_changed and not snapshot_diff.likely_new_cycle:
        if state.current_phase_rank is not None and state.current_phase_rank >= VESSEL_SWAP_MIN_RANK:
            change = next((c for c in snapshot_diff.changes if c.field == "current_vessel"), None)
            reason = (
                f"Vessel changed from {change.old_value!r} to {change.new_value!r} "
                f"while already at phase {state.current_phase!r}" if change else
                "Vessel changed after the shipment had already reached ocean transit or later"
            )
            exceptions.append(_route("vessel_swap_near_arrival", "high", reason, state.container))

    if (
        is_rail_expected(ship_to_location)
        and DISCHARGED_RANK in state.phases_visited
        and RAIL_RANK not in state.phases_visited
        and state.latest_event_date is not None
        and (as_of - state.latest_event_date).days >= rules["rail_missing_grace_days"]
    ):
        days = (as_of - state.latest_event_date).days
        exceptions.append(_route(
            "rail_expected_missing", "medium",
            f"Discharged and ship-to location is rail-served, but no rail event seen "
            f"{days} days after the last known activity", state.container,
        ))

    if (
        state.current_phase_rank is not None
        and state.current_phase_rank < DELIVERED_RANK
        and state.latest_event_date is not None
        and (as_of - state.latest_event_date).days >= rules["stalled_days"]
    ):
        days = (as_of - state.latest_event_date).days
        exceptions.append(_route(
            "stalled", "medium",
            f"No phase advance for {days} days (currently {state.current_phase!r})", state.container,
        ))

    return exceptions
