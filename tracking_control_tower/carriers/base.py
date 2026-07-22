"""
The narrow, carrier-agnostic contract (ARCHITECTURE.md §06/§09).
Everything carrier-specific stays behind search()/parse(); the domain
core (events/, shipment_state/, comparison/, exceptions/, reporting/)
only ever sees RawEvent objects and cannot tell which carrier produced
them.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from tracking_control_tower.shipment_state.models import RawEvent


@dataclass
class RawPage:
    """
    What search() hands to parse() - still carrier-specific shape (raw
    scraped text), not yet the canonical RawEvent list. error is set
    instead of raising, so a batch run can record a per-container
    failure and continue (MSC_INC.py's original try/except pattern).
    """

    container: str
    text: str = ""
    pod_eta_text: str | None = None
    scraped_at: datetime = field(default_factory=datetime.now)
    error: str | None = None


@dataclass
class StealthProfile:
    headless: bool = False
    proxy: str | None = None


class CarrierAdapter(ABC):
    vessel_prefixes: list[str]
    tracking_url: str
    stealth_profile: StealthProfile
    # Human-readable carrier name for reports (e.g. "Hapag-Lloyd", not
    # the internal vessel-prefix code "HL") - a non-technical reader of
    # the Excel output should never need to know the prefix scheme.
    carrier_name: str
    # None for MSC and Hapag-Lloyd on current evidence (FEASIBILITY.md
    # §06) - a real browser session clears both without a solver.
    # Maersk's hCaptcha fallback, if the Step 0 trial shows it's needed,
    # goes here later.
    challenge_handler: object | None = None

    @abstractmethod
    def search(self, container: str) -> RawPage: ...

    @abstractmethod
    def parse(self, raw: RawPage) -> list[RawEvent]: ...

    def close(self) -> None:
        """Override if the adapter holds a browser session to tear down."""

    def __enter__(self) -> "CarrierAdapter":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
