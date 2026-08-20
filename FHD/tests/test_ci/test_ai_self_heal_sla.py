# mypy: disable-error-code="import-not-found"
"""ai_self_heal_sla.py 单元测试。

覆盖：
- _extract_login: 从 GitHub user 字段提取 login（None / 缺字段 / 正常）
- load_trusted_authors: yaml 文件缺失 / enabled=false / 字段缺失 / 正常 / 无 PyYAML fallback
- _parse_allowlist_fallback: 极简 yaml 解析（无 PyYAML 时）
- check_regular_pr_gates: 三重门禁（ai-review + ci + author）+ hold-merge veto
- process_regular_pr: 通过/失败/合并失败/dry-run 各路径
- behind PR: update-branch 后等待新 head 全量重检，不直接 merge
- list_regular_prs: 排除 ai-self-heal / ai-generated label 的 PR
- get_workflow_run_conclusion: workflow run 各状态判定
- PRInfo: kind="regular" 字段填充
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 把 FHD/scripts/ci 加入 sys.path 以便直接 import ai_self_heal_sla 模块
FHD_ROOT = Path(__file__).resolve().parents[2]
CI_SCRIPTS = FHD_ROOT / "scripts" / "ci"
if str(CI_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CI_SCRIPTS))

import ai_self_heal_sla as sla  # noqa: E402, I001


# =====================================================================
# _extract_login 测试
# =====================================================================


class TestExtractLogin:
    def test_normal_dict_returns_login(self) -> None:
        assert sla._extract_login({"login": "octocat", "id": 1}) == "octocat"

    def test_none_returns_empty(self) -> None:
        assert sla._extract_login(None) == ""

    def test_missing_login_returns_empty(self) -> None:
        assert sla._extract_login({"id": 1}) == ""

    def test_login_none_returns_empty(self) -> None:
        assert sla._extract_login({"login": None}) == ""

    def test_non_dict_returns_empty(self) -> None:
        assert sla._extract_login("octocat") == ""
        assert sla._extract_login(["login"]) == ""


# =====================================================================
# load_trusted_authors / _parse_allowlist_fallback 测试
# =====================================================================


class TestLoadTrustedAuthors:
    def test_file_missing_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "no-such.yaml"
        assert sla.load_trusted_authors(path) == []

    def test_enabled_false_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "allowlist.yaml"
        path.write_text(
            "version: 1\nenabled: false\ntrusted_authors:\n  - octocat\n",
            encoding="utf-8",
        )
        assert sla.load_trusted_authors(path) == []

    def test_missing_trusted_authors_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "allowlist.yaml"
        path.write_text(
            "version: 1\nenabled: true\nlabel_patterns:\n  - '^bug-.*'\n",
            encoding="utf-8",
        )
        assert sla.load_trusted_authors(path) == []

    def test_normal_loads_authors(self, tmp_path: Path) -> None:
        path = tmp_path / "allowlist.yaml"
        path.write_text(
            "version: 1\nenabled: true\n"
            "label_patterns:\n  - '^bug-.*'\n"
            "trusted_authors:\n  - octocat\n  - 'dev-2'\n",
            encoding="utf-8",
        )
        authors = sla.load_trusted_authors(path)
        assert authors == ["octocat", "dev-2"]

    def test_strips_whitespace_and_quotes(self, tmp_path: Path) -> None:
        path = tmp_path / "allowlist.yaml"
        path.write_text(
            "trusted_authors:\n  - '  alice  '\n  - \"bob\"\n",
            encoding="utf-8",
        )
        authors = sla.load_trusted_authors(path)
        # PyYAML 解析会保留 inner 空格（'  alice  '），strip 会去掉
        assert authors == ["alice", "bob"]

    def test_non_list_trusted_authors_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "allowlist.yaml"
        path.write_text(
            "enabled: true\ntrusted_authors: 'not-a-list'\n",
            encoding="utf-8",
        )
        assert sla.load_trusted_authors(path) == []


class TestParseAllowlistFallback:
    def test_parses_trusted_authors_list(self) -> None:
        text = (
            "version: 1\n"
            "enabled: true\n"
            "label_patterns:\n"
            "  - '^bug-.*'\n"
            "trusted_authors:\n"
            "  - octocat\n"
            "  - 'dev-2'\n"
        )
        data = sla._parse_allowlist_fallback(text)
        assert data["enabled"] is True
        assert data["trusted_authors"] == ["octocat", "dev-2"]

    def test_enabled_false(self) -> None:
        text = "enabled: false\ntrusted_authors:\n  - octocat\n"
        data = sla._parse_allowlist_fallback(text)
        assert data["enabled"] is False
        # 解析仍返回 authors，但 load_trusted_authors 会因 enabled=false 拒绝
        assert data["trusted_authors"] == ["octocat"]

    def test_no_trusted_authors_section(self) -> None:
        text = "enabled: true\nlabel_patterns:\n  - '^bug-.*'\n"
        data = sla._parse_allowlist_fallback(text)
        assert data["trusted_authors"] == []

    def test_comments_stripped(self) -> None:
        text = "enabled: true  # 主开关\ntrusted_authors:\n  - octocat  # 主作者\n"
        data = sla._parse_allowlist_fallback(text)
        assert data["enabled"] is True
        assert data["trusted_authors"] == ["octocat"]


# =====================================================================
# check_regular_pr_gates 测试（hold-merge veto / ai-review / ci / author）
# =====================================================================


def _make_pr(
    *,
    number: int = 100,
    labels: list[str] | None = None,
    author: str = "octocat",
    head_sha: str = "abc123",
) -> sla.PRInfo:
    return sla.PRInfo(
        number=number,
        title="test pr",
        url=f"https://github.com/test/repo/pull/{number}",
        head_branch="feature/test",
        created_at=time.time(),
        labels=labels or [],
        changed_files=2,
        additions=10,
        deletions=2,
        kind="regular",
        author=author,
        head_sha=head_sha,
    )


def _mock_client(
    *,
    ai_review_ok: bool = True,
    ai_review_reason: str = "ok",
    ci_ok: bool = True,
    ci_reason: str = "ok",
) -> MagicMock:
    """Mock GitHubClient，仅暴露 check_regular_pr_gates 调用到的方法。"""
    client = MagicMock(spec=sla.GitHubClient)
    client.get_workflow_run_conclusion.return_value = (ai_review_ok, ai_review_reason)
    client.get_pr_check_runs.return_value = (ci_ok, ci_reason)
    client.get_pr_head_sha.return_value = "abc123"
    client.get_pr_mergeability.return_value = (True, "ok")
    client.has_issue_comment_containing.return_value = False
    client.merge_pr.return_value = (True, "ok", "a" * 40)
    client.dispatch_workflow.return_value = (True, "ok")
    return client


class TestCheckRegularPrGates:
    def test_hold_merge_label_vetoes(self) -> None:
        pr = _make_pr(labels=["hold-merge"])
        client = _mock_client()
        passed, reason = sla.check_regular_pr_gates(client, pr, ["octocat"])
        assert passed is False
        assert "veto:hold-merge" in reason
        # veto 应在调用任何 API 之前返回
        client.get_workflow_run_conclusion.assert_not_called()
        client.get_pr_check_runs.assert_not_called()

    def test_all_gates_pass_with_ai_review_label(self) -> None:
        pr = _make_pr(labels=["ai-review: passed"], author="octocat")
        client = _mock_client()
        passed, reason = sla.check_regular_pr_gates(client, pr, ["octocat"])
        assert passed is True
        assert reason == "ok"
        # 有 label 时不查 workflow run
        client.get_workflow_run_conclusion.assert_not_called()
        # ci 仍要查
        client.get_pr_check_runs.assert_called_once()

    def test_all_gates_pass_with_workflow_run(self) -> None:
        pr = _make_pr(author="octocat")
        client = _mock_client(ai_review_ok=True)
        passed, reason = sla.check_regular_pr_gates(client, pr, ["octocat"])
        assert passed is True
        assert reason == "ok"
        client.get_workflow_run_conclusion.assert_called_once_with(
            "abc123", sla.AI_REVIEW_WORKFLOW_NAME
        )

    def test_ai_review_workflow_fails(self) -> None:
        pr = _make_pr(author="octocat")
        client = _mock_client(
            ai_review_ok=False, ai_review_reason="workflow_failed:AI Review:failure"
        )
        passed, reason = sla.check_regular_pr_gates(client, pr, ["octocat"])
        assert passed is False
        assert "ai_review:" in reason

    def test_ci_not_green_blocks(self) -> None:
        pr = _make_pr(author="octocat")
        client = _mock_client(ci_ok=False, ci_reason="ci_not_green:backend-test")
        passed, reason = sla.check_regular_pr_gates(client, pr, ["octocat"])
        assert passed is False
        assert "ci:" in reason

    def test_author_not_in_trusted_blocks(self) -> None:
        pr = _make_pr(author="untrusted-user")
        client = _mock_client()
        passed, reason = sla.check_regular_pr_gates(client, pr, ["octocat"])
        assert passed is False
        assert "author:not_trusted" in reason
        assert "untrusted-user" in reason

    def test_empty_trusted_authors_blocks(self) -> None:
        pr = _make_pr(author="octocat")
        client = _mock_client()
        passed, reason = sla.check_regular_pr_gates(client, pr, [])
        assert passed is False
        assert "trusted_authors:empty_allowlist" in reason

    def test_unknown_author_blocks(self) -> None:
        # author="" 模拟 user 字段缺失
        pr = _make_pr(author="")
        client = _mock_client()
        passed, reason = sla.check_regular_pr_gates(client, pr, ["octocat"])
        assert passed is False
        assert "author:not_trusted" in reason


# =====================================================================
# process_regular_pr 测试
# =====================================================================


class TestProcessRegularPr:
    def test_gates_pass_triggers_squash_merge(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 把 stale jsonl 重定向到 tmp_path，避免污染真实 metrics
        monkeypatch.setattr(sla, "METRICS_DIR", tmp_path)
        monkeypatch.setattr(sla, "STALE_JSONL", tmp_path / "stale.jsonl")

        pr = _make_pr(labels=["ai-review: passed"], author="octocat")
        client = _mock_client()
        client.get_pr_mergeability.return_value = (True, "ok")
        client.merge_pr.return_value = (True, "ok", "a" * 40)
        client.comment.return_value = True

        action = sla.process_regular_pr(client, pr, ["octocat"], dry_run=False)
        assert action == "auto_merged"
        client.merge_pr.assert_called_once_with(100, method="squash")
        assert client.dispatch_workflow.call_count == 2
        client.dispatch_workflow.assert_any_call(
            "fhd-ci-cd.yml",
            ref="main",
            inputs={
                "release_channel": "stable",
                "push_to_cvm": "true",
                "push_image_tar": "false",
            },
        )
        client.dispatch_workflow.assert_any_call(
            "modstore-ci-backend-python.yml",
            ref="main",
            inputs={},
        )
        client.comment.assert_called()

    def test_gates_fail_skips_merge(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sla, "METRICS_DIR", tmp_path)
        monkeypatch.setattr(sla, "STALE_JSONL", tmp_path / "stale.jsonl")

        pr = _make_pr(labels=["hold-merge"], author="octocat")
        client = _mock_client()
        client.merge_pr.return_value = (True, "ok", "a" * 40)

        action = sla.process_regular_pr(client, pr, ["octocat"], dry_run=False)
        assert action == "skipped"
        client.merge_pr.assert_not_called()

    def test_dry_run_does_not_merge(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sla, "METRICS_DIR", tmp_path)
        monkeypatch.setattr(sla, "STALE_JSONL", tmp_path / "stale.jsonl")

        pr = _make_pr(labels=["ai-review: passed"], author="octocat")
        client = _mock_client()
        client.merge_pr.return_value = (True, "ok", "a" * 40)

        action = sla.process_regular_pr(client, pr, ["octocat"], dry_run=True)
        assert action == "auto_merged_dry"
        client.merge_pr.assert_not_called()
        client.comment.assert_not_called()

    def test_merge_failure_returns_merge_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sla, "METRICS_DIR", tmp_path)
        monkeypatch.setattr(sla, "STALE_JSONL", tmp_path / "stale.jsonl")

        pr = _make_pr(labels=["ai-review: passed"], author="octocat")
        client = _mock_client()
        client.get_pr_mergeability.return_value = (True, "ok")
        client.merge_pr.return_value = (False, "permission", "")
        client.has_issue_comment_containing.return_value = False
        client.comment.return_value = True
        client.add_labels.return_value = True

        action = sla.process_regular_pr(client, pr, ["octocat"], dry_run=False)
        assert action == "merge_failed"
        client.merge_pr.assert_called_once_with(100, method="squash")
        # 失败也要发评论告知（且文案应区分权限）
        client.comment.assert_called()
        body = client.comment.call_args.args[1]
        assert "权限不足" in body
        client.add_labels.assert_called()

    def test_behind_updates_branch_then_waits_for_new_checks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sla, "METRICS_DIR", tmp_path)
        stale = tmp_path / "stale.jsonl"
        monkeypatch.setattr(sla, "STALE_JSONL", stale)

        pr = _make_pr(
            labels=["ai-review: passed"],
            author="octocat",
            head_sha="d" * 40,
        )
        client = _mock_client()
        client.get_pr_mergeability.return_value = (True, "behind")
        client.update_pr_branch.return_value = (True, "ok")

        action = sla.process_regular_pr(client, pr, ["octocat"], dry_run=False)

        assert action == "branch_updated"
        client.update_pr_branch.assert_called_once_with(100, "d" * 40)
        client.merge_pr.assert_not_called()
        client.comment.assert_not_called()
        client.add_labels.assert_not_called()
        record = __import__("json").loads(stale.read_text(encoding="utf-8"))
        assert record["action"] == "branch_update_requested"
        assert record["previous_head_sha"] == "d" * 40

    def test_behind_update_failure_fails_closed_without_hold(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sla, "METRICS_DIR", tmp_path)
        stale = tmp_path / "stale.jsonl"
        monkeypatch.setattr(sla, "STALE_JSONL", stale)

        pr = _make_pr(labels=["ai-review: passed"], author="octocat")
        client = _mock_client()
        client.get_pr_mergeability.return_value = (True, "behind")
        client.update_pr_branch.return_value = (False, "http_422:Head branch was modified")

        action = sla.process_regular_pr(client, pr, ["octocat"], dry_run=False)

        assert action == "skipped"
        client.merge_pr.assert_not_called()
        client.comment.assert_not_called()
        client.add_labels.assert_not_called()
        record = __import__("json").loads(stale.read_text(encoding="utf-8"))
        assert record["action"] == "branch_update_failed"
        assert record["reason"].startswith("http_422")

    def test_post_merge_dispatch_failure_is_not_counted_as_closed_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sla, "METRICS_DIR", tmp_path)
        stale = tmp_path / "stale.jsonl"
        monkeypatch.setattr(sla, "STALE_JSONL", stale)

        pr = _make_pr(labels=["ai-review: passed"], author="octocat")
        client = _mock_client()
        client.merge_pr.return_value = (True, "ok", "b" * 40)
        client.dispatch_workflow.side_effect = [
            (True, "ok"),
            (False, "http_403:Resource not accessible by integration"),
        ]

        action = sla.process_regular_pr(client, pr, ["octocat"], dry_run=False)

        assert action == "post_merge_dispatch_failed"
        client.add_labels.assert_called_once_with(100, ["needs-human"])
        assert sla.POST_MERGE_DISPATCH_FAIL_MARKER in client.comment.call_args.args[1]
        record = __import__("json").loads(stale.read_text(encoding="utf-8"))
        assert record["action"] == "post_merge_dispatch_failed"
        assert record["merge_sha"] == "b" * 40
        assert "modstore-ci-backend-python.yml" in record["reason"]

    def test_conflict_blocks_before_merge_and_dedupes_comment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sla, "METRICS_DIR", tmp_path)
        monkeypatch.setattr(sla, "STALE_JSONL", tmp_path / "stale.jsonl")

        pr = _make_pr(labels=["ai-review: passed"], author="octocat")
        client = _mock_client()
        client.get_pr_mergeability.return_value = (False, "conflict")
        client.has_issue_comment_containing.return_value = True  # 已通知过
        client.add_labels.return_value = True

        action = sla.process_regular_pr(client, pr, ["octocat"], dry_run=False)
        assert action == "merge_failed"
        client.merge_pr.assert_not_called()
        client.comment.assert_not_called()
        client.add_labels.assert_called()
        labels = client.add_labels.call_args.args[1]
        assert "needs-human" in labels
        assert "hold-merge" in labels

    def test_stale_log_appended_on_skip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sla, "METRICS_DIR", tmp_path)
        stale = tmp_path / "stale.jsonl"
        monkeypatch.setattr(sla, "STALE_JSONL", stale)

        pr = _make_pr(labels=["hold-merge"], author="octocat")
        client = _mock_client()

        sla.process_regular_pr(client, pr, ["octocat"], dry_run=False)
        assert stale.is_file()
        content = stale.read_text(encoding="utf-8").strip()
        import json

        rec = json.loads(content)
        assert rec["pr"] == 100
        assert rec["kind"] == "regular"
        assert rec["action"] == "regular_skipped"
        assert "veto:hold-merge" in rec["reason"]


class TestProcessAiGeneratedPr:
    def test_missing_risk_label_fails_closed_to_manual_review(self) -> None:
        pr = _make_pr(labels=[])
        pr.kind = "ai_generated"
        pr.created_at = time.time() - 24 * 3600
        client = _mock_client()

        action = sla.process_pr(
            client,
            pr,
            r0_hours=0,
            r1_hours=0,
            r2_stale_days=7,
            r2_close_days=14,
            r3_stale_days=7,
            r3_close_days=30,
        )

        assert action == "skipped"
        client.get_pr_check_runs.assert_not_called()
        client.merge_pr.assert_not_called()


class TestMergeFailureHelpers:
    def test_merge_failure_comment_distinguishes_conflict_vs_permission(self) -> None:
        conflict = sla._merge_failure_comment("conflict")
        permission = sla._merge_failure_comment("permission")
        assert "合并冲突" in conflict
        assert "非权限问题" in conflict
        assert "权限不足" in permission
        assert conflict.startswith(sla.MERGE_FAIL_COMMENT_MARKER)
        assert permission.startswith(sla.MERGE_FAIL_COMMENT_MARKER)


# =====================================================================
# list_regular_prs 测试（通过 mock client）
# =====================================================================


class TestListRegularPrs:
    def test_excludes_ai_self_heal_and_ai_generated_labels(self) -> None:
        # 构造真实 GitHubClient（不连网），mock 内部 client.get
        client = sla.GitHubClient.__new__(sla.GitHubClient)
        client.repo = "test/repo"
        client.token = "fake-token"

        # 模拟分页：第一页返回 3 条（含 1 个 ai-self-heal 和 1 个 ai-generated），第二页空
        page1 = [
            {
                "number": 1,
                "title": "regular PR",
                "html_url": "https://github.com/test/repo/pull/1",
                "head": {"ref": "feature/1", "sha": "sha-1"},
                "created_at": "2026-07-20T10:00:00Z",
                "labels": [{"name": "enhancement"}],
                "changed_files": 2,
                "additions": 10,
                "deletions": 1,
                "user": {"login": "octocat"},
            },
            {
                "number": 2,
                "title": "ai-self-heal PR",
                "html_url": "https://github.com/test/repo/pull/2",
                "head": {"ref": "autonomy/self-heal-x", "sha": "sha-2"},
                "created_at": "2026-07-20T11:00:00Z",
                "labels": [{"name": "ai-self-heal"}, {"name": "risk:r0"}],
                "changed_files": 1,
                "additions": 2,
                "deletions": 1,
                "user": {"login": "github-actions[bot]"},
            },
            {
                "number": 3,
                "title": "ai-generated PR",
                "html_url": "https://github.com/test/repo/pull/3",
                "head": {"ref": "ai-impl/x", "sha": "sha-3"},
                "created_at": "2026-07-20T12:00:00Z",
                "labels": [{"name": "ai-generated"}],
                "changed_files": 3,
                "additions": 50,
                "deletions": 0,
                "user": {"login": "github-actions[bot]"},
            },
        ]
        # 第二页空 → 触发 break
        page2: list[dict] = []

        mock_http = MagicMock()
        resp1 = MagicMock()
        resp1.raise_for_status.return_value = None
        resp1.json.return_value = page1
        resp2 = MagicMock()
        resp2.raise_for_status.return_value = None
        resp2.json.return_value = page2
        mock_http.get.side_effect = [resp1, resp2]
        client.client = mock_http

        prs = client.list_regular_prs()
        # 仅保留 #1（普通 PR），排除 #2 #3
        numbers = [p.number for p in prs]
        assert numbers == [1]
        assert prs[0].kind == "regular"
        assert prs[0].author == "octocat"
        assert prs[0].head_sha == "sha-1"

    def test_empty_repo_returns_empty_list(self) -> None:
        client = sla.GitHubClient.__new__(sla.GitHubClient)
        client.repo = "test/repo"
        client.token = "fake-token"

        mock_http = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = []
        mock_http.get.return_value = resp
        client.client = mock_http

        prs = client.list_regular_prs()
        assert prs == []


# =====================================================================
# get_workflow_run_conclusion 测试
# =====================================================================


def _make_real_client() -> sla.GitHubClient:
    """构造真实 GitHubClient（不连网），caller 自行 mock client.client。"""
    client = sla.GitHubClient.__new__(sla.GitHubClient)
    client.repo = "test/repo"
    client.token = "fake-token"
    client.branch_update_client = None
    client.workflow_dispatch_client = None
    client.require_independent_workflow_dispatch = False
    return client


class TestGetWorkflowRunConclusion:
    def test_no_head_sha_returns_false(self) -> None:
        client = _make_real_client()
        client.client = MagicMock()
        passed, reason = client.get_workflow_run_conclusion("", "AI Review")
        assert passed is False
        assert reason == "no_head_sha"
        # 没 head_sha 时不该发 API 请求
        client.client.get.assert_not_called()

    def test_no_workflow_runs_for_sha(self) -> None:
        client = _make_real_client()
        mock_http = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"workflow_runs": []}
        mock_http.get.return_value = resp
        client.client = mock_http

        passed, reason = client.get_workflow_run_conclusion("abc123", "AI Review")
        assert passed is False
        assert "no_workflow_run" in reason

    def test_workflow_not_completed(self) -> None:
        client = _make_real_client()
        mock_http = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "workflow_runs": [
                {
                    "name": "AI Review",
                    "status": "in_progress",
                    "conclusion": None,
                    "created_at": "2026-07-20T10:00:00Z",
                }
            ]
        }
        mock_http.get.return_value = resp
        client.client = mock_http

        passed, reason = client.get_workflow_run_conclusion("abc123", "AI Review")
        assert passed is False
        assert "workflow_not_completed" in reason

    def test_workflow_failed(self) -> None:
        client = _make_real_client()
        mock_http = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "workflow_runs": [
                {
                    "name": "AI Review",
                    "status": "completed",
                    "conclusion": "failure",
                    "created_at": "2026-07-20T10:00:00Z",
                }
            ]
        }
        mock_http.get.return_value = resp
        client.client = mock_http

        passed, reason = client.get_workflow_run_conclusion("abc123", "AI Review")
        assert passed is False
        assert "workflow_failed" in reason
        assert "failure" in reason

    def test_workflow_success(self) -> None:
        client = _make_real_client()
        mock_http = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "workflow_runs": [
                {
                    "name": "Other Workflow",
                    "status": "completed",
                    "conclusion": "success",
                    "created_at": "2026-07-20T09:00:00Z",
                },
                {
                    "name": "AI Review",
                    "status": "completed",
                    "conclusion": "success",
                    "created_at": "2026-07-20T10:00:00Z",
                },
            ]
        }
        mock_http.get.return_value = resp
        client.client = mock_http

        passed, reason = client.get_workflow_run_conclusion("abc123", "AI Review")
        assert passed is True
        assert reason == "ok"

    def test_api_error_returns_false(self) -> None:
        client = _make_real_client()
        mock_http = MagicMock()
        resp = MagicMock()
        resp.status_code = 500
        mock_http.get.return_value = resp
        client.client = mock_http

        passed, reason = client.get_workflow_run_conclusion("abc123", "AI Review")
        assert passed is False
        assert "workflow_runs_api_error_500" in reason

    def test_picks_latest_run_by_created_at(self) -> None:
        client = _make_real_client()
        mock_http = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        # 新 run failure，旧 run success，应取新的 failure
        resp.json.return_value = {
            "workflow_runs": [
                {
                    "name": "AI Review",
                    "status": "completed",
                    "conclusion": "success",
                    "created_at": "2026-07-20T09:00:00Z",
                },
                {
                    "name": "AI Review",
                    "status": "completed",
                    "conclusion": "failure",
                    "created_at": "2026-07-20T10:00:00Z",
                },
            ]
        }
        mock_http.get.return_value = resp
        client.client = mock_http

        passed, reason = client.get_workflow_run_conclusion("abc123", "AI Review")
        assert passed is False
        assert "failure" in reason


# =====================================================================
# merge + workflow_dispatch API contract tests
# =====================================================================


class TestMergeAndDispatchApi:
    def test_workflow_requires_independent_post_merge_dispatch_token(self) -> None:
        workflow = (FHD_ROOT / ".github" / "workflows" / "ai-self-heal-auto-merge.yml").read_text(
            encoding="utf-8"
        )

        assert "WORKFLOW_DISPATCH_TOKEN: ${{ secrets.CI_COMMIT_TOKEN }}" in workflow
        assert 'REQUIRE_INDEPENDENT_WORKFLOW_DISPATCH_TOKEN: "1"' in workflow

    def test_mergeability_reports_behind_state(self) -> None:
        client = _make_real_client()
        mock_http = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "mergeable": True,
            "mergeable_state": "behind",
        }
        mock_http.get.return_value = response
        client.client = mock_http

        assert client.get_pr_mergeability(42) == (True, "behind")

    def test_mergeability_retries_transient_unknown_until_behind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_real_client()
        mock_http = MagicMock()
        unknown = MagicMock()
        unknown.status_code = 200
        unknown.json.return_value = {
            "mergeable": None,
            "mergeable_state": "unknown",
        }
        behind = MagicMock()
        behind.status_code = 200
        behind.json.return_value = {
            "mergeable": True,
            "mergeable_state": "behind",
        }
        mock_http.get.side_effect = [unknown, behind]
        client.client = mock_http
        sleep = MagicMock()
        monkeypatch.setattr(sla, "MERGEABILITY_POLL_ATTEMPTS", 3)
        monkeypatch.setattr(sla, "MERGEABILITY_POLL_BASE_SECONDS", 0.25)
        monkeypatch.setattr(sla.time, "sleep", sleep)

        assert client.get_pr_mergeability(42) == (True, "behind")
        assert mock_http.get.call_count == 2
        sleep.assert_called_once_with(0.25)

    def test_mergeability_unknown_retry_is_bounded_and_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_real_client()
        mock_http = MagicMock()
        unknown = MagicMock()
        unknown.status_code = 200
        unknown.json.return_value = {
            "mergeable": None,
            "mergeable_state": "unknown",
        }
        mock_http.get.return_value = unknown
        client.client = mock_http
        sleep = MagicMock()
        monkeypatch.setattr(sla, "MERGEABILITY_POLL_ATTEMPTS", 3)
        monkeypatch.setattr(sla, "MERGEABILITY_POLL_BASE_SECONDS", 0.25)
        monkeypatch.setattr(sla.time, "sleep", sleep)

        assert client.get_pr_mergeability(42) == (
            None,
            "unknown_after_3_attempts",
        )
        assert mock_http.get.call_count == 3
        assert [call.args[0] for call in sleep.call_args_list] == [0.25, 0.5]

    def test_update_branch_sends_expected_head_sha(self) -> None:
        client = _make_real_client()
        mock_http = MagicMock()
        response = MagicMock()
        response.status_code = 202
        mock_http.put.return_value = response
        client.client = mock_http
        client.branch_update_client = mock_http

        assert client.update_pr_branch(42, "d" * 40) == (True, "ok")
        mock_http.put.assert_called_once_with(
            "https://api.github.com/repos/test/repo/pulls/42/update-branch",
            json={"expected_head_sha": "d" * 40},
        )

    def test_update_branch_without_dedicated_token_fails_closed(self) -> None:
        client = _make_real_client()
        client.client = MagicMock()

        assert client.update_pr_branch(42, "d" * 40) == (
            False,
            "branch_update_token_missing",
        )
        client.client.put.assert_not_called()

    def test_merge_returns_exact_sha_from_github(self) -> None:
        client = _make_real_client()
        mock_http = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"merged": True, "sha": "c" * 40}
        mock_http.put.return_value = response
        client.client = mock_http

        assert client.merge_pr(42, method="squash") == (True, "ok", "c" * 40)
        mock_http.put.assert_called_once_with(
            "https://api.github.com/repos/test/repo/pulls/42/merge",
            json={"merge_method": "squash"},
        )

    def test_dispatch_posts_ref_and_inputs(self) -> None:
        client = _make_real_client()
        mock_http = MagicMock()
        response = MagicMock()
        response.status_code = 204
        mock_http.post.return_value = response
        client.client = mock_http

        result = client.dispatch_workflow(
            "fhd-ci-cd.yml",
            ref="main",
            inputs={"push_to_cvm": "true"},
        )

        assert result == (True, "ok")
        mock_http.post.assert_called_once_with(
            "https://api.github.com/repos/test/repo/actions/workflows/fhd-ci-cd.yml/dispatches",
            json={"ref": "main", "inputs": {"push_to_cvm": "true"}},
        )

    def test_dispatch_uses_independent_token_client_for_downstream_cd(self) -> None:
        client = _make_real_client()
        primary = MagicMock()
        dispatch = MagicMock()
        response = MagicMock()
        response.status_code = 204
        dispatch.post.return_value = response
        client.client = primary
        client.workflow_dispatch_client = dispatch
        client.require_independent_workflow_dispatch = True

        result = client.dispatch_workflow("modstore-ci-backend-python.yml")

        assert result == (True, "ok")
        dispatch.post.assert_called_once_with(
            "https://api.github.com/repos/test/repo/actions/workflows/"
            "modstore-ci-backend-python.yml/dispatches",
            json={"ref": "main"},
        )
        primary.post.assert_not_called()

    def test_dispatch_fails_closed_when_independent_token_is_required(self) -> None:
        client = _make_real_client()
        client.client = MagicMock()
        client.require_independent_workflow_dispatch = True

        assert client.dispatch_workflow("modstore-ci-backend-python.yml") == (
            False,
            "workflow_dispatch_token_missing",
        )
        client.client.post.assert_not_called()

    def test_dispatch_failure_preserves_api_reason(self) -> None:
        client = _make_real_client()
        mock_http = MagicMock()
        response = MagicMock()
        response.status_code = 403
        response.json.return_value = {"message": "Resource not accessible by integration"}
        mock_http.post.return_value = response
        client.client = mock_http

        ok, reason = client.dispatch_workflow("fhd-ci-cd.yml")

        assert ok is False
        assert reason == "http_403:Resource not accessible by integration"


# =====================================================================
# main 测试（端到端，mock GitHubClient）
# =====================================================================


class TestMainScanRegularPrs:
    def test_scan_regular_prs_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 不传 --scan-regular-prs 时，不调用 list_regular_prs
        monkeypatch.setenv("GITHUB_TOKEN", "fake")
        monkeypatch.setenv("GITHUB_REPOSITORY", "test/repo")

        created_client = MagicMock(spec=sla.GitHubClient)
        created_client.list_self_heal_prs.return_value = []
        created_client.list_regular_prs.return_value = []
        monkeypatch.setattr(sla, "GitHubClient", lambda repo, token: created_client)

        rc = sla.main([])
        assert rc == 0
        created_client.list_self_heal_prs.assert_called_once()
        created_client.list_regular_prs.assert_not_called()

    def test_scan_regular_prs_enabled_with_empty_allowlist_skips(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "fake")
        monkeypatch.setenv("GITHUB_REPOSITORY", "test/repo")

        # allowlist 文件不存在 → trusted_authors 空 → 跳过普通 PR 扫描
        empty_path = tmp_path / "missing.yaml"

        created_client = MagicMock(spec=sla.GitHubClient)
        created_client.list_self_heal_prs.return_value = []
        created_client.list_regular_prs.return_value = []
        monkeypatch.setattr(sla, "GitHubClient", lambda repo, token: created_client)

        rc = sla.main(["--scan-regular-prs", "--allowlist-path", str(empty_path)])
        assert rc == 0
        # allowlist 为空，不调用 list_regular_prs
        created_client.list_regular_prs.assert_not_called()

    def test_scan_regular_prs_processes_regular_prs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "fake")
        monkeypatch.setenv("GITHUB_REPOSITORY", "test/repo")
        monkeypatch.setattr(sla, "METRICS_DIR", tmp_path)
        monkeypatch.setattr(sla, "STALE_JSONL", tmp_path / "stale.jsonl")

        # 构造一个 allowlist 文件
        allowlist = tmp_path / "allowlist.yaml"
        allowlist.write_text(
            "enabled: true\ntrusted_authors:\n  - octocat\n",
            encoding="utf-8",
        )

        pr = sla.PRInfo(
            number=42,
            title="test",
            url="https://github.com/test/repo/pull/42",
            head_branch="feature/x",
            created_at=time.time(),
            labels=["ai-review: passed"],
            changed_files=2,
            additions=10,
            deletions=2,
            kind="regular",
            author="octocat",
            head_sha="sha-42",
        )

        created_client = MagicMock(spec=sla.GitHubClient)
        created_client.list_self_heal_prs.return_value = []
        created_client.list_regular_prs.return_value = [pr]
        created_client.get_pr_check_runs.return_value = (True, "ok")
        created_client.get_workflow_run_conclusion.return_value = (True, "ok")
        created_client.get_pr_head_sha.return_value = "sha-42"
        created_client.merge_pr.return_value = (True, "ok", "a" * 40)
        created_client.get_pr_mergeability.return_value = (True, "ok")
        created_client.dispatch_workflow.return_value = (True, "ok")
        created_client.comment.return_value = True
        monkeypatch.setattr(sla, "GitHubClient", lambda repo, token: created_client)

        rc = sla.main(["--scan-regular-prs", "--allowlist-path", str(allowlist)])
        assert rc == 0
        created_client.list_regular_prs.assert_called_once()
        created_client.merge_pr.assert_called_once_with(42, method="squash")

    def test_post_merge_dispatch_failure_makes_workflow_fail(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "fake")
        monkeypatch.setenv("GITHUB_REPOSITORY", "test/repo")
        monkeypatch.setattr(sla, "METRICS_DIR", tmp_path)
        monkeypatch.setattr(sla, "STALE_JSONL", tmp_path / "stale.jsonl")

        allowlist = tmp_path / "allowlist.yaml"
        allowlist.write_text(
            "enabled: true\ntrusted_authors:\n  - octocat\n",
            encoding="utf-8",
        )
        pr = _make_pr(number=43, labels=["ai-review: passed"], author="octocat")
        created_client = _mock_client()
        created_client.list_self_heal_prs.return_value = []
        created_client.list_regular_prs.return_value = [pr]
        created_client.dispatch_workflow.side_effect = [
            (True, "ok"),
            (False, "http_403:denied"),
        ]
        monkeypatch.setattr(sla, "GitHubClient", lambda repo, token: created_client)

        rc = sla.main(["--scan-regular-prs", "--allowlist-path", str(allowlist)])

        assert rc == 1
