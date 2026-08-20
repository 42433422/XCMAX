# mypy: disable-error-code="var-annotated"
"""Tests for app.fastapi_routes.voice_routes — POST /api/voice/command 端到端语音指令。

覆盖 ASR → 意图识别 → 可选自动执行 的关键分支：
- auto_execute=False 只返回 text + intent（不执行）
- auto_execute=True 低风险高置信度意图直接执行
- auto_execute=True 高风险意图拒绝执行（high_risk_needs_confirmation）
- auto_execute=True 低置信度意图拒绝执行（low_confidence）
- auto_execute=True 否定式意图拒绝执行（negated）
- ASR 转写为空时返回 asr_empty
- ASR 抛 HTTPException 时错误传播
- 空文件 / 超大文件分别返回 400 / 413
- _recognize_intent / _execute_intent_tool 单元测试
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.application  # noqa: F401 — 先加载 app.application 打破 app.services 循环导入
import app.services.intent_service  # noqa: F401 — 注册子模块，使 patch("app.services.intent_service.recognize_intents") 能解析
from app.fastapi_routes.voice_routes import (
    HIGH_RISK_INTENTS,
    INTENT_CONFIDENCE_THRESHOLD,
    _execute_intent_tool,
    _recognize_intent,
    _transcribe_audio,
    router,
    voice_command,
)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _transcribe_audio
# ---------------------------------------------------------------------------


class TestTranscribeAudioHelper:
    def test_returns_text_only(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_ASR_BEAM", "1")
        mock_result = {"text": "  hello world  ", "language": "en", "audio_seconds": 5.0}
        with patch(
            "app.fastapi_routes.voice_routes._run_transcribe",
            return_value=mock_result,
        ):
            text = _transcribe_audio(tmp_path / "audio.webm", None)
            assert text == "hello world"

    def test_empty_text_returns_empty(self, tmp_path: Path):
        mock_result = {"text": "   ", "language": "zh", "audio_seconds": 0.0}
        with patch(
            "app.fastapi_routes.voice_routes._run_transcribe",
            return_value=mock_result,
        ):
            assert _transcribe_audio(tmp_path / "audio.webm") == ""

    def test_none_text_returns_empty(self, tmp_path: Path):
        mock_result = {"text": None, "language": "", "audio_seconds": 0.0}
        with patch(
            "app.fastapi_routes.voice_routes._run_transcribe",
            return_value=mock_result,
        ):
            assert _transcribe_audio(tmp_path / "audio.webm") == ""

    def test_propagates_http_exception(self, tmp_path: Path):
        with patch(
            "app.fastapi_routes.voice_routes._run_transcribe",
            side_effect=HTTPException(status_code=500, detail="ASR 失败"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                _transcribe_audio(tmp_path / "audio.webm")
            assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# _recognize_intent
# ---------------------------------------------------------------------------


class TestRecognizeIntentHelper:
    def test_empty_text_returns_unclear(self):
        result = _recognize_intent("")
        assert result["tool_key"] is None
        assert result["confidence"] == 0.0
        assert result["is_likely_unclear"] is True
        assert result["source"] == "empty"

    def test_whitespace_only_returns_unclear(self):
        result = _recognize_intent("   \n  ")
        assert result["tool_key"] is None
        assert result["confidence"] == 0.0
        assert result["source"] == "empty"

    def test_rule_engine_hit_returns_high_confidence(self):
        mock_rule_result = {
            "primary_intent": "shipment_generate",
            "tool_key": "shipment_generate",
            "intent_hints": ["shipment_generate"],
            "is_negated": False,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_likely_unclear": False,
            "all_matched_tools": [("shipment_generate", "shipment_generate")],
            "slots": {"unit_name": "ABC公司"},
        }
        with patch(
            "app.services.intent_service.recognize_intents",
            return_value=mock_rule_result,
        ):
            result = _recognize_intent("给ABC公司开5桶货")
            assert result["tool_key"] == "shipment_generate"
            assert result["primary_intent"] == "shipment_generate"
            assert result["confidence"] == 0.85
            assert result["source"] == "rule"
            assert result["slots"] == {"unit_name": "ABC公司"}
            assert result["is_negated"] is False

    def test_rule_engine_no_tool_key_returns_low_confidence(self):
        mock_rule_result = {
            "primary_intent": None,
            "tool_key": None,
            "intent_hints": [],
            "is_negated": False,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_likely_unclear": False,
            "all_matched_tools": [],
            "slots": {},
        }
        with patch(
            "app.services.intent_service.recognize_intents",
            return_value=mock_rule_result,
        ):
            result = _recognize_intent("今天天气真好")
            assert result["tool_key"] is None
            assert result["confidence"] == 0.0
            assert result["source"] == "unclear"

    def test_is_likely_unclear_caps_confidence_at_04(self):
        mock_rule_result = {
            "primary_intent": "shipment_generate",
            "tool_key": "shipment_generate",
            "intent_hints": ["shipment_generate"],
            "is_negated": False,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_likely_unclear": True,
            "all_matched_tools": [],
            "slots": {},
        }
        with patch(
            "app.services.intent_service.recognize_intents",
            return_value=mock_rule_result,
        ):
            result = _recognize_intent("短句")
            # 规则命中本应给 0.85，但 is_likely_unclear 把它压到 ≤ 0.4
            assert result["tool_key"] == "shipment_generate"
            assert result["confidence"] <= 0.4
            assert result["is_likely_unclear"] is True

    def test_recognize_intents_import_error_falls_back_to_unclear(self):
        # 模拟 intent_service 不可用：通过 patch 抛 RECOVERABLE_ERRORS
        with patch(
            "app.services.intent_service.recognize_intents",
            side_effect=RuntimeError("intent service unavailable"),
        ):
            result = _recognize_intent("任意文本")
            assert result["tool_key"] is None
            assert result["confidence"] == 0.0
            assert result["is_likely_unclear"] is True
            assert result["source"] == "unclear"

    def test_negated_intent_flag_propagates(self):
        mock_rule_result = {
            "primary_intent": "shipment_generate",
            "tool_key": None,  # negated 通常会清空 tool_key
            "intent_hints": [],
            "is_negated": True,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_likely_unclear": False,
            "all_matched_tools": [],
            "slots": {},
        }
        with patch(
            "app.services.intent_service.recognize_intents",
            return_value=mock_rule_result,
        ):
            result = _recognize_intent("不要发货")
            assert result["is_negated"] is True


# ---------------------------------------------------------------------------
# _execute_intent_tool
# ---------------------------------------------------------------------------


class TestExecuteIntentToolHelper:
    def test_empty_tool_key_returns_no_tool_key(self):
        result = _execute_intent_tool("", "text", {}, "session-1")
        assert result["executed"] is False
        assert result["reason"] == "no_tool_key"
        assert result["result"] is None

    def test_delegates_to_app_service_pro_mode_tools(self):
        mock_app_service = MagicMock()
        mock_app_service._execute_pro_mode_tools.return_value = {
            "response": "查询到 5 个产品",
            "toolCall": {"tool_id": "products", "action": "执行", "params": {}},
            "data": {"data": {"items": [{"name": "产品A"}]}},
        }
        with patch(
            "app.application.ai_chat_app_service.get_ai_chat_app_service",
            return_value=mock_app_service,
        ):
            result = _execute_intent_tool("products", "查询产品", {"keyword": "A"}, "session-1")
        assert result["executed"] is True
        assert result["reason"] == "executed"
        assert result["session_id"] == "session-1"
        assert result["result"]["response"] == "查询到 5 个产品"
        assert result["result"]["toolCall"]["tool_id"] == "products"
        assert result["result"]["data"]["items"][0]["name"] == "产品A"
        # 验证调用参数完整传递
        call_kwargs = mock_app_service._execute_pro_mode_tools.call_args.kwargs
        assert call_kwargs["tool_key"] == "products"
        assert call_kwargs["original_message"] == "查询产品"
        assert call_kwargs["slots"] == {"keyword": "A"}

    def test_propagates_exceptions(self):
        mock_app_service = MagicMock()
        mock_app_service._execute_pro_mode_tools.side_effect = RuntimeError("DB down")
        with patch(
            "app.application.ai_chat_app_service.get_ai_chat_app_service",
            return_value=mock_app_service,
        ):
            with pytest.raises(RuntimeError, match="DB down"):
                _execute_intent_tool("products", "查询产品", {}, "")


# ---------------------------------------------------------------------------
# POST /api/voice/command — route tests
# ---------------------------------------------------------------------------


class TestVoiceCommandRoute:
    """端到端 /api/voice/command 测试，mock ASR + 意图识别 + 工具执行。"""

    def test_empty_file_returns_400(self, client: TestClient):
        response = client.post(
            "/api/voice/command",
            files={"file": ("audio.webm", b"", "audio/webm")},
            data={"auto_execute": "false", "session_id": "s1"},
        )
        assert response.status_code == 400
        assert "为空" in response.json()["detail"]

    def test_file_too_large_returns_413(self, client: TestClient):
        from app.fastapi_routes.voice_routes import _MAX_UPLOAD_BYTES

        large = b"x" * (_MAX_UPLOAD_BYTES + 1)
        response = client.post(
            "/api/voice/command",
            files={"file": ("audio.webm", large, "audio/webm")},
            data={"auto_execute": "false"},
        )
        assert response.status_code == 413
        assert "过大" in response.json()["detail"]

    def test_asr_empty_returns_asr_empty_reason(self, client: TestClient):
        """ASR 转写为空时返回 success=true + reason=asr_empty，不跑意图识别。"""
        with patch(
            "app.fastapi_routes.voice_routes._transcribe_audio",
            return_value="",
        ):
            response = client.post(
                "/api/voice/command",
                files={"file": ("audio.webm", b"audio", "audio/webm")},
                data={"auto_execute": "true", "session_id": "s1"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["text"] == ""
        assert data["data"]["executed"] is False
        assert data["data"]["reason"] == "asr_empty"
        assert data["data"]["session_id"] == "s1"

    def test_asr_exception_propagates_as_500(self, client: TestClient):
        """ASR 内部抛 HTTPException(500) 时，错误向上传播（不在 command 路由层吞掉）。"""
        with patch(
            "app.fastapi_routes.voice_routes._transcribe_audio",
            side_effect=HTTPException(status_code=500, detail="whisper 解码失败"),
        ):
            response = client.post(
                "/api/voice/command",
                files={"file": ("audio.webm", b"audio", "audio/webm")},
                data={"auto_execute": "false"},
            )
        assert response.status_code == 500
        assert "whisper 解码失败" in response.json()["detail"]

    def test_auto_execute_false_returns_text_and_intent_without_executing(self, client: TestClient):
        """auto_execute=False：返回 text + intent，executed=false，不调用 _execute_intent_tool。"""
        intent_data = {
            "tool_key": "products",
            "primary_intent": "products",
            "confidence": 0.85,
            "slots": {"keyword": "A"},
            "is_negated": False,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_likely_unclear": False,
            "intent_hints": ["products"],
            "source": "rule",
        }
        with (
            patch(
                "app.fastapi_routes.voice_routes._transcribe_audio",
                return_value="查询A产品",
            ),
            patch(
                "app.fastapi_routes.voice_routes._recognize_intent",
                return_value=intent_data,
            ),
            patch("app.fastapi_routes.voice_routes._execute_intent_tool") as mock_exec,
        ):
            response = client.post(
                "/api/voice/command",
                files={"file": ("audio.webm", b"audio", "audio/webm")},
                data={"auto_execute": "false", "session_id": "s2"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["text"] == "查询A产品"
        assert data["data"]["intent"] == "products"
        assert data["data"]["confidence"] == 0.85
        assert data["data"]["executed"] is False
        assert data["data"]["reason"] == "auto_execute_disabled"
        assert data["data"]["is_high_risk"] is False
        # 不应调用执行器
        mock_exec.assert_not_called()

    def test_auto_execute_true_low_risk_high_confidence_executes(self, client: TestClient):
        """auto_execute=True + 低风险 + 高置信度 → 调用 _execute_intent_tool 并返回 executed=true。"""
        intent_data = {
            "tool_key": "products",
            "primary_intent": "products",
            "confidence": 0.85,
            "slots": {"keyword": "A"},
            "is_negated": False,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_likely_unclear": False,
            "intent_hints": ["products"],
            "source": "rule",
        }
        exec_payload = {
            "executed": True,
            "result": {
                "response": "找到 2 个产品",
                "toolCall": {"tool_id": "products"},
                "data": {"count": 2},
            },
            "reason": "executed",
            "session_id": "s3",
        }
        with (
            patch(
                "app.fastapi_routes.voice_routes._transcribe_audio",
                return_value="查询A产品",
            ),
            patch(
                "app.fastapi_routes.voice_routes._recognize_intent",
                return_value=intent_data,
            ),
            patch(
                "app.fastapi_routes.voice_routes._execute_intent_tool",
                return_value=exec_payload,
            ) as mock_exec,
        ):
            response = client.post(
                "/api/voice/command",
                files={"file": ("audio.webm", b"audio", "audio/webm")},
                data={"auto_execute": "true", "session_id": "s3"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["text"] == "查询A产品"
        assert data["data"]["intent"] == "products"
        assert data["data"]["executed"] is True
        assert data["data"]["reason"] == "executed"
        assert data["data"]["result"]["response"] == "找到 2 个产品"
        assert data["data"]["result"]["data"]["count"] == 2
        # 验证执行器收到正确参数
        mock_exec.assert_called_once_with("products", "查询A产品", {"keyword": "A"}, "s3")

    def test_auto_execute_true_high_risk_intent_blocks_execution(self, client: TestClient):
        """auto_execute=True + 高风险意图（delete/clear_all/customer_edit/wechat_send）→ 拒绝执行。"""
        # 用 HIGH_RISK_INTENTS 中第一个做测试
        high_risk_tool = next(iter(HIGH_RISK_INTENTS))
        intent_data = {
            "tool_key": high_risk_tool,
            "primary_intent": high_risk_tool,
            "confidence": 0.95,  # 置信度很高也照样拒绝
            "slots": {},
            "is_negated": False,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_likely_unclear": False,
            "intent_hints": [],
            "source": "rule",
        }
        with (
            patch(
                "app.fastapi_routes.voice_routes._transcribe_audio",
                return_value=f"执行 {high_risk_tool}",
            ),
            patch(
                "app.fastapi_routes.voice_routes._recognize_intent",
                return_value=intent_data,
            ),
            patch("app.fastapi_routes.voice_routes._execute_intent_tool") as mock_exec,
        ):
            response = client.post(
                "/api/voice/command",
                files={"file": ("audio.webm", b"audio", "audio/webm")},
                data={"auto_execute": "true", "session_id": "s4"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["executed"] is False
        assert data["data"]["reason"] == "high_risk_needs_confirmation"
        assert data["data"]["is_high_risk"] is True
        # 高风险意图不调用执行器
        mock_exec.assert_not_called()

    def test_auto_execute_true_low_confidence_blocks_execution(self, client: TestClient):
        """auto_execute=True + 低置信度（≤ INTENT_CONFIDENCE_THRESHOLD）→ 拒绝执行。"""
        intent_data = {
            "tool_key": "products",
            "primary_intent": "products",
            "confidence": INTENT_CONFIDENCE_THRESHOLD,  # 边界值：等于阈值也拒绝（条件是 > 阈值）
            "slots": {},
            "is_negated": False,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_likely_unclear": False,
            "intent_hints": [],
            "source": "rule_fallback",
        }
        with (
            patch(
                "app.fastapi_routes.voice_routes._transcribe_audio",
                return_value="那个啥",
            ),
            patch(
                "app.fastapi_routes.voice_routes._recognize_intent",
                return_value=intent_data,
            ),
            patch("app.fastapi_routes.voice_routes._execute_intent_tool") as mock_exec,
        ):
            response = client.post(
                "/api/voice/command",
                files={"file": ("audio.webm", b"audio", "audio/webm")},
                data={"auto_execute": "true"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["executed"] is False
        assert data["data"]["reason"] == "low_confidence"
        assert data["data"]["confidence"] == INTENT_CONFIDENCE_THRESHOLD
        mock_exec.assert_not_called()

    def test_auto_execute_true_negated_intent_blocks_execution(self, client: TestClient):
        """auto_execute=True + 否定式意图（is_negated=true）→ 拒绝执行。"""
        intent_data = {
            "tool_key": "shipment_generate",
            "primary_intent": "shipment_generate",
            "confidence": 0.85,
            "slots": {},
            "is_negated": True,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_likely_unclear": False,
            "intent_hints": [],
            "source": "rule",
        }
        with (
            patch(
                "app.fastapi_routes.voice_routes._transcribe_audio",
                return_value="不要发货",
            ),
            patch(
                "app.fastapi_routes.voice_routes._recognize_intent",
                return_value=intent_data,
            ),
            patch("app.fastapi_routes.voice_routes._execute_intent_tool") as mock_exec,
        ):
            response = client.post(
                "/api/voice/command",
                files={"file": ("audio.webm", b"audio", "audio/webm")},
                data={"auto_execute": "true"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["executed"] is False
        assert data["data"]["reason"] == "negated"
        assert data["data"]["is_negated"] is True
        mock_exec.assert_not_called()

    def test_auto_execute_true_no_intent_blocks_execution(self, client: TestClient):
        """auto_execute=True 但未识别到意图（tool_key=None）→ reason=no_intent。"""
        intent_data = {
            "tool_key": None,
            "primary_intent": None,
            "confidence": 0.0,
            "slots": {},
            "is_negated": False,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_likely_unclear": True,
            "intent_hints": [],
            "source": "unclear",
        }
        with (
            patch(
                "app.fastapi_routes.voice_routes._transcribe_audio",
                return_value="今天天气真好",
            ),
            patch(
                "app.fastapi_routes.voice_routes._recognize_intent",
                return_value=intent_data,
            ),
            patch("app.fastapi_routes.voice_routes._execute_intent_tool") as mock_exec,
        ):
            response = client.post(
                "/api/voice/command",
                files={"file": ("audio.webm", b"audio", "audio/webm")},
                data={"auto_execute": "true"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["executed"] is False
        assert data["data"]["reason"] == "no_intent"
        assert data["data"]["intent"] is None
        mock_exec.assert_not_called()

    def test_execution_failure_returns_execution_failed_reason(self, client: TestClient):
        """auto_execute=True + 低风险 + 高置信度，但 _execute_intent_tool 抛异常 → reason=execution_failed。"""
        intent_data = {
            "tool_key": "products",
            "primary_intent": "products",
            "confidence": 0.85,
            "slots": {"keyword": "A"},
            "is_negated": False,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_likely_unclear": False,
            "intent_hints": [],
            "source": "rule",
        }
        with (
            patch(
                "app.fastapi_routes.voice_routes._transcribe_audio",
                return_value="查询A产品",
            ),
            patch(
                "app.fastapi_routes.voice_routes._recognize_intent",
                return_value=intent_data,
            ),
            patch(
                "app.fastapi_routes.voice_routes._execute_intent_tool",
                side_effect=RuntimeError("DB connection lost"),
            ),
        ):
            response = client.post(
                "/api/voice/command",
                files={"file": ("audio.webm", b"audio", "audio/webm")},
                data={"auto_execute": "true", "session_id": "s5"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["executed"] is False
        assert data["data"]["reason"] == "execution_failed"
        assert data["data"]["result"]["error"] == "语音指令执行服务暂时不可用"
        assert "DB connection lost" not in data["data"]["result"]["error"]

    def test_response_includes_slots_and_intent_hints(self, client: TestClient):
        """响应里应携带 slots / intent_hints / is_negated / is_high_risk / elapsed_ms_asr 字段。"""
        intent_data = {
            "tool_key": "shipment_generate",
            "primary_intent": "shipment_generate",
            "confidence": 0.85,
            "slots": {"unit_name": "ABC", "quantity_tins": 5},
            "is_negated": False,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_likely_unclear": False,
            "intent_hints": ["shipment_generate", "template_query"],
            "source": "rule",
        }
        with (
            patch(
                "app.fastapi_routes.voice_routes._transcribe_audio",
                return_value="给ABC开5桶",
            ),
            patch(
                "app.fastapi_routes.voice_routes._recognize_intent",
                return_value=intent_data,
            ),
        ):
            response = client.post(
                "/api/voice/command",
                files={"file": ("audio.webm", b"audio", "audio/webm")},
                data={"auto_execute": "false"},
            )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["slots"] == {"unit_name": "ABC", "quantity_tins": 5}
        assert data["intent_hints"] == ["shipment_generate", "template_query"]
        assert data["is_negated"] is False
        assert data["is_high_risk"] is False
        assert isinstance(data["elapsed_ms_asr"], int)
        assert data["elapsed_ms_asr"] >= 0


# ---------------------------------------------------------------------------
# HIGH_RISK_INTENTS / INTENT_CONFIDENCE_THRESHOLD 常量合理性
# ---------------------------------------------------------------------------


class TestConstants:
    def test_high_risk_intents_contains_delete_and_clear_all(self):
        """任务规格明确要求 delete / clear_all 必须二次确认。"""
        assert "delete" in HIGH_RISK_INTENTS
        assert "clear_all" in HIGH_RISK_INTENTS

    def test_high_risk_intents_is_frozenset(self):
        assert isinstance(HIGH_RISK_INTENTS, frozenset)

    def test_confidence_threshold_is_07(self):
        """任务规格：auto_execute 时置信度 > 0.7 才执行。"""
        assert INTENT_CONFIDENCE_THRESHOLD == 0.7

    def test_low_risk_intents_not_in_high_risk(self):
        """常见低风险意图（查询类）不应在 HIGH_RISK_INTENTS 中。"""
        low_risk = {"products", "shipments", "materials", "shipment_generate", "print_label"}
        assert not (low_risk & HIGH_RISK_INTENTS)


# ---------------------------------------------------------------------------
# voice_command 函数签名一致性
# ---------------------------------------------------------------------------


class TestVoiceCommandSignature:
    def test_voice_command_is_coroutine(self):
        """voice_command 必须是 async 函数（FastAPI 路由）。"""
        import inspect

        assert inspect.iscoroutinefunction(voice_command)

    def test_voice_command_has_auto_execute_and_session_id_params(self):
        """验证 Form 参数存在（FastAPI 在运行时解析签名，这里只验证函数可调用）。"""
        import inspect

        sig = inspect.signature(voice_command)
        param_names = set(sig.parameters.keys())
        assert "file" in param_names
        assert "auto_execute" in param_names
        assert "session_id" in param_names
        assert "language" in param_names
