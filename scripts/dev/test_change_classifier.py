#!/usr/bin/env python3
"""change_classifier.py 的单元测试（SSOT：scripts/dev/change_classifier.py）。

约定：分类器是唯一 changed-path 判断入口，所以它的三种 PR 形态必须可回归：
docs-only / frontend-only / backend-only，外加跨平台互斥（Windows 不算 macOS、
macOS 不算 Windows）与 fail-open 口径。
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.dev.change_classifier import CATEGORY_MODE, RELEVANT, decide
from scripts.dev.change_classifier import main as classifier_main

DOCS_ONLY = ["docs/CI_SSOT.md", "FHD/docs/WINDOWS_RELEASE_SSOT.md"]
FRONTEND_ONLY = [
    "FHD/frontend/src/views/ApprovalHubView.vue",
    "FHD/frontend/package-lock.json",
]
BACKEND_ONLY = [
    "FHD/app/application/rbac_app_service.py",
    "FHD/app/fastapi_routes/desktop_runtime.py",
]
WINDOWS_ONLY = [
    "FHD/scripts/package/acceptance-windows.ps1",
    "FHD/desktop/build/windows-sign.cjs",
]
MACOS_ONLY = [
    "FHD/desktop/autonomy/controller.ts",
    "FHD/scripts/package/build-installer.sh",
]
MOBILE_ONLY = ["FHD/mobile-flutter-poc/lib/main.dart"]
ETL_OUTPUT_SECURITY = ["FHD/app/application/shipment_excel_etl_security.py"]
METRIC_SNAPSHOTS = [
    "FHD/metrics/dora-20261029.json",
    "FHD/metrics/slo-production/20261029T150013Z-40896990546-1.json",
]


class SkipIfAllIrrelevantTests(unittest.TestCase):
    """backend / frontend / release：只在「全都不相关」时才跳过。"""

    def test_docs_only_is_skipped_everywhere(self) -> None:
        for category in ("backend", "frontend", "release"):
            with self.subTest(category=category):
                self.assertFalse(decide(category, DOCS_ONLY))

    def test_frontend_only_skips_backend_and_release(self) -> None:
        self.assertFalse(decide("backend", FRONTEND_ONLY))
        self.assertFalse(decide("release", FRONTEND_ONLY))
        self.assertTrue(decide("frontend", FRONTEND_ONLY))

    def test_backend_only_skips_frontend(self) -> None:
        self.assertFalse(decide("frontend", BACKEND_ONLY))
        self.assertTrue(decide("backend", BACKEND_ONLY))
        self.assertTrue(decide("release", BACKEND_ONLY))

    def test_alembic_only_counts_as_backend(self) -> None:
        self.assertTrue(decide("backend", ["FHD/alembic/versions/abc123_add_col.py"]))

    def test_docs_plus_frontend_only_skips_backend(self) -> None:
        mixed = DOCS_ONLY + FRONTEND_ONLY
        self.assertFalse(decide("backend", mixed))
        self.assertFalse(decide("release", mixed))
        self.assertTrue(decide("frontend", mixed))

    def test_unknown_path_is_fail_open(self) -> None:
        self.assertTrue(decide("backend", ["some/new/area/file.bin"]))
        self.assertTrue(decide("frontend", ["some/new/area/file.bin"]))


class MetricSnapshotFastPathTests(unittest.TestCase):
    """快照精确放行；配置、代码及形似路径不得绕过完整 CI。"""

    def test_pr_2775_snapshot_plus_docs_skips_heavy_runtime_suites(self) -> None:
        changed = DOCS_ONLY + METRIC_SNAPSHOTS
        for category in ("backend", "frontend", "release"):
            with self.subTest(category=category):
                self.assertFalse(decide(category, changed))
        self.assertTrue(decide("docs", changed))

    def test_snapshot_files_without_docs_skip_runtime_suites(self) -> None:
        for path in METRIC_SNAPSHOTS:
            for category in ("backend", "frontend", "release"):
                with self.subTest(path=path, category=category):
                    self.assertFalse(decide(category, [path]))

    def test_operational_inputs_and_near_misses_remain_fail_open(self) -> None:
        unsafe = [
            "FHD/metrics/backend_test_timings.json",
            "FHD/metrics/intent_benchmark_latest.json",
            "FHD/metrics/slo-production/config.json",
            "FHD/metrics/dora-20261029.json.bak",
            "FHD/metrics/dora-2026102x.json",
            "FHD/metrics/dora-20261029.json/extra",
            "FHD/metrics/slo-production/20261029T150013Z-40896990546.json",
            "FHD/metrics/slo-production/20261029T150013Z-run-1.json",
            "FHD/scripts/ci/backend_shards.py",
            "FHD/requirements-server-api.txt",
        ]
        for path in unsafe:
            for category in ("backend", "frontend", "release"):
                with self.subTest(path=path, category=category):
                    self.assertTrue(decide(category, [path]))

    def test_snapshot_plus_backend_change_runs_backend(self) -> None:
        changed = METRIC_SNAPSHOTS + BACKEND_ONLY
        self.assertTrue(decide("backend", changed))
        self.assertTrue(decide("release", changed))

    def test_snapshot_plus_frontend_change_runs_frontend(self) -> None:
        changed = METRIC_SNAPSHOTS + FRONTEND_ONLY
        self.assertTrue(decide("frontend", changed))


class RunIfAnyRelevantTests(unittest.TestCase):
    """codeql / macos / windows / mobile / docs：只在命中相关文件时才跑。"""

    def test_docs_category(self) -> None:
        self.assertTrue(decide("docs", DOCS_ONLY))
        self.assertFalse(decide("docs", BACKEND_ONLY))

    def test_mobile_category(self) -> None:
        self.assertTrue(decide("mobile", MOBILE_ONLY))
        self.assertFalse(decide("mobile", BACKEND_ONLY))

    def test_codeql_splits_by_language(self) -> None:
        self.assertTrue(decide("codeql_python", BACKEND_ONLY))
        self.assertFalse(decide("codeql_javascript", BACKEND_ONLY))
        self.assertTrue(decide("codeql_javascript", FRONTEND_ONLY))
        self.assertFalse(decide("codeql_python", FRONTEND_ONLY))

    def test_windows_only_change_runs_windows_not_macos(self) -> None:
        self.assertTrue(decide("windows", WINDOWS_ONLY))
        # Windows 专属产物不得算作 macOS 改动（item：Windows 改动不拉起 macOS 重测试）。
        self.assertFalse(decide("macos", WINDOWS_ONLY))

    def test_macos_only_change_runs_macos_not_windows(self) -> None:
        self.assertTrue(decide("macos", MACOS_ONLY))
        self.assertFalse(decide("windows", MACOS_ONLY))

    def test_unrelated_change_runs_nothing(self) -> None:
        for category in ("macos", "windows", "mobile", "docs", "runtime_contract"):
            with self.subTest(category=category):
                self.assertFalse(decide(category, BACKEND_ONLY))

    def test_shipment_etl_output_security_runs_cross_platform_contract(self) -> None:
        self.assertTrue(decide("runtime_contract", ETL_OUTPUT_SECURITY))


class FailOpenTests(unittest.TestCase):
    def test_no_changed_files_runs_full(self) -> None:
        for category in sorted(CATEGORY_MODE):
            with self.subTest(category=category):
                self.assertTrue(decide(category, []))

    def test_every_category_has_a_spec(self) -> None:
        for category, mode in CATEGORY_MODE.items():
            with self.subTest(category=category):
                if mode == "run_if_any_relevant":
                    self.assertIn(category, RELEVANT)
                    self.assertTrue(
                        any(
                            RELEVANT[category].get(key)
                            for key in ("prefixes", "suffixes", "exact", "contains")
                        ),
                        f"{category} 的相关 glob 不能为空",
                    )


class CliContractTests(unittest.TestCase):
    """workflow 依赖 GITHUB_OUTPUT 同时产出 run / skip 两个口径。"""

    def test_cli_writes_run_and_skip_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "github_output")
            old = os.environ.get("GITHUB_OUTPUT")
            os.environ["GITHUB_OUTPUT"] = out
            try:
                code = classifier_main(["--category", "backend", "--json"])
            finally:
                if old is None:
                    os.environ.pop("GITHUB_OUTPUT", None)
                else:
                    os.environ["GITHUB_OUTPUT"] = old
            self.assertEqual(code, 0)
            with open(out, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        # 无 base/head → 取不到 diff → fail-open 全量。
        self.assertIn("run=true", lines)
        self.assertIn("skip=false", lines)

    def test_all_categories_share_one_diff_and_bind_checkout(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    "GITHUB_OUTPUT": str(Path(tmp) / "outputs"),
                    "GITHUB_RUN_ID": "123",
                    "GITHUB_RUN_ATTEMPT": "2",
                },
            ),
            patch(
                "scripts.dev.change_classifier._changed_files",
                return_value=FRONTEND_ONLY,
            ) as diff,
        ):
            report = Path(tmp) / "classification.json"
            source = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip()
            self.assertEqual(
                classifier_main(
                    [
                        "--all",
                        "--base",
                        "base",
                        "--head",
                        "head",
                        "--source-sha",
                        source,
                        "--report",
                        str(report),
                    ]
                ),
                0,
            )
            data = json.loads(report.read_text())
            diff.assert_called_once_with("base", "head")
            self.assertEqual(set(data["decisions"]), set(CATEGORY_MODE))
            self.assertFalse(data["decisions"]["backend"])
            self.assertTrue(data["decisions"]["frontend"])
            self.assertEqual(data["source_sha"], source)
            self.assertNotEqual(data["source_sha"], data["pr_head_sha"])
            self.assertEqual(data["run_attempt"], "2")
            outputs = (Path(tmp) / "outputs").read_text()
            self.assertIn("backend_skip=true\n", outputs)
            self.assertIn("frontend_skip=false\n", outputs)
            self.assertIn("valid=true\n", outputs)

    def test_unavailable_diff_runs_every_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "classification.json"
            self.assertEqual(
                classifier_main(
                    [
                        "--all",
                        "--base",
                        "missing-base-ref",
                        "--head",
                        "missing-head-ref",
                        "--report",
                        str(report),
                    ]
                ),
                0,
            )
            data = json.loads(report.read_text())
            self.assertTrue(all(data["decisions"].values()))
            self.assertEqual(data["reason"], "empty_or_unavailable_diff_run_all")

    def test_wrong_source_cannot_emit_valid_skip(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    "GITHUB_OUTPUT": str(Path(tmp) / "outputs"),
                },
            ),
        ):
            with self.assertRaises(SystemExit):
                classifier_main(["--all", "--source-sha", "0" * 40])
            self.assertFalse((Path(tmp) / "outputs").exists())

    def test_source_binding_is_not_silently_ignored_by_legacy_mode(self) -> None:
        with self.assertRaises(SystemExit):
            classifier_main(["--category", "backend", "--source-sha", "a" * 40])


# —— CI 加速专项 2026-10-12 清单回归测试（计划 Task 6，TDD）——


class BackendScope(unittest.TestCase):
    def test_desktop_and_installer_changes_skip_backend_suite(self):
        # Windows/桌面专项 PR（PR #2300 形态）不再触发 27 分钟后端全量。
        changed = [
            "FHD/desktop/main.ts",
            "FHD/desktop/backend-process.ts",
            "FHD/tools/XcagiInstaller/MainWindow.cs",
            "FHD/scripts/package/build-installer.ps1",
            "FHD/docs/MIGRATION_REGISTRY.md",
        ]
        self.assertFalse(decide("backend", changed))

    def test_app_code_change_still_runs_backend(self):
        self.assertTrue(decide("backend", ["FHD/app/fastapi_routes/app.py"]))

    def test_requirements_and_pyproject_still_run_backend(self):
        self.assertTrue(decide("backend", ["FHD/requirements-server-api.txt"]))

    def test_unknown_path_fails_open(self):
        # 无法归类 → 扩大范围，绝不漏测（分类器铁律）。
        self.assertTrue(decide("backend", ["some/new/dir/file.bin"]))

    def test_empty_diff_fails_open(self):
        self.assertTrue(decide("backend", []))


class FrontendScope(unittest.TestCase):
    def test_desktop_changes_skip_frontend_suite(self):
        self.assertFalse(decide("frontend", ["FHD/desktop/updater.ts"]))

    def test_frontend_source_change_runs_frontend(self):
        self.assertTrue(decide("frontend", ["FHD/frontend/src/App.vue"]))


class MacosScope(unittest.TestCase):
    def test_installer_cs_change_triggers_desktop_windows_checks(self):
        # 补漏测：纯安装器改动此前不跑 desktop/windows 专项检查。
        self.assertTrue(decide("macos", ["FHD/tools/XcagiInstaller/App.xaml.cs"]))

    def test_pure_doc_change_stays_off(self):
        self.assertFalse(decide("macos", ["FHD/docs/some-guide.md"]))


if __name__ == "__main__":
    unittest.main()
