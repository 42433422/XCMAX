"""ai_issue_implement 决策矩阵约束的纯函数单测。

只测不依赖 GitHub API / git / LLM 的纯逻辑：
- _has_aimplement_label
- _owner_confirmed（关键词匹配 + author 校验）
- _allowlist_preauthorized / _is_authorized（方案 B 域预授权）
- _estimate_files（粗估规则）
- _apply_files（路径穿越/敏感文件过滤）
- ImplementResult / _write_report
- _call_llm 缺 key 容错

不测：网络请求、git 调用、LLM 调用、PR 创建（端到端在 CI 实跑）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

# ai_issue_implement 在 scripts/dev/ 下，不是包内模块，需要用 spec 加载
# 必须先注册到 sys.modules 否则 @dataclass 装饰器在解析 __module__ 时会失败
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "dev" / "ai_issue_implement.py"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW_PATHS = (
    _REPO_ROOT / "FHD" / ".github" / "workflows" / "ai-issue-implement.yml",
    _REPO_ROOT / ".github" / "workflows" / "fhd-ai-issue-implement.yml",
)
_spec = importlib.util.spec_from_file_location("ai_issue_implement", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
_ai_impl = importlib.util.module_from_spec(_spec)
sys.modules["ai_issue_implement"] = _ai_impl
_spec.loader.exec_module(_ai_impl)


def test_workflow_comment_trigger_requires_open_issue_owner_confirmation() -> None:
    for workflow_path in _WORKFLOW_PATHS:
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "github.event.issue.state == 'open'" in workflow
        assert "github.event.comment.author_association == 'OWNER'" in workflow
        assert "contains(github.event.comment.body, '确认')" in workflow


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
        assert "未在评论中确认" in msg

    def test_other_user_comment_not_confirmed(self) -> None:
        issue = self._issue(login="owner")
        comments = [{"user": {"login": "someone-else"}, "body": "确认"}]
        ok, _ = _ai_impl._owner_confirmed(issue, comments, "owner/repo")
        assert ok is False

    def test_owner_chinese_confirm_keyword(self) -> None:
        issue = self._issue(login="owner")
        comments = [{"user": {"login": "owner"}, "body": "确认，开始执行吧"}]
        ok, msg = _ai_impl._owner_confirmed(issue, comments, "owner/repo")
        assert ok is True
        assert "owner" in msg

    def test_owner_english_confirm(self) -> None:
        issue = self._issue(login="alice")
        comments = [{"user": {"login": "alice"}, "body": "approved, go ahead"}]
        ok, _ = _ai_impl._owner_confirmed(issue, comments, "alice/repo")
        assert ok is True

    def test_owner_plus_one(self) -> None:
        issue = self._issue(login="bob")
        comments = [{"user": {"login": "bob"}, "body": "+1"}]
        ok, _ = _ai_impl._owner_confirmed(issue, comments, "bob/repo")
        assert ok is True

    def test_owner_ok_keyword(self) -> None:
        issue = self._issue(login="carol")
        comments = [{"user": {"login": "carol"}, "body": "OK"}]
        ok, _ = _ai_impl._owner_confirmed(issue, comments, "carol/repo")
        assert ok is True

    def test_owner_go_keyword(self) -> None:
        issue = self._issue(login="dan")
        comments = [{"user": {"login": "dan"}, "body": "go"}]
        ok, _ = _ai_impl._owner_confirmed(issue, comments, "dan/repo")
        assert ok is True

    def test_case_insensitive(self) -> None:
        issue = self._issue(login="eve")
        comments = [{"user": {"login": "eve"}, "body": "CONFIRM"}]
        ok, _ = _ai_impl._owner_confirmed(issue, comments, "eve/repo")
        assert ok is True

    def test_issue_body_contains_confirm_keyword(self) -> None:
        # issue 本身 body 含确认也算（owner 自己写的）
        issue = self._issue(login="frank", body="已确认，请执行")
        ok, _ = _ai_impl._owner_confirmed(issue, [], "frank/repo")
        assert ok is True

    def test_no_author_not_confirmed(self) -> None:
        issue = {"user": {}, "body": "确认"}
        ok, msg = _ai_impl._owner_confirmed(issue, [], "owner/repo")
        assert ok is False
        assert "未解析" in msg


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
        _ai_impl._load_allowlist_patterns = lambda path=None: [r"^refactor-.*"]  # type: ignore[assignment]
        try:
            ok, msg, source = _ai_impl._is_authorized(issue, [], "owner/repo")
            assert ok is True
            assert "域预授权" in msg
            assert source == "allowlist"
        finally:
            _ai_impl._load_allowlist_patterns = original  # type: ignore[assignment]

    def test_falls_back_to_owner_confirm(self) -> None:
        issue = {
            "user": {"login": "owner"},
            "body": "plain body",
            "labels": [{"name": "ai-implement"}],
        }
        original = _ai_impl._load_allowlist_patterns
        _ai_impl._load_allowlist_patterns = lambda path=None: [r"^bug-mech-.*"]  # type: ignore[assignment]
        try:
            ok, _, source = _ai_impl._is_authorized(
                issue,
                [{"user": {"login": "owner"}, "body": "确认"}],
                "owner/repo",
            )
            assert ok is True
            assert source == "owner"
        finally:
            _ai_impl._load_allowlist_patterns = original  # type: ignore[assignment]

    def test_not_authorized_returns_empty_source(self) -> None:
        issue = {
            "user": {"login": "owner"},
            "body": "just a plain description",
            "labels": [{"name": "ai-implement"}],
        }
        original = _ai_impl._load_allowlist_patterns
        _ai_impl._load_allowlist_patterns = lambda path=None: [r"^bug-mech-.*"]  # type: ignore[assignment]
        try:
            ok, _, source = _ai_impl._is_authorized(issue, [], "owner/repo")
            assert ok is False
            assert source == ""
        finally:
            _ai_impl._load_allowlist_patterns = original  # type: ignore[assignment]

    def test_allowlist_takes_priority_over_owner(self) -> None:
        # 同时命中 allowlist 且 owner 确认 → source 必须是 allowlist（更优先）
        issue = {
            "user": {"login": "owner"},
            "body": "已确认",
            "labels": [{"name": "ai-implement"}, {"name": "bug-mech-typo"}],
        }
        original = _ai_impl._load_allowlist_patterns
        _ai_impl._load_allowlist_patterns = lambda path=None: [r"^bug-mech-.*"]  # type: ignore[assignment]
        try:
            ok, _, source = _ai_impl._is_authorized(
                issue,
                [{"user": {"login": "owner"}, "body": "确认"}],
                "owner/repo",
            )
            assert ok is True
            assert source == "allowlist"
        finally:
            _ai_impl._load_allowlist_patterns = original  # type: ignore[assignment]


class TestCommitAndPrLabelRouting:
    """_commit_and_pr 按授权来源分流标签（Gap-1 核心保证）。"""

    def test_allowlist_source_labels_r0(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_git(*args: str, cwd: str | None = None) -> str:
            return ""

        def fake_gh_post(url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
            if url.endswith("/pulls"):
                captured["pr_payload"] = payload
                return {"html_url": "https://github.com/o/r/pull/1", "number": 1}
            if "/issues/1/labels" in url:
                captured["labels_payload"] = payload
                return {}
            return {}

        monkeypatch.setattr(_ai_impl, "_git", fake_git)
        monkeypatch.setattr(_ai_impl, "_gh_post", fake_gh_post)

        pr_url, pr_num = _ai_impl._commit_and_pr(
            tmp_path,
            "fix-branch",
            1,
            "title",
            ["a.py"],
            "o/r",
            "tok",
            auth_source="allowlist",
        )
        assert pr_num == 1
        assert "ai-generated" in captured["labels_payload"]["labels"]
        assert "risk:r0" in captured["labels_payload"]["labels"]
        assert "needs-human" not in captured["labels_payload"]["labels"]
        assert "risk:r2" not in captured["labels_payload"]["labels"]
        # PR body 必须含 allowlist 来源说明
        assert "allowlist" in captured["pr_payload"]["body"]

    def test_owner_source_labels_r2_needs_human(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_git(*args: str, cwd: str | None = None) -> str:
            return ""

        def fake_gh_post(url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
            if url.endswith("/pulls"):
                captured["pr_payload"] = payload
                return {"html_url": "https://github.com/o/r/pull/2", "number": 2}
            if "/issues/2/labels" in url:
                captured["labels_payload"] = payload
                return {}
            return {}

        monkeypatch.setattr(_ai_impl, "_git", fake_git)
        monkeypatch.setattr(_ai_impl, "_gh_post", fake_gh_post)

        pr_url, pr_num = _ai_impl._commit_and_pr(
            tmp_path,
            "fix-branch",
            2,
            "title",
            ["a.py"],
            "o/r",
            "tok",
            auth_source="owner",
        )
        assert pr_num == 2
        labels = captured["labels_payload"]["labels"]
        assert "needs-human" in labels
        assert "ai-generated" in labels
        assert "risk:r2" in labels
        assert "risk:r0" not in labels
        # PR body 必须含 owner 来源说明
        assert "owner" in captured["pr_payload"]["body"]

    def test_default_source_treats_as_owner(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # auth_source 缺省（空字符串）→ 按保守策略走 owner 路径
        captured: dict[str, Any] = {}

        def fake_git(*args: str, cwd: str | None = None) -> str:
            return ""

        def fake_gh_post(url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
            if url.endswith("/pulls"):
                return {"html_url": "https://github.com/o/r/pull/3", "number": 3}
            if "/issues/3/labels" in url:
                captured["labels_payload"] = payload
                return {}
            return {}

        monkeypatch.setattr(_ai_impl, "_git", fake_git)
        monkeypatch.setattr(_ai_impl, "_gh_post", fake_gh_post)

        _ai_impl._commit_and_pr(
            tmp_path,
            "fix-branch",
            3,
            "title",
            ["a.py"],
            "o/r",
            "tok",
        )
        labels = captured["labels_payload"]["labels"]
        assert "needs-human" in labels
        assert "risk:r2" in labels
        assert "risk:r0" not in labels


class TestEstimateFiles:
    def test_min_one(self) -> None:
        # 没有明确文件路径，没有触发关键词 → 1
        assert _ai_impl._estimate_files("修个 bug", "啥也没说") >= 1

    def test_explicit_paths_counted(self) -> None:
        body = "改 app/foo.py 和 tests/test_foo.py"
        n = _ai_impl._estimate_files("title", body)
        assert n >= 2  # 两个明确路径

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


class TestApplyFiles:
    def test_create_writes_file(self, tmp_path: Path) -> None:
        files = [
            {
                "path": "new_module.py",
                "action": "create",
                "content": "print('hello')\n",
            }
        ]
        written = _ai_impl._apply_files(tmp_path, files)
        assert len(written) == 1
        assert written[0] == "new_module.py"
        assert (tmp_path / "new_module.py").read_text(encoding="utf-8") == "print('hello')\n"

    def test_modify_not_applied(self, tmp_path: Path) -> None:
        files = [{"path": "existing.py", "action": "modify", "content": "..."}]
        written = _ai_impl._apply_files(tmp_path, files)
        assert written == []

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        files = [{"path": "../escape.py", "action": "create", "content": "x"}]
        written = _ai_impl._apply_files(tmp_path, files)
        assert written == []

    def test_absolute_path_blocked(self, tmp_path: Path) -> None:
        files = [{"path": "/etc/passwd", "action": "create", "content": "x"}]
        written = _ai_impl._apply_files(tmp_path, files)
        assert written == []

    def test_secrets_path_blocked(self, tmp_path: Path) -> None:
        files = [
            {"path": "_local_secrets/creds.py", "action": "create", "content": "x"},
            {"path": "env_file.env", "action": "create", "content": "x"},
            {"path": "payment_processor.py", "action": "create", "content": "x"},
            {"path": "secrets_loader.py", "action": "create", "content": "x"},
        ]
        written = _ai_impl._apply_files(tmp_path, files)
        assert written == []

    def test_existing_file_not_overwritten(self, tmp_path: Path) -> None:
        (tmp_path / "exists.py").write_text("ORIGINAL", encoding="utf-8")
        files = [{"path": "exists.py", "action": "create", "content": "OVERWRITE"}]
        written = _ai_impl._apply_files(tmp_path, files)
        assert written == []
        assert (tmp_path / "exists.py").read_text(encoding="utf-8") == "ORIGINAL"

    def test_nested_dir_created(self, tmp_path: Path) -> None:
        files = [
            {
                "path": "deep/nested/dir/file.py",
                "action": "create",
                "content": "x",
            }
        ]
        written = _ai_impl._apply_files(tmp_path, files)
        assert len(written) == 1
        assert (tmp_path / "deep/nested/dir/file.py").is_file()

    def test_empty_path_skipped(self, tmp_path: Path) -> None:
        files = [{"path": "", "action": "create", "content": "x"}]
        written = _ai_impl._apply_files(tmp_path, files)
        assert written == []

    def test_no_content_uses_summary(self, tmp_path: Path) -> None:
        files = [
            {
                "path": "from_summary.py",
                "action": "create",
                "content_summary": "# generated stub\n",
            }
        ]
        written = _ai_impl._apply_files(tmp_path, files)
        assert len(written) == 1
        assert "stub" in (tmp_path / "from_summary.py").read_text(encoding="utf-8")

    def test_multiple_files_mixed_actions(self, tmp_path: Path) -> None:
        (tmp_path / "existing.py").write_text("ORIG", encoding="utf-8")
        files = [
            {"path": "existing.py", "action": "modify", "content": "x"},
            {"path": "new1.py", "action": "create", "content": "1"},
            {"path": "new2.py", "action": "create", "content": "2"},
            {"path": "../escape.py", "action": "create", "content": "x"},
        ]
        written = _ai_impl._apply_files(tmp_path, files)
        assert sorted(written) == ["new1.py", "new2.py"]


class TestImplementResultDataclass:
    def test_default_values(self) -> None:
        r = _ai_impl.ImplementResult(
            issue_number=1, repo="owner/repo", started_at="2026-01-01T00:00:00Z"
        )
        assert r.ok is False
        assert r.status == "init"
        assert r.changed_files == []
        assert r.pr_number == 0
        assert r.llm_used is False

    def test_report_written(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_ai_impl, "REPORT_DIR", tmp_path)
        r = _ai_impl.ImplementResult(
            issue_number=42,
            repo="o/r",
            started_at="2026-01-01T00:00:00Z",
            ok=True,
            status="dry_run",
            finished_at="2026-01-01T00:00:01Z",
        )
        path = _ai_impl._write_report(r)
        assert path.name == "ai_issue_implement_42.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["issue_number"] == 42
        assert data["status"] == "dry_run"
        assert data["ok"] is True


class TestCallLlmNoKey:
    def test_empty_api_key_returns_not_ok(self) -> None:
        result = _ai_impl._call_llm(prompt="test", api_key="")
        assert result["ok"] is False
        assert "LLM_API_KEY" in result["error"]


class TestChatCompletionsUrl:
    @pytest.mark.parametrize(
        ("base", "expected"),
        [
            (
                "https://api.minimaxi.com",
                "https://api.minimaxi.com/v1/chat/completions",
            ),
            (
                "https://api.minimax.io/",
                "https://api.minimax.io/v1/chat/completions",
            ),
            (
                "https://api.minimaxi.com/v1",
                "https://api.minimaxi.com/v1/chat/completions",
            ),
            (
                "https://gateway.example/v1/chat/completions",
                "https://gateway.example/v1/chat/completions",
            ),
        ],
    )
    def test_normalizes_provider_root(self, base: str, expected: str) -> None:
        assert _ai_impl._chat_completions_url(base) == expected
