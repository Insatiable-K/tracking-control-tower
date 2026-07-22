"""
Vessel name normalization for comparison purposes.

Both carriers' raw vessel fields follow the same rough shape once you
strip the carrier prefix and trailing voyage code: "MSK-CLEMENTINE
MAERSK / 621W" (SPS) and "TORRENTE 5137" (scraped) both reduce to a bare
vessel name. This replaces MSC_INC.py's extract_after_last_hyphen()
(splits on the LAST hyphen, which breaks on multi-word vessel names
containing no hyphen at all - it's a no-op there) and HL logic.py's
re.sub(r'^.*?-', '', x) (strips up to the FIRST hyphen only, and does
nothing about the trailing voyage code, so "CLEMENTINE MAERSK / 621W"
and "CLEMENTINE MAERSK 540S" would compare as different vessels even on
the very next voyage of the same ship).
"""
import re

from tracking_control_tower.config.settings import VESSEL_PREFIXES

# Only strip a leading carrier code, not any letters-then-hyphen pattern -
# a real vessel name can itself contain a hyphen (e.g. "X-Press Carina",
# a real X-Press Feeders vessel seen in HL's history). Longest prefix
# first so "MAERSK-" doesn't get shadowed by a hypothetical shorter match.
_KNOWN_PREFIXES = sorted(VESSEL_PREFIXES, key=len, reverse=True)
_LEADING_PREFIX = re.compile(r"^(" + "|".join(_KNOWN_PREFIXES) + r")\s*-\s*")
# Voyage codes seen in real data: "621W", "MC528R", "UA536R", "AX540R" -
# an optional short letter prefix, digits, optional short letter suffix.
_TRAILING_VOYAGE_CODE = re.compile(r"\s+[A-Z]{0,3}[0-9]+[A-Z]{0,2}$")
_SLASHES = re.compile(r"\s*/\s*")
_WHITESPACE = re.compile(r"\s+")

# Real data: MSC's scraped "Vessel Info" field sometimes holds the
# container's load-state word instead of an actual vessel name (same
# root cause as the Empty/Full/Laden qualifier events.py's normalizer
# already strips from descriptions - see run_sample_report.py, which
# caught "LADEN" appearing as current_vessel and silently triggering a
# bogus SPS vessel-update recommendation). Not a real vessel; must not
# be compared as one.
_NOT_A_VESSEL = {"LADEN", "EMPTY", "FULL"}


def normalize_vessel_name(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if not text or text == "NAN" or text in _NOT_A_VESSEL:
        return None

    text = _LEADING_PREFIX.sub("", text)
    text = _SLASHES.sub(" ", text)
    text = _TRAILING_VOYAGE_CODE.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text or None


def vessels_effectively_match(sps_normalized: str | None, tracked_normalized: str | None) -> bool:
    """
    True if two already-normalized vessel names should be treated as the
    same vessel for SPS-update purposes.

    Handles one more real SPS data quirk on top of normalize_vessel_name:
    the carrier code sometimes gets mechanically glued onto the vessel
    field twice - "MSC-MSC CAPE TAINARO MC621A" normalizes to "MSC CAPE
    TAINARO", but that vessel's own tracked name has no "MSC" in it at
    all ("CAPE TAINARO"). Stripping a repeated leading word inside
    normalize_vessel_name() itself is NOT safe to do in isolation - it
    would also strip the "MSC" that's genuinely part of a real
    MSC-branded vessel's name (e.g. "MSC Flora", "MSC Ursula VI"), and
    that function only ever sees one side of the comparison at a time.
    Here, with both sides available, a mismatch can be specifically
    re-checked against "SPS name with one leading known-prefix word
    removed" before concluding the vessel actually changed.
    """
    if sps_normalized == tracked_normalized:
        return True
    if not sps_normalized or not tracked_normalized:
        return False

    first_word, _, rest = sps_normalized.partition(" ")
    if first_word in _KNOWN_PREFIXES and rest == tracked_normalized:
        return True
    return False
