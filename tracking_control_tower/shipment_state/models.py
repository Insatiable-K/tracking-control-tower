"""
Data model for one container's classified event history and the inferred
shipment state derived from it.
"""
from dataclasses import dataclass, field
from datetime import datetime

from tracking_control_tower.events.classifier import ClassificationResult


@dataclass
class RawEvent:
    """Carrier-agnostic shape a CarrierAdapter.parse() would return."""

    container: str
    date: datetime | None
    raw_text: str
    location: str | None = None
    vessel_info: str | None = None
    facility: str | None = None
    source: str = ""
    scraped_at: datetime | None = None


@dataclass
class ClassifiedEvent:
    raw: RawEvent
    classification: ClassificationResult

    @property
    def date(self) -> datetime | None:
        return self.raw.date

    @property
    def category(self) -> str:
        return self.classification.category

    @property
    def phase_rank(self) -> int | None:
        return self.classification.phase_rank

    @property
    def is_projection(self) -> bool:
        return self.classification.is_projection


@dataclass
class ShipmentState:
    container: str
    current_phase: str | None
    current_phase_rank: int | None
    current_location: str | None
    current_vessel: str | None
    current_eta: datetime | None
    previous_event: str | None
    previous_event_date: datetime | None
    first_event_date: datetime | None
    latest_event_date: datetime | None
    next_expected_event: str | None
    confidence_score: float
    delivery_attempt_count: int
    # Where the container was loaded onto its most recent ocean vessel,
    # and where it arrived/discharged at that vessel's destination port -
    # both derived from the event history itself (not carried on any
    # single event field), so they stay None until that milestone has
    # actually happened rather than guessing a planned route no adapter
    # currently exposes.
    departure_port: str | None = None
    arrival_port: str | None = None
    data_quality_issues: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    # Effective ranks ever reached in this history - lets a rule like
    # "rail expected but never happened" be checked without re-walking
    # the full event list (exceptions/evaluator.py needs this).
    phases_visited: frozenset[int] = field(default_factory=frozenset)
