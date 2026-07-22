"""
Canonical shipment timeline (ARCHITECTURE.md §04).

Real HL data changed one design assumption from the original architecture
doc: multi-leg transshipment does NOT show up as a distinct category in
practice (HL has no "transshipment" wording at all - it just repeats
loaded -> departed -> arrived -> discharged once per leg, cycling back to
rank 2 after reaching rank 7). MSC does have explicit "Full Transshipment
Discharged/Loaded" wording, which gets its own rank-4 category. Both
patterns are real; the timeline and state engine have to tolerate a
legitimate rank *decrease* between ranks 2-7 (another leg starting) without
treating it as a contradiction - see shipment_state/engine.py.
"""
from tracking_control_tower.config.settings import RAIL_LOCATIONS

PHASE_LABELS: dict[int, str] = {
    1: "Export",
    2: "Loaded on vessel",
    3: "Departed",
    4: "Transshipment",
    5: "Ocean transit",
    6: "Arrived at port",
    7: "Discharged",
    8: "Customs",
    9: "Rail",
    10: "Destination terminal",
    11: "Delivery",
    12: "Delivered",
}

# Ranks that can legitimately recur across multiple transshipment legs
# before final arrival - a rank decrease within this band is a new leg,
# not a contradiction.
OCEAN_LEG_RANKS = {2, 3, 4, 6, 7}

MAX_RANK = max(PHASE_LABELS)


def is_rail_expected(ship_to_location: str | None) -> bool:
    if not ship_to_location:
        return False
    return ship_to_location.strip().lower() in {loc.lower() for loc in RAIL_LOCATIONS}


def label(rank: int | None) -> str | None:
    if rank is None:
        return None
    return PHASE_LABELS.get(rank)


def next_expected(current_rank: int | None, rail_expected: bool) -> str | None:
    """
    Best-guess next canonical phase after current_rank. Deliberately a
    hint, not a guarantee: for ranks in OCEAN_LEG_RANKS, the true "next"
    event could equally be another transshipment leg (back to rank 2) or
    genuine progress toward the US port - the event history alone can't
    disambiguate that without a "final leg" signal from the carrier.
    """
    if current_rank is None:
        return None
    candidate = current_rank + 1
    while candidate <= MAX_RANK:
        if candidate == 9 and not rail_expected:
            candidate += 1
            continue
        return PHASE_LABELS.get(candidate)
    return None
