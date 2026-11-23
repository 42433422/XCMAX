"""Exercise the actual cron monitor without contacting production."""

import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

MONITOR = Path(__file__).resolve().parents[2] / "monitor" / "xcmax_monitor.py"
spec = importlib.util.spec_from_file_location("xcmax_monitor_under_test", MONITOR)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class MonitorEvidenceTest(unittest.TestCase):
    def test_failed_delivery_preserves_previous_state_and_retries(self):
        for ok, previous in (
            (False, {}),
            (True, {"probe": {"status": "bad", "last_alert": 1, "since": 1}}),
            (False, {"probe": {"status": "bad", "last_alert": 1, "since": 1}}),
        ):
            with self.subTest(ok=ok, previous=previous), redirect_stdout(io.StringIO()):
                result = monitor._result("probe", ok, "crit", "fixture")
                with patch.object(monitor, "run_checks", return_value=[result]), patch.object(
                    monitor, "load_state", return_value=previous
                ), patch.object(monitor, "save_state") as save, patch.object(
                    monitor.notify, "deliver", side_effect=[(False, "failed"), (True, "sent")]
                ) as deliver:
                    self.assertEqual(monitor.main([]), 3)
                    save.assert_not_called()
                    self.assertEqual(monitor.main([]), 0)
                    self.assertEqual(deliver.call_count, 2)
                    save.assert_called_once()
                    self.assertEqual(save.call_args.args[0]["probe"]["status"], "ok" if ok else "bad")

    def test_journal_unavailable_is_not_healthy(self):
        for rc in (1, 127):
            with self.subTest(rc=rc), patch.object(monitor, "_run", return_value=(rc, "")):
                results = monitor.check_journal_errors()
                self.assertEqual({r["id"] for r in results}, {"journal:errors", "journal:quota"})
                self.assertTrue(all(not r["ok"] for r in results))
        with patch.object(monitor, "_run", return_value=(0, "")):
            self.assertTrue(all(r["ok"] for r in monitor.check_journal_errors()))

    def test_invalid_wal_timestamps_do_not_certify_freshness(self):
        with tempfile.TemporaryDirectory() as root, patch.multiple(
            monitor, STATE_DIR=root, WAL_ENABLED=True, WAL_PG16_ENABLED=False
        ), patch.object(monitor.time, "time", return_value=10000):
            state = Path(root) / "state"
            state.mkdir()
            for filename in ("wal_ship_last_success", "wal_base_last_success"):
                (state / filename).write_text("9999", encoding="utf-8")
            self.assertTrue(all(r["ok"] for r in monitor.check_wal_freshness()))
            for raw in ("NaN", "Infinity", "10001", "0"):
                with self.subTest(raw=raw):
                    (state / "wal_ship_last_success").write_text(raw, encoding="utf-8")
                    results = {r["id"]: r for r in monitor.check_wal_freshness()}
                    self.assertFalse(results["wal:ship"]["ok"])
                    self.assertTrue(results["wal:base"]["ok"])

    def test_backup_requires_success_receipt_and_manifest(self):
        with tempfile.TemporaryDirectory() as root, patch.multiple(
            monitor, STATE_DIR=root, BACKUP_DIR=root
        ):
            state = Path(root) / "state"
            state.mkdir()
            stamp = int(monitor.time.time())
            day = monitor.time.strftime("%Y%m%d", monitor.time.gmtime(stamp))
            snapshot = Path(root) / "daily" / day
            snapshot.mkdir(parents=True)
            marker = state / "backup_last_success"
            manifest = snapshot / "MANIFEST.txt"
            self.assertFalse(monitor.check_backup_freshness()[0]["ok"])
            marker.write_text(str(stamp), encoding="utf-8")
            self.assertFalse(monitor.check_backup_freshness()[0]["ok"])
            manifest.write_text("fixture manifest", encoding="utf-8")
            self.assertTrue(monitor.check_backup_freshness()[0]["ok"])
            marker.write_text(str(stamp + 3600), encoding="utf-8")
            self.assertFalse(monitor.check_backup_freshness()[0]["ok"])
            marker.write_text(str(stamp - 27 * 3600), encoding="utf-8")
            self.assertFalse(monitor.check_backup_freshness()[0]["ok"])

    def test_deploy_requires_valid_digests(self):
        with tempfile.TemporaryDirectory() as root, patch.multiple(
            monitor, MANIFEST=str(Path(root) / "manifest.json"), FHD_DEPLOY_ROOT=root
        ):
            manifest = Path(monitor.MANIFEST)
            deployed = Path(root) / ".deploy-sha256"
            deployed.write_text("a" * 64, encoding="utf-8")
            for doc in ("{}", "[]", '{"sha256": null}', '{"sha256": "x"}'):
                with self.subTest(doc=doc):
                    manifest.write_text(doc, encoding="utf-8")
                    self.assertFalse(monitor.check_deploy_chain()[0]["ok"])
            manifest.write_text(monitor.json.dumps({"sha256": "a" * 64}), encoding="utf-8")
            self.assertTrue(monitor.check_deploy_chain()[0]["ok"])
            deployed.write_text("", encoding="utf-8")
            self.assertFalse(monitor.check_deploy_chain()[0]["ok"])



if __name__ == "__main__":
    unittest.main()
