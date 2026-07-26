from __future__ import annotations

import unittest

from FHD.scripts.dev import count_big_files
from scripts.dev import source_governance


def current_state(
    *,
    files: list[dict] | None = None,
    routers: list[dict] | None = None,
    duplicate_lines: int = 10,
    ignored: list[str] | None = None,
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
