from dataclasses import dataclass


@dataclass
class RiskException:
    """One flagged issue for one shipment - a reason code, not just a red pill."""

    rule: str
    severity: str  # "low" | "medium" | "high"
    reason: str
    container: str
    routed_to: str | None = None
