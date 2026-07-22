"""
Text normalization for raw carrier event descriptions.

Real historical data from both carriers shows the same pattern: many event
descriptions are prefixed with a container-load-state qualifier -
"Empty Gate out", "Full Transshipment Discharged", "Empty Arrival in X" -
where the qualifier (empty/full/laden) describes the container's cargo
state, not the event itself. HL's old parser treated "Empty Arrival in
RIVOLI VERONESE" as a single unrecognized token and mis-split it into
status="Empty", place="Arrival in RIVOLI VERONESE" (see FEASIBILITY.md
§02/§07). Splitting the qualifier off before classification fixes that
class of bug structurally rather than by special-casing one phrase.
"""
import re
from dataclasses import dataclass

_CONTAINER_STATE_PREFIX = re.compile(r"^(empty|full|laden)\s+", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


@dataclass
class NormalizedEvent:
    container_state: str | None
    text: str
    raw: str


def normalize(raw_text: str) -> NormalizedEvent:
    text = (raw_text or "").strip()
    text = _WHITESPACE.sub(" ", text)

    container_state = None
    match = _CONTAINER_STATE_PREFIX.match(text)
    if match:
        container_state = match.group(1).lower()
        text = text[match.end():].strip()

    return NormalizedEvent(container_state=container_state, text=text, raw=raw_text)
