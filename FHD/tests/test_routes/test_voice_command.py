"""Voice input delegates to the configured ASR and the single chat workflow."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.voice_routes import _transcribe_audio, router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_voice_command_uses_platform_asr_without_executing(client):
    platform = AsyncMock(return_value={"text": "查一下订单"})
    with (
        patch("app.fastapi_routes.voice_routes._platform_transcribe", platform),
        patch("app.application.ai_chat_app_service.get_ai_chat_app_service") as service,
    ):
        response = client.post(
            "/api/voice/command",
            files={"file": ("audio.wav", b"audio", "audio/wav")},
            data={"auto_execute": "false"},
        )
    assert response.status_code == 200
    assert response.json()["data"]["text"] == "查一下订单"
    assert response.json()["data"]["reason"] == "auto_execute_disabled"
    assert response.json()["data"]["executed"] is False
    platform.assert_awaited_once()
    service.assert_not_called()


def test_voice_command_empty_asr_returns_without_chat(client):
    with patch(
        "app.fastapi_routes.voice_routes._platform_transcribe",
        new=AsyncMock(return_value={"text": ""}),
    ):
        response = client.post(
            "/api/voice/command",
            files={"file": ("audio.wav", b"audio", "audio/wav")},
        )
    assert response.status_code == 200
    assert response.json()["data"]["reason"] == "asr_empty"


def test_voice_command_auto_execute_uses_chat_application(client):
    service = type(
        "Service",
        (),
        {
            "process_chat": lambda self, **kwargs: {
                "success": True,
                "response": "订单已查询",
                "data": {"data": {"node_results": [{"success": True}]}},
            }
        },
    )()
    with (
        patch(
            "app.fastapi_routes.voice_routes._platform_transcribe",
            new=AsyncMock(return_value={"text": "查一下订单"}),
        ),
        patch(
            "app.application.ai_chat_app_service.get_ai_chat_app_service",
            return_value=service,
        ),
        patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._runtime_context_with_authenticated_actor",
            return_value={"actor_id": "user-7"},
        ),
        patch(
            "app.application.ai_chat.chat_evidence.prepare_chat_evidence",
            side_effect=lambda _r, c, _m: c,
        ),
    ):
        response = client.post(
            "/api/voice/command",
            files={"file": ("audio.wav", b"audio", "audio/wav")},
            data={"auto_execute": "true", "session_id": "session-1"},
        )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["executed"] is True
    assert data["reason"] == "executed"
    assert data["result"]["response"] == "订单已查询"


def test_voice_command_empty_file_rejected(client):
    response = client.post(
        "/api/voice/command",
        files={"file": ("audio.wav", b"", "audio/wav")},
    )
    assert response.status_code == 400


def test_voice_command_preserves_unknown_write_receipt(client):
    result = {
        "success": False,
        "response": "业务结果暂时无法核实，请核对原任务和业务数据，勿重复提交。",
        "requires_reconciliation": True,
        "retryable": False,
    }
    with (
        patch(
            "app.fastapi_routes.voice_routes._platform_transcribe",
            new=AsyncMock(return_value={"text": "新增客户"}),
        ),
        patch("app.application.ai_chat_app_service.get_ai_chat_app_service") as service,
        patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._runtime_context_with_authenticated_actor",
            return_value={"actor_id": "user-7"},
        ),
        patch(
            "app.application.ai_chat.chat_evidence.prepare_chat_evidence",
            side_effect=lambda _r, c, _m: c,
        ),
    ):
        service.return_value.process_chat.return_value = result
        response = client.post(
            "/api/voice/command",
            files={"file": ("audio.wav", b"audio", "audio/wav")},
            data={"auto_execute": "true"},
        )
    receipt = response.json()["data"]
    assert receipt["executed"] is False
    assert receipt["result"]["requires_reconciliation"] is True
    assert receipt["result"]["retryable"] is False


@pytest.mark.parametrize("kind", ["failed", "unknown", "nested_partial", "not_executed"])
def test_voice_command_hides_tool_exception_without_reporting_execution(client, kind):
    private = "Traceback /private/tool.db token=private-voice-failure"
    result = {"success": False, "response": private, "message": private, "run_id": "existing-run"}
    if kind == "unknown":
        result.update(outcome="unknown", reconciliation_required=True, retryable=False)
    if kind in {"nested_partial", "not_executed"}:
        result["data"] = {
            "data": {
                "approval_request_id": "existing-approval",
                "plan_id": "existing-plan",
                "execution": {
                    "committed": kind == "nested_partial",
                    "effect": "partial" if kind == "nested_partial" else "none",
                    "outcome": "partial" if kind == "nested_partial" else "not_executed",
                    "message": private,
                },
            }
        }
    with (
        patch(
            "app.fastapi_routes.voice_routes._platform_transcribe",
            new=AsyncMock(return_value={"text": "新增客户"}),
        ),
        patch("app.application.ai_chat_app_service.get_ai_chat_app_service") as service,
        patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._runtime_context_with_authenticated_actor",
            return_value={"actor_id": "user-7"},
        ),
        patch(
            "app.application.ai_chat.chat_evidence.prepare_chat_evidence",
            side_effect=lambda _r, c, _m: c,
        ),
    ):
        service.return_value.process_chat.return_value = result
        response = client.post(
            "/api/voice/command",
            files={"file": ("audio.wav", b"audio", "audio/wav")},
            data={"auto_execute": "true"},
        )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["executed"] is False and data["result"]["success"] is False
    assert private not in response.text
    if kind in {"unknown", "nested_partial"}:
        assert data["result"]["requires_reconciliation"] and data["result"]["retryable"] is False
        assert data["result"]["run_id"] == "existing-run"
    if kind in {"nested_partial", "not_executed"}:
        assert data["result"]["approval_request_id"] == "existing-approval"
        assert data["result"]["plan_id"] == "existing-plan"
        receipt = data["result"]["data"]["data"]["execution"]
        assert receipt["committed"] is (kind == "nested_partial")
        assert receipt["outcome"] == ("partial" if kind == "nested_partial" else "not_executed")
    if kind == "not_executed":
        assert data["result"]["execution_state"] == "not_executed"
        assert data["result"].get("requires_reconciliation") is not True


def test_transcribe_audio_returns_normalized_text(tmp_path: Path):
    with patch(
        "app.fastapi_routes.voice_routes._run_transcribe",
        return_value={"text": "  hello world  ", "language": "en"},
    ):
        assert _transcribe_audio(tmp_path / "audio.wav") == "hello world"
