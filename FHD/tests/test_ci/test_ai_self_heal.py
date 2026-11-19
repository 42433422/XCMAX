"""ai_self_heal.py 单元测试。

覆盖：
- extract_errors 解析 ruff/bandit/mypy/pytest 错误
- compute_fingerprint 确定性（相同输入相同输出）
- is_already_processed 24h 内去重
- record_fingerprint 写 jsonl
- match_rules ruff F401 → 删 import / bandit B101 → needs-human
- call_llm fail-open（mock httpx 超时返回 None）
- GitHub incident/dispatch receipts and bounded recovery
- autonomy/ 分支不递归
- 空日志会创建 remediation incident 并保持失败
- LLM API key 缺失 fail-open
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 把 FHD/scripts/ci 加入 sys.path 以便直接 import ai_self_heal 模块
FHD_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = FHD_ROOT.parent
CI_SCRIPTS = FHD_ROOT / "scripts" / "ci"
if str(CI_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CI_SCRIPTS))

import ai_self_heal as heal


def test_script_help_imports_app_from_fhd_working_directory() -> None:
    """The workflow executes the script by path from ``FHD``."""
    completed = subprocess.run(
        [sys.executable, "-I", "scripts/ci/ai_self_heal.py", "--help"],
        cwd=FHD_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_self_heal_workflow_carries_failure_branch_and_serializes_duplicates() -> None:
    for workflow_path in (
        FHD_ROOT / ".github" / "workflows" / "ai-self-heal.yml",
        REPO_ROOT / ".github" / "workflows" / "fhd-ai-self-heal.yml",
    ):
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "concurrency:" in workflow
        assert "--head-repo" in workflow
        assert "github.event.workflow_run.head_repository.full_name" in workflow
        assert "AI_SELF_HEAL_MAX_OPEN_INCIDENTS" in workflow
        assert "AI_SELF_HEAL_MAX_OPEN_PER_WORKFLOW" in workflow
        assert "AI_SELF_HEAL_MAX_RECENT_INCIDENTS" in workflow


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
        assert heal.extract_errors(None) == []

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

    def test_generic_exit_uses_stable_root_cause_context(self) -> None:
        errors = [
            heal.ErrorEntry(
                "github-actions",
                "EXIT_1",
                "Process completed with exit code 1.",
                "",
                0,
                "##[error]Process completed with exit code 1.",
            )
        ]
        first = (
            "2026-08-01T03:25:50.097Z [big-files-ratchet] 1 VIOLATION(S):\n"
            "2026-08-01T03:25:50.098Z - app/a.py grew 100 → 120\n"
            "2026-08-01T03:25:50.102Z ##[error]Process completed with exit code 1."
        )
        second = first.replace("03:25:50", "03:32:40")

        assert heal.canonical_fingerprint_evidence(
            errors, first
        ) == heal.canonical_fingerprint_evidence(errors, second)

    def test_generic_exit_different_root_causes_do_not_collide(self) -> None:
        errors = [
            heal.ErrorEntry(
                "github-actions",
                "EXIT_1",
                "Process completed with exit code 1.",
                "",
                0,
                "##[error]Process completed with exit code 1.",
            )
        ]

        assert heal.canonical_fingerprint_evidence(
            errors,
            "ERROR: coverage below threshold\n##[error]Process completed with exit code 1.",
        ) != heal.canonical_fingerprint_evidence(
            errors,
            "[big-files-ratchet] 1 VIOLATION(S)\n##[error]Process completed with exit code 1.",
        )

    def test_specific_error_normalizes_run_ids_and_digests(self) -> None:
        first = [
            heal.ErrorEntry(
                "github-actions",
                "EXIT_78",
                "deploy failed",
                "",
                0,
                "run_id=123 artifact 0123456789abcdef0123456789abcdef01234567 failed",
            )
        ]
        second = [
            heal.ErrorEntry(
                "github-actions",
                "EXIT_78",
                "deploy failed",
                "",
                0,
                "run_id=456 artifact fedcba9876543210fedcba9876543210fedcba98 failed",
            )
        ]

        assert heal.canonical_fingerprint_evidence(
            first, first[0].raw
        ) == heal.canonical_fingerprint_evidence(second, second[0].raw)


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

    def test_github_incident_is_durable_cross_runner_dedup(self) -> None:
        client = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = [
            {
                "html_url": "https://github.com/a/b/issues/9",
                "body": "Correlation/Fingerprint: `same-fingerprint`",
            }
        ]
        client.get.return_value = response

        existing = heal.find_existing_remediation_issue(
            "same-fingerprint",
            token="tok",
            repo="a/b",
            client=client,
            now_ts=1_800_000_000,
        )

        assert existing == "https://github.com/a/b/issues/9"
        assert client.get.call_args.kwargs["params"]["labels"] == "auto-incident"
        assert client.get.call_args.kwargs["params"]["state"] == "open"

    def test_github_incident_lookup_failure_does_not_prove_absence(self) -> None:
        client = MagicMock()
        client.get.side_effect = RuntimeError("github unavailable")

        with pytest.raises(heal.freshness.LookupFailed):
            heal.find_existing_remediation_issue(
                "fingerprint",
                token="tok",
                repo="a/b",
                client=client,
            )


class TestIncidentBudget:
    @staticmethod
    def _response(items: list[dict], *, status_code: int = 200) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = items
        return response

    @staticmethod
    def _issue(number: int, workflow: str = "CI/CD Pipeline") -> dict:
        return {
            "number": number,
            "created_at": "2026-08-01T12:00:00Z",
            "body": f"- Workflow: `{workflow}`\n",
        }

    def test_allows_creation_below_global_and_workflow_limits(self) -> None:
        client = MagicMock()
        client.get.return_value = self._response([self._issue(1)])

        decision = heal.check_incident_budget(
            "CI/CD Pipeline",
            token="tok",
            repo="a/b",
            client=client,
            now_ts=datetime(2026, 8, 1, 13, tzinfo=UTC).timestamp(),
            max_open=20,
            max_open_per_workflow=5,
            max_recent=20,
        )

        assert decision.allowed is True
        assert decision.reason == "within_budget"
        assert decision.open_total == 1
        assert decision.open_for_workflow == 1

    def test_blocks_global_open_incident_storm(self) -> None:
        client = MagicMock()
        client.get.return_value = self._response([self._issue(i) for i in range(20)])

        decision = heal.check_incident_budget(
            "CI/CD Pipeline",
            token="tok",
            repo="a/b",
            client=client,
            max_open=20,
            max_open_per_workflow=50,
            max_recent=50,
        )

        assert decision.allowed is False
        assert decision.reason == "global_open_incidents:20>=20"
        assert decision.open_total == 20

    def test_blocks_per_workflow_queue(self) -> None:
        client = MagicMock()
        client.get.return_value = self._response(
            [self._issue(1, "Deploy"), self._issue(2, "Deploy")]
        )

        decision = heal.check_incident_budget(
            "Deploy",
            token="tok",
            repo="a/b",
            client=client,
            max_open=20,
            max_open_per_workflow=2,
            max_recent=20,
        )

        assert decision.allowed is False
        assert decision.reason == "workflow_open_incidents:2>=2"

    def test_lookup_failure_fails_closed(self) -> None:
        client = MagicMock()
        client.get.side_effect = RuntimeError("github unavailable")

        decision = heal.check_incident_budget(
            "CI/CD Pipeline", token="tok", repo="a/b", client=client
        )

        assert decision.allowed is False
        assert decision.reason == "budget_lookup_error:LookupFailed"

    def test_dynamic_titles_share_api_verified_workflow_budget(self) -> None:
        client = MagicMock()
        path = ".github/workflows/fhd-ci-cd.yml"
        incidents = [
            {"number": n, "body": f"- Workflow: `CI/CD {n:040x}`\n- Run ID: `{n}`\n"}
            for n in range(1, 6)
        ]

        def get(url, **kw):
            if url.endswith("/issues"):
                return self._response(incidents)
            run = int(url.rsplit("/", 1)[1])
            return self._response({"id": run, "workflow_id": 99, "path": path})

        client.get.side_effect = get
        result = heal.check_incident_budget(
            "CI/CD Pipeline",
            token="tok",
            repo="a/b",
            client=client,
            workflow_path=path,
            workflow_id=99,
        )
        assert result.reason == "workflow_open_incidents:5>=5" and result.open_for_workflow == 5

    def test_unavailable_legacy_run_does_not_guess_workflow_bucket(self) -> None:
        client = MagicMock()
        client.get.side_effect = [
            self._response([{"body": "- Run ID: `9`\n"}]),
            self._response({}, status_code=404),
        ]
        result = heal.check_incident_budget(
            "CI/CD Pipeline",
            token="tok",
            repo="a/b",
            client=client,
            workflow_path=".github/workflows/fhd-ci-cd.yml",
            workflow_id=99,
        )
        assert not result.allowed and result.reason == "budget_lookup_error:LookupFailed"


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


_LLM_ENDPOINT = "https://llm.internal.test/v1/fix"


class TestCallLlm:
    def test_missing_endpoint_never_sends_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未配置 XCAGI_LLM_ENDPOINT 时不得把密钥发往任何默认/占位地址。"""
        monkeypatch.delenv("XCAGI_LLM_ENDPOINT", raising=False)
        err = heal.ErrorEntry("ruff", "F401", "msg", "f", 1, "raw")
        client = MagicMock()
        assert heal.call_llm([err], api_key="secret", client=client) is None
        client.post.assert_not_called()

    def test_endpoint_from_env_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_LLM_ENDPOINT", _LLM_ENDPOINT)
        err = heal.ErrorEntry("ruff", "F401", "msg", "f", 1, "raw")
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 500
        client.post.return_value = resp
        assert heal.call_llm([err], api_key="k", client=client) is None
        assert client.post.call_args.args[0] == _LLM_ENDPOINT

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
        result = heal.call_llm([err], api_key="k", endpoint=_LLM_ENDPOINT, client=client)
        assert result is None

    def test_http_500_returns_none(self) -> None:
        err = heal.ErrorEntry("ruff", "F401", "msg", "f", 1, "raw")
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 500
        client.post.return_value = resp
        result = heal.call_llm([err], api_key="k", endpoint=_LLM_ENDPOINT, client=client)
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
        result = heal.call_llm([err], api_key="k", endpoint=_LLM_ENDPOINT, client=client)
        assert result is not None
        assert len(result) == 1
        assert result[0].needs_human is False


# =====================================================================
# incident / dispatch 测试
# =====================================================================


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
        response.status_code = 200
        response.json.return_value = {"workflow_run_id": 404}
        intent = MagicMock(status_code=201)
        intent.json.return_value = {"id": 303}
        client.post.side_effect = [intent, response]
        client.patch.return_value.status_code = 200

        ok = heal.dispatch_issue_implementation(
            "https://github.com/owner/repo/issues/505",
            token="tok",
            repo="owner/repo",
            target_branch="feature/failing-ci",
            client=client,
        )

        assert ok is True
        assert client.post.call_args.kwargs["json"] == {
            "ref": "main",
            "return_run_details": True,
            "inputs": {
                "issue_number": "505",
                "target_branch": "feature/failing-ci",
            },
        }
        assert '"dispatch_run_id": 404' in client.patch.call_args.kwargs["json"]["body"]
        assert client.post.call_args.kwargs["headers"]["X-GitHub-Api-Version"] == "2022-11-28"

    def test_dispatch_timeout_keeps_durable_unknown_intent_without_retry(self) -> None:
        client = MagicMock()
        intent = MagicMock(status_code=201)
        intent.json.return_value = {"id": 303}
        client.post.side_effect = [intent, heal.httpx.ReadTimeout("unknown result")]
        client.patch.return_value.status_code = 200
        assert not heal.dispatch_issue_implementation(
            "https://github.com/a/b/issues/1", token="tok", repo="a/b", client=client
        )
        assert client.post.call_count == 2
        assert '"status": "unknown"' in client.patch.call_args.kwargs["json"]["body"]

    def test_intent_failure_prevents_untracked_dispatch(self) -> None:
        client = MagicMock()
        client.post.return_value.status_code = 403
        assert not heal.dispatch_issue_implementation(
            "https://github.com/a/b/issues/1", token="tok", repo="a/b", client=client
        )
        assert client.post.call_count == 1 and client.post.call_args.args[0].endswith("/comments")


# =====================================================================
# approval ledger 旁路调用测试
# =====================================================================


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
        assert heal.is_autonomy_branch(None) is False

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
    @pytest.fixture(autouse=True)
    def _allow_incident_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(heal, "find_existing_remediation_issue", lambda *a, **k: "")
        monkeypatch.setattr(
            heal, "recover_existing_incident", lambda *a, **k: {"state": "unresolved"}
        )
        monkeypatch.setattr(
            heal,
            "check_incident_budget",
            lambda *args, **kwargs: heal.IncidentBudgetDecision(True, "within_budget"),
        )
        monkeypatch.setattr(
            heal,
            "check_freshness",
            lambda *a, **k: heal.freshness.Decision("proceed", "not_code_ci_whitelisted"),
        )

    def test_no_run_id_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
        monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
        rc = heal.main(["--branch", "feature/x"])
        assert rc == 2

    def test_open_circuit_skips_llm_issue_and_dispatch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPOSITORY", "a/b")
        monkeypatch.setattr(
            heal,
            "fetch_workflow_logs",
            lambda *a, **k: "##[error]Process completed with exit code 1.",
        )
        monkeypatch.setattr(
            heal,
            "check_incident_budget",
            lambda *a, **k: heal.IncidentBudgetDecision(
                False,
                "global_open_incidents:20>=20",
                open_total=20,
            ),
        )
        calls: list[str] = []
        monkeypatch.setattr(
            heal,
            "call_llm",
            lambda *a, **k: calls.append("llm"),
        )
        monkeypatch.setattr(
            heal,
            "create_remediation_issue",
            lambda **kwargs: calls.append("issue") or "",
        )
        monkeypatch.setattr(
            heal,
            "dispatch_issue_implementation",
            lambda *a, **k: calls.append("dispatch") or True,
        )

        rc = heal.main(
            [
                "--run-id",
                "1",
                "--workflow",
                "CI/CD Pipeline",
                "--branch",
                "main",
                "--store",
                str(tmp_path / "fps.jsonl"),
            ]
        )

        assert rc == 2
        assert calls == []

    def test_empty_log_routes_incident_and_blocks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPOSITORY", "a/b")
        monkeypatch.setattr(heal, "fetch_workflow_logs", lambda *a, **k: "")
        monkeypatch.setattr(heal, "find_existing_remediation_issue", lambda *a, **k: "")
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

    def test_durable_fingerprint_keeps_unresolved_incident_visible(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPOSITORY", "a/b")
        log = "app/foo.py:10:1: F401 'os' imported but unused\n"
        monkeypatch.setattr(heal, "fetch_workflow_logs", lambda *a, **k: log)
        monkeypatch.setattr(
            heal,
            "find_existing_remediation_issue",
            lambda *a, **k: "https://github.com/a/b/issues/77",
        )
        created: list[object] = []
        monkeypatch.setattr(
            heal,
            "create_remediation_issue",
            lambda **kwargs: created.append(kwargs) or "",
        )

        rc = heal.main(
            [
                "--run-id",
                "1",
                "--workflow",
                "ci",
                "--branch",
                "feature/x",
                "--store",
                str(tmp_path / "fps.jsonl"),
            ]
        )

        assert rc == 2
        assert created == []
        assert not heal.is_already_processed(
            heal.compute_fingerprint(
                "a/b",
                "ci",
                "feature/x",
                "app/foo.py:10:1: F401 'os' imported but unused",
            ),
            store_path=tmp_path / "fps.jsonl",
        )

    def test_dry_run_does_not_create_pr(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPOSITORY", "a/b")
        log = "app/foo.py:10:1: F401 'os' imported but unused\n"
        monkeypatch.setattr(heal, "fetch_workflow_logs", lambda *a, **k: log)
        called = {"create_remediation_issue": False}

        def fake_create_remediation_issue(*args: object, **kwargs: object) -> str:
            called["create_remediation_issue"] = True
            return ""

        monkeypatch.setattr(heal, "create_remediation_issue", fake_create_remediation_issue)
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
        assert called["create_remediation_issue"] is False

    def test_local_fingerprint_does_not_bypass_durable_recovery(
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
        fp = heal.compute_fingerprint("a/b", "ci", "main", "\n".join(err_lines))
        heal.record_fingerprint(fp, "https://existing/pr", store_path=store)
        monkeypatch.setattr(
            heal,
            "find_existing_remediation_issue",
            lambda *a, **k: "https://github.com/a/b/issues/2",
        )
        resumed = []
        monkeypatch.setattr(
            heal,
            "recover_existing_incident",
            lambda *a, **k: resumed.append(a) or {"state": "resumed"},
        )

        called = {"create_remediation_issue": False}

        def fake_create_remediation_issue(*args: object, **kwargs: object) -> str:
            called["create_remediation_issue"] = True
            return ""

        monkeypatch.setattr(heal, "create_remediation_issue", fake_create_remediation_issue)
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
        assert rc == 2
        assert len(resumed) == 1
        assert called["create_remediation_issue"] is False  # 去重命中，不创建 PR


# =====================================================================
# apply_fixes 测试
# =====================================================================
