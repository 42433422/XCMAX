#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "xcmax_release_sync_prune.py"
SPEC = importlib.util.spec_from_file_location("xcmax_release_sync_prune", MODULE_PATH)
assert SPEC and SPEC.loader
PRUNE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PRUNE)


def marker(
    sha: str,
    component: str,
    timestamp: str,
) -> str:
    date_text, time_text = timestamp.split()
    return f"-rw-r--r-- 41 {date_text} {time_text} {sha}/{component}.SHA"


class ReleaseSyncPruneTest(unittest.TestCase):
    def test_removes_only_oldest_release_for_same_component(self) -> None:
        old_modstore = "1" * 40
        current_modstore = "2" * 40
        old_fhd = "3" * 40
        current_fhd = "4" * 40
        listing = [
            marker(old_modstore, "modstore", "2026/08/10 01:00:00"),
            marker(current_modstore, "modstore", "2026/08/11 01:00:00"),
            marker(old_fhd, "fhd", "2026/08/09 01:00:00"),
            marker(current_fhd, "fhd", "2026/08/12 01:00:00"),
        ]

        self.assertEqual(
            PRUNE.select_victims(listing, "modstore", "5" * 40, 2),
            [old_modstore],
        )
        self.assertEqual(
            PRUNE.select_victims(listing, "fhd", "6" * 40, 2),
            [old_fhd],
        )

    def test_does_not_prune_when_target_is_already_complete(self) -> None:
        target = "a" * 40
        listing = [
            marker("9" * 40, "modstore", "2026/08/10 01:00:00"),
            marker(target, "modstore", "2026/08/11 01:00:00"),
        ]

        self.assertEqual(PRUNE.select_victims(listing, "modstore", target, 2), [])

    def test_keeps_single_previous_candidate(self) -> None:
        listing = [marker("b" * 40, "modstore", "2026/08/10 01:00:00")]

        self.assertEqual(PRUNE.select_victims(listing, "modstore", "c" * 40, 2), [])

    def test_rejects_unsafe_retention_or_malformed_marker(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 2"):
            PRUNE.select_victims([], "modstore", "d" * 40, 1)
        with self.assertRaisesRegex(ValueError, "timestamp"):
            PRUNE.select_victims(
                [marker("e" * 40, "modstore", "not-a-date value")],
                "modstore",
                "f" * 40,
                2,
            )


if __name__ == "__main__":
    unittest.main()
