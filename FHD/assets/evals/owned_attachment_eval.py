"""Owned-file Codex contracts: real parsing/session/SQL, scripted external model I/O."""

from __future__ import annotations

import io
import json
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


def _scripted_model_response(task: dict, prompt: dict) -> dict | None:
    """Judge only a declared fixture goal and its exact original request/effects.

    The positive judgement is fixture data, never inferred from a tool's success.
    Production still independently checks ownership, receipt and goal digests.
    """
    if (
        prompt.get("task") != "verify_runtime_goal"
        or prompt.get("original_request", {}).get("text") != task["message"]
        or not isinstance(task.get("runtime_review"), dict)
    ):
        return None
    actions = task.get("runtime_actions", [])
    evidence = prompt.get("evidence", [])
    keys = ("tool_id", "action", "params")
    expected = [{key: row[key] for key in keys} for row in actions]
    actual = [{key: row.get(key) for key in keys} for row in evidence]
    if actual != expected or prompt.get("response") != task.get(
        "runtime_reply", "本轮模型已结束。"
    ):
        return None
    result = json.loads(json.dumps(task["runtime_review"]))
    for goal in result["goals"]:
        selected = goal.pop("action_indexes", [])
        goal["evidence_ids"] = (
            ["response"]
            if goal["kind"] == "reply"
            else [evidence[index]["evidence_id"] for index in selected]
        )
    return result


def xiaox_eval_runtime(stack: ExitStack, root: Path, client, task: dict):
    """Real SQL admission, MCP, approval and reviewer; scripted external model I/O.

    This is explicitly a local fixture, not a real-model qualification or score.
    Shared synthetic evidence does not substitute business verification results.
    """
    import weakref

    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import db as host_db
    from app.application.agent_orchestrator import run_repository, task_execution_repository
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.agent_runtime import gateway
    from app.application.ai_chat import dialogue_memory
    from app.fastapi_routes.domains.agent.agent_routes import router
    from app.infrastructure.xiaox.binding import XiaoxBindingStore
    from app.infrastructure.xiaox.local_server import LocalRuntimeServer
    from app.infrastructure.xiaox.policy import ModelRoute, RuntimeSettings
    from app.infrastructure.xiaox.receipt_projection import (
        refresh_xiaox_receipts,
        resume_ready_xiaox_runs,
    )
    from tests.fixtures.xiaox_qualification import synthetic_qualification

    repository = SQLAlchemyAgentRunRepository(session_factory=host_db.HostSessionLocal)
    stack.enter_context(
        patch.object(task_execution_repository, "_OPEN_REPOSITORIES", weakref.WeakSet())
    )
    queue = SQLAlchemyTaskExecutionRepository(session_factory=host_db.HostSessionLocal)
    state = SimpleNamespace(
        repository=repository, queue=queue, inputs=[], reviews=[], receipts=[], servers=[]
    )
    stack.enter_context(
        patch.dict("os.environ", {"XCAGI_DIALOGUE_MEMORY_DIR": str(root / "dialogue")})
    )
    stack.enter_context(patch.object(dialogue_memory, "_INFLIGHT", {}))

    def release_turn_locks():
        for lock in tuple(dialogue_memory._INFLIGHT.values()):
            lock.release()
        dialogue_memory._INFLIGHT.clear()

    stack.callback(release_turn_locks)
    stack.enter_context(patch.object(run_repository, "_agent_run_repository", repository))
    stack.enter_context(
        patch.object(task_execution_repository, "_task_execution_repository", queue)
    )
    stack.enter_context(
        patch("app.fastapi_routes.domains.agent.agent_routes.notify_agent_task_dispatcher")
    )
    route = ModelRoute(
        base_url="http://127.0.0.1:19112/v1",
        model="offline-eval-fixture",
        provider_id="fixture",
        upstream_vendor="offline-fixture",
        context_window=32000,
        max_output_tokens=4000,
    )
    qualification = root / "offline-fixture-qualification.json"
    qualification.write_text(json.dumps(synthetic_qualification(route, root)), encoding="utf-8")
    settings = RuntimeSettings(
        route=route, runtime_root=root / "runtime", qualification_file=qualification
    )
    stack.enter_context(patch.object(gateway, "runtime_settings", lambda: settings))
    stack.enter_context(
        patch.dict(
            "os.environ", {"XCAGI_PRODUCT_SKU": "enterprise", "MODEL_USAGE_WALLET_BACKEND": "audit"}
        )
    )

    def upstream(request):
        body = json.loads(request.content)
        assert body["tools"] == [] and body["store"] is False
        prompt = json.loads(body["input"][1]["content"])
        state.reviews.append(prompt)
        review = _scripted_model_response(task, prompt)
        return httpx.Response(
            200,
            json={
                "id": "resp_offline_fixture",
                "object": "response",
                "created_at": 1,
                "model": body["model"],
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_offline_fixture",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(review, ensure_ascii=False),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
            },
        )

    class Server(LocalRuntimeServer):
        def __init__(self, app):
            state.servers.append(app)
            app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
                transport=httpx.MockTransport(upstream), **kwargs
            )
            super().__init__(app)

    class Transport:
        def __init__(self, config):
            self.config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def start_thread(self, *, developer_instructions):
            return "offline-eval-thread"

        async def resume_thread(self, thread_id, *, developer_instructions):
            return thread_id

        async def interrupt(self):
            return None

        async def stream_turn(self, text, *, goal_feedback=None, output_schema=None):
            state.inputs.append(text)
            bridge = state.servers[-1].state.xiaox_tool_bridge
            for action in task.get("runtime_actions", []):
                described = bridge.invoke(
                    self.config.mcp_token,
                    "capability_describe",
                    {key: action[key] for key in ("tool_id", "action")},
                )
                receipt = bridge.invoke(
                    self.config.mcp_token,
                    "execute_action",
                    {**action, "schema_digest": described["capability"]["schema_digest"]},
                )
                state.receipts.append(receipt)
                if receipt.get("status") in {
                    "waiting_user",
                    "blocked",
                    "unknown",
                    "running",
                    "queued",
                }:
                    break
            for method, payload in (
                ("turn/started", {"turn": {"status": "inProgress"}}),
                (
                    "item/completed",
                    {
                        "item": {
                            "type": "agentMessage",
                            "text": task.get("runtime_reply", "本轮模型已结束。"),
                        }
                    },
                ),
                ("turn/completed", {"turn": {"status": "completed"}}),
            ):
                yield {
                    "method": method,
                    "payload": payload,
                    "thread_id": "offline-eval-thread",
                    "turn_id": "offline-eval-turn",
                }

    stack.enter_context(patch.object(gateway, "LocalRuntimeServer", Server))
    stack.enter_context(patch("app.infrastructure.xiaox.XiaoxTransport", Transport))
    app = FastAPI()
    app.include_router(router)
    state.client = stack.enter_context(TestClient(app, headers=client.headers))

    def drain(run_id):
        owner = "offline-eval-worker"
        claimed = queue.claim(owner, lease_seconds=120)
        assert claimed is not None and claimed.run_id == run_id, "original SQL task was not claimed"
        AgentTaskDispatcher(execution_repository=queue, run_repository=repository)._execute_claim(
            claimed, owner
        )
        return repository.get(run_id)

    def start(context):
        from app.application.ai_chat.dialogue_memory import prepare_chat_turn

        context.setdefault("turn_id", "eval-" + task["id"])
        prepared = prepare_chat_turn(task["message"], context)
        assert prepared is None, prepared
        result = gateway.run_runtime_task(
            task=task["message"],
            system_prompt="",
            runtime_context=context,
            completion_mode="auto",
            start_queued=True,
            _repository=repository,
        )
        assert result.get("execution_state") == "queued", result
        return drain(result["run_id"])

    def approve(parent):
        store = XiaoxBindingStore(repository)
        for row in store.receipt_snapshot(parent.run_id):
            child_id = row["child_run_id"]
            child = repository.get(child_id)
            if child is None or child.status != "waiting_user":
                continue
            current = state.client.get(f"/api/agent/runs/{child_id}")
            assert current.status_code == 200, current.text
            grant = current.json()["approval"]["grant"]
            approved = state.client.post(
                f"/api/agent/runs/{child_id}/continue", json={"approval_grant": grant}
            )
            assert approved.status_code == 202, approved.text
            drain(child_id)
        if resume_ready_xiaox_runs(repository=repository):
            drain(parent.run_id)
        return refresh_xiaox_receipts(repository.get(parent.run_id), repository=repository)

    state.start, state.approve = start, approve
    return state


def run_owned_attachment_task(task):
    from starlette.requests import Request

    from app.application.elt.service_uploads import UploadServiceMixin
    from app.db.session import get_db
    from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context
    from app.infrastructure.auth.agent_principal import require_agent_principal
    from app.infrastructure.tenant_scope import tenant_scope

    try:
        from evals.run_agent_eval import (
            _authenticated_route_fixture,
            _check_equal,
            _check_event_types,
            _check_tool_calls,
            _result,
        )
    except ModuleNotFoundError:
        # 脚本直跑时评测入口模块名为 __main__，避免重复执行
        from __main__ import (
            _authenticated_route_fixture,
            _check_equal,
            _check_event_types,
            _check_tool_calls,
            _result,
        )

    expected = task["expected"]
    kind = task["attachment_kind"]
    raw = io.BytesIO()
    evidence = "XCauto server platform model; human review and tenant scoped citations."
    if kind == "image":
        from PIL import Image

        Image.new("RGB", (100, 30), "white").save(raw, format="PNG")
        filename, mime = "policy.png", "image/png"
    elif kind == "excel":
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.append(["客户", "产品名称", "型号", "单价"])
        sheet.append(["甲公司", "清漆", "5003", 120])
        book.save(raw)
        book.close()
        filename, mime = (
            "products.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        evidence = "清漆"
    else:
        from reportlab.pdfgen.canvas import Canvas

        canvas = Canvas(raw)
        canvas.drawString(30, 700, evidence)
        canvas.save()
        filename, mime = "policy.pdf", "application/pdf"
    raw.seek(0)
    checks = []
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as root, ExitStack() as stack:
        client = SimpleNamespace(headers={})
        stack.enter_context(_authenticated_route_fixture(client, role_name="admin"))
        stack.enter_context(
            patch("app.utils.path_io.path_utils.get_app_data_dir", return_value=root)
        )
        stack.enter_context(
            patch("app.application.elt.service_uploads.get_app_data_dir", return_value=root)
        )
        runtime = xiaox_eval_runtime(stack, Path(root), client, task)
        if kind == "image":
            stack.enter_context(
                patch(
                    "app.domain.shared_services.ocr_service.get_ocr_service",
                    return_value=SimpleNamespace(
                        recognize_text_blocks=lambda _: [{"text": evidence}]
                    ),
                )
            )
        request = Request(
            {
                "type": "http",
                "headers": [(b"x-session-id", client.headers["X-Session-ID"].encode())],
            }
        )
        principal = require_agent_principal(request, x_user_id=None)
        with tenant_scope(int(principal.tenant_id)), get_db() as db:
            upload = UploadServiceMixin().save_upload(
                db,
                owner_user_id=int(principal.user_id),
                file_name=filename,
                content_type=mime,
                stream=raw,
            )
        context = authenticated_runtime_context(
            {"attachment_upload_ids": [upload["upload_id"]]}, principal
        )
        products = Mock()
        products.get_products.return_value = {"success": True, "data": []}
        products.create_product.return_value = {"success": True}
        customers = Mock()
        customers.match_purchase_unit.return_value = None
        customers.create.return_value = {"success": True}
        stack.enter_context(patch("app.bootstrap.get_products_service", return_value=products))
        stack.enter_context(patch("app.bootstrap.get_customer_app_service", return_value=customers))
        if task.get("mock_office_document"):
            from docx import Document

            office = task["mock_office_document"]
            document = Document()
            document.add_paragraph("Policy summary: human review and tenant scoped citations.")
            generated = io.BytesIO()
            document.save(generated)
            stack.enter_context(
                patch(
                    "app.domain.shared_services.kitten_ai_document.generate.generate_office_file",
                    return_value=(generated.getvalue(), office["file_name"]),
                )
            )
        from app.application.dataset_rag_app_service import get_dataset_rag_app_service

        dataset = get_dataset_rag_app_service()
        ingest = stack.enter_context(
            patch.object(dataset, "ingest_document", wraps=dataset.ingest_document)
        )
        run = runtime.start(context)
        initial = run.status
        _check_equal(checks, "no_knowledge_write_before_approval", ingest.call_count, 0)
        _check_equal(
            checks, "no_business_write_before_approval", products.create_product.call_count, 0
        )
        if expected.get("continue_after_approval"):
            run = runtime.approve(run)
        if kind == "excel":
            _check_equal(checks, "approved_business_write", products.create_product.call_count, 1)
        if task.get("explicit_knowledge_import"):
            _check_equal(checks, "explicit_approved_knowledge_write", ingest.call_count, 1)
            _check_equal(
                checks,
                "no_model_file_path",
                bool(ingest.call_args and not ingest.call_args.kwargs.get("file_path")),
                True,
            )
        _check_equal(
            checks,
            "parsed_evidence_reaches_model",
            bool(runtime.inputs and evidence in runtime.inputs[0]),
            True,
        )
        _check_equal(
            checks,
            "source_artifact_is_owned",
            bool(
                run.artifacts
                and run.artifacts[0].source == "owned_elt_upload"
                and run.artifacts[0].metadata.get("upload_id") == upload["upload_id"]
                and run.artifacts[0].metadata.get("parser_used") == "owned_upload"
            ),
            True,
        )
        _check_equal(
            checks, "source_has_no_path", run.artifacts[0].uri if run.artifacts else None, ""
        )
        _check_equal(
            checks,
            "source_does_not_implicitly_ingest",
            run.artifacts[0].metadata.get("skip_dataset_ingest") if run.artifacts else None,
            True,
        )
        _check_equal(checks, "initial_status", initial, expected["initial_status"])
        _check_equal(checks, "final_status", run.status, expected["final_status"])
        from app.infrastructure.xiaox.binding import XiaoxBindingStore

        children = [
            runtime.repository.get(row["child_run_id"])
            for row in XiaoxBindingStore(runtime.repository).receipt_snapshot(run.run_id)
        ]
        calls = [call for child in children for call in child.tool_calls]
        events = [*run.events, *(event for child in children for event in child.events)]
        _check_equal(checks, "runtime", run.metadata.get("runtime_type"), "xiaox")
        _check_equal(checks, "no_retired_plan", "runtime_frozen_plan" in run.metadata, False)
        _check_tool_calls(checks, calls, expected.get("tool_calls", []))
        _check_event_types(checks, events, expected["event_types"])
        import hashlib

        _check_equal(
            checks,
            "source_hash",
            run.artifacts[0].metadata.get("sha256") if run.artifacts else None,
            hashlib.sha256(raw.getvalue()).hexdigest(),
        )
        _check_equal(
            checks,
            "source_implicit_ingest_count",
            sum(
                a.metadata.get("dataset_ingest") is not None
                for a in run.artifacts
                if a.metadata.get("upload_id") == upload["upload_id"]
            ),
            0,
        )
        observed = {
            **run.to_dict(),
            "tool_calls": [call.to_dict() for call in calls],
            "steps": [step.to_dict() for child in children for step in child.steps],
            "events": [event.to_dict() for event in events],
        }
    return _result(
        task,
        checks,
        {
            "run": observed,
            "child_runs": [child.to_dict() for child in children],
            "runtime_inputs": runtime.inputs,
        },
    )
