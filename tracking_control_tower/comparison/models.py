from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldChange:
    field: str
    old_value: Any
    new_value: Any


@dataclass
class SnapshotDiff:
    """This run's state vs. the last persisted snapshot for the same container."""

    container: str
    is_first_seen: bool
    state_changed: bool
    vessel_changed: bool
    eta_changed: bool
    likely_new_cycle: bool = False
    changes: list[FieldChange] = field(default_factory=list)


@dataclass
class SPSFieldRecommendation:
    field: str
    current_sps_value: Any
    recommended_value: Any
    reason: str


@dataclass
class SPSDiff:
    """Inferred shipment state vs. the SPS export's own fields for this container."""

    container: str
    recommendations: list[SPSFieldRecommendation] = field(default_factory=list)

    @property
    def should_update(self) -> bool:
        return len(self.recommendations) > 0
