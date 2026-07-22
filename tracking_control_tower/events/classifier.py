"""
Event classification engine — replaces hardcoded string equality
(MSC_INC.py's `if description == "Estimated Time of Arrival"` and
HL Tracking/parsing.py's first-word split) with taxonomy-driven matching.

Classification order (see ARCHITECTURE.md §05 / FEASIBILITY.md §08):
  1. Normalize (strip container-state qualifier, collapse whitespace).
  2. Exact / prefix match against the taxonomy phrase list.
  3. Fuzzy fallback (RapidFuzz) for near-miss wording.
  4. Unclassified - never guess, never silently drop.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

from tracking_control_tower.events.normalizer import normalize

TAXONOMY_PATH = Path(__file__).parent / "taxonomy.yaml"
FUZZY_THRESHOLD = 92.0

UNCLASSIFIED = "unclassified"


@dataclass
class ClassificationResult:
    category: str
    phase_rank: int | None
    is_projection: bool
    confidence: float
    container_state: str | None
    matched_phrase: str | None
    raw_text: str


@dataclass(frozen=True)
class _PhraseEntry:
    phrase: str
    category: str
    phase_rank: int | None
    is_projection: bool


@lru_cache(maxsize=1)
def _load_taxonomy(path: str = str(TAXONOMY_PATH)) -> tuple[_PhraseEntry, ...]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    entries: list[_PhraseEntry] = []
    for category, spec in data["categories"].items():
        phase_rank = spec.get("phase_rank")
        is_projection = bool(spec.get("is_projection", False))
        for phrase in spec["phrases"]:
            entries.append(
                _PhraseEntry(
                    phrase=phrase.lower(),
                    category=category,
                    phase_rank=phase_rank,
                    is_projection=is_projection,
                )
            )
    # Longest phrase first so a specific multi-word phrase (e.g.
    # "transshipment discharged") is tried before a shorter one that
    # could otherwise shadow it (e.g. "discharged").
    entries.sort(key=lambda e: -len(e.phrase))
    return tuple(entries)


def classify(raw_text: str) -> ClassificationResult:
    normalized = normalize(raw_text)
    text = normalized.text.lower()
    entries = _load_taxonomy()

    if not text:
        return ClassificationResult(
            category=UNCLASSIFIED, phase_rank=None, is_projection=False,
            confidence=0.0, container_state=normalized.container_state,
            matched_phrase=None, raw_text=raw_text,
        )

    for entry in entries:
        if text == entry.phrase or text.startswith(entry.phrase + " ") or text.startswith(entry.phrase):
            return ClassificationResult(
                category=entry.category, phase_rank=entry.phase_rank,
                is_projection=entry.is_projection, confidence=1.0,
                container_state=normalized.container_state,
                matched_phrase=entry.phrase, raw_text=raw_text,
            )

    phrase_list = [e.phrase for e in entries]
    match = process.extractOne(text, phrase_list, scorer=fuzz.token_sort_ratio)
    if match is not None:
        matched_phrase, score, idx = match
        if score >= FUZZY_THRESHOLD:
            entry = entries[idx]
            return ClassificationResult(
                category=entry.category, phase_rank=entry.phase_rank,
                is_projection=entry.is_projection, confidence=score / 100.0,
                container_state=normalized.container_state,
                matched_phrase=entry.phrase, raw_text=raw_text,
            )

    return ClassificationResult(
        category=UNCLASSIFIED, phase_rank=None, is_projection=False,
        confidence=0.0, container_state=normalized.container_state,
        matched_phrase=None, raw_text=raw_text,
    )
