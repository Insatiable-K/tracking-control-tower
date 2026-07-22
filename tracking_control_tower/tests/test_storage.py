"""
Tests for the storage layer: snapshot round-tripping, ordering, and the
composite (SIPL, container)-keying fix for two real findings - the
container-reuse case from test_comparison.py, and one SIPL legitimately
spanning multiple containers (found via the orchestration layer's smoke
test against real 1RAW.xlsx data) - plus the scrape cache.
"""
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from tracking_control_tower.comparison.snapshot_diff import diff_snapshots
from tracking_control_tower.events.classifier import classify
from tracking_control_tower.shipment_state.engine import infer_state
from tracking_control_tower.shipment_state.models import ClassifiedEvent, RawEvent
from tracking_control_tower.storage.scrape_cache import ScrapeCache
from tracking_control_tower.storage.snapshot_store import SnapshotStore


def _events(container: str, rows: list[tuple[str, str]]) -> list[ClassifiedEvent]:
    out = []
    for date_str, text in rows:
        raw = RawEvent(container=container, date=datetime.fromisoformat(date_str), raw_text=text)
        out.append(ClassifiedEvent(raw=raw, classification=classify(text)))
    return out


class TempDbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test.db"

    def tearDown(self):
        self._tmpdir.cleanup()


class TestSnapshotStoreRoundTrip(TempDbTestCase):
    def test_save_and_get_latest_round_trips_all_fields(self):
        rows = [
            ("2025-09-01", "Export received at CY"),
            ("2025-09-05", "Export Loaded on Vessel"),
        ]
        state = infer_state("TEMU1111111", _events("TEMU1111111", rows))

        with SnapshotStore(self.db_path) as store:
            store.save(sipl="SIPL001", container="TEMU1111111", state=state)
            fetched = store.get_latest("SIPL001", "TEMU1111111")

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.current_phase, state.current_phase)
        self.assertEqual(fetched.current_phase_rank, state.current_phase_rank)
        self.assertEqual(fetched.confidence_score, state.confidence_score)
        self.assertEqual(fetched.data_quality_issues, state.data_quality_issues)
        self.assertEqual(fetched.missing_information, state.missing_information)

    def test_unseen_sipl_returns_none(self):
        with SnapshotStore(self.db_path) as store:
            self.assertIsNone(store.get_latest("NEVER-SEEN", "NEVER0000000"))

    def test_get_latest_returns_most_recent_of_multiple_runs(self):
        rows_day1 = [("2025-09-01", "Export received at CY")]
        rows_day2 = [
            ("2025-09-01", "Export received at CY"),
            ("2025-09-05", "Export Loaded on Vessel"),
        ]
        state_day1 = infer_state("TEMU2222222", _events("TEMU2222222", rows_day1))
        state_day2 = infer_state("TEMU2222222", _events("TEMU2222222", rows_day2))

        with SnapshotStore(self.db_path) as store:
            store.save("SIPL002", "TEMU2222222", state_day1, run_at=datetime(2025, 9, 1, 20, 0))
            store.save("SIPL002", "TEMU2222222", state_day2, run_at=datetime(2025, 9, 5, 20, 0))
            latest = store.get_latest("SIPL002", "TEMU2222222")

        self.assertEqual(latest.current_phase, state_day2.current_phase)
        self.assertNotEqual(latest.current_phase, state_day1.current_phase)

    def test_get_history_returns_all_runs_in_order(self):
        with SnapshotStore(self.db_path) as store:
            for i, day in enumerate([1, 5, 10]):
                rows = [("2025-09-01", "Export received at CY")] * 1
                state = infer_state("TEMU3333333", _events("TEMU3333333", rows))
                store.save("SIPL003", "TEMU3333333", state, run_at=datetime(2025, 9, day, 12, 0))
            history = store.get_history("SIPL003", "TEMU3333333")

        self.assertEqual(len(history), 3)
        run_dates = [ts.day for ts, _ in history]
        self.assertEqual(run_dates, [1, 5, 10])


class TestCompositeKeySolvesContainerReuse(TempDbTestCase):
    """
    Real-data-derived: HLXU3511177 was reused for two unrelated shipments
    (comparison/snapshot_diff.py's docstring / test_comparison.py's
    TestContainerReuseKnownLimitation). Storage keyed by (SIPL,
    container) is the actual fix - proving that here rather than just
    asserting it in a docstring.
    """

    OLD_SHIPMENT = [
        ("2025-06-18", "Gate out empty JAIPUR"),
        ("2025-08-29", "Discharged HOUSTON, TX"),
        ("2025-09-10", "Arrival in DENVER, CO"),
    ]
    NEW_SHIPMENT = [
        ("2025-08-19", "Gate out empty JAIPUR"),
        ("2025-11-01", "Vessel arrival PORT EVERGLADES, FL"),
    ]

    def test_same_container_different_sipl_do_not_collide(self):
        old_state = infer_state("HLXU3511177", _events("HLXU3511177", self.OLD_SHIPMENT))
        new_state = infer_state("HLXU3511177", _events("HLXU3511177", self.NEW_SHIPMENT))

        with SnapshotStore(self.db_path) as store:
            store.save("SIPL-OLD-001", "HLXU3511177", old_state)
            store.save("SIPL-NEW-002", "HLXU3511177", new_state)

            fetched_old = store.get_latest("SIPL-OLD-001", "HLXU3511177")
            fetched_new = store.get_latest("SIPL-NEW-002", "HLXU3511177")

        self.assertEqual(fetched_old.current_phase, old_state.current_phase)
        self.assertEqual(fetched_new.current_phase, new_state.current_phase)
        self.assertNotEqual(fetched_old.current_phase, fetched_new.current_phase)


class TestCompositeKeySolvesMultiContainerSIPL(TempDbTestCase):
    """
    Real-data-derived: 1RAW.xlsx has SIPL 168893 spanning three distinct
    containers (MEDU3697078, MEDU2304983, MEDU6299740) - a normal
    purchase-order/consolidated-shipment pattern, not a data error.
    Storage keyed by SIPL alone would let one container's snapshot
    overwrite another's under the shared SIPL; the composite key keeps
    each container's history independent.
    """

    def test_containers_sharing_a_sipl_do_not_collide(self):
        state_a = infer_state("MEDU3697078", _events("MEDU3697078", [
            ("2025-11-01", "Export received at CY"),
        ]))
        state_b = infer_state("MEDU2304983", _events("MEDU2304983", [
            ("2025-11-01", "Export received at CY"),
            ("2025-11-05", "Export Loaded on Vessel"),
        ]))

        with SnapshotStore(self.db_path) as store:
            store.save("168893", "MEDU3697078", state_a)
            store.save("168893", "MEDU2304983", state_b)

            fetched_a = store.get_latest("168893", "MEDU3697078")
            fetched_b = store.get_latest("168893", "MEDU2304983")
            fetched_c = store.get_latest("168893", "MEDU6299740")  # third container, never saved

        self.assertEqual(fetched_a.current_phase, "Export")
        self.assertEqual(fetched_b.current_phase, "Loaded on vessel")
        self.assertIsNone(fetched_c)


class TestEndToEndRunCycle(TempDbTestCase):
    """
    Real TEMU4439276 progression (same data as
    test_comparison.TestSnapshotDiffRealProgression), wired through an
    actual save -> retrieve -> diff -> save cycle, the way a daily batch
    run would use this module.
    """

    DAY1 = [
        ("2025-06-30", "Gate out empty JEBEL ALI"),
        ("2025-07-09", "Loaded JEBEL ALI"),
        ("2025-09-12", "Vessel arrival HOUSTON, TX"),
    ]
    DAY2 = DAY1 + [
        ("2025-09-12", "Discharged HOUSTON, TX"),
        ("2025-09-18", "Departure from HOUSTON, TX"),
    ]

    def test_run_cycle_persists_and_diffs_correctly(self):
        with SnapshotStore(self.db_path) as store:
            # --- Day 1 run ---
            previous = store.get_latest("SIPL-E2E-001", "TEMU4439276")
            self.assertIsNone(previous)  # first time seeing this shipment
            day1_state = infer_state("TEMU4439276", _events("TEMU4439276", self.DAY1))
            diff1 = diff_snapshots(previous, day1_state)
            self.assertTrue(diff1.is_first_seen)
            store.save("SIPL-E2E-001", "TEMU4439276", day1_state, run_at=datetime(2025, 9, 12, 20, 0))

            # --- Day 2 run ---
            previous = store.get_latest("SIPL-E2E-001", "TEMU4439276")
            self.assertIsNotNone(previous)
            day2_state = infer_state("TEMU4439276", _events("TEMU4439276", self.DAY2))
            diff2 = diff_snapshots(previous, day2_state)
            store.save("SIPL-E2E-001", "TEMU4439276", day2_state, run_at=datetime(2025, 9, 18, 20, 0))

        self.assertFalse(diff2.is_first_seen)
        self.assertTrue(diff2.state_changed)
        self.assertEqual(day1_state.current_phase, "Arrived at port")
        self.assertEqual(day2_state.current_phase, "Destination terminal")


class TestScrapeCache(TempDbTestCase):
    def test_miss_then_put_then_hit(self):
        with ScrapeCache(self.db_path) as cache:
            self.assertIsNone(cache.get("TEMU1111111", date(2025, 9, 1), "HL"))
            cache.put("TEMU1111111", date(2025, 9, 1), "HL", payload='{"events": []}')
            self.assertEqual(cache.get("TEMU1111111", date(2025, 9, 1), "HL"), '{"events": []}')

    def test_put_overwrites_same_day_entry(self):
        with ScrapeCache(self.db_path) as cache:
            cache.put("TEMU1111111", date(2025, 9, 1), "HL", payload="first")
            cache.put("TEMU1111111", date(2025, 9, 1), "HL", payload="second")
            self.assertEqual(cache.get("TEMU1111111", date(2025, 9, 1), "HL"), "second")

    def test_different_carriers_same_container_do_not_collide(self):
        with ScrapeCache(self.db_path) as cache:
            cache.put("MSCU1234567", date(2025, 9, 1), "MSC", payload="msc-data")
            cache.put("MSCU1234567", date(2025, 9, 1), "HL", payload="hl-data")
            self.assertEqual(cache.get("MSCU1234567", date(2025, 9, 1), "MSC"), "msc-data")
            self.assertEqual(cache.get("MSCU1234567", date(2025, 9, 1), "HL"), "hl-data")


if __name__ == "__main__":
    unittest.main()
