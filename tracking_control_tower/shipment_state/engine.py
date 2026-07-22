"""
Shipment state engine (ARCHITECTURE.md §04, extended per FEASIBILITY.md §07).

Infers current_phase from a container's FULL classified event history,
never by picking one "best" row. Two design points came directly out of
testing against real data rather than the original architecture sketch:

1. current_phase = the chronologically LATEST confirmed event's phase,
   not the highest rank ever seen. Real HL histories cycle
   loaded -> departed -> arrived -> discharged once per transshipment
   leg (rank 2,3,6,7,2,3,6,7,...) with no distinct "transshipment"
   wording at all - "max rank ever" would freeze at 7 after the first
   leg and misreport a container that's actually mid-way through a
   second leg. "Latest event" handles this correctly for free.

2. Contradiction detection only fires once a shipment has left the
   ocean-leg cycle (reached rank 8+: customs/rail/destination/delivery).
   Within ranks 2-7, a rank decrease is a new transshipment leg, not a
   data error. After rank 8+, a decrease genuinely is a contradiction -
   you don't go back to "loaded on vessel" after being on rail.

3. "inland_leg_arrival"/"inland_leg_departure" (truck/rail moves by
   text alone) are genuinely ambiguous: the same wording covers
   pre-carriage moves before export (JAIPUR, MUNDRA - rank 1) and the
   final-mile move after the LAST discharge (NORFOLK -> destination -
   much later in the journey). A first version re-ranked these to
   rank 10 as soon as ANY "discharged" event had been seen - which
   over-fired on real multi-leg transshipment data (HLXU1294961): an
   inland move at COLOMBO between two vessel legs got mistaken for a
   final-mile move because it followed the first leg's discharge, even
   though the container was reloaded onto a second vessel right after.
   Fixed by only treating a discharge as "final" if no later
   loaded_on_vessel event follows it - only inland-leg events after
   that specific discharge get promoted to rank 10.

4. "export_received" has the same ambiguity for one specific phrase:
   "received at CY" is used both for the dominant case (a container
   picked up empty for export stuffing, rank 1) and, rarely, for an
   empty container returned to the depot after delivery (real example:
   MSNU2265734's last event, "Empty received at CY", dated after
   "Import to consignee"). Resolved the same way: export_received
   events after the shipment's first delivered_to_consignee event are
   treated as post-delivery administrative closure (rank 12), not a
   regression back to "Export".

5. "discharged" gets reused a third time on HL's current SPA: real
   FCIU4746425 history has "Discharged" twice - once for the actual
   vessel discharge at Norfolk (the real rank-7 anchor), and again
   later for a rail-ramp unload at Chicago. Without special handling,
   the second "Discharged" would flag a false contradiction (a rank-7
   event after the shipment had already reached rank 10 via the
   promoted post-discharge inland moves). Any "discharged" event after
   the final anchor is promoted the same way inland-leg events are -
   it's further post-discharge activity, not a second vessel discharge.
"""
from tracking_control_tower.events.classifier import UNCLASSIFIED
from tracking_control_tower.shipment_state.models import ClassifiedEvent, ShipmentState
from tracking_control_tower.shipment_state.timeline import (
    OCEAN_LEG_RANKS,
    is_rail_expected,
    label,
    next_expected,
)

DELIVERY_ZONE_RANKS = {10, 11}
# "discharged" is included here too: HL's current SPA reuses the word
# for a later rail-ramp unload, not just the original vessel discharge
# (point 5 above) - only the FIRST (anchor) occurrence keeps rank 7.
AMBIGUOUS_INLAND_CATEGORIES = {"inland_leg_arrival", "inland_leg_departure", "discharged"}
POST_DISCHARGE_INLAND_RANK = 10
POST_DELIVERY_RETURN_RANK = 12


def _resolve_effective_ranks(confirmed: list[ClassifiedEvent]) -> list[int]:
    """
    confirmed must already be sorted chronologically.

    Anchors on the last "arrived_at_port" OR "discharged" event (rank 6
    or 7) with no later "loaded_on_vessel" - not "discharged" alone.
    Real data caught the narrower version failing: one scrape of a real
    container's final Houston leg had "Vessel arrived HOUSTON" but no
    "Discharged HOUSTON" line at all (a genuine data gap, not a bug),
    so the discharged-only check never found a final anchor and a
    container already moving inland toward Denver by rail got
    mislabeled current_phase="Export". Using rank 6-or-7 as the anchor
    is robust to a missing discharge line for the same underlying
    reason arrived_at_port already has to tolerate a missing one.
    """
    ocean_arrival_positions = [i for i, e in enumerate(confirmed) if e.phase_rank in (6, 7)]
    loaded_positions = [i for i, e in enumerate(confirmed) if e.category == "loaded_on_vessel"]

    final_discharge_position = None
    for i in reversed(ocean_arrival_positions):
        if not any(j > i for j in loaded_positions):
            final_discharge_position = i
            break

    delivered_positions = [i for i, e in enumerate(confirmed) if e.category == "delivered_to_consignee"]
    first_delivered_position = delivered_positions[0] if delivered_positions else None

    effective_ranks: list[int] = []
    for i, event in enumerate(confirmed):
        if (
            event.category in AMBIGUOUS_INLAND_CATEGORIES
            and final_discharge_position is not None
            and i > final_discharge_position
        ):
            effective_ranks.append(POST_DISCHARGE_INLAND_RANK)
        elif (
            event.category == "export_received"
            and first_delivered_position is not None
            and i > first_delivered_position
        ):
            effective_ranks.append(POST_DELIVERY_RETURN_RANK)
        else:
            effective_ranks.append(event.phase_rank)
    return effective_ranks


def infer_state(
    container: str,
    events: list[ClassifiedEvent],
    ship_to_location: str | None = None,
) -> ShipmentState:
    data_quality_issues: list[str] = []
    missing_information: list[str] = []

    undated = [e for e in events if e.date is None]
    if undated:
        data_quality_issues.append(f"{len(undated)} event(s) missing a date and excluded from ordering")

    unclassified = [e for e in events if e.category == UNCLASSIFIED]
    if unclassified:
        data_quality_issues.append(
            f"{len(unclassified)} of {len(events)} event(s) did not classify (unclassified)"
        )

    dated = [e for e in events if e.date is not None]
    # Secondary sort key: MSC's scraped dates carry no time-of-day, so
    # same-day events tie on date alone (real example: "Full Available
    # for Delivery" and "Import to consignee" both dated 2025-12-29,
    # with the delivery-attempt event appearing second in raw scrape
    # order despite logically preceding it). Falling back to phase_rank
    # reconstructs the intended order without needing finer timestamps.
    confirmed = sorted(
        (e for e in dated if e.phase_rank is not None and not e.is_projection),
        key=lambda e: (e.date, e.phase_rank),
    )
    projections = [e for e in dated if e.is_projection]

    if not confirmed:
        missing_information.append("no classifiable, dated milestone events found for this container")
        return ShipmentState(
            container=container, current_phase=None, current_phase_rank=None,
            current_location=None, current_vessel=None, current_eta=None,
            previous_event=None, previous_event_date=None,
            first_event_date=None, latest_event_date=None, next_expected_event=None,
            confidence_score=0.0, delivery_attempt_count=0,
            data_quality_issues=data_quality_issues, missing_information=missing_information,
        )

    effective_ranks = _resolve_effective_ranks(confirmed)

    # --- contradiction detection: only meaningful once rank >= 8 is reached ---
    max_rank_at_or_above_8: int | None = None
    for event, eff_rank in zip(confirmed, effective_ranks):
        if max_rank_at_or_above_8 is not None and eff_rank < max_rank_at_or_above_8:
            data_quality_issues.append(
                f"contradiction: {event.category!r} (effective rank {eff_rank}) on "
                f"{event.date:%Y-%m-%d} occurs after the shipment had already reached "
                f"rank {max_rank_at_or_above_8}"
            )
        elif eff_rank >= 8:
            max_rank_at_or_above_8 = max(max_rank_at_or_above_8 or 0, eff_rank)

    # --- current / previous event ---
    latest, latest_rank = confirmed[-1], effective_ranks[-1]
    previous, previous_rank = (confirmed[-2], effective_ranks[-2]) if len(confirmed) >= 2 else (None, None)

    # --- current ETA: most recently scraped estimated_arrival projection ---
    eta_events = [e for e in projections if e.category == "estimated_arrival"]
    current_eta = None
    if eta_events:
        eta_events.sort(key=lambda e: (e.raw.scraped_at or e.date, e.date))
        current_eta = eta_events[-1].date

    delivery_attempt_count = sum(1 for r in effective_ranks if r in DELIVERY_ZONE_RANKS)

    rail_expected = is_rail_expected(ship_to_location)
    if ship_to_location is None:
        missing_information.append("no ship_to_location provided; rail-expectation unknown")

    # --- confidence: average classifier confidence, penalized for gaps/contradictions ---
    scored = [e.classification.confidence for e in events if e.category != UNCLASSIFIED]
    avg_confidence = sum(scored) / len(scored) if scored else 0.0
    penalty = 0.0
    if unclassified:
        penalty += 0.3 * (len(unclassified) / len(events))
    contradiction_count = sum(1 for issue in data_quality_issues if issue.startswith("contradiction"))
    if contradiction_count:
        penalty += 0.5
    confidence_score = max(0.0, min(1.0, avg_confidence - penalty))

    next_hint = next_expected(latest_rank, rail_expected)
    if latest_rank in OCEAN_LEG_RANKS:
        next_hint = f"{next_hint} (or another transshipment leg — ambiguous from event history alone)"

    # Departure/arrival port: the LAST (most recent) loaded_on_vessel
    # event's location and the LAST rank-6/7 event's location - "most
    # recent" rather than "first ever" so a multi-leg transshipment
    # reports the current/final leg's ports, not the very first origin
    # port from a leg that's already behind it. Stays None until that
    # milestone has actually happened, same as current_eta does for a
    # container with no estimated_arrival projection yet.
    loaded_events = [e for e in confirmed if e.category == "loaded_on_vessel"]
    departure_port = loaded_events[-1].raw.location if loaded_events else None

    ocean_arrival_events = [e for e in confirmed if e.phase_rank in (6, 7)]
    arrival_port = ocean_arrival_events[-1].raw.location if ocean_arrival_events else None

    return ShipmentState(
        container=container,
        current_phase=label(latest_rank),
        current_phase_rank=latest_rank,
        current_location=latest.raw.location,
        current_vessel=latest.raw.vessel_info,
        current_eta=current_eta,
        previous_event=label(previous_rank) if previous else None,
        previous_event_date=previous.date if previous else None,
        first_event_date=confirmed[0].date,
        latest_event_date=latest.date,
        next_expected_event=next_hint,
        confidence_score=round(confidence_score, 3),
        delivery_attempt_count=delivery_attempt_count,
        departure_port=departure_port,
        arrival_port=arrival_port,
        data_quality_issues=data_quality_issues,
        missing_information=missing_information,
        phases_visited=frozenset(effective_ranks),
    )
