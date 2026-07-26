from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from FHD.scripts.dev import count_big_files
from scripts.dev import source_governance


def current_state(
    *,
    files: list[dict] | None = None,
    routers: list[dict] | None = None,
    duplicate_lines: int = 10,
    ignored: list[str] | None = None,
    mirrors: list[str] | None = None,
) -> dict:
    return {
        "oversized_files": files or [],
        "oversized_routers": routers or [],
        "duplicate_metrics": {
            "groups": 1,
            "redundant_files": 1,
            "redundant_lines": duplicate_lines,
            "redundant_bytes": 100,
        },
        "forbidden_source_mirrors": mirrors or [],
        "ignored_tracked_files": ignored or [],
    }


def baseline_state() -> dict:
    return {
        "oversized_files": {
            "FHD/app/legacy.py": {
                "stack": "fhd_backend",
                "lines": 900,
                "soft_cap": 800,
            }
        },
        "oversized_routers": {
            "FHD/app/routes.py": {
                "stack": "fhd_backend",
                "routes": 30,
                "soft_cap": 20,
            }
        },
        "duplicate_metrics": {
            "groups": 1,
            "redundant_files": 1,
            "redundant_lines": 10,
            "redundant_bytes": 100,
        },
    }


class SourceGovernanceEvaluateTests(unittest.TestCase):
    def test_rejects_positive_growth_in_grandfathered_file(self) -> None:
        current = current_state(
            files=[
                {
                    "file": "FHD/app/legacy.py",
                    "stack": "fhd_backend",
                    "lines": 901,
                    "soft_cap": 800,
                }
            ]
        )
        errors, _ = source_governance.evaluate(current, baseline_state())
        self.assertTrue(any("oversized file grew" in item for item in errors))

    def test_rejects_new_oversized_file(self) -> None:
        current = current_state(
            files=[
                {
                    "file": "FHD/app/new_monolith.py",
                    "stack": "fhd_backend",
                    "lines": 801,
                    "soft_cap": 800,
                }
            ]
        )
        errors, _ = source_governance.evaluate(current, baseline_state())
        self.assertTrue(any("new oversized" in item for item in errors))

    def test_rejects_duplicate_growth_and_ignored_tracked_file(self) -> None:
        current = current_state(
            duplicate_lines=11, ignored=["FHD/templates/generated.js"]
        )
        errors, _ = source_governance.evaluate(current, baseline_state())
        self.assertTrue(any("exact-copy debt grew" in item for item in errors))
        self.assertTrue(any("also ignored by Git" in item for item in errors))

    def test_accepts_debt_reduction(self) -> None:
        errors, progress = source_governance.evaluate(current_state(), baseline_state())
        self.assertEqual(errors, [])
        self.assertTrue(any("oversized-file debt reduced" in item for item in progress))

    def test_rejects_source_in_retired_static_mirror(self) -> None:
        current = current_state(mirrors=["FHD/static/js/legacy.js"])
        errors, _ = source_governance.evaluate(current, baseline_state())
        self.assertTrue(any("retired source mirror" in item for item in errors))

    def test_detects_retired_online_update_daemon_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            rel = "FHD/scripts/dev/online_update_daemon.py"
            path = repo_root / rel
            path.parent.mkdir(parents=True)
            path.write_text("print('duplicate')\n", encoding="utf-8")
            self.assertEqual(
                source_governance._forbidden_source_mirrors(repo_root, [rel]),
                [rel],
            )

    def test_ignored_tracked_paths_skip_pending_deletions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            live = repo_root / "generated/live.py"
            live.parent.mkdir(parents=True)
            live.write_text("print('tracked')\n", encoding="utf-8")
            with patch.object(
                source_governance,
                "_git_paths",
                return_value=["generated/live.py", "generated/deleted.py"],
            ):
                self.assertEqual(
                    source_governance._ignored_tracked_paths(repo_root),
                    ["generated/live.py"],
                )


class FhdBigFileRatchetV2Tests(unittest.TestCase):
    def test_rejects_growth_even_when_file_count_is_unchanged(self) -> None:
        baseline = {
            "big_files_over_800_lines": 1,
            "big_router_files_over_20_routes": 0,
            "thresholds": {
                "file_lines_soft_cap": 800,
                "routes_per_file_soft_cap": 20,
            },
            "file_line_limits": {"app/legacy.py": 900},
            "router_route_limits": {},
        }
        current = {
            "big_files_count": 1,
            "big_router_count": 0,
            "big_files_over_cap": [{"file": "app/legacy.py", "lines": 901}],
            "big_router_files_over_cap": [],
        }
        errors, _ = count_big_files.evaluate(current, baseline)
        self.assertTrue(any("继续增长" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
