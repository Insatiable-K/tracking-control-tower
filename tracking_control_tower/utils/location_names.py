"""
Location/port name normalization for dashboard-safe grouping.

Real data (the first production Tracking_Report_*.xlsx) shows at least
three incompatible shapes for the same real port, confirmed as actual
duplicate categories in the same report:
  - "City, CC" (MSC-style country code): "Houston, US", "Genoa, IT"
  - "CITY, ST" (US state code, no country marker): "HOUSTON, TX", "NORFOLK, VA"
  - "CITY / TERMINAL NAME" (HL/Maersk-style, ALL CAPS): "JAIPUR / JAIPUR RAIL TERMINAL"
  - a bare city name with no separator at all: "GENOA", "NHAVA SHEVA"

Without normalizing, "Houston, US" and "HOUSTON, TX" count as two
different arrival ports in any chart or pivot. This deliberately does
NOT try to resolve the region code (state vs. country is genuinely
ambiguous in this data - "PA" means Panama here, not Pennsylvania,
confirmed by "Rodman, PA"/"Colon, PA"/"Cristobal, PA" all being real
Panama Canal ports) - it only extracts and title-cases the city/place
name, which is the part that's actually duplicated across formats. The
original raw string stays intact everywhere else (the Excel report,
ShipmentState) - this is a grouping key for analysis, not a
replacement for the carrier's own text.
"""
import re

_WHITESPACE = re.compile(r"\s+")


def normalize_location(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in ("nan", "none"):
        return None

    # Slash-separated (HL/Maersk terminal listings): the place name
    # comes first, the terminal/facility name after.
    text = text.split("/")[0].strip()
    # Comma-separated (MSC-style, and some Maersk US ports): the city
    # comes first, the region code (country or state) second - dropped
    # here, not resolved, per the module docstring.
    text = text.split(",")[0].strip()

    text = _WHITESPACE.sub(" ", text)
    return text.title() if text else None
