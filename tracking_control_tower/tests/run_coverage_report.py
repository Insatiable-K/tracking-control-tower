"""
Real-world coverage report: run the classifier against every distinct
event description that actually appears in the historical archives
(OLD/msc_scraped_results_*.xlsx and HL Tracking/old/HL_Parsed_*.xlsx),
weighted by how often each one occurred.

This is deliberately separate from tests/test_classifier.py (curated,
fast, CI-safe unit tests) - it's a one-off validation script proving the
taxonomy holds up at real scale, per FEASIBILITY.md Step 3's exit
criterion: "reprocessing historical scraped data through the new
classifier produces zero unclassified events on already-seen wordings."

Run: python -m tracking_control_tower.tests.run_coverage_report
"""
import collections
import glob
from pathlib import Path

import pandas as pd

from tracking_control_tower.events.classifier import UNCLASSIFIED, classify

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _msc_vocabulary() -> collections.Counter:
    counter: collections.Counter = collections.Counter()
    files = sorted(glob.glob(str(PROJECT_ROOT / "OLD" / "msc_scraped_results_*.xlsx")))
    for f in files:
        try:
            d = pd.read_excel(f, sheet_name="Clean Data")
        except Exception:
            continue
        if "description" in d.columns:
            for v in d["description"].dropna():
                counter[str(v).strip()] += 1
    return counter


def _hl_vocabulary() -> collections.Counter:
    """
    Classify from the raw 'History Entry' text, not the old parser's
    'Status' column - Status is already-corrupted output of the buggy
    first-word-split parser (see FEASIBILITY.md §02), so testing against
    it would just re-measure the old bug instead of proving it's fixed.
    """
    counter: collections.Counter = collections.Counter()
    files = sorted(glob.glob(str(PROJECT_ROOT / "HL Tracking" / "old" / "HL_Parsed_*.xlsx")))
    for f in files:
        try:
            d = pd.read_excel(f)
        except Exception:
            continue
        if "History Entry" in d.columns:
            for v in d["History Entry"].dropna():
                counter[str(v).strip()] += 1
    return counter


def _report(carrier: str, vocabulary: collections.Counter) -> None:
    total = sum(vocabulary.values())
    if total == 0:
        print(f"\n=== {carrier}: no historical data found, skipping ===")
        return

    category_counts: collections.Counter = collections.Counter()
    unclassified_items: list[tuple[str, int]] = []

    for text, count in vocabulary.items():
        result = classify(text)
        category_counts[result.category] += count
        if result.category == UNCLASSIFIED:
            unclassified_items.append((text, count))

    classified = total - category_counts[UNCLASSIFIED]
    print(f"\n=== {carrier}: {total:,} historical event rows, {len(vocabulary)} distinct phrasings ===")
    print(f"  Classified:   {classified:,} rows ({100 * classified / total:.1f}%)")
    print(f"  Unclassified: {category_counts[UNCLASSIFIED]:,} rows ({100 * category_counts[UNCLASSIFIED] / total:.1f}%)")
    print(f"\n  Category breakdown (by row count):")
    for category, count in category_counts.most_common():
        if category == UNCLASSIFIED:
            continue
        print(f"    {count:8,d}  {category}")

    if unclassified_items:
        unclassified_items.sort(key=lambda x: -x[1])
        print(f"\n  Unclassified phrasings ({len(unclassified_items)} distinct), by frequency:")
        for text, count in unclassified_items[:25]:
            print(f"    {count:6d}  {text!r}")
        if len(unclassified_items) > 25:
            print(f"    ... and {len(unclassified_items) - 25} more distinct unclassified phrasings")


def main() -> None:
    _report("MSC", _msc_vocabulary())
    _report("Hapag-Lloyd (legacy endpoint, historical)", _hl_vocabulary())


if __name__ == "__main__":
    main()
