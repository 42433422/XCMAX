# mypy: disable-error-code="import-not-found"
"""escalate_to_human.py 单元测试。

覆盖：
- escalate() 调用 post_to_approval_ledger 参数正确（action / source / payload）
- post_to_approval_ledger 返回 None（fail-open）不阻断主流程
- 调用顺序：subprocess.run(comment) → subprocess.run(label) → append_event → post_to_approval_ledger
- subprocess.run 被调用 2 次（comment + label），命令字符串含 issue_number / needs-human
- append_event 被调用且 event_type=escalated_to_human
- GITHUB_REPO 缺失 → RuntimeError
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 把 FHD/scripts/dev 和 FHD/scripts/ci 加入 sys.path
FHD_ROOT = Path(__file__).resolve().parents[2]
DEV_SCRIPTS = FHD_ROOT / "scripts" / "dev"
CI_SCRIPTS = FHD_ROOT / "scripts" / "ci"
for _p in (DEV_SCRIPTS, CI_SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import escalate_to_human as esc  # noqa: E402

# =====================================================================
# fixtures
# =====================================================================


@pytest.fixture
def env_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """注入必要的 env。"""
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")


@pytest.fixture
def proposal() -> dict:
    return {
        "triggered_by": "ai_issue_implement",
        "summary": "fix bug X",
        "files": ["app/foo.py"],
    }


@pytest.fixture
def failure_reasons() -> list[str]:
    return ["retry 1 failed", "retry 2 failed", "retry 3 failed"]


# =====================================================================
# post_to_approval_ledger 调用
# =====================================================================


class TestLedgerCall:
    def test_ledger_called_with_correct_args(
        self,
        env_ok: None,
        proposal: dict,
        failure_reasons: list[str],
    ) -> None:
        with (
            patch.object(esc.subprocess, "run"),
            patch.object(esc, "append_event"),
            patch.object(esc, "post_to_approval_ledger") as mock_ledger,
            patch.object(esc, "notify_boss_im"),
        ):
            esc.escalate(
                issue_number=42,
                proposal=proposal,
                failure_reasons=failure_reasons,
            )

        mock_ledger.assert_called_once_with(
            action="ai_issue_implement",
            payload={
                "issue_number": 42,
                "failure_reasons": failure_reasons,
                "proposal": proposal,
            },
            source="ci_escalate",
            action_id="escalate:42",
        )

    def test_ledger_returns_none_does_not_break(
        self,
        env_ok: None,
        proposal: dict,
        failure_reasons: list[str],
    ) -> None:
        """client fail-open 返回 None 时主流程仍正常完成。"""
        with (
            patch.object(esc.subprocess, "run") as mock_run,
            patch.object(esc, "append_event") as mock_append,
            patch.object(esc, "post_to_approval_ledger", return_value=None) as mock_ledger,
            patch.object(esc, "notify_boss_im"),
        ):
            # 不应抛异常
            esc.escalate(
                issue_number=42,
                proposal=proposal,
                failure_reasons=failure_reasons,
            )

        mock_ledger.assert_called_once()
        mock_append.assert_called_once()
        assert mock_run.call_count == 2

    def test_ledger_called_after_append_event(
        self,
        env_ok: None,
        proposal: dict,
        failure_reasons: list[str],
    ) -> None:
        """调用顺序：append_event 在 post_to_approval_ledger 之前。"""
        manager = MagicMock()
        with (
            patch.object(esc.subprocess, "run"),
            patch.object(esc, "append_event", manager.append_event),
            patch.object(esc, "post_to_approval_ledger", manager.post_to_approval_ledger),
            patch.object(esc, "notify_boss_im"),
        ):
            esc.escalate(
                issue_number=1,
                proposal=proposal,
                failure_reasons=failure_reasons,
            )

        # 通过 manager.mock_calls 顺序断言
        method_names = [c[0] for c in manager.mock_calls]
        assert "append_event" in method_names
        assert "post_to_approval_ledger" in method_names
        assert method_names.index("append_event") < method_names.index("post_to_approval_ledger")


# =====================================================================
# 原有行为不变：subprocess / append_event / GITHUB_REPO
# =====================================================================


class TestExistingBehavior:
    def test_subprocess_run_called_twice_for_comment_and_label(
        self,
        env_ok: None,
        proposal: dict,
        failure_reasons: list[str],
    ) -> None:
        with (
            patch.object(esc.subprocess, "run") as mock_run,
            patch.object(esc, "append_event"),
            patch.object(esc, "post_to_approval_ledger"),
            patch.object(esc, "notify_boss_im"),
        ):
            esc.escalate(
                issue_number=7,
                proposal=proposal,
                failure_reasons=failure_reasons,
            )

        assert mock_run.call_count == 2
        # 第一次：comment
        first_cmd = mock_run.call_args_list[0].args[0]
        assert "gh issue comment 7" in first_cmd
        assert "needs-human" not in first_cmd  # comment 不带 label
        # 第二次：label
        second_cmd = mock_run.call_args_list[1].args[0]
        assert "gh issue edit 7" in second_cmd
        assert "needs-human" in second_cmd

    def test_append_event_called_with_correct_event_type(
        self,
        env_ok: None,
        proposal: dict,
        failure_reasons: list[str],
    ) -> None:
        with (
            patch.object(esc.subprocess, "run"),
            patch.object(esc, "append_event") as mock_append,
            patch.object(esc, "post_to_approval_ledger"),
            patch.object(esc, "notify_boss_im"),
        ):
            esc.escalate(
                issue_number=99,
                proposal=proposal,
                failure_reasons=failure_reasons,
            )

        mock_append.assert_called_once()
        event = mock_append.call_args.args[0]
        assert event["event_type"] == "escalated_to_human"
        assert event["issue_number"] == 99
        assert event["failure_reasons"] == failure_reasons
        assert event["final_status"] == "needs_human"
        assert event["llm_proposal"] == proposal

    def test_missing_github_repo_raises_runtime_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        proposal: dict,
        failure_reasons: list[str],
    ) -> None:
        monkeypatch.delenv("GITHUB_REPO", raising=False)
        with pytest.raises(RuntimeError, match="GITHUB_REPO"):
            esc.escalate(
                issue_number=1,
                proposal=proposal,
                failure_reasons=failure_reasons,
            )
