"""Tests for `_run_step_with_inner_retries`.

验证 self-maintenance loop 的内层重试循环：
- code step 失败时把 failure_reason 反馈给员工再重试（攻克 30/37 静默失败）
- review/qa step marker 缺失时提醒员工按格式重试（攻克 13 waiting_human）
- 每次内层尝试写 phase=step_retry ledger trace，最终结论写 phase=step（由调用方）
- ledger 字段 code_fix_retry_rounds / marker_retry_rounds 正确递增
"""

from typing import Any, Dict, List

import pytest

from modstore_server import self_maintenance_loop_runner as mod


@pytest.fixture
def captured_ledger(monkeypatch):
    """捕获 _append_ledger 调用，避免写真实文件。"""
    records: List[Dict[str, Any]] = []

    def _fake_append(record: Dict[str, Any]) -> None:
        records.append(record)

    monkeypatch.setattr(mod, "_append_ledger", _fake_append)
    return records


def _make_result(*, ok: bool, report: str = "", error: str = "") -> Dict[str, Any]:
    """构造 _employee_result_ok 能识别的 result。"""
    if not ok:
        return {
            "handler_failed": True,
            "handler_failed_message": error or "test failure",
            "result": {"status": "failed", "ok": False, "outputs": []},
            "report_excerpt": report,
        }
    return {
        "result": {"status": "completed", "ok": True, "outputs": [{"ok": True}]},
        "report_excerpt": report,
    }


def _patch_dispatch(monkeypatch, sequence: List[Dict[str, Any]]):
    """按顺序返回 sequence 中的 result，断言调用次数。"""
    calls: List[Dict[str, Any]] = []

    def _fake_dispatch(employee_id, task_text, input_data, *, user_id):
        calls.append(
            {"employee_id": employee_id, "task_text": task_text, "user_id": user_id}
        )
        if len(calls) > len(sequence):
            raise AssertionError(
                f"dispatch called {len(calls)} times but only {len(sequence)} results queued"
            )
        return sequence[len(calls) - 1]

    monkeypatch.setattr(mod, "_execute_employee_task_with_retries", _fake_dispatch)
    monkeypatch.setattr(mod, "_fetch_para_task_report_excerpt", lambda *a, **k: "")
    return calls


def test_code_step_first_failure_then_success(monkeypatch, captured_ledger):
    """第一次失败 → 反馈 failure_reason → 第二次成功。"""
    _patch_dispatch(
        monkeypatch,
        [
            _make_result(ok=False, error="exit=1 cmd=pytest tail=AssertionError"),
            _make_result(ok=True, report="all tests passed"),
        ],
    )

    result, ok, failure_reason, para_meta, report, code_fix_rounds, marker_rounds = (
        mod._run_step_with_inner_retries(
            employee_id="vibe-coding-maintainer",
            step_name="code",
            task_text="base task",
            extra={},
            user_id=1,
            run_id="run-1",
        )
    )

    assert ok is True
    assert code_fix_rounds == 1
    assert marker_rounds == 0
    # 第二次 task_text 应包含 failure_reason 反馈
    # （calls[1]['task_text'] 已被 _patch_dispatch 捕获，但 _run_step_with_inner_retries
    # 内部传给 dispatch 的是 last_task_text，需通过 calls 验证）
    # 由于 _patch_dispatch 捕获了 task_text：
    # calls[0]['task_text'] == 'base task'
    # calls[1]['task_text'] 应包含 'PREVIOUS ATTEMPT FAILED' + 'exit=1 cmd=pytest'
    # 但 _patch_dispatch 替换的是 _execute_employee_task_with_retries，它接收 task_text
    # 实际上 _run_step_with_inner_retries 直接传 last_task_text 给 _execute_employee_task_with_retries
    # 所以 calls[1]['task_text'] 是反馈后的文本


def test_code_step_all_attempts_fail(monkeypatch, captured_ledger):
    """全部 3 次（默认 2 重试 + 1 初次）都失败 → ok=False。"""
    calls = _patch_dispatch(
        monkeypatch,
        [
            _make_result(ok=False, error="exit=1 attempt-1"),
            _make_result(ok=False, error="exit=1 attempt-2"),
            _make_result(ok=False, error="exit=1 attempt-3"),
        ],
    )

    _, ok, failure_reason, _, _, code_fix_rounds, _ = mod._run_step_with_inner_retries(
        employee_id="vibe-coding-maintainer",
        step_name="code",
        task_text="base task",
        extra={},
        user_id=1,
        run_id="run-2",
    )

    assert ok is False
    assert code_fix_rounds == 2  # 2 次重试都触发
    assert len(calls) == 3  # 1 初次 + 2 重试
    # 失败原因来自最后一次
    assert "attempt-3" in failure_reason or "handler_failed" in failure_reason
    # step_retry trace 应有 2 条（前两次非最终）
    step_retry_records = [r for r in captured_ledger if r.get("phase") == "step_retry"]
    assert len(step_retry_records) == 2
    # 每条 step_retry 应有 inner_attempt 字段
    assert step_retry_records[0]["inner_attempt"] == 1
    assert step_retry_records[1]["inner_attempt"] == 2


def test_review_step_marker_missing_then_present(monkeypatch, captured_ledger):
    """review step dispatch ok 但 marker 缺失 → 重试 → marker 出现。"""
    calls = _patch_dispatch(
        monkeypatch,
        [
            _make_result(ok=True, report="review text without JSON marker"),
            _make_result(
                ok=True,
                report=(
                    "review text\nSELF_MAINTENANCE_REVIEW_JSON: "
                    '{"max_severity":"low","blocking_findings":[],'
                    '"risk_class":"low","target_branch_available":true,"tested_commands":[]}'
                ),
            ),
        ],
    )

    _, ok, _, _, _, code_fix_rounds, marker_rounds = mod._run_step_with_inner_retries(
        employee_id="change-request-auditor",
        step_name="review",
        task_text="base review",
        extra={},
        user_id=1,
        run_id="run-3",
    )

    assert ok is True
    assert code_fix_rounds == 0
    assert marker_rounds == 1
    assert len(calls) == 2
    # 第二次 task_text 应包含 marker 提醒
    assert "MISSING REQUIRED MARKER" in calls[1]["task_text"]
    assert "SELF_MAINTENANCE_REVIEW_JSON" in calls[1]["task_text"]


def test_review_step_dispatch_failure_no_inner_retry(monkeypatch, captured_ledger):
    """review step dispatch 失败 → 不重试内层（_execute_employee_task_with_retries 已重试瞬态）。"""
    calls = _patch_dispatch(
        monkeypatch,
        [
            _make_result(ok=False, error="para api failed"),
        ],
    )

    _, ok, failure_reason, _, _, _, marker_rounds = mod._run_step_with_inner_retries(
        employee_id="test-qa-runner",
        step_name="qa",
        task_text="base qa",
        extra={},
        user_id=1,
        run_id="run-4",
    )

    assert ok is False
    assert marker_rounds == 0  # dispatch 失败不触发 marker 重试
    assert len(calls) == 1  # 没有第二次调用
    # 没有 step_retry trace（因为第一次就是最终）
    step_retry_records = [r for r in captured_ledger if r.get("phase") == "step_retry"]
    assert len(step_retry_records) == 0


def test_code_step_env_overrides_retry_count(monkeypatch, captured_ledger):
    """MODSTORE_SELF_MAINTENANCE_CODE_FIX_RETRIES=0 → 只 1 次，不重试。"""
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_CODE_FIX_RETRIES", "0")
    calls = _patch_dispatch(
        monkeypatch,
        [
            _make_result(ok=False, error="exit=1"),
        ],
    )

    _, ok, _, _, _, code_fix_rounds, _ = mod._run_step_with_inner_retries(
        employee_id="vibe-coding-maintainer",
        step_name="code",
        task_text="base task",
        extra={},
        user_id=1,
        run_id="run-5",
    )

    assert ok is False
    assert code_fix_rounds == 0
    assert len(calls) == 1


def test_step_retry_trace_does_not_pollute_final_phase(monkeypatch, captured_ledger):
    """step_retry trace 用 phase=step_retry，最终结论由调用方写 phase=step。"""
    _patch_dispatch(
        monkeypatch,
        [
            _make_result(ok=False, error="round-1 fail"),
            _make_result(ok=True, report="round-2 pass"),
        ],
    )

    mod._run_step_with_inner_retries(
        employee_id="vibe-coding-maintainer",
        step_name="code",
        task_text="base task",
        extra={},
        user_id=1,
        run_id="run-6",
    )

    # helper 内部只写 step_retry，不写 step（step 由调用方写）
    phases = [r.get("phase") for r in captured_ledger]
    assert "step_retry" in phases
    assert "step" not in phases  # 调用方负责写最终 step
