"""Path guard regression tests run with stdlib unittest, without dependencies."""

import importlib.util
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "guard_customer_data", Path(__file__).with_name("guard_customer_data.py")
)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class CustomerDataGuardTests(unittest.TestCase):
    def test_forbidden_and_allowed_paths(self):
        blocked = [
            "outputs/考勤 记录.xlsx",
            guard.MODSTORE + "var/employee_draft_assets/1/合同.docx",
            guard.MODSTORE + "var/employee_uploads/1/秘密\n记录.xlsx",
            guard.MODSTORE + "modstore_server/data/event_outbox_retry.jsonl",
            guard.MODSTORE + "modstore_server/webhook_events/delivery.json",
            guard.MODSTORE + "modstore_server/payment_orders/123.json",
            guard.MODSTORE + "modstore_server/data/payment_orders/123.json",
            guard.MODSTORE + "modstore_server/data/chroma/data.bin",
            guard.CORP + "taiyangniao-pro/backend/_conv_example.xlsx",
            "FHD/delivery/sunbird-seed/config/sunbird-roster.json",
            "FHD/delivery/sunbird-seed/data/mod_dbs/customer.db",
        ]
        for path in blocked:
            with self.subTest(path=path):
                self.assertTrue(guard.forbidden(path))
        for path in [
            "FHD/tests/fixtures/synthetic_attendance/template.xlsx",
            "templates/合同.docx",
            "FHD/tests/test_考勤.py",
            "docs/outputs.md",
            "FHD/delivery/sunbird-seed/README.md",
        ]:
            with self.subTest(path=path):
                self.assertFalse(guard.forbidden(path))

    def test_regex_rules_also_reject_newlines_and_tabs(self):
        for separator in ("\n", "\t"):
            paths = [
                f"FHD/.cursor/customer{separator}contract.docx",
                guard.CORP
                + f"taiyangniao-pro/backend/_conv_customer{separator}data.xlsx",
                guard.MODSTORE
                + f"modstore_server/webhook_events/customer{separator}data.json",
                guard.MODSTORE
                + f"modstore_server/data/event_outbox_customer{separator}data.jsonl",
                guard.MODSTORE
                + f"modstore_server/payment_orders/customer{separator}data.json",
            ]
            for path in paths:
                with self.subTest(path=path):
                    self.assertTrue(guard.forbidden(path))

    def test_index_rejects_force_added_chinese_file_even_when_worktree_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            (root / ".gitignore").write_text("outputs/\n")
            artifact = root / "outputs/合成 考勤\n记录.xlsx"
            artifact.parent.mkdir()
            artifact.write_bytes(b"synthetic test only")
            subprocess.run(
                ["git", "add", "-f", "--", str(artifact)], cwd=root, check=True
            )
            artifact.unlink()
            self.assertEqual(guard.main(root), 1)
            subprocess.run(
                ["git", "rm", "--cached", "-f", "--", str(artifact)],
                cwd=root,
                check=True,
                capture_output=True,
            )
            self.assertEqual(guard.main(root), 0)

    def test_git_failure_is_not_reported_as_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(subprocess.CalledProcessError):
                guard.main(Path(directory))

    def test_known_private_blob_cannot_be_renamed_into_fixture_directory(self):
        with patch.object(
            guard,
            "indexed_entries",
            return_value=[
                ("tests/fixtures/renamed.xlsx", next(iter(guard.BLOCKED_BLOBS)))
            ],
        ):
            self.assertEqual(guard.main(Path(".")), 1)


if __name__ == "__main__":
    unittest.main()
