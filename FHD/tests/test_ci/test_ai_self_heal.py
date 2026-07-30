"""ai_self_heal.py 单元测试。

覆盖：
- extract_errors 解析 ruff/bandit/mypy/pytest 错误
- compute_fingerprint 确定性（相同输入相同输出）
- is_already_processed 24h 内去重
- record_fingerprint 写 jsonl
- match_rules ruff F401 → 删 import / bandit B101 → needs-human
- call_llm fail-open（mock httpx 超时返回 None）
- create_pr mock github API
- autonomy/ 分支不递归
- 空日志会创建 remediation incident 并保持失败
- LLM API key 缺失 fail-open
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 把 FHD/scripts/ci 加入 sys.path 以便直接 import ai_self_heal 模块
FHD_ROOT = Path(__file__).resolve().parents[2]
CI_SCRIPTS = FHD_ROOT / "scripts" / "ci"
if str(CI_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CI_SCRIPTS))

import ai_self_heal as heal  # noqa: E402

# =====================================================================
# extract_errors 测试
# =====================================================================


class TestExtractErrors:
    def test_ruff_error_parsed(self) -> None:
        log = "app/foo.py:10:1: F401 'os' imported but unused"
        errors = heal.extract_errors(log)
        assert len(errors) == 1
        assert errors[0].tool == "ruff"
        assert errors[0].code == "F401"
        assert errors[0].file_path == "app/foo.py"
        assert errors[0].line == 10
        assert "imported but unused" in errors[0].message

    def test_bandit_error_parsed(self) -> None:
        log = "  Issue: [B101] Use of assert detected."
        errors = heal.extract_errors(log)
        assert len(errors) == 1
        assert errors[0].tool == "bandit"
        assert errors[0].code == "B101"
        assert "assert detected" in errors[0].message

    def test_mypy_error_parsed(self) -> None:
        log = "app/foo.py:42: error: Argument 1 has incompatible type [arg-type]"
        errors = heal.extract_errors(log)
        assert len(errors) == 1
        assert errors[0].tool == "mypy"
        assert errors[0].file_path == "app/foo.py"
        assert errors[0].line == 42
        assert "incompatible" in errors[0].message

    def test_pytest_failed_parsed(self) -> None:
        log = "FAILED tests/test_foo.py::test_bar - assert 1 == 2"
        errors = heal.extract_errors(log)
        assert len(errors) == 1
        assert errors[0].tool == "pytest"
        assert errors[0].code == "FAILED"

    def test_empty_log_returns_empty_list(self) -> None:
        assert heal.extract_errors("") == []
        assert heal.extract_errors(None) == []  # type: ignore[arg-type]

    def test_dedup_identical_errors(self) -> None:
        log = (
            "app/foo.py:10:1: F401 'os' imported but unused\n"
            "app/foo.py:10:1: F401 'os' imported but unused\n"
        )
        errors = heal.extract_errors(log)
        assert len(errors) == 1

    def test_github_action_timeout_with_envelope_is_parsed(self) -> None:
        log = (
            "cvm-push-release\tPush to CVM update server\t"
            "2026-07-23T09:16:55.1008330Z ##[error]CVM push failed with status 124.\n"
            "cvm-push-release\tPush to CVM update server\t"
            "2026-07-23T09:17:00.1021661Z ##[error]Process completed with exit code 124."
        )

        errors = heal.extract_errors(log)

        assert {error.code for error in errors} == {"EXIT_124"}
        assert any("CVM push failed" in error.message for error in errors)

    def test_incident_excerpt_prefers_failure_context(self) -> None:
        log = "\n".join(
            ["unrelated checkout output"] * 30
            + ["upload started", "##[error]CVM push failed with status 124."]
            + ["unrelated later job"] * 30
        )

        excerpt = heal.select_incident_log_excerpt(log, max_chars=1000)

        assert "CVM push failed with status 124" in excerpt
        assert "upload started" in excerpt
        assert excerpt.count("unrelated later job") < 30

    def test_actionable_errors_drop_advisories_from_successful_jobs(self) -> None:
        log = (
            "app/advisory.py:12: error: Optional check from a successful job [arg-type]\n"
            "cvm-push-release\tPush to CVM update server\t"
            "2026-07-23T09:16:55Z ##[error]CVM push failed with status 124.\n"
            "cvm-push-release\tPush to CVM update server\t"
            "2026-07-23T09:17:00Z ##[error]Process completed with exit code 124."
        )

        selected = heal.select_actionable_errors(heal.extract_errors(log))

        assert len(selected) == 1
        assert selected[0].tool == "github-actions"
        assert selected[0].code == "EXIT_124"
        assert "CVM push failed" in selected[0].message
        assert all(not error.file_path for error in selected)

    def test_actionable_errors_keep_tool_errors_without_action_marker(self) -> None:
        errors = heal.extract_errors("app/foo.py:10:1: F401 'os' imported but unused")

        assert heal.select_actionable_errors(errors) == errors


# =====================================================================
# compute_fingerprint 测试
# =====================================================================


class TestComputeFingerprint:
    def test_deterministic_same_input(self) -> None:
        fp1 = heal.compute_fingerprint("owner/repo", "fhd-ci-cd", "backend-test", "err1")
        fp2 = heal.compute_fingerprint("owner/repo", "fhd-ci-cd", "backend-test", "err1")
        assert fp1 == fp2
        assert len(fp1) == 64  # SHA256 hex

    def test_different_input_different_fp(self) -> None:
        fp1 = heal.compute_fingerprint("owner/repo", "fhd-ci-cd", "job", "err1")
        fp2 = heal.compute_fingerprint("owner/repo", "fhd-ci-cd", "job", "err2")
        assert fp1 != fp2

    def test_different_repo_different_fp(self) -> None:
        fp1 = heal.compute_fingerprint("a/b", "wf", "job", "err")
        fp2 = heal.compute_fingerprint("c/d", "wf", "job", "err")
        assert fp1 != fp2


# =====================================================================
# is_already_processed / record_fingerprint 测试
# =====================================================================


class TestFingerprintStore:
    def test_record_and_check_within_budget(self, tmp_path: Path) -> None:
        store = tmp_path / "fps.jsonl"
        fp = "abc123"
        heal.record_fingerprint(fp, "https://pr/1", store_path=store)
        assert heal.is_already_processed(fp, store_path=store) is True

    def test_check_unknown_fp_returns_false(self, tmp_path: Path) -> None:
        store = tmp_path / "fps.jsonl"
        heal.record_fingerprint("known", "https://pr/1", store_path=store)
        assert heal.is_already_processed("unknown", store_path=store) is False

    def test_expired_fp_outside_budget(self, tmp_path: Path) -> None:
        store = tmp_path / "fps.jsonl"
        old_ts = time.time() - 25 * 3600  # 25h ago
        heal.record_fingerprint("expired", "https://pr/1", store_path=store, now_ts=old_ts)
        # budget=24h → 已过期
        assert heal.is_already_processed("expired", budget_hours=24, store_path=store) is False

    def test_record_writes_jsonl_line(self, tmp_path: Path) -> None:
        store = tmp_path / "fps.jsonl"
        heal.record_fingerprint("fp1", "https://pr/1", repo="a/b", workflow="ci", store_path=store)
        content = store.read_text(encoding="utf-8").strip()
        rec = json.loads(content)
        assert rec["fingerprint"] == "fp1"
        assert rec["pr_url"] == "https://pr/1"
        assert rec["repo"] == "a/b"
        assert rec["workflow"] == "ci"
        assert "ts" in rec


# =====================================================================
# match_rules 测试
# =====================================================================


class TestMatchRules:
    def test_ruff_F401_autofix(self) -> None:
        err = heal.ErrorEntry(
            tool="ruff",
            code="F401",
            message="'os' imported but unused",
            file_path="app/foo.py",
            line=10,
            raw="app/foo.py:10:1: F401 'os' imported but unused",
        )
        fixes = heal.match_rules([err])
        assert len(fixes) == 1
        assert fixes[0].needs_human is False
        assert "a/app/foo.py" in fixes[0].patch

    def test_ruff_E501_autofix(self) -> None:
        err = heal.ErrorEntry(
            tool="ruff",
            code="E501",
            message="line too long",
            file_path="app/foo.py",
            line=42,
            raw="app/foo.py:42:1: E501 line too long",
        )
        fixes = heal.match_rules([err])
        assert len(fixes) == 1
        assert fixes[0].needs_human is False
        assert "E501" in fixes[0].patch

    def test_bandit_B101_needs_human(self) -> None:
        err = heal.ErrorEntry(
            tool="bandit",
            code="B101",
            message="Use of assert detected",
            file_path="",
            line=0,
            raw="Issue: [B101] Use of assert detected",
        )
        fixes = heal.match_rules([err])
        assert len(fixes) == 1
        assert fixes[0].needs_human is True
        assert fixes[0].patch == ""

    def test_mypy_needs_human(self) -> None:
        err = heal.ErrorEntry(
            tool="mypy",
            code="arg-type",
            message="incompatible type",
            file_path="app/foo.py",
            line=42,
            raw="app/foo.py:42: error: incompatible type [arg-type]",
        )
        fixes = heal.match_rules([err])
        assert len(fixes) == 1
        assert fixes[0].needs_human is True

    def test_pytest_needs_human(self) -> None:
        err = heal.ErrorEntry(
            tool="pytest",
            code="FAILED",
            message="assert 1 == 2",
            file_path="",
            line=0,
            raw="FAILED test_foo - assert 1 == 2",
        )
        fixes = heal.match_rules([err])
        assert len(fixes) == 1
        assert fixes[0].needs_human is True


# =====================================================================
# call_llm fail-open 测试
# =====================================================================


class TestCallLlm:
    def test_no_api_key_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_LLM_API_KEY", raising=False)
        err = heal.ErrorEntry("ruff", "F401", "msg", "f", 1, "raw")
        assert heal.call_llm([err]) is None

    def test_no_errors_returns_none(self) -> None:
        assert heal.call_llm([], api_key="k") is None

    def test_timeout_returns_none(self) -> None:
        """mock client 抛超时 → fail-open 返回 None。"""
        err = heal.ErrorEntry("ruff", "F401", "msg", "f", 1, "raw")
        client = MagicMock()
        client.post.side_effect = TimeoutError("timeout")
        result = heal.call_llm([err], api_key="k", client=client)
        assert result is None

    def test_http_500_returns_none(self) -> None:
        err = heal.ErrorEntry("ruff", "F401", "msg", "f", 1, "raw")
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 500
        client.post.return_value = resp
        result = heal.call_llm([err], api_key="k", client=client)
        assert result is None

    def test_valid_response_returns_fixes(self) -> None:
        err = heal.ErrorEntry("ruff", "F401", "msg", "f", 1, "raw")
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "fixes": [
                {
                    "error_index": 0,
                    "patch": "--- a/f\n+++ b/f\n",
                    "needs_human": False,
                    "description": "fix",
                }
            ]
        }
        client.post.return_value = resp
        result = heal.call_llm([err], api_key="k", client=client)
        assert result is not None
        assert len(result) == 1
        assert result[0].needs_human is False


# =====================================================================
# create_pr 测试
# =====================================================================


class TestCreatePr:
    def test_no_token_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_REPOSITORY", "a/b")
        url = heal.create_pr("autonomy/x", "patch")
        assert url == ""


class TestCreateRemediationIssue:
    def test_uses_only_provisioned_incident_labels(self) -> None:
        client = MagicMock()
        response = MagicMock()
        response.status_code = 201
        response.json.return_value = {"html_url": "https://github.com/owner/repo/issues/2"}
        client.post.return_value = response

        url = heal.create_remediation_issue(
            run_id=42,
            workflow="CI/CD Pipeline",
            branch="main",
            fingerprint="f" * 64,
            log_excerpt="failed",
            errors=[],
            token="tok",
            repo="owner/repo",
            client=client,
        )

        assert url.endswith("/issues/2")
        assert client.post.call_args.kwargs["json"]["labels"] == [
            "ai-implement",
            "incident",
            "auto-incident",
        ]

    def test_dispatches_issue_implementation_explicitly(self) -> None:
        client = MagicMock()
        response = MagicMock()
        response.status_code = 204
        client.post.return_value = response

        ok = heal.dispatch_issue_implementation(
            "https://github.com/owner/repo/issues/505",
            token="tok",
            repo="owner/repo",
            client=client,
        )

        assert ok is True
        assert client.post.call_args.kwargs["json"] == {
            "ref": "main",
            "inputs": {"issue_number": "505"},
        }

    def test_no_repo_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        url = heal.create_pr("autonomy/x", "patch")
        assert url == ""

    def test_success_returns_pr_url(self) -> None:
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"html_url": "https://github.com/owner/repo/pull/1", "number": 1}
        client.post.return_value = resp
        url = heal.create_pr(
            "autonomy/x",
            "patch",
            token="tok",
            repo="owner/repo",
            client=client,
        )
        assert url == "https://github.com/owner/repo/pull/1"
        # 应该被调用 2 次：创建 PR + 添加标签
        assert client.post.call_count == 2

    def test_http_error_returns_empty(self) -> None:
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 422
        client.post.return_value = resp
        url = heal.create_pr(
            "autonomy/x",
            "patch",
            token="tok",
            repo="owner/repo",
            client=client,
        )
        assert url == ""


# =====================================================================
# approval ledger 旁路调用测试
# =====================================================================


class TestApprovalLedger:
    """create_pr 成功后旁路调用 approval ledger（fire-and-forget，fail-open）。"""

    def test_ledger_called_with_correct_args(self) -> None:
        """create_pr 成功 → 调用 post_to_approval_ledger，action=self_maintenance_merge，source=ci_self_heal。"""
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {
            "html_url": "https://github.com/owner/repo/pull/42",
            "number": 42,
        }
        client.post.return_value = resp
        with patch.object(heal, "post_to_approval_ledger") as mock_ledger:
            url = heal.create_pr(
                "autonomy/fix-abc",
                "patch",
                token="tok",
                repo="owner/repo",
                client=client,
                fixes=[],
            )
        assert url == "https://github.com/owner/repo/pull/42"
        mock_ledger.assert_called_once_with(
            action="self_maintenance_merge",
            payload={
                "pr_number": 42,
                "pr_url": "https://github.com/owner/repo/pull/42",
                "branch": "autonomy/fix-abc",
                "base": "main",
                "risk_level": "r3",
                "fixes_summary": [],
            },
            source="ci_self_heal",
        )

    def test_ledger_not_called_when_pr_creation_fails(self) -> None:
        """PR 创建失败（422）→ 不调用 ledger。"""
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 422
        client.post.return_value = resp
        with patch.object(heal, "post_to_approval_ledger") as mock_ledger:
            url = heal.create_pr(
                "autonomy/x",
                "patch",
                token="tok",
                repo="owner/repo",
                client=client,
            )
        assert url == ""
        mock_ledger.assert_not_called()

    def test_ledger_failure_does_not_break_pr_creation(self) -> None:
        """ledger 抛异常 → 不影响 PR 创建，仍返回 pr_url。"""
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {
            "html_url": "https://github.com/owner/repo/pull/1",
            "number": 1,
        }
        client.post.return_value = resp
        with patch.object(heal, "post_to_approval_ledger", side_effect=RuntimeError("net down")):
            url = heal.create_pr(
                "autonomy/x",
                "patch",
                token="tok",
                repo="owner/repo",
                client=client,
            )
        assert url == "https://github.com/owner/repo/pull/1"

    def test_ledger_risk_level_r0_when_no_needs_human_label(self) -> None:
        """labels 不含 needs-human → risk_level=r0。"""
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"html_url": "u", "number": 7}
        client.post.return_value = resp
        with patch.object(heal, "post_to_approval_ledger") as mock_ledger:
            heal.create_pr(
                "autonomy/x",
                "patch",
                token="tok",
                repo="owner/repo",
                client=client,
                labels=["auto-merge"],
            )
        assert mock_ledger.call_args.kwargs["payload"]["risk_level"] == "r0"


# =====================================================================
# fetch_workflow_logs 测试
# =====================================================================


class TestFetchLogs:
    def test_no_run_id_returns_empty(self) -> None:
        assert heal.fetch_workflow_logs(0, token="t", repo="a/b") == ""

    def test_no_repo_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        assert heal.fetch_workflow_logs(123, token="t") == ""

    def test_http_error_returns_empty(self) -> None:
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 404
        client.get.return_value = resp
        assert heal.fetch_workflow_logs(123, token="t", repo="a/b", client=client) == ""


# =====================================================================
# autonomy 分支递归保护
# =====================================================================


class TestAutonomyRecursion:
    def test_autonomy_branch_detected(self) -> None:
        assert heal.is_autonomy_branch("autonomy/self-heal-abc123") is True

    def test_non_autonomy_branch_not_detected(self) -> None:
        assert heal.is_autonomy_branch("feature/foo") is False
        assert heal.is_autonomy_branch("main") is False
        assert heal.is_autonomy_branch("") is False
        assert heal.is_autonomy_branch(None) is False  # type: ignore[arg-type]

    def test_main_skips_autonomy_branch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # autonomy/ 分支应直接 return 0，不调用 fetch_workflow_logs
        called = {"fetch": False}

        def fake_fetch(*args: object, **kwargs: object) -> str:
            called["fetch"] = True
            return ""

        monkeypatch.setattr(heal, "fetch_workflow_logs", fake_fetch)
        rc = heal.main(["--branch", "autonomy/self-heal-abc", "--run-id", "1"])
        assert rc == 0
        assert called["fetch"] is False


# =====================================================================
# main 集成测试
# =====================================================================


class TestMainFlow:
    def test_no_run_id_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
        monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
        rc = heal.main(["--branch", "feature/x"])
        assert rc == 2

    def test_empty_log_routes_incident_and_blocks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPOSITORY", "a/b")
        monkeypatch.setattr(heal, "fetch_workflow_logs", lambda *a, **k: "")
        monkeypatch.setattr(
            heal,
            "create_remediation_issue",
            lambda **kwargs: "https://github.com/a/b/issues/1",
        )
        dispatched = []
        monkeypatch.setattr(
            heal,
            "dispatch_issue_implementation",
            lambda issue_url, **kwargs: dispatched.append(issue_url) or True,
        )
        rc = heal.main(
            [
                "--run-id",
                "1",
                "--workflow",
                "ci",
                "--branch",
                "main",
                "--store",
                str(tmp_path / "fps.jsonl"),
            ]
        )
        assert rc == 2
        assert dispatched == ["https://github.com/a/b/issues/1"]

    def test_dry_run_does_not_create_pr(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPOSITORY", "a/b")
        log = "app/foo.py:10:1: F401 'os' imported but unused\n"
        monkeypatch.setattr(heal, "fetch_workflow_logs", lambda *a, **k: log)
        called = {"create_pr": False}

        def fake_create_pr(*args: object, **kwargs: object) -> str:
            called["create_pr"] = True
            return ""

        monkeypatch.setattr(heal, "create_pr", fake_create_pr)
        rc = heal.main(
            [
                "--run-id",
                "1",
                "--workflow",
                "ci",
                "--branch",
                "main",
                "--store",
                str(tmp_path / "fps.jsonl"),
                "--dry-run",
            ]
        )
        assert rc == 0
        assert called["create_pr"] is False

    def test_fingerprint_dedup_skips_pr(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPOSITORY", "a/b")
        log = "app/foo.py:10:1: F401 'os' imported but unused\n"
        monkeypatch.setattr(heal, "fetch_workflow_logs", lambda *a, **k: log)
        store = tmp_path / "fps.jsonl"

        # 预先记录相同指纹
        err_lines = ["app/foo.py:10:1: F401 'os' imported but unused"]
        fp = heal.compute_fingerprint("a/b", "ci", "", "\n".join(err_lines))
        heal.record_fingerprint(fp, "https://existing/pr", store_path=store)

        called = {"create_pr": False}

        def fake_create_pr(*args: object, **kwargs: object) -> str:
            called["create_pr"] = True
            return ""

        monkeypatch.setattr(heal, "create_pr", fake_create_pr)
        rc = heal.main(
            [
                "--run-id",
                "1",
                "--workflow",
                "ci",
                "--branch",
                "main",
                "--store",
                str(store),
            ]
        )
        assert rc == 0
        assert called["create_pr"] is False  # 去重命中，不创建 PR


# =====================================================================
# apply_fixes 测试
# =====================================================================


class TestApplyFixes:
    def test_empty_fixes_returns_empty(self) -> None:
        assert heal.apply_fixes([]) == ""

    def test_concatenates_patches(self) -> None:
        fix1 = heal.Fix(
            error=heal.ErrorEntry("ruff", "F401", "msg", "f", 1, "raw"),
            patch="patch1",
            needs_human=False,
            description="d1",
        )
        fix2 = heal.Fix(
            error=heal.ErrorEntry("ruff", "F401", "msg", "f", 2, "raw"),
            patch="patch2",
            needs_human=False,
            description="d2",
        )
        result = heal.apply_fixes([fix1, fix2])
        assert "patch1" in result
        assert "patch2" in result

    def test_skips_empty_patch(self) -> None:
        fix1 = heal.Fix(
            error=heal.ErrorEntry("mypy", "", "err", "f", 1, "raw"),
            patch="",
            needs_human=True,
            description="d1",
        )
        fix2 = heal.Fix(
            error=heal.ErrorEntry("ruff", "F401", "msg", "f", 2, "raw"),
            patch="patch2",
            needs_human=False,
            description="d2",
        )
        result = heal.apply_fixes([fix1, fix2])
        assert result == "patch2"
