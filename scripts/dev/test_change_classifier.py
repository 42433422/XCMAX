#!/usr/bin/env python3
"""change_classifier.py 的单元测试（SSOT：scripts/dev/change_classifier.py）。

约定：分类器是唯一 changed-path 判断入口，所以它的三种 PR 形态必须可回归：
docs-only / frontend-only / backend-only，外加跨平台互斥（Windows 不算 macOS、
macOS 不算 Windows）与 fail-open 口径。
"""

from __future__ import annotations

import os
import tempfile
import unittest

from scripts.dev.change_classifier import CATEGORY_MODE, RELEVANT, decide
from scripts.dev.change_classifier import main as classifier_main

DOCS_ONLY = ["docs/CI_SSOT.md", "FHD/docs/WINDOWS_RELEASE_SSOT.md"]
FRONTEND_ONLY = ["FHD/frontend/src/views/ApprovalHubView.vue", "FHD/frontend/package-lock.json"]
BACKEND_ONLY = ["FHD/app/application/rbac_app_service.py", "FHD/app/fastapi_routes/desktop_runtime.py"]
WINDOWS_ONLY = ["FHD/scripts/package/acceptance-windows.ps1", "FHD/desktop/build/windows-sign.cjs"]
MACOS_ONLY = ["FHD/desktop/autonomy/controller.ts", "FHD/scripts/package/build-installer.sh"]
MOBILE_ONLY = ["FHD/mobile-flutter-poc/lib/main.dart"]


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


if __name__ == "__main__":
    unittest.main()
