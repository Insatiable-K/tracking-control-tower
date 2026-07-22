"""
Routes a vessel name to the CarrierAdapter that owns its prefix -
replaces MSC_INC.py's hardcoded `prefixes` list with a per-adapter
declaration (ARCHITECTURE.md §09). Adding a carrier means adding its
adapter class here, nothing else.
"""
from tracking_control_tower.carriers.base import CarrierAdapter
from tracking_control_tower.carriers.hl import HLAdapter
from tracking_control_tower.carriers.maersk import MaerskAdapter
from tracking_control_tower.carriers.msc import MSCAdapter

_REGISTERED_ADAPTERS: list[type[CarrierAdapter]] = [MSCAdapter, HLAdapter, MaerskAdapter]


def adapter_for_vessel(vessel: str | None) -> type[CarrierAdapter] | None:
    if not vessel:
        return None
    vessel = vessel.strip().upper()
    for adapter_cls in _REGISTERED_ADAPTERS:
        for prefix in adapter_cls.vessel_prefixes:
            if vessel.startswith(prefix):
                return adapter_cls
    return None


def carrier_name_for_vessel(vessel: str | None) -> str | None:
    """Human-readable carrier name for report display - None for any
    vessel prefix without a registered adapter (routed to the "Other
    Carriers" sheet instead of the main tracking report)."""
    adapter_cls = adapter_for_vessel(vessel)
    return adapter_cls.carrier_name if adapter_cls else None
