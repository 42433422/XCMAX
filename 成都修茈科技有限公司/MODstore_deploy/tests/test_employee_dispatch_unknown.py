"""Unknown remote outcomes must survive every local fallback and retry boundary."""

from __future__ import annotations

import pytest

from modstore_server import employee_executor
from modstore_server.maintenance_loop import dispatch, para_client, results, store


@pytest.fixture(
    params=[
        {"status": "para_api_failed_outboxed", "outcome": "unknown", "accepted": False},
        {
            "status": "para_api_failed_outboxed",
            "requires_reconciliation": True,
            "accepted": True,
            "task_id": "original-task",
            "devices": [{"device_id": "worker-1", "subtask_id": "original-subtask"}],
        },
        {"status": "para_task_timeout", "accepted": True, "task_id": "original-task"},
        {"status": "denied", "retryable": False},
        {
            "status": "para_task_accepted",
            "ok": True,
            "accepted": True,
            "task_id": "original-task",
        },
    ],
    ids=[
        "lost-ack",
        "partial-fleet",
        "accepted-timeout",
        "non-retryable",
        "accepted-pending",
    ],
)
def receipt(request):
    return {
        "handler": "para_delegate",
        "ok": False,
        "error": "Para API 调用失败: connection refused while awaiting receipt",
        **request.param,
    }


def test_employee_action_preserves_receipt_without_local_fallback(monkeypatch, receipt):
    monkeypatch.setattr(
        "modstore_server.para_delegate_handler.dispatch_para_delegate",
        lambda **kwargs: receipt,
    )
    monkeypatch.setattr(
        employee_executor,
        "_action_agent_runner",
        lambda *args: pytest.fail("remote work must not be duplicated by the local agent"),
    )
    result = employee_executor._actions_real(
        {"handlers": ["para_delegate", "agent"]},
        {"input": {"im_reply_managed": True}},
        "repair synthetic bug",
        "synthetic-worker",
    )
    assert result["outputs"] == [receipt]


def test_maintenance_transport_retry_does_not_resubmit_unknown(monkeypatch, receipt):
    result = {"result": {"outputs": [receipt]}}
    calls = []

    def execute(*args, **kwargs):
        calls.append(args)
        assert len(calls) == 1, "unknown dispatch was resubmitted"
        return result

    monkeypatch.setattr(employee_executor, "execute_employee_task", execute)
    monkeypatch.setattr(para_client, "_wait_for_para_device_online", lambda: {"online": True})
    monkeypatch.setattr(dispatch, "_loop_platform_bench_override", lambda: None)
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_STEP_RETRIES", "2")
    returned = dispatch._execute_employee_task_with_retries("worker", "repair", {}, user_id=1)
    assert returned["self_maintenance_retry_attempts"] == 1
    assert returned["result"]["outputs"] == [receipt]
    assert results._is_transient_employee_dispatch_failure(returned) is False
    assert results._employee_result_ok(returned) is False


@pytest.mark.parametrize("step_name", ["code", "review"])
def test_maintenance_inner_retry_keeps_original_receipt(monkeypatch, receipt, step_name):
    result = {"result": {"outputs": [receipt]}}
    calls = []

    def execute(*args, **kwargs):
        calls.append(args)
        assert len(calls) == 1, "inner code/marker retry repeated remote work"
        return result

    monkeypatch.setattr(dispatch, "_execute_employee_task_with_retries", execute)
    monkeypatch.setattr(para_client, "_fetch_para_task_report_excerpt", lambda *args: "")
    monkeypatch.setattr(store, "_append_ledger", lambda row: pytest.fail("unexpected retry"))
    returned, ok, _, para_meta, _, code_retries, marker_retries = (
        dispatch._run_step_with_inner_retries(
            employee_id="worker",
            step_name=step_name,
            task_text="repair synthetic bug",
            extra={},
            user_id=1,
            run_id="original-run",
        )
    )
    assert returned["result"]["outputs"] == [receipt]
    assert para_meta["task_id"] == receipt.get("task_id")
    assert ok is False
    assert (code_retries, marker_retries) == (0, 0)


def test_local_fallback_remains_available_after_definite_pre_send_failure(monkeypatch):
    receipt = {
        "handler": "para_delegate",
        "ok": False,
        "accepted": False,
        "queued": False,
        "status": "blocked_no_online_para_device",
    }
    monkeypatch.setattr(
        "modstore_server.para_delegate_handler.dispatch_para_delegate",
        lambda **kwargs: receipt,
    )
    monkeypatch.setattr(
        employee_executor,
        "_action_agent_runner",
        lambda *args: {"handler": "agent", "ok": True},
    )
    result = employee_executor._actions_real(
        {"handlers": ["para_delegate", "agent"]},
        {"input": {"im_reply_managed": True}},
        "repair synthetic bug",
        "synthetic-worker",
    )
    assert result["outputs"] == [receipt, {"handler": "agent", "ok": True}]
