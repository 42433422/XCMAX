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
        calls.append({"employee_id": employee_id, "task_text": task_text, "user_id": user_id})
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


def test_code_step_accepted_para_timeout_does_not_start_duplicate_retry(
    monkeypatch, captured_ledger
):
    """已受理 Para 任务等待超时后，不能把它当成代码缺陷再次派发。"""
    timeout = {
        "result": {
            "ok": False,
            "outputs": [
                {
                    "accepted": True,
                    "error": "Para task task-1 未在 900s 内完成",
                    "handler": "para_delegate",
                    "ok": False,
                    "para_result": {"task_id": "task-1", "task_status": "running"},
                    "status": "para_task_timeout",
                }
            ],
            "status": "failed",
        }
    }
    calls = _patch_dispatch(monkeypatch, [timeout])

    outcome = mod._run_step_with_inner_retries(
        employee_id="vibe-coding-maintainer",
        step_name="code",
        task_text="base task",
        extra={},
        user_id=1,
        run_id="run-timeout",
    )
    _, ok, failure_reason, para_meta, _, code_fix_rounds, _ = outcome

    assert ok is False
    assert "未在 900s 内完成" in failure_reason
    assert para_meta["task_id"] == "task-1"
    assert code_fix_rounds == 0
    assert len(calls) == 1
    assert not [record for record in captured_ledger if record.get("phase") == "step_retry"]
    # Outer dispatch retry path must also refuse to treat this as transient.
    assert mod._is_accepted_para_wait_timeout(timeout) is True
    assert mod._is_transient_employee_dispatch_failure(timeout) is False


def test_para_success_nested_delivery_validation_marks_completion(monkeypatch, captured_ledger):
    """Mock Para success + nested delivery_validation(all exit 0) → validate/writeback ok."""
    dv = {
        "commands": [
            {
                "command": "pytest tests/test_self_maintenance_inner_retries.py",
                "exit_code": 0,
                "output_tail": "1 passed",
            },
            {"command": "ruff check .", "exit_code": 0},
        ],
        "ok": True,
    }
    success = {
        "result": {
            "ok": True,
            "status": "completed",
            "outputs": [
                {
                    "accepted": True,
                    "completed": True,
                    "handler": "para_delegate",
                    "ok": True,
                    "status": "para_task_completed",
                    "para_result": {
                        "task_id": "task-dv-ok",
                        "status": "completed",
                        "subtasks": [
                            {
                                "id": "sub-1",
                                "branch": "devfleet/codex/fix-dv-ok",
                                "delivery_validation": dv,
                            }
                        ],
                    },
                }
            ],
        }
    }
    calls = _patch_dispatch(monkeypatch, [success])

    result, ok, failure_reason, para_meta, _, code_fix_rounds, marker_rounds = (
        mod._run_step_with_inner_retries(
            employee_id="vibe-coding-maintainer",
            step_name="code",
            task_text="base task with kb writeback",
            extra={},
            user_id=1,
            run_id="run-dv-ok",
        )
    )

    assert ok is True
    assert failure_reason == ""
    assert code_fix_rounds == 0
    assert marker_rounds == 0
    assert len(calls) == 1
    assert para_meta["task_id"] == "task-dv-ok"
    assert para_meta["branch"] == "devfleet/codex/fix-dv-ok"
    gate = mod._delivery_validation_gate(result)
    assert gate["found"] is True
    assert gate["ok"] is True
    assert gate["reason"] == "delivery_validation_passed"
    assert gate["delivery_validation"] is dv
    assert mod._employee_result_ok(result) is True
    assert not [record for record in captured_ledger if record.get("phase") == "step_retry"]


def test_nested_delivery_validation_failure_blocks_completion_even_if_envelope_ok():
    """Outer ok=True 但 nested DV exit_code≠0 → 不得标完成。"""
    result = {
        "result": {
            "ok": True,
            "status": "completed",
            "outputs": [
                {
                    "handler": "para_delegate",
                    "ok": True,
                    "para_result": {
                        "delivery_validation": {
                            "commands": [
                                {
                                    "command": "pytest tests/bad.py",
                                    "exit_code": 1,
                                    "output_tail": "FAILED",
                                }
                            ]
                        }
                    },
                }
            ],
        }
    }

    gate = mod._delivery_validation_gate(result)
    assert gate["found"] is True
    assert gate["ok"] is False
    assert gate["reason"] == "delivery_validation_failed"
    assert mod._employee_result_ok(result) is False
    reason = mod._extract_failure_reason(result, {})
    assert "delivery_validation_failed" in reason
    assert "exit=1" in reason


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
                    '"risk_class":"low","target_branch_available":true,"tested_commands":[],'
                    '"dimensions":{'
                    '"security":{"status":"pass","findings":[]},'
                    '"business_logic":{"status":"pass","findings":[]},'
                    '"performance":{"status":"pass","findings":[]}}}'
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
    # 第二次 task_text 应包含协议打回提醒
    assert "PROTOCOL REJECTED" in calls[1]["task_text"]
    assert "SELF_MAINTENANCE_REVIEW_JSON" in calls[1]["task_text"]


def test_review_step_incomplete_dimensions_protocol_rerun(monkeypatch, captured_ledger):
    """有 marker 但缺 dimensions → 协议打回 → 补齐后通过。"""
    calls = _patch_dispatch(
        monkeypatch,
        [
            _make_result(
                ok=True,
                report=(
                    "SELF_MAINTENANCE_REVIEW_JSON: "
                    '{"max_severity":"low","blocking_findings":[],'
                    '"risk_class":"low","target_branch_available":true,"tested_commands":[]}'
                ),
            ),
            _make_result(
                ok=True,
                report=(
                    "SELF_MAINTENANCE_REVIEW_JSON: "
                    '{"max_severity":"low","blocking_findings":[],'
                    '"risk_class":"low","target_branch_available":true,"tested_commands":[],'
                    '"dimensions":{'
                    '"security":{"status":"pass","findings":[]},'
                    '"business_logic":{"status":"pass","findings":[]},'
                    '"performance":{"status":"n/a","findings":[]}}}'
                ),
            ),
        ],
    )

    _, ok, _, _, _, _, marker_rounds = mod._run_step_with_inner_retries(
        employee_id="change-request-auditor",
        step_name="review",
        task_text="base review",
        extra={},
        user_id=1,
        run_id="run-3b",
    )

    assert ok is True
    assert marker_rounds == 1
    assert len(calls) == 2
    assert "missing_dimensions" in calls[1]["task_text"]


def test_qa_executor_outage_retries_fresh_report_only_task(monkeypatch, captured_ledger):
    """QA shell outage is infrastructure evidence, so retry QA instead of accepting FAIL."""
    outage_report = (
        "SELF_MAINTENANCE_QA_JSON: "
        '{"verdict":"FAIL","blocking_findings":['
        '"QA worker shell execution backend unavailable; could not run focused pytest.",'
        '"Missing successful focused tested_commands entry.",'
        '"Diff review not executed due same backend failure."],'
        '"tested_commands":[{"command":"python -m pytest focused.py -q",'
        '"exit_code":1,"status":"failed"}],'
        '"quality_checks":{},'
        '"target_branch_available":true,'
        '"test_delta":{"new_failures":["focused pytest not executed"],'
        '"new_errors":["shell execution backend unavailable; no observable exit codes"]},'
        '"changed_files_scope":"medium","risk_class":"high"}'
    )
    pass_report = (
        "SELF_MAINTENANCE_QA_JSON: "
        '{"verdict":"PASS","blocking_findings":[],'
        '"tested_commands":[{"command":"python -m pytest focused.py -q",'
        '"exit_code":0,"status":"passed"}],'
        '"quality_checks":{},'
        '"target_branch_available":true,'
        '"test_delta":{"new_failures":[],"new_errors":[]},'
        '"changed_files_scope":"low","risk_class":"low"}'
    )
    calls = _patch_dispatch(
        monkeypatch,
        [
            _make_result(ok=True, report=outage_report),
            _make_result(ok=True, report=pass_report),
        ],
    )

    _, ok, _, _, report, _, marker_rounds = mod._run_step_with_inner_retries(
        employee_id="test-qa-runner",
        step_name="qa",
        task_text="base qa",
        extra={},
        user_id=1,
        run_id="run-qa-executor-retry",
    )

    assert ok is True
    assert marker_rounds == 1
    assert pass_report in report
    assert len(calls) == 2
    assert "PREVIOUS QA EXECUTOR UNAVAILABLE" in calls[1]["task_text"]
    assert captured_ledger[0]["error"] == "structured_qa_executor_unavailable"


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
