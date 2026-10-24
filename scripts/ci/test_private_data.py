"""The private-data gate inspects staged data, not ignore rules or filenames alone."""

from __future__ import annotations

import hashlib
import io
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from check_private_data import check_index, inspect_blob, private_path


class PrivateDataGateTest(unittest.TestCase):
    def test_runtime_paths_and_documentation_boundary(self):
        self.assertTrue(private_path("outputs/new-customer.csv"))
        self.assertTrue(
            private_path("service/var/employee_draft_assets/2/id/asset_manifest.json")
        )
        self.assertTrue(private_path("FHD/delivery/sunbird-seed/config/roster.json"))
        self.assertFalse(private_path("FHD/delivery/sunbird-seed/README.md"))
        self.assertFalse(private_path("FHD/tests/fixtures/synthetic.xlsx"))

    def test_renamed_nested_archive_cannot_hide_known_data(self):
        data = b"synthetic sensitive fixture for the regression test"
        blocked = {hashlib.sha256(data).hexdigest()}
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as archive:
            archive.writestr("renamed.csv", data)
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as archive:
            archive.writestr("renamed.bin", inner.getvalue())
        errors = inspect_blob("example.xcemp", outer.getvalue(), blocked)
        self.assertEqual(len(errors), 1)
        self.assertIn("example.xcemp!renamed.bin!renamed.csv", errors[0])

    def test_force_added_and_staged_data_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", tmp], check=True)
            (root / ".gitignore").write_text("outputs/\n")
            (root / "outputs").mkdir()
            path = root / "outputs" / "data.txt"
            path.write_bytes(b"private fixture")
            subprocess.run(
                ["git", "add", "-f", "outputs/data.txt"], cwd=root, check=True
            )
            path.write_text("working tree has been changed")
            errors = check_index(root, {hashlib.sha256(b"private fixture").hexdigest()})
            self.assertEqual(len(errors), 2)
            subprocess.run(
                ["git", "rm", "--cached", "-f", "outputs/data.txt"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            self.assertEqual(check_index(root, set()), [])

    def test_uninspectable_archive_fails_closed(self):
        self.assertTrue(inspect_blob("package.xcemp", b"not a zip", set()))


if __name__ == "__main__":
    unittest.main()
