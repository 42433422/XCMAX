# -*- coding: utf-8 -*-
"""employee_runtime.workspace_guard 工作空间 gate 单元测试。

覆盖 glob→regex 转换、basename/路径匹配、forbidden/scope/read_only 决策与各分支。
"""

from __future__ import annotations

import re

import pytest

from app.application.employee_runtime import workspace_guard as wg


class TestGlobToRegex:
    def test_single_star_no_slash(self):
        rx = re.compile(wg._glob_to_regex("*.py"))
        assert rx.match("a.py")
        assert not rx.match("dir/a.py")

    def test_double_star_slash_matches_any_depth(self):
        rx = re.compile(wg._glob_to_regex("**/secret.key"))
        assert rx.match("secret.key")
        assert rx.match("a/b/secret.key")

    def test_double_star_trailing(self):
        rx = re.compile(wg._glob_to_regex("keys/**"))
        assert rx.match("keys/a/b.txt")

    def test_question_mark(self):
        rx = re.compile(wg._glob_to_regex("a?.txt"))
        assert rx.match("ab.txt")
        assert not rx.match("a/b.txt")

    def test_escapes_regex_specials(self):
        rx = re.compile(wg._glob_to_regex("a.b+c"))
        assert rx.match("a.b+c")
        assert not rx.match("aXbXc")


class TestCompileAndMatch:
    def test_compile_skips_blank(self):
        compiled = wg._compile_globs(["", "  ", "*.py"])
        assert len(compiled) == 1

    def test_compile_skips_invalid_glob(self):
        # 引发 re.error 的 pattern 被跳过而不抛
        compiled = wg._compile_globs(["[unterminated"])
        assert isinstance(compiled, list)

    def test_matches_any_basename_when_no_slash(self):
        compiled = wg._compile_globs(["*.key"])
        assert wg._matches_any("deep/dir/secret.key", compiled)

    def test_matches_any_full_path_when_slash(self):
        compiled = wg._compile_globs(["migrations/*.sql"])
        assert wg._matches_any("migrations/001.sql", compiled)
        assert not wg._matches_any("other/001.sql", compiled)

    def test_matches_any_empty_patterns(self):
        assert wg._matches_any("x", []) is False


class TestExtractPaths:
    def test_input_output_list_keys(self):
        args = {
            "file_path": "in.csv",
            "output_path": "out.xlsx",
            "file_paths": ["a.csv", "b.csv"],
        }
        paths = wg._extract_paths(args)
        assert ("in.csv", False) in paths
        assert ("out.xlsx", True) in paths
        assert ("a.csv", False) in paths

    def test_non_dict_returns_empty(self):
        assert wg._extract_paths("x") == []

    def test_blank_values_skipped(self):
        assert wg._extract_paths({"file_path": "   ", "output": ""}) == []


class TestWorkspacePolicy:
    def test_config_workspace_policy_wins(self):
        wp = wg._workspace_policy({}, {"workspace_policy": {"scope_globs": ["a"]}})
        assert wp == {"scope_globs": ["a"]}

    def test_v2_fallback(self):
        wp = wg._workspace_policy(
            {"employee_config_v2": {"workspace_policy": {"forbidden_globs": ["b"]}}}, {}
        )
        assert wp == {"forbidden_globs": ["b"]}

    def test_empty_when_absent(self):
        assert wg._workspace_policy({}, {}) == {}


class TestNormalizeRel:
    def test_blank_returns_empty(self):
        assert wg._normalize_rel("  ", None) == ""

    def test_no_root_strips_dotslash(self):
        assert wg._normalize_rel("./a/b.txt", None) == "a/b.txt"

    def test_within_root(self, tmp_path):
        f = tmp_path / "sub" / "x.txt"
        f.parent.mkdir(parents=True)
        f.write_text("x")
        rel = wg._normalize_rel(str(f), str(tmp_path))
        assert rel == "sub/x.txt"

    def test_outside_root_returns_posix(self, tmp_path):
        # 绝对路径在 root 外 → relative_to 抛 ValueError → 返回 posix 原路径
        rel = wg._normalize_rel("/etc/hosts", str(tmp_path))
        assert rel.endswith("etc/hosts")


class TestBuildEmployeeGate:
    def test_returns_none_when_nothing_to_enforce(self):
        gate = wg.build_employee_gate("e", {}, {}, None)
        assert gate is None

    def test_read_only_blocks_write_tools(self):
        # is_read_only 读 manifest.employee_config_v2.workspace_policy.read_only
        manifest = {"employee_config_v2": {"workspace_policy": {"read_only": True}}}
        gate = wg.build_employee_gate("e", manifest, {}, None)
        assert gate is not None
        verdict = gate("import_excel_to_database", {})
        assert verdict["ok"] is False
        assert "只读" in verdict["reason"]

    def test_read_only_via_actions_agent_workspace(self):
        config = {"actions": {"agent": {"workspace": {"read_only": True}}}}
        gate = wg.build_employee_gate("e", {}, config, None)
        assert gate is not None
        assert gate("products_bulk_import", {})["ok"] is False

    def test_forbidden_glob_blocks(self):
        config = {"workspace_policy": {"forbidden_globs": ["*.key"]}}
        gate = wg.build_employee_gate("e", {}, config, None)
        verdict = gate("excel_analysis", {"file_path": "secret.key"})
        assert verdict["ok"] is False
        assert "forbidden" in verdict["reason"]

    def test_scope_glob_blocks_output_outside(self):
        config = {"workspace_policy": {"scope_globs": ["outputs/*"]}}
        gate = wg.build_employee_gate("e", {}, config, None)
        verdict = gate("generate_office_document", {"output_path": "elsewhere/x.docx"})
        assert verdict["ok"] is False
        assert "scope_globs" in verdict["reason"]

    def test_scope_glob_allows_in_scope_output(self):
        config = {"workspace_policy": {"scope_globs": ["outputs/*"]}}
        gate = wg.build_employee_gate("e", {}, config, None)
        verdict = gate("generate_office_document", {"output_path": "outputs/x.docx"})
        assert verdict["ok"] is True

    def test_scope_not_enforced_on_read_input_for_nonwrite_tool(self):
        # 只配 scope_globs，非写类工具的输入路径不应被 scope 拦
        config = {"workspace_policy": {"scope_globs": ["outputs/*"]}}
        gate = wg.build_employee_gate("e", {}, config, None)
        verdict = gate("excel_analysis", {"file_path": "uploads/in.csv"})
        assert verdict["ok"] is True

    def test_blank_path_skipped(self):
        config = {"workspace_policy": {"forbidden_globs": ["*.key"]}}
        gate = wg.build_employee_gate("e", {}, config, None)
        verdict = gate("excel_analysis", {"file_path": "   "})
        assert verdict["ok"] is True
