#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "xcmax_release_order.py"
SPEC = importlib.util.spec_from_file_location("xcmax_release_order", MODULE_PATH)
assert SPEC and SPEC.loader
ORDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORDER)


class ReleaseOrderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.incoming = self.root / "incoming"
        self.state = self.root / "state"
        self.incoming.mkdir()
        self.state.mkdir()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def add_component(self, sha: str, component: str, created_at: int) -> Path:
        candidate = self.incoming / sha
        candidate.mkdir(exist_ok=True)
        (candidate / f"{component}.MANIFEST.txt").write_text(
            "verified\n", encoding="utf-8"
        )
        (candidate / f"{component}.CREATED_AT").write_text(
            f"{created_at}\n", encoding="utf-8"
        )
        return candidate

    def set_current(self, component: str, sha: str, created_at: int) -> None:
        (self.state / f"release_applied_{component}_sha").write_text(
            f"{sha}\n", encoding="utf-8"
        )
        (self.state / f"release_applied_{component}_created_at").write_text(
            f"{created_at}\n", encoding="utf-8"
        )

    def test_components_advance_independently_without_rollback(self) -> None:
        old_sha = "1" * 40
        modstore_sha = "2" * 40
        fhd_sha = "3" * 40
        self.set_current("modstore", old_sha, 100)
        self.set_current("fhd", old_sha, 100)
        stale_mixed = self.add_component(old_sha, "modstore", 100)
        self.add_component(old_sha, "fhd", 100)
        modstore_release = self.add_component(modstore_sha, "modstore", 200)
        fhd_release = self.add_component(fhd_sha, "fhd", 300)
        self.add_component(fhd_sha, "modstore", 50)

        self.assertEqual(ORDER.select_release(self.incoming, self.state), fhd_release)
        self.assertTrue(
            ORDER.should_apply(self.incoming, self.state, fhd_release, "fhd")
        )
        self.assertFalse(
            ORDER.should_apply(self.incoming, self.state, fhd_release, "modstore")
        )
        self.set_current("fhd", fhd_sha, 300)

        self.assertEqual(
            ORDER.select_release(self.incoming, self.state), modstore_release
        )
        self.assertFalse(
            ORDER.should_apply(self.incoming, self.state, stale_mixed, "fhd")
        )
        self.set_current("modstore", modstore_sha, 200)
        self.assertIsNone(ORDER.select_release(self.incoming, self.state))

    def test_current_timestamp_falls_back_to_current_artifact(self) -> None:
        current_sha = "a" * 40
        older_sha = "b" * 40
        self.add_component(current_sha, "modstore", 500)
        older = self.add_component(older_sha, "modstore", 400)
        (self.state / "release_applied_modstore_sha").write_text(
            current_sha, encoding="utf-8"
        )

        self.assertFalse(
            ORDER.should_apply(self.incoming, self.state, older, "modstore")
        )
        self.assertIsNone(ORDER.select_release(self.incoming, self.state))

    def test_invalid_or_unstamped_release_is_ignored(self) -> None:
        invalid = self.incoming / "not-a-sha"
        invalid.mkdir()
        (invalid / "fhd.MANIFEST.txt").write_text("x", encoding="utf-8")
        candidate = self.add_component("c" * 40, "fhd", 0)

        self.assertFalse(
            ORDER.should_apply(self.incoming, self.state, candidate, "fhd")
        )
        self.assertIsNone(ORDER.select_release(self.incoming, self.state))


if __name__ == "__main__":
    unittest.main()
