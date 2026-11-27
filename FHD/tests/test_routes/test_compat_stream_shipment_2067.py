"""#2067：桌面「智能对话」流式入口开单要和 /api/ai/chat 走同一套规则识别。"""

from __future__ import annotations

import io
import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.workflow.workflow_types import PlanGraph, plan_to_dict
from app.fastapi_routes import xcagi_compat_chat_helpers as chat_helpers
from app.infrastructure.xiaox.policy import RuntimePolicyError
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import dynamic_chat_runtime as dynamic_chat_runtime
from tests.fixtures.xiaox_http_runtime import finish_queued_chat, fixture_goal_review
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry

ISSUE_MESSAGE = "客户闭环验收客户 发货单：客户闭环测试商品A 数量24 单价3.5"


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/mod/xcagi-planner-bridge/chat/stream",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


@pytest.fixture(autouse=True)
def authenticated_stream(monkeypatch, trusted_actor, tmp_path):
    from evals.run_agent_eval import _isolated_task_execution_queue

    actor = trusted_actor(user_id=2067, tenant_id=7, role="admin", permissions=[])
    original_request = _request

    def request():
        scope = dict(original_request().scope)
        scope["headers"] = [(k.lower().encode(), v.encode()) for k, v in actor.headers.items()]
        return Request(scope)

    monkeypatch.setattr(__name__ + "._request", request)
    with _isolated_task_execution_queue(tmp_path):
        yield actor


def _body(**kwargs):
    kwargs.setdefault("mode", "online")
    return chat_helpers.XcagiCompatChatBody(**kwargs)


def _events(raw: bytes) -> list[dict[str, Any]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in raw.decode("utf-8").splitlines()
        if line.startswith("data: ")
    ]


def _no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*_args: Any, **_kwargs: Any):
        raise AssertionError("开单不能交给 LLM 规划器")

    monkeypatch.setattr(
        chat_helpers, "_xcagi_guarded_planner_stream_events", fail_if_called, raising=False
    )
    monkeypatch.setattr(
        "app.domain.shared_services.conversation.modstore_adapter.create_modstore_openai_client_from_request",
        fail_if_called,
    )
    monkeypatch.setattr(
        "app.fastapi_routes.xcagi_compat_chat_stream._classify_and_submit_client_issue",
        lambda *_a, **_k: None,
    )


def test_stream_entry_stages_order_with_explicit_quantity_and_price(
    monkeypatch, dynamic_chat_runtime, local_tools
):
    from app.application.workflow.workflow_types import WorkflowNode

    service = AIChatApplicationService()
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    shipment_svc = MagicMock()
    plan = PlanGraph(
        plan_id="shipment-2067",
        intent="shipment_generate",
        nodes=[
            WorkflowNode(
                node_id="generate",
                tool_id="shipment_orders",
                action="generate",
                params={
                    "unit_name": "客户闭环验收客户",
                    "products": [
                        {
                            "name": "客户闭环测试商品A",
                            "quantity": 24,
                            "unit": "kg",
                            "unit_price": 3.5,
                        }
                    ],
                },
            )
        ],
    )
    body = _body(message=ISSUE_MESSAGE.replace("数量24", "数量24kg"), user_id="u-2067")

    state = dynamic_chat_runtime
    state.actions = [
        {
            "tool_id": "shipment_orders",
            "action": "generate",
            "params": plan.nodes[0].params,
            "call_id": "generate",
        }
    ]
    state.review = lambda prompt: pytest.fail("pending write must stop before final review")
    with patch("app.bootstrap.get_shipment_app_service", return_value=shipment_svc):
        events = _events(
            b"".join(chat_helpers._xcagi_planner_stream_bytes(_request(), body, ai_tier="P1"))
        )
        assert events[-1]["type"] == "done"
        ack = events[-1]["result"]
        assert ack["execution_state"] == "queued", ack
        result = finish_queued_chat(state, ack)
    assert result["runtime"] == "xiaox" and result["requires_confirmation"] is True, result
    parent = state.repository.get(result["run_id"])
    assert parent.metadata["runtime_goal_contract"]["request"]["text"] == body.message
    child_id = result["data"]["data"]["approval_card"]["run_id"]
    child = state.repository.get(child_id)
    assert child.status == "waiting_user" and not child.tool_calls
    assert child.steps[0].params == plan.nodes[-1].params
    assert child.steps[0].risk in {"medium", "high"}
    assert len(state.transports) == 1 and not hasattr(service, "_pending_workflows")
    shipment_svc.generate_shipment_document.assert_not_called()


@pytest.mark.parametrize(
    "message",
    [
        ISSUE_MESSAGE,
        "请备份数据库。执行前先给我确认，需要审批的操作提交审批。",
        "请恢复数据库，使用备份 xcagi.db.20261011_160815.bak。执行前先给我确认。",
    ],
)
def test_stream_entry_hands_shipment_to_the_same_chat_service(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    _no_llm(monkeypatch)
    service = MagicMock(_pending_workflows={})
    service.process_chat.return_value = {"success": True, "response": "已生成发货单"}
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    body = _body(message=message, user_id="u-2067")
    raw = b"".join(chat_helpers._xcagi_planner_stream_bytes(_request(), body, ai_tier="P1"))

    service.process_chat.assert_called_once()
    assert service.process_chat.call_args.kwargs["message"] == message
    assert _events(raw)[-1]["result"]["response"] == "已生成发货单"


@pytest.mark.parametrize("message", ["确认", "取消"])
@pytest.mark.parametrize(
    "case", ["absent", "missing", "corrupt", "empty", "expired", "cross_session"]
)
def test_legacy_in_memory_controls_cannot_start_retired_kernel(monkeypatch, message, case):
    _no_llm(monkeypatch)
    monkeypatch.setattr(
        "app.application.agent_runtime.gateway.runtime_settings",
        MagicMock(side_effect=RuntimePolicyError("fixture qualification is missing")),
    )
    service = AIChatApplicationService()
    assert not hasattr(service, "_pending_workflows")
    assert not hasattr(service, "_hydrate_pending_workflow")
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    execute = MagicMock(side_effect=AssertionError("Invalid control must not execute"))
    monkeypatch.setattr(
        "app.application.agent_orchestrator.AgentOrchestrator.start_run_from_plan", execute
    )
    body = _body(
        message=message,
        user_id="u-cancel",
        context={
            "session_id": "s",
            "_pending_workflows": {"case": case, "approved": True},
            "approved": True,
            "approved_step_id": "generate",
        },
    )
    result = _events(
        b"".join(chat_helpers._xcagi_planner_stream_bytes(_request(), body, ai_tier="P1"))
    )[-1]["result"]
    # Legacy in-memory slots are not execution authority. The fixed runtime
    # must refuse this unqualified route, with no planner or business fallback.
    assert result["success"] is False
    assert result["data"]["error_code"] == "runtime_policy_blocked"
    assert "qualification is missing" in result["response"]
    assert result["business_completed"] is False
    assert result["requires_confirmation"] is False
    execute.assert_not_called()


def test_stream_missing_spec_requests_clarification_without_document(
    monkeypatch, dynamic_chat_runtime
):
    from app.application.shipment_app_service import ShipmentApplicationService

    service = AIChatApplicationService()
    state = dynamic_chat_runtime

    def ask_units(binding, text):
        observed = state.bridge.invoke(
            state.token, "request_input", {"question": "请补充数量24对应的计量单位。"}
        )
        assert observed["needs_user_input"] is True
        return observed["question"]

    state.script = ask_units
    state.review = lambda prompt: pytest.fail("missing units are not a completed goal")
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    generator = MagicMock()
    shipment = ShipmentApplicationService(MagicMock(), generator, MagicMock())
    body = _body(message=ISSUE_MESSAGE, user_id="u-2292")
    with patch("app.bootstrap.get_shipment_app_service", return_value=shipment):
        raw = b"".join(chat_helpers._xcagi_planner_stream_bytes(_request(), body, ai_tier="P1"))
        ack = _events(raw)[-1]["result"]
        assert ack["execution_state"] == "queued", ack
        result = finish_queued_chat(state, ack)
    assert result["runtime"] == "xiaox" and result["needs_user_input"] is True, result
    assert "计量单位" in result["response"]
    assert "已生成" not in result["response"]
    parent = state.repository.get(result["run_id"])
    assert parent.metadata["runtime_goal_contract"]["request"]["text"] == ISSUE_MESSAGE
    assert parent.status == "waiting_user" and not parent.tool_calls
    assert len(state.transports) == 1 and not hasattr(service, "_pending_workflows")
    assert state.model_requests == []
    generator.generate.assert_not_called()


@pytest.mark.parametrize("message", ["当前客户端版本是多少？", "刚才说的客户总数是多少？"])
def test_stream_fact_and_version_use_same_mainline(monkeypatch, message):
    _no_llm(monkeypatch)
    service = MagicMock(_pending_workflows={})
    service.process_chat.return_value = {"success": True, "response": "同一套对话规则"}
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    body = _body(message=message, user_id="u-fact", mode="online")
    result = _events(
        b"".join(chat_helpers._xcagi_planner_stream_bytes(_request(), body, ai_tier="P1"))
    )[-1]["result"]
    service.process_chat.assert_called_once()
    assert result["response"] == "同一套对话规则"


@pytest.mark.parametrize("endpoint", ["/api/ai/chat", "/api/ai/chat/stream"])
def test_mainline_uses_owned_upload_not_caller_file_path(
    monkeypatch,
    tmp_path,
    authenticated_stream,
    endpoint,
    dynamic_chat_runtime,
):
    from app.application.elt.service_uploads import UploadServiceMixin
    from app.db.models.elt import EltUpload
    from app.infrastructure.tenant_scope import tenant_scope
    from app.legacy.routes.conversation.compat_routes import router

    actor = authenticated_stream
    secret = tmp_path / "not-an-upload.txt"
    secret.write_text("PRIVATE_LOCAL_CONTENT_MUST_NOT_BE_READ", encoding="utf-8")
    seen = []
    reviewed = []

    state = dynamic_chat_runtime
    state.actions = []

    def inspect_turn(binding):
        original = binding.run.metadata["runtime_goal_contract"]["request"]
        seen.append(original)
        state.reply = (
            "已查看附件：paint 的价格为 3.5。"
            if original["attachments"]
            else "未提供可读取的附件，请上传需要解释的文档。"
        )

    def review(prompt):
        reviewed.append(prompt)
        assert prompt["original_request"]["text"] in {
            "Summarize attached prices.",
            "Explain the attached document.",
        }
        assert prompt["response"] == state.reply
        assessment = fixture_goal_review(prompt, kind="reply")
        files = prompt.get("file_evidence")
        if files:
            [source] = files.values()
            assert source["name"] == "prices.csv" and not source["coverage"]["truncated"]
            [source_block] = [key for key, text in source["blocks"].items() if text == "paint,3.5"]
            [response_block] = [
                key for key, text in prompt["response_blocks"].items() if text == state.reply
            ]
            assessment["feedback_disposition"] = "none"
            assessment["goals"][0].update(
                file_basis="complete",
                file_citations=[
                    {"source_block_id": source_block, "response_block_id": response_block}
                ],
            )
        return assessment

    state.on_turn = inspect_turn
    state.review = review
    service = AIChatApplicationService()
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        "app.application.elt.service_uploads.get_app_data_dir", lambda: str(tmp_path)
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    streaming = endpoint.endswith("/stream")
    with tenant_scope(7), actor.factory.begin() as db:
        upload = UploadServiceMixin().save_upload(
            db,
            owner_user_id=2067,
            file_name="prices.csv",
            content_type="text/csv",
            stream=io.BytesIO(b"product,price\npaint,3.5\n"),
        )
    with TestClient(app, headers=actor.headers) as client:
        response = client.post(
            endpoint,
            json={
                "message": "Summarize attached prices.",
                "mode": "online",
                "context": {"attachment_upload_ids": [upload["upload_id"]]},
            },
        )
        assert response.status_code == 200, response.text
        ack = _events(response.content)[-1]["result"] if streaming else response.json()
        assert ack["execution_state"] == "queued", ack
        completed = finish_queued_chat(state, ack)
        assert len(seen) == 1
        assert len(reviewed) == 1
        assert "paint" in seen[0]["attachments"][0]["preview"]["text"]
        assert "已查看附件" in completed["response"]
        with tenant_scope(7), actor.factory.begin() as db:
            db.query(EltUpload).filter(EltUpload.id == upload["upload_id"]).one().owner_user_id = 99
        denied = client.post(
            endpoint,
            json={
                "message": "Read the attachment.",
                "mode": "online",
                "context": {"attachment_upload_ids": [upload["upload_id"]]},
            },
        )
        assert denied.status_code == 200, denied.text
        denied_ack = _events(denied.content)[-1]["result"] if streaming else denied.json()
        denied_payload = finish_queued_chat(state, denied_ack)
        assert "重新上传" in denied_payload["response"]
        assert denied_payload["needs_user_input"] is True
        assert denied_payload["requires_confirmation"] is False
        assert len(seen) == 1
        assert len(reviewed) == 1
        raw_path = client.post(
            endpoint,
            json={
                "message": "Explain the attached document.",
                "mode": "online",
                "context": {
                    "file_analysis": {"file_path": str(secret)},
                    "file_context": {"file_path": str(secret)},
                },
            },
        )
        assert raw_path.status_code == 200, raw_path.text
        ack = _events(raw_path.content)[-1]["result"] if streaming else raw_path.json()
        assert ack["execution_state"] == "queued", ack
        completed = finish_queued_chat(state, ack)
        assert len(seen) == 2
        assert len(reviewed) == 2
        assert "PRIVATE_LOCAL_CONTENT_MUST_NOT_BE_READ" not in str(seen[-1])
        assert state.transports[-1].history
        assert "PRIVATE_LOCAL_CONTENT_MUST_NOT_BE_READ" not in str(state.transports[-1].history)
        assert seen[-1]["attachments"] == []
        assert "owned_upload" not in str(completed)
