"""Exercise the shipped process adapter, including late subprocess side effects."""

import json
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import (
    AgentToolExecutor,
    execute_with_tool_deadline,
)
from app.application.tool_execution_deadline import invocation_deadline


def _step(action="read", **params):
    return AgentStep(node_id=action, tool_id="fixture", action=action, params=params)


class FixtureExecutor(AgentToolExecutor):
    def execute(self, step, *, runtime_context):
        if step.action == "llm":
            from app.application.employee_runtime.agent_loop import run_employee_agent_loop
            from app.application.employee_runtime.agent_runner import _chat_completion, _run_async
            from app.application.workflow.planner import LLMWorkflowPlanner
            from app.application.workflow.planner_llm_gateway import request_planner_completion
            from app.application.workflow.types import PlanGraph

            planner = request_planner_completion(ai_service=None, context={}, messages=[])
            agent = run_employee_agent_loop(
                employee_id="fixture", system_prompt="test", task="test", tools=[]
            )
            cognition = _run_async(_chat_completion([]))
            repair = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
            repair._ai_service = None
            critic = repair._critic_repair_with_llm(
                "fixture", "owner", "test", {}, {}, "invalid", PlanGraph("invalid", "test")
            )
            return {
                "success": agent["ok"],
                "planner_model": planner["model"],
                "cognition_model": cognition["model"],
                "critic_model": critic.intent,
            }
        if step.tool_id == "business_db":
            return {"success": True, "business_verification": {"verified": True, "record_id": 42}}
        if step.action == "typed_result":
            from datetime import date
            from decimal import Decimal

            return {"success": True, "price": Decimal("99.50"), "date": date(2026, 10, 21)}
        if step.action == "invalid_result":
            return {"success": True, "live_object": object()}
        if step.action == "hang":
            script = (
                "import os,time,json;from pathlib import Path;"
                f"deadline=time.monotonic()+{step.params['late_after']};"
                f"Path({step.params['receipt']!r}).write_text(json.dumps([{os.getpid()},os.getpid(),deadline]));"
                "time.sleep(max(0,deadline-time.monotonic()));"
                f"Path({step.params['late']!r}).write_text('late')"
            )
            subprocess.Popen([sys.executable, "-c", script])
            while True:
                time.sleep(1)
        if step.action == "uncertain":
            with invocation_deadline(float("inf")) as budget:
                budget.uncertain.append({"kind": "http_timeout", "method": "POST"})
        return {"success": True, "tenant": runtime_context.get("tenant_id"), "pid": os.getpid()}


@pytest.mark.parametrize("budget", [2, 8])
def test_real_adapter_reaps_hung_tool_and_child_then_reuses_executor(tmp_path, budget):
    executor = FixtureExecutor()
    children = {child.pid for child in multiprocessing.active_children()}
    late, receipt = tmp_path / "late", tmp_path / "receipt"
    start = time.monotonic()
    result = execute_with_tool_deadline(
        executor,
        _step("hang", late=str(late), receipt=str(receipt), late_after=budget + 3),
        runtime_context={"tenant_id": 7},
        timeout_seconds=budget,
    )
    print({"budget": budget, "result": result, "child_receipt": receipt.exists()})
    assert time.monotonic() - start < budget + 3
    if budget == 2 and not receipt.exists():
        code = result.get("reconciliation_evidence", result).get("error_code")
        assert result["retryable"] is False
        if code == "tool_worker_incomplete":
            # Ready/start can complete before the grandchild writes its receipt.
            assert result["outcome"] == "unknown" and result["reconciliation_required"]
        else:
            assert code == "tool_worker_not_started", result
        write_deadline = start + 2 * budget + 3
    else:
        assert result.get("outcome") == "unknown" and result["retryable"] is False, result
        worker_pid, child_pid, write_deadline = json.loads(receipt.read_text())
        assert all(not psutil.pid_exists(pid) for pid in (worker_pid, child_pid))
    assert {child.pid for child in multiprocessing.active_children()} <= children
    assert not late.exists()
    next_result = execute_with_tool_deadline(
        executor,
        _step(),
        runtime_context={"tenant_id": 9},
        timeout_seconds=5,
    )
    assert next_result["success"] and next_result["tenant"] == 9
    assert next_result["pid"] != os.getpid()
    time.sleep(max(0, write_deadline + 0.5 - time.monotonic()))
    assert not late.exists()


def test_child_unknown_io_cannot_be_hidden_by_successful_tool():
    result = execute_with_tool_deadline(
        FixtureExecutor(),
        _step("uncertain"),
        runtime_context={},
        timeout_seconds=5,
    )
    assert result["outcome"] == "unknown" and result["reconciliation_required"]
    assert result["io_reconciliation"] == [{"kind": "http_timeout", "method": "POST"}]


def test_spawned_write_target_returns_to_owner_and_conversation(monkeypatch):
    from app.application.agent_task_context import scoped_conversation_user_id
    from app.services import tools_workflow_common as targets

    monkeypatch.setattr(targets, "_RECENT_BUSINESS_DB_TARGETS", {})
    context = {
        "user_id": "2",
        "local_user_id": 2,
        "tenant_id": 7,
        "mod_id": "a",
        "session_id": "same",
    }
    step = AgentStep(
        node_id="write",
        tool_id="business_db",
        action="write",
        params={"entity": "customers", "operation": "create", "payload": {}},
    )
    assert execute_with_tool_deadline(
        FixtureExecutor(), step, runtime_context=context, timeout_seconds=5
    )["success"]
    key = scoped_conversation_user_id("2", context)
    assert targets.get_recent_business_db_target(key) == {"entity": "customers", "id": 42}
    for field, value in [
        ("local_user_id", 3),
        ("tenant_id", 8),
        ("mod_id", "b"),
        ("session_id", "other"),
    ]:
        assert (
            targets.get_recent_business_db_target(
                scoped_conversation_user_id("2", {**context, field: value})
            )
            is None
        )


@pytest.mark.parametrize("receipt", [None, {"verified": False, "record_id": 9}, {"verified": True}])
def test_follow_up_memory_never_queries_database_or_infers_an_unverified_record(
    monkeypatch, receipt
):
    from types import SimpleNamespace

    from app.services import tools_workflow_common as targets

    monkeypatch.setattr(targets, "_RECENT_BUSINESS_DB_TARGETS", {})
    monkeypatch.setattr(
        targets,
        "_business_db_target_candidates",
        lambda *_: pytest.fail("memory must not query DB"),
    )
    result = {"success": True, "data": {"id": 9}, "business_verification": receipt}
    executor = SimpleNamespace(execute_with_deadline=lambda *_, **__: result)
    step = AgentStep(
        node_id="write",
        tool_id="business_db",
        action="write",
        params={"entity": "customers", "operation": "create", "payload": {"id": 9}},
    )
    assert (
        execute_with_tool_deadline(
            executor, step, runtime_context={"user_id": "owner"}, timeout_seconds=5
        )
        is result
    )
    assert targets.get_recent_business_db_target("owner") is None


@pytest.mark.parametrize("client_kind", ["openai", "modstore"])
def test_spawned_planner_agent_and_cognition_keep_each_requests_model_and_credentials(
    monkeypatch, client_kind
):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from openai import OpenAI

    from app.infrastructure.llm.client import llm_client_scope

    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.headers["Authorization"], payload["model"]))
            reply = {
                "id": "fixture",
                "object": "chat.completion",
                "created": 0,
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "intent": payload["model"],
                                    "nodes": [
                                        {"node_id": "n", "tool_id": "clarify", "action": "ask"}
                                    ],
                                }
                            ),
                        },
                    }
                ],
            }
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def execute(owner):
            from app.services.conversation.modstore_adapter import (
                ModstoreOpenAICompatibleClient,
                ModstorePlatformAdapter,
            )

            base = f"http://127.0.0.1:{server.server_port}"
            client = (
                OpenAI(api_key=f"fake-{owner}", base_url=f"{base}/v1")
                if client_kind == "openai"
                else ModstoreOpenAICompatibleClient(
                    ModstorePlatformAdapter(platform_url=base, auth_token=f"fake-{owner}")
                )
            )
            try:
                with llm_client_scope(client, owner):
                    result = execute_with_tool_deadline(
                        FixtureExecutor(),
                        _step("llm"),
                        runtime_context={"user_id": owner},
                        timeout_seconds=15,
                    )
            finally:
                if client_kind == "openai":
                    client.close()
            assert result == {
                "success": True,
                "planner_model": owner,
                "cognition_model": owner,
                "critic_model": owner,
            }

        try:
            with ThreadPoolExecutor(max_workers=2) as workers:
                list(workers.map(execute, ["owner-a", "owner-b"]))
        finally:
            server.shutdown()
            thread.join()
    assert sorted(seen) == [
        (f"Bearer fake-{owner}", owner) for owner in ["owner-a", "owner-b"] for _ in range(4)
    ]


def test_default_adapter_refuses_unserializable_or_expired_start_without_dispatch():
    children = {child.pid for child in multiprocessing.active_children()}
    for context, budget, codes in (
        ({"transaction": object()}, 1, {"tool_context_not_serializable"}),
        ({}, 0.001, {"tool_worker_not_started", "tool_timeout_unknown"}),
    ):
        result = execute_with_tool_deadline(
            AgentToolExecutor(),
            _step(),
            runtime_context=context,
            timeout_seconds=budget,
        )
        assert result["error_code"] in codes and result["success"] is False, result
        assert {child.pid for child in multiprocessing.active_children()} <= children


def test_real_adapter_transports_database_scalars_and_reports_unsupported_result():
    executor = FixtureExecutor()
    result = execute_with_tool_deadline(
        executor,
        _step("typed_result"),
        runtime_context={},
        timeout_seconds=5,
    )
    assert result["success"] and result["price"] == 99.5
    assert result["date"] == "2026-10-21"
    started = time.monotonic()
    invalid = execute_with_tool_deadline(
        executor,
        _step("invalid_result"),
        runtime_context={},
        timeout_seconds=20,
    )
    assert time.monotonic() - started < 10
    assert invalid["outcome"] == "unknown" and invalid["retryable"] is False
    assert "tool_result_transport_failed" in str(invalid)


@pytest.mark.parametrize("cleanup_error", [FileNotFoundError, PermissionError])
def test_cleanup_races_preserve_results_and_unresolved_cleanup_blocks_reuse(
    monkeypatch, cleanup_error
):
    from app.application.agent_orchestrator import tool_process

    remove = tool_process.shutil.rmtree

    def raced_cleanup(folder, *, onerror):
        remove(folder, onerror=onerror)
        onerror(os.unlink, folder, (cleanup_error, cleanup_error("cleanup race"), None))

    monkeypatch.setattr(tool_process.shutil, "rmtree", raced_cleanup)
    executor = FixtureExecutor()
    result = execute_with_tool_deadline(
        executor, _step(), runtime_context={"tenant_id": 9}, timeout_seconds=5
    )
    if cleanup_error is FileNotFoundError:
        assert result["success"] and result["tenant"] == 9
        assert not getattr(executor, "_tool_cleanup_failed", False)
    else:
        assert result["outcome"] == "unknown"
        assert executor._tool_cleanup_failed
        again = execute_with_tool_deadline(executor, _step(), runtime_context={}, timeout_seconds=5)
        assert again["error_code"] == "tool_cleanup_unresolved"
