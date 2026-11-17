"""Authorization and scope limits shared by cloud execution and legacy readback."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/dev/ai_issue_implement.py"
_spec = importlib.util.spec_from_file_location("_ai_impl", _SCRIPT_PATH)
_ai_impl = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _ai_impl
_spec.loader.exec_module(_ai_impl)


class TestHasAimplementLabel:
    def test_present(self) -> None:
        issue = {"labels": [{"name": "bug"}, {"name": "ai-implement"}]}
        assert _ai_impl._has_aimplement_label(issue) is True

    def test_absent(self) -> None:
        issue = {"labels": [{"name": "bug"}]}
        assert _ai_impl._has_aimplement_label(issue) is False

    def test_empty_labels(self) -> None:
        assert _ai_impl._has_aimplement_label({"labels": []}) is False

    def test_no_labels_key(self) -> None:
        assert _ai_impl._has_aimplement_label({}) is False

    def test_whitespace_normalized(self) -> None:
        issue = {"labels": [{"name": "  ai-implement  "}]}
        assert _ai_impl._has_aimplement_label(issue) is True

    def test_non_dict_label_skipped(self) -> None:
        issue = {"labels": ["ai-implement", {"name": "ai-implement"}]}
        assert _ai_impl._has_aimplement_label(issue) is True


class TestOwnerConfirmed:
    def _issue(self, login: str = "owner", body: str = "issue body") -> dict[str, Any]:
        return {"user": {"login": login}, "body": body}

    def test_no_comments_not_confirmed(self) -> None:
        ok, msg = _ai_impl._owner_confirmed(self._issue(), [], "owner/repo")
        assert ok is False
        assert "精确批准命令" in msg

    def test_other_user_comment_not_confirmed(self) -> None:
        issue = self._issue(login="owner")
        comments = [
            {
                "user": {"login": "someone-else"},
                "author_association": "CONTRIBUTOR",
                "body": "确认实现",
            }
        ]
        ok, _ = _ai_impl._owner_confirmed(issue, comments, "owner/repo")
        assert ok is False

    def test_repository_owner_chinese_exact_command(self) -> None:
        issue = self._issue(login="github-actions[bot]")
        comments = [
            {
                "user": {"login": "repo-owner"},
                "author_association": "OWNER",
                "body": "确认实现",
            }
        ]
        ok, msg = _ai_impl._owner_confirmed(issue, comments, "owner/repo")
        assert ok is True
        assert "repo-owner" in msg

    def test_repository_owner_english_exact_command(self) -> None:
        issue = self._issue(login="alice")
        comments = [
            {
                "user": {"login": "alice"},
                "author_association": "OWNER",
                "body": "/APPROVE-IMPLEMENTATION",
            }
        ]
        ok, _ = _ai_impl._owner_confirmed(issue, comments, "alice/repo")
        assert ok is True

    @pytest.mark.parametrize("body", ["确认", "已确认，请执行", "approved", "+1", "OK", "go"])
    def test_ambiguous_owner_comment_does_not_authorize(self, body: str) -> None:
        issue = self._issue(login="frank")
        comments = [
            {
                "user": {"login": "frank"},
                "author_association": "OWNER",
                "body": body,
            }
        ]
        ok, _ = _ai_impl._owner_confirmed(issue, comments, "frank/repo")
        assert ok is False

    def test_issue_body_never_authorizes_itself(self) -> None:
        issue = self._issue(login="frank", body="已确认，请执行")
        ok, _ = _ai_impl._owner_confirmed(issue, [], "frank/repo")
        assert ok is False

    def test_issue_author_is_not_repository_owner_proof(self) -> None:
        issue = {"user": {"login": "owner"}, "body": "确认实现"}
        comments = [
            {
                "user": {"login": "owner"},
                "author_association": "NONE",
                "body": "确认实现",
            }
        ]
        ok, msg = _ai_impl._owner_confirmed(issue, comments, "owner/repo")
        assert ok is False
        assert "精确批准命令" in msg


class TestAllowlistPreauthorized:
    def test_pattern_hit(self) -> None:
        issue = {"labels": [{"name": "ai-implement"}, {"name": "bug-mech-timeout"}]}
        ok, msg = _ai_impl._allowlist_preauthorized(
            issue, patterns=[r"^bug-mech-.*", r"^refactor-.*"]
        )
        assert ok is True
        assert "bug-mech-timeout" in msg

    def test_pattern_miss_keeps_gate(self) -> None:
        issue = {"labels": [{"name": "ai-implement"}, {"name": "enhancement"}]}
        ok, _ = _ai_impl._allowlist_preauthorized(
            issue, patterns=[r"^bug-mech-.*", r"^refactor-.*"]
        )
        assert ok is False

    def test_empty_patterns_not_authorized(self) -> None:
        issue = {"labels": [{"name": "bug-mech-x"}]}
        ok, msg = _ai_impl._allowlist_preauthorized(issue, patterns=[])
        assert ok is False
        assert "未配置" in msg or "未启用" in msg

    def test_invalid_regex_skipped(self) -> None:
        issue = {"labels": [{"name": "refactor-foo"}]}
        ok, _ = _ai_impl._allowlist_preauthorized(issue, patterns=[r"[invalid", r"^refactor-.*"])
        assert ok is True

    def test_load_repo_allowlist_file(self, tmp_path: Path) -> None:
        cfg = tmp_path / "auto-implement-allowlist.yaml"
        cfg.write_text(
            "version: 1\nenabled: true\nlabel_patterns:\n  - '^bug-fix$'\n",
            encoding="utf-8",
        )
        pats = _ai_impl._load_allowlist_patterns(cfg)
        assert pats == ["^bug-fix$"]
        issue = {"labels": [{"name": "bug-fix"}]}
        ok, _ = _ai_impl._allowlist_preauthorized(issue, patterns=pats)
        assert ok is True

    def test_disabled_allowlist(self, tmp_path: Path) -> None:
        cfg = tmp_path / "auto-implement-allowlist.yaml"
        cfg.write_text(
            "enabled: false\nlabel_patterns:\n  - '^bug-fix$'\n",
            encoding="utf-8",
        )
        assert _ai_impl._load_allowlist_patterns(cfg) == []


class TestIsAuthorized:
    def test_allowlist_bypasses_confirm_comment(self) -> None:
        issue = {
            "user": {"login": "owner"},
            "body": "no confirm keyword",
            "labels": [{"name": "ai-implement"}, {"name": "refactor-cleanup"}],
        }
        # monkeypatch patterns via _allowlist_preauthorized patterns arg is internal;
        # call _is_authorized after temporarily stubbing loader
        original = _ai_impl._load_allowlist_patterns
        _ai_impl._load_allowlist_patterns = lambda path=None: [r"^refactor-.*"]
        try:
            ok, msg, source = _ai_impl._is_authorized(issue, [], "owner/repo")
            assert ok is True
            assert "域预授权" in msg
            assert source == "allowlist"
        finally:
            _ai_impl._load_allowlist_patterns = original

    def test_falls_back_to_owner_confirm(self) -> None:
        issue = {
            "user": {"login": "owner"},
            "body": "plain body",
            "labels": [{"name": "ai-implement"}],
        }
        original = _ai_impl._load_allowlist_patterns
        _ai_impl._load_allowlist_patterns = lambda path=None: [r"^bug-mech-.*"]
        try:
            ok, _, source = _ai_impl._is_authorized(
                issue,
                [
                    {
                        "user": {"login": "owner"},
                        "author_association": "OWNER",
                        "body": "确认实现",
                    }
                ],
                "owner/repo",
            )
            assert ok is True
            assert source == "owner"
        finally:
            _ai_impl._load_allowlist_patterns = original

    def test_not_authorized_returns_empty_source(self) -> None:
        issue = {
            "user": {"login": "owner"},
            "body": "just a plain description",
            "labels": [{"name": "ai-implement"}],
        }
        original = _ai_impl._load_allowlist_patterns
        _ai_impl._load_allowlist_patterns = lambda path=None: [r"^bug-mech-.*"]
        try:
            ok, _, source = _ai_impl._is_authorized(issue, [], "owner/repo")
            assert ok is False
            assert source == ""
        finally:
            _ai_impl._load_allowlist_patterns = original

    def test_allowlist_takes_priority_over_owner(self) -> None:
        # 同时命中 allowlist 且 owner 确认 → source 必须是 allowlist（更优先）
        issue = {
            "user": {"login": "owner"},
            "body": "已确认",
            "labels": [{"name": "ai-implement"}, {"name": "bug-mech-typo"}],
        }
        original = _ai_impl._load_allowlist_patterns
        _ai_impl._load_allowlist_patterns = lambda path=None: [r"^bug-mech-.*"]
        try:
            ok, _, source = _ai_impl._is_authorized(
                issue,
                [
                    {
                        "user": {"login": "owner"},
                        "author_association": "OWNER",
                        "body": "确认实现",
                    }
                ],
                "owner/repo",
            )
            assert ok is True
            assert source == "allowlist"
        finally:
            _ai_impl._load_allowlist_patterns = original


class TestEstimateFiles:
    def test_min_one(self) -> None:
        # 没有明确文件路径，没有触发关键词 → 1
        assert _ai_impl._estimate_files("修个 bug", "啥也没说") >= 1

    def test_explicit_paths_counted(self) -> None:
        body = "改 app/foo.py 和 tests/test_foo.py"
        n = _ai_impl._estimate_files("title", body)
        assert n == 2  # 明确的测试文件不再重复计数

    @pytest.mark.parametrize(
        "prefix",
        [
            "",
            "./",
            "FHD/",
            "./FHD/",
            "/github/workspace/FHD/",
            "/home/runner/work/XCMAX/XCMAX/FHD/",
            "/__w/XCMAX/XCMAX/FHD/",
            "D:/a/XCMAX/XCMAX/FHD/",
        ],
    )
    def test_source_path_aliases_count_once(self, prefix: str) -> None:
        path = f"{prefix}app/services/foo.py"
        body = "\n".join(
            ["app/services/foo.py", path, path.replace("/", "\\"), path.replace("/", "//")]
        )
        assert _ai_impl._estimate_files("title", body) == 1

    @pytest.mark.parametrize(
        "artifact",
        [
            "test_reports/result.json",
            "shard-summary.json",
            "shard-evidence/worker.json",
            "coverage/report.json",
            "htmlcov/coverage.js",
            "/opt/python/site-packages/pkg/foo.py",
            "frontend/node_modules/pkg/index.js",
            "app/__pycache__/cached.py",
            ".pytest_cache/results.json",
            "logs/run.jsonl",
        ],
    )
    def test_artifacts_are_not_source_changes(self, artifact: str) -> None:
        assert _ai_impl._estimate_files("title", f"app/foo.py app/bar.py {artifact}") == 2

    def test_artifact_heavy_failure_stays_within_limit(self) -> None:
        body = """Fix FHD/scripts/dev/nightly.py and FHD/tests/test_dev/test_nightly.py.
```text
File /home/runner/work/XCMAX/XCMAX/FHD/scripts/dev/nightly.py:42
FAILED tests/test_dev/test_nightly.py::test_summary
test_reports/nightly.json test_reports/failures.json test_reports/gate.json
shard-summary.json shard-evidence/worker-1.json shard-evidence/worker-2.json
coverage/summary.json htmlcov/assets/index.js logs/receipts.jsonl
/opt/python/site-packages/pytest/runner.py frontend/node_modules/pkg/index.js
```
"""
        assert _ai_impl._estimate_files("修复夜间测试", body) == 2

    def test_six_real_files_including_config_and_docs_exceed_limit(self) -> None:
        body = """```text
app/foo.py app/bar.py tests/test_foo.py
config/settings.json docs/coverage.md pyproject.toml
```"""
        assert _ai_impl._estimate_files("title", body) == 6

    @pytest.mark.parametrize(
        "test_path",
        [
            "test_foo.py",
            "src/foo_test.py",
            "src/foo.test.ts",
            "src/foo.spec.js",
            "src/__tests__/foo.ts",
        ],
    )
    def test_explicit_test_does_not_add_keyword_allowance(self, test_path: str) -> None:
        assert _ai_impl._estimate_files("补测试", f"app/foo.py {test_path}") == 2

    def test_add_new_keyword_adds_two(self) -> None:
        body = "新增一个工具模块"
        n = _ai_impl._estimate_files("title", body)
        assert n >= 2

    def test_test_keyword_adds_one(self) -> None:
        body = "补测试"
        n = _ai_impl._estimate_files("title", body)
        assert n >= 1

    def test_explicit_path_with_backticks(self) -> None:
        body = "修改 `FHD/app/services/foo.py`"
        n = _ai_impl._estimate_files("title", body)
        assert n >= 1

    def test_returns_at_least_one(self) -> None:
        # 即使文本为空，max(1, 0) = 1
        n = _ai_impl._estimate_files("", "")
        assert n == 1
