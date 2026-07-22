"""
Tests for the orchestration layer. Uses fake adapters that subclass the
real MSCAdapter/HLAdapter and override only search() to return canned
RawPage data - parse() is the real, already-validated logic, and no
live browser is ever launched. Canned pages reuse real captured fixture
text from test_msc_adapter.py / test_hl_adapter.py.
"""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from tracking_control_tower.carriers.base import RawPage
from tracking_control_tower.carriers.hl import HLAdapter
from tracking_control_tower.carriers.msc import MSCAdapter
from tracking_control_tower.orchestration.checkpoint import Checkpoint
from tracking_control_tower.orchestration.run_daily import run_daily_batch
from tracking_control_tower.storage.snapshot_store import SnapshotStore
from tracking_control_tower.tests.test_hl_adapter import LIVE_CAPTURED_FCIU4746425
from tracking_control_tower.tests.test_msc_adapter import LIVE_CAPTURED_RAW_TEXT as MSC_LIVE_TEXT


def _fake_adapter(base_cls, canned: dict[str, RawPage]):
    class _Fake(base_cls):
        def __init__(self, headless: bool = False):
            super().__init__(headless=headless)
            self.searched_containers: list[str] = []

        def search(self, container: str) -> RawPage:
            self.searched_containers.append(container)
            return canned.get(container, RawPage(container=container, error=f"no fixture for {container}"))

        def close(self) -> None:
            pass  # no real driver to tear down

    return _Fake


MSC_PAGE = RawPage(container="MEDU5655981", text=MSC_LIVE_TEXT, pod_eta_text="13/08/2026")
HL_PAGE = RawPage(container="FCIU4746425", text=LIVE_CAPTURED_FCIU4746425)


def _crashing_adapter(base_cls):
    """search() raises instead of returning RawPage(error=...) - the
    exact shape of the real bug: an uncaught exception (a browser
    launch failure with nowhere to land) escaping the adapter entirely,
    which used to crash the whole run_daily_batch call and lose any
    other carrier's already-collected results."""
    class _Crashing(base_cls):
        def __init__(self, headless: bool = False):
            super().__init__(headless=headless)

        def search(self, container: str) -> RawPage:
            raise RuntimeError("simulated browser launch failure")

        def close(self) -> None:
            pass

    return _Crashing


def _flaky_adapter(base_cls, canned: dict[str, RawPage], fail_once_for: set[str]):
    """Errors on the FIRST search() call for any container in
    fail_once_for, succeeds on every call after that - simulates the
    transient failure the end-of-session retry exists to recover from."""
    class _Flaky(base_cls):
        def __init__(self, headless: bool = False):
            super().__init__(headless=headless)
            self._attempts: dict[str, int] = {}

        def search(self, container: str) -> RawPage:
            attempt = self._attempts.get(container, 0) + 1
            self._attempts[container] = attempt
            if container in fail_once_for and attempt == 1:
                return RawPage(container=container, error="transient failure")
            return canned.get(container, RawPage(container=container, error=f"no fixture for {container}"))

        def close(self) -> None:
            pass

    return _Flaky


def _make_raw_export(path: Path, rows: list[dict]) -> None:
    """Build a minimal 1RAW.xlsx-shaped file with the 16 expected columns."""
    columns = [
        "sipl", "supplier", "port_eta", "rail_eta", "location_eta",
        "ship_to_location", "purchase_location", "container", "vessel",
        "lfd", "sipl_status", "status", "initiated_on", "eta_date",
        "fr_forwarder", "departure_port",
    ]
    df = pd.DataFrame([{c: r.get(c) for c in columns} for r in rows], columns=columns)
    df.to_excel(path, sheet_name="Sheet 1", index=False)


class OrchestrationTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.raw_export = self.tmp_path / "1RAW.xlsx"
        self.output_path = self.tmp_path / "report.xlsx"
        self.snapshot_db = self.tmp_path / "snapshots.db"
        self.checkpoint_db = self.tmp_path / "checkpoint.db"

    def tearDown(self):
        self._tmpdir.cleanup()


class TestMultiCarrierGrouping(OrchestrationTestCase):
    def test_each_carrier_only_receives_its_own_containers(self):
        _make_raw_export(self.raw_export, [
            {"sipl": "155259", "container": "MEDU5655981", "vessel": "MSC-CAPE TAINARO 545A",
             "ship_to_location": "Houston", "sipl_status": "Active"},
            {"sipl": "166028", "container": "FCIU4746425", "vessel": "HL-CLEMENTINE MAERSK",
             "ship_to_location": "Houston", "sipl_status": "Active"},
        ])

        FakeMSC = _fake_adapter(MSCAdapter, {"MEDU5655981": MSC_PAGE})
        FakeHL = _fake_adapter(HLAdapter, {"FCIU4746425": HL_PAGE})

        def route(vessel):
            if vessel and vessel.upper().startswith("MSC"):
                return FakeMSC
            if vessel and vessel.upper().startswith("HL"):
                return FakeHL
            return None

        rows, stats, _ = run_daily_batch(
            str(self.raw_export), str(self.output_path), str(self.snapshot_db), str(self.checkpoint_db),
            run_id="test-run", as_of=datetime(2026, 7, 13), route_vessel=route,
        )

        self.assertEqual(stats["processed"], 2)
        self.assertEqual({r.sipl for r in rows}, {"155259", "166028"})
        self.assertTrue(self.output_path.exists())


class TestChangeAwareScheduling(OrchestrationTestCase):
    def test_delivered_shipment_is_skipped_without_a_search_call(self):
        _make_raw_export(self.raw_export, [
            {"sipl": "155259", "container": "MEDU5655981", "vessel": "MSC-CAPE TAINARO 545A",
             "ship_to_location": "Houston", "sipl_status": "Active"},
        ])
        FakeMSC = _fake_adapter(MSCAdapter, {"MEDU5655981": MSC_PAGE})

        # Pre-seed a Delivered (rank 12) snapshot as if a prior run already resolved this shipment.
        from tracking_control_tower.shipment_state.models import ShipmentState
        delivered_state = ShipmentState(
            container="MEDU5655981", current_phase="Delivered", current_phase_rank=12,
            current_location=None, current_vessel=None, current_eta=None,
            previous_event=None, previous_event_date=None,
            first_event_date=datetime(2026, 1, 1), latest_event_date=datetime(2026, 1, 5),
            next_expected_event=None, confidence_score=1.0, delivery_attempt_count=1,
        )
        with SnapshotStore(self.snapshot_db) as store:
            store.save("155259", "MEDU5655981", delivered_state, run_at=datetime(2026, 6, 1))

        rows, stats, _ = run_daily_batch(
            str(self.raw_export), str(self.output_path), str(self.snapshot_db), str(self.checkpoint_db),
            run_id="test-run", as_of=datetime(2026, 7, 13), route_vessel=lambda v: FakeMSC,
        )

        self.assertEqual(stats["skipped_delivered"], 1)
        self.assertEqual(stats["processed"], 0)
        self.assertEqual(rows, [])


class TestCheckpointResume(OrchestrationTestCase):
    def test_rerunning_the_same_run_id_skips_already_completed_shipments(self):
        _make_raw_export(self.raw_export, [
            {"sipl": "155259", "container": "MEDU5655981", "vessel": "MSC-CAPE TAINARO 545A",
             "ship_to_location": "Houston", "sipl_status": "Active"},
        ])
        FakeMSC = _fake_adapter(MSCAdapter, {"MEDU5655981": MSC_PAGE})

        rows1, stats1, _ = run_daily_batch(
            str(self.raw_export), str(self.output_path), str(self.snapshot_db), str(self.checkpoint_db),
            run_id="resume-test", as_of=datetime(2026, 7, 13), route_vessel=lambda v: FakeMSC,
        )
        self.assertEqual(stats1["processed"], 1)

        # Same run_id again - simulates re-invoking after a crash/interruption.
        rows2, stats2, _ = run_daily_batch(
            str(self.raw_export), str(self.output_path), str(self.snapshot_db), str(self.checkpoint_db),
            run_id="resume-test", as_of=datetime(2026, 7, 13), route_vessel=lambda v: FakeMSC,
        )
        self.assertEqual(stats2["skipped_checkpoint"], 1)
        self.assertEqual(stats2["processed"], 0)

    def test_different_run_id_reprocesses_normally(self):
        _make_raw_export(self.raw_export, [
            {"sipl": "155259", "container": "MEDU5655981", "vessel": "MSC-CAPE TAINARO 545A",
             "ship_to_location": "Houston", "sipl_status": "Active"},
        ])
        FakeMSC = _fake_adapter(MSCAdapter, {"MEDU5655981": MSC_PAGE})

        run_daily_batch(
            str(self.raw_export), str(self.output_path), str(self.snapshot_db), str(self.checkpoint_db),
            run_id="run-a", as_of=datetime(2026, 7, 13), route_vessel=lambda v: FakeMSC,
        )
        _, stats2, _ = run_daily_batch(
            str(self.raw_export), str(self.output_path), str(self.snapshot_db), str(self.checkpoint_db),
            run_id="run-b", as_of=datetime(2026, 7, 14), route_vessel=lambda v: FakeMSC,
        )
        # A new day's run_id reprocesses even though the shipment isn't delivered.
        self.assertEqual(stats2["processed"], 1)


class TestErrorHandling(OrchestrationTestCase):
    def test_search_error_is_recorded_and_does_not_crash_the_batch(self):
        _make_raw_export(self.raw_export, [
            {"sipl": "155259", "container": "MEDU5655981", "vessel": "MSC-CAPE TAINARO 545A",
             "ship_to_location": "Houston", "sipl_status": "Active"},
            {"sipl": "166028", "container": "BADU0000000", "vessel": "MSC-CAPE TAINARO 545A",
             "ship_to_location": "Houston", "sipl_status": "Active"},
        ])
        # BADU0000000 has no fixture -> search() returns an error automatically.
        FakeMSC = _fake_adapter(MSCAdapter, {"MEDU5655981": MSC_PAGE})

        rows, stats, _ = run_daily_batch(
            str(self.raw_export), str(self.output_path), str(self.snapshot_db), str(self.checkpoint_db),
            run_id="test-run", as_of=datetime(2026, 7, 13), route_vessel=lambda v: FakeMSC,
        )

        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["processed"], 1)
        self.assertEqual({r.sipl for r in rows}, {"155259"})


class TestEndOfSessionRetry(OrchestrationTestCase):
    """
    Per direct request: a container that fails on its first attempt
    gets one more try at the end of its carrier's whole batch (same
    still-open adapter session), in case the failure was transient
    rather than a real per-container problem.
    """

    def test_transient_failure_recovers_on_end_of_session_retry(self):
        _make_raw_export(self.raw_export, [
            {"sipl": "155259", "container": "MEDU5655981", "vessel": "MSC-CAPE TAINARO 545A",
             "ship_to_location": "Houston", "sipl_status": "Active"},
            {"sipl": "166028", "container": "TLLU3415434", "vessel": "MSC-CAPE TAINARO 545A",
             "ship_to_location": "Houston", "sipl_status": "Active"},
        ])
        # TLLU3415434 fails its first search() call, then succeeds using
        # the same MSC_PAGE fixture on retry - the process_item logic
        # doesn't care which container's data comes back, only that
        # search() eventually succeeds.
        FakeMSC = _flaky_adapter(
            MSCAdapter, {"MEDU5655981": MSC_PAGE, "TLLU3415434": MSC_PAGE}, fail_once_for={"TLLU3415434"},
        )

        rows, stats, _ = run_daily_batch(
            str(self.raw_export), str(self.output_path), str(self.snapshot_db), str(self.checkpoint_db),
            run_id="test-run", as_of=datetime(2026, 7, 13), route_vessel=lambda v: FakeMSC,
        )

        self.assertEqual(stats["errors"], 0)
        self.assertEqual(stats["processed"], 2)
        self.assertEqual(stats["recovered_on_retry"], 1)
        self.assertEqual({r.sipl for r in rows}, {"155259", "166028"})

    def test_persistent_failure_is_still_a_final_error_after_one_retry(self):
        _make_raw_export(self.raw_export, [
            {"sipl": "155259", "container": "MEDU5655981", "vessel": "MSC-CAPE TAINARO 545A",
             "ship_to_location": "Houston", "sipl_status": "Active"},
            {"sipl": "166028", "container": "BADU0000000", "vessel": "MSC-CAPE TAINARO 545A",
             "ship_to_location": "Houston", "sipl_status": "Active"},
        ])
        # BADU0000000 has no fixture at all - fails every attempt, not
        # just the first, so the retry doesn't help and it must still
        # end up as a real error (not retried forever).
        FakeMSC = _fake_adapter(MSCAdapter, {"MEDU5655981": MSC_PAGE})

        rows, stats, _ = run_daily_batch(
            str(self.raw_export), str(self.output_path), str(self.snapshot_db), str(self.checkpoint_db),
            run_id="test-run", as_of=datetime(2026, 7, 13), route_vessel=lambda v: FakeMSC,
        )

        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["recovered_on_retry"], 0)
        self.assertEqual(stats["processed"], 1)


class TestCarrierLevelCrashIsolation(OrchestrationTestCase):
    """
    Real bug: a browser launch failure inside _ensure_driver() used to
    be called before search()'s own try/except, so it had nowhere to
    land as a normal per-container error - it escaped as a raw
    exception, crashed run_daily_batch entirely, and lost whatever
    OTHER carrier's work had already completed in that same run, since
    the Excel report is only written at the very end. Adapters now
    catch their own launch failures (see carriers/*.py); this test
    covers the orchestration-level safety net for anything that still
    gets through uncaught.
    """

    def test_one_carrier_crashing_does_not_lose_another_carriers_results(self):
        _make_raw_export(self.raw_export, [
            {"sipl": "155259", "container": "MEDU5655981", "vessel": "MSC-CAPE TAINARO 545A",
             "ship_to_location": "Houston", "sipl_status": "Active"},
            {"sipl": "166028", "container": "FCIU4746425", "vessel": "HL-CLEMENTINE MAERSK",
             "ship_to_location": "Houston", "sipl_status": "Active"},
        ])
        CrashingMSC = _crashing_adapter(MSCAdapter)
        FakeHL = _fake_adapter(HLAdapter, {"FCIU4746425": HL_PAGE})

        def route(vessel):
            if vessel and vessel.upper().startswith("MSC"):
                return CrashingMSC
            if vessel and vessel.upper().startswith("HL"):
                return FakeHL
            return None

        rows, stats, _ = run_daily_batch(
            str(self.raw_export), str(self.output_path), str(self.snapshot_db), str(self.checkpoint_db),
            run_id="test-run", as_of=datetime(2026, 7, 13), route_vessel=route,
        )

        self.assertEqual(stats["carrier_crashed"], 1)
        self.assertEqual(stats["processed"], 1)
        self.assertEqual({r.sipl for r in rows}, {"166028"})
        self.assertTrue(self.output_path.exists())  # the report still gets written


class TestUnroutedVessel(OrchestrationTestCase):
    def test_unmatched_vessel_is_skipped_gracefully(self):
        _make_raw_export(self.raw_export, [
            {"sipl": "155259", "container": "ZIMU1234567", "vessel": "ZIM-SOME VESSEL",
             "ship_to_location": "Houston", "sipl_status": "Active"},
        ])

        rows, stats, _ = run_daily_batch(
            str(self.raw_export), str(self.output_path), str(self.snapshot_db), str(self.checkpoint_db),
            run_id="test-run", as_of=datetime(2026, 7, 13), route_vessel=lambda v: None,
        )

        self.assertEqual(stats["unrouted"], 1)
        self.assertEqual(rows, [])
        self.assertTrue(self.output_path.exists())  # still renders an (empty) report, doesn't crash


class TestRealCleaningIntegration(OrchestrationTestCase):
    """Runs the orchestrator against the real 1RAW.xlsx (already
    validated for parity in test_cleaning.py), routing its real MSC
    shipments to a fake adapter so the whole chain - real cleaning,
    real worklist building, real routing logic - is exercised without
    a live browser."""

    def test_real_1raw_flows_through_without_crashing(self):
        project_root = Path(__file__).resolve().parents[2]
        real_raw = project_root / "1RAW.xlsx"
        if not real_raw.exists():
            self.skipTest(f"{real_raw} not present")

        FakeMSC = _fake_adapter(MSCAdapter, {})  # every real container errors (no fixture) - fine, just checking no crash

        rows, stats, _ = run_daily_batch(
            str(real_raw), str(self.output_path), str(self.snapshot_db), str(self.checkpoint_db),
            run_id="real-data-smoke-test", as_of=datetime(2026, 7, 13),
            route_vessel=lambda v: FakeMSC if v and v.upper().startswith("MSC") else None,
        )

        self.assertTrue(self.output_path.exists())
        self.assertGreater(stats["errors"] + stats["unrouted"], 0)


if __name__ == "__main__":
    unittest.main()
