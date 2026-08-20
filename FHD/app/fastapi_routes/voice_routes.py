"""
Voice / ASR Routes - FastAPI Implementation

为前端主聊天输入栏提供"按住说话"语音转写能力，独立于专业模式 phone_agent 链路：
- POST /api/voice/transcribe      短录音（MediaRecorder blob）→ 文本
- POST /api/voice/command         语音 → ASR → 意图识别 → 可选自动执行（端到端语音指令）

与 mods/sz-qsm-pro/phone_agent/asr_processor.py 的差异：
- 那边针对电话采音流（float32 numpy + 双阈值 VAD 分段），这里直接接受 webm/ogg/wav 文件。
- 为避免互相污染模型实例和环境变量，这里使用独立的 XCAGI_CHAT_ASR_* 命名空间。
"""

from __future__ import annotations

import logging
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.fastapi_routes.voice_model_source import (
    env as _env,
)
from app.fastapi_routes.voice_model_source import (
    resolve_compute_type as _resolve_compute_type,
)
from app.fastapi_routes.voice_model_source import (
    resolve_device as _resolve_device,
)
from app.fastapi_routes.voice_model_source import (
    resolve_model_name as _resolve_model_name,
)
from app.fastapi_routes.voice_model_source import (
    resolve_model_source as _resolve_model_source,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB；等同于 OpenAI Whisper 官方上限，足够覆盖一次按住说话

# 懒加载：第一次调用才把 faster-whisper 模型加载进内存，避免服务冷启动时白耗几百 MB
_model_holder: dict[str, Any] = {"instance": None, "signature": None}


def _get_model():
    """返回已就绪的 faster-whisper 模型实例；未安装 faster-whisper 时抛 HTTPException 503"""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        logger.error("faster-whisper 未安装，无法处理语音转写请求: %s", exc)
        if getattr(sys, "frozen", False):
            detail = "当前桌面安装包缺少语音识别组件，请更新或重新安装 XCAGI。"
        else:
            detail = "语音识别依赖未就绪：请安装 `faster-whisper` 后重启 FastAPI。"
        raise HTTPException(
            status_code=503,
            detail=detail,
        ) from exc

    model_name = _resolve_model_name()
    device = _resolve_device()
    compute_type = _resolve_compute_type(device)
    signature = (model_name, device, compute_type)

    if _model_holder["instance"] is not None and _model_holder["signature"] == signature:
        return _model_holder["instance"]

    logger.info(
        "加载语音识别模型：model=%s device=%s compute_type=%s",
        model_name,
        device,
        compute_type,
    )
    try:
        model_source = _resolve_model_source(model_name)
        instance = WhisperModel(model_source, device=device, compute_type=compute_type)
    except RECOVERABLE_ERRORS as exc:  # 例如 CUDA 不可用、模型未下载、依赖 DLL 缺失
        logger.exception("加载 faster-whisper 模型失败: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"语音识别模型加载失败：{exc}",
        ) from exc

    _model_holder["instance"] = instance
    _model_holder["signature"] = signature
    return instance


def _save_upload_to_tempfile(upload: UploadFile, raw: bytes) -> Path:
    """把上传内容落盘到临时文件。faster-whisper 内部用 ffmpeg 解码，通用 webm/ogg/wav/mp4 都能读。"""
    suffix = ""
    if upload.filename:
        suffix = Path(upload.filename).suffix
    if not suffix:
        mime = (upload.content_type or "").lower()
        if "webm" in mime:
            suffix = ".webm"
        elif "ogg" in mime:
            suffix = ".ogg"
        elif "mp4" in mime or "m4a" in mime:
            suffix = ".m4a"
        elif "wav" in mime or "wave" in mime:
            suffix = ".wav"
        else:
            suffix = ".bin"

    tmp = tempfile.NamedTemporaryFile(prefix="xcagi_chat_asr_", suffix=suffix, delete=False)
    try:
        tmp.write(raw)
        tmp.flush()
    finally:
        tmp.close()
    return Path(tmp.name)


def _run_transcribe(path: Path, language: str | None) -> dict[str, Any]:
    model = _get_model()

    beam = max(1, int(_env("XCAGI_CHAT_ASR_BEAM", "1")))
    lang = (language or _env("XCAGI_CHAT_ASR_LANGUAGE", "zh")).strip() or None

    try:
        segments_iter, info = model.transcribe(
            str(path),
            language=lang,
            beam_size=beam,
            vad_filter=False,  # 前端已按住才录音，完全不需要再做 VAD 切分
            condition_on_previous_text=False,
            without_timestamps=True,
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("faster-whisper 转写失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"语音识别执行失败：{exc}") from exc

    parts = [(seg.text or "").strip() for seg in segments_iter]
    text = "".join(parts).strip()

    return {
        "text": text,
        "language": getattr(info, "language", lang) or "",
        "audio_seconds": float(getattr(info, "duration", 0.0) or 0.0),
    }


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(..., description="按住说话录制的音频（webm/ogg/wav/m4a）"),
    language: str | None = Form(default=None, description="ISO 语言代码，如 zh/en；留空走默认"),
):
    """短语音转文字：直接把 MediaRecorder 的 blob 发上来即可。"""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="录音内容为空")
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"录音文件过大：{len(raw)} 字节，上限 {_MAX_UPLOAD_BYTES} 字节",
        )

    tmp_path = _save_upload_to_tempfile(file, raw)
    t0 = time.monotonic()
    try:
        result = _run_transcribe(tmp_path, language)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except RECOVERABLE_ERRORS as exc:
            logger.debug("删除 ASR 临时文件失败（可忽略）: %s", exc)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    return {
        "success": True,
        "data": {
            **result,
            "elapsed_ms": elapsed_ms,
            "bytes": len(raw),
        },
    }


@router.get("/health")
async def voice_health():
    """轻量健康检查：只检查 faster-whisper 是否可导入，不触发模型加载（避免健康检查拖慢冷启动）。"""
    try:
        import faster_whisper  # noqa: F401 — 仅检查可导入性，不加载模型

        ready = True
        reason = ""
    except RECOVERABLE_ERRORS as exc:
        ready = False
        reason = str(exc)
    return {
        "success": True,
        "data": {
            "ready": ready,
            "reason": reason,
            "model": _resolve_model_name(),
            "device_hint": _resolve_device(),
        },
    }


# ---------------------------------------------------------------------------
# 语音指令端到端：ASR → 意图识别 → 可选自动执行
# ---------------------------------------------------------------------------

# 高风险意图白名单：即使 auto_execute=True 也必须二次确认才执行。
# delete / clear_all 为典型 destructive 操作；customer_edit 改客户档案、wechat_send 对外发消息，
# 风险等级同样高，统一拒绝自动执行。
HIGH_RISK_INTENTS: frozenset[str] = frozenset(
    {
        "delete",
        "clear_all",
        "customer_edit",
        "wechat_send",
    }
)

# 意图置信度阈值：高于此值才允许 auto_execute 直接执行；低于则只返回意图供前端二次确认。
INTENT_CONFIDENCE_THRESHOLD: float = 0.7


def _transcribe_audio(file_path: Path, language: str | None = None) -> str:
    """对落盘的音频文件做 ASR，返回纯文本（不带 language / audio_seconds 等元信息）。

    供 /api/voice/command 复用：把 _run_transcribe 的字典结果压平成字符串，
    便于上层与意图识别链路串联。
    """
    result = _run_transcribe(file_path, language)
    return (result.get("text") or "").strip()


def _recognize_intent(text: str) -> dict[str, Any]:
    """对转写文本做意图识别，返回统一结构。

    优先复用规则引擎（``app.services.intent_service.recognize_intents``），
    规则未命中 tool_key 时再尝试 unified_intent_recognizer（覆盖蒸馏/BERT/DeepSeek 等慢路径，
    失败回退为纯规则结果）。规则引擎同步、轻量、无外部依赖，适合语音指令场景。

    返回字典字段：
    - tool_key: 命中的工具 key（如 ``shipment_generate``）；未命中为 None
    - primary_intent: 主意图 id
    - confidence: 0~1 浮点；规则引擎命中给 0.85，heuristic fallback 给 0.6，未命中 0.0
    - slots: 槽位 dict
    - is_negated: 是否否定式（如 "不要发货"）
    - is_greeting / is_goodbye / is_help / is_likely_unclear: 语义标记
    - intent_hints: 附加 hint 列表
    - source: 识别来源（rule / unified / unclear）
    """
    text_norm = (text or "").strip()
    if not text_norm:
        return {
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
            "source": "empty",
        }

    try:
        from app.application.business_route_facade import recognize_business_intents

        rule_result = recognize_business_intents(text_norm)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("语音指令意图识别失败（规则引擎）: %s", exc)
        rule_result = {
            "primary_intent": None,
            "tool_key": None,
            "intent_hints": [],
            "is_negated": False,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_confirmation": False,
            "is_negation_intent": False,
            "is_likely_unclear": True,
            "all_matched_tools": [],
            "slots": {},
        }

    tool_key = rule_result.get("tool_key")
    primary_intent = rule_result.get("primary_intent")
    slots = rule_result.get("slots", {}) or {}

    # 规则引擎命中 → 高置信度；heuristic fallback（只有 primary_intent 没有 tool_key）→ 中等置信度；
    # 完全未命中 → 0；is_likely_unclear 拉低置信度避免误触发。
    if tool_key:
        confidence = 0.85
        source = "rule"
    elif primary_intent:
        confidence = 0.6
        source = "rule_fallback"
    else:
        confidence = 0.0
        source = "unclear"

    if rule_result.get("is_likely_unclear"):
        confidence = min(confidence, 0.4)

    return {
        "tool_key": tool_key,
        "primary_intent": primary_intent,
        "confidence": float(confidence),
        "slots": slots,
        "is_negated": bool(rule_result.get("is_negated", False)),
        "is_greeting": bool(rule_result.get("is_greeting", False)),
        "is_goodbye": bool(rule_result.get("is_goodbye", False)),
        "is_help": bool(rule_result.get("is_help", False)),
        "is_likely_unclear": bool(rule_result.get("is_likely_unclear", False)),
        "intent_hints": list(rule_result.get("intent_hints", []) or []),
        "source": source,
    }


def _execute_intent_tool(
    tool_key: str,
    text: str,
    slots: dict[str, Any],
    session_id: str = "",
) -> dict[str, Any]:
    """复用 AIChatApplicationService._execute_pro_mode_tools 执行低风险工具。

    构造与 ai_chat_app_service 内部一致的 response_data / ai_result / parsed_params 形状，
    调用 mixin 方法触发真实工具执行（如 products 查询 / shipment_generate 开单）。
    任何异常向上抛出，由 voice_command 路由层捕获并降级为"未执行"。
    """
    if not tool_key:
        return {"executed": False, "result": None, "reason": "no_tool_key"}

    # 延迟导入避免冷启动拖慢 /transcribe 端点；get_ai_chat_app_service 是单例。
    from app.application.ai_chat_app_service import get_ai_chat_app_service

    app_service = get_ai_chat_app_service()

    response_data: dict[str, Any] = {
        "response": "",
        "data": {"data": {}},
        "toolCall": None,
    }
    ai_result: dict[str, Any] = {"text": text, "data": {}}
    parsed_params: dict[str, Any] = dict(slots or {})

    executed_data = app_service._execute_pro_mode_tools(
        response_data=response_data,
        tool_key=tool_key,
        slots=slots or {},
        parsed_params=parsed_params,
        ai_result=ai_result,
        original_message=text,
    )

    return {
        "executed": True,
        "result": {
            "response": executed_data.get("response", ""),
            "toolCall": executed_data.get("toolCall"),
            "data": executed_data.get("data", {}).get("data", {}),
        },
        "reason": "executed",
        "session_id": session_id,
    }


@router.post("/command")
async def voice_command(
    file: UploadFile = File(..., description="按住说话录制的音频（webm/ogg/wav/m4a）"),
    auto_execute: bool = Form(default=False, description="是否自动执行识别到的低风险意图"),
    session_id: str = Form(default="", description="会话 ID，用于执行链路追踪"),
    language: str | None = Form(default=None, description="ISO 语言代码，留空走默认"),
):
    """语音指令端到端：ASR → 意图识别 → 可选自动执行。

    与 /transcribe 的差异：
    - /transcribe 只返回文本，由用户手动点发送
    - /command 额外做意图识别，并按 auto_execute + 置信度 + 风险等级决定是否直接执行工具

    返回结构：
    - success: True
    - data.text: ASR 转写文本
    - data.intent: 命中的 tool_key（未命中为 None）
    - data.confidence: 意图置信度 0~1
    - data.executed: 是否真的执行了工具
    - data.result: 执行结果（executed=True 时非空）
    - data.reason: 未执行的原因代码：
        - ``asr_empty`` ASR 无文本
        - ``no_intent`` 未识别到意图
        - ``low_confidence`` 置信度低于阈值
        - ``high_risk_needs_confirmation`` 高风险意图需二次确认
        - ``negated`` 否定式意图
        - ``auto_execute_disabled`` auto_execute=False
        - ``execution_failed`` 执行抛异常
        - ``executed`` 执行成功
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="录音内容为空")
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"录音文件过大：{len(raw)} 字节，上限 {_MAX_UPLOAD_BYTES} 字节",
        )

    tmp_path = _save_upload_to_tempfile(file, raw)
    t0 = time.monotonic()
    try:
        text = _transcribe_audio(tmp_path, language)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except RECOVERABLE_ERRORS as exc:
            logger.debug("删除 ASR 临时文件失败（可忽略）: %s", exc)
    elapsed_asr_ms = int((time.monotonic() - t0) * 1000)

    # ASR 空文本：直接返回，避免无意义跑意图识别
    if not text:
        return {
            "success": True,
            "data": {
                "text": "",
                "intent": None,
                "primary_intent": None,
                "confidence": 0.0,
                "executed": False,
                "result": None,
                "reason": "asr_empty",
                "session_id": session_id,
                "elapsed_ms_asr": elapsed_asr_ms,
            },
        }

    # 意图识别（同步规则引擎，失败已兜底为 unclear）
    intent_data = _recognize_intent(text)
    tool_key = intent_data.get("tool_key")
    confidence = float(intent_data.get("confidence", 0.0))
    slots = intent_data.get("slots", {}) or {}
    is_negated = bool(intent_data.get("is_negated", False))

    # 决策是否自动执行
    executed = False
    result: dict[str, Any] | None = None
    reason: str = ""

    if not tool_key:
        reason = "no_intent"
    elif is_negated:
        reason = "negated"
    elif not auto_execute:
        reason = "auto_execute_disabled"
    elif tool_key in HIGH_RISK_INTENTS:
        # 高风险意图即使 auto_execute=True 也必须二次确认
        reason = "high_risk_needs_confirmation"
    elif confidence <= INTENT_CONFIDENCE_THRESHOLD:
        reason = "low_confidence"
    else:
        # 低风险 + 高置信度 + auto_execute=True → 真实执行
        try:
            exec_payload = _execute_intent_tool(tool_key, text, slots, session_id)
            executed = bool(exec_payload.get("executed", False))
            result = exec_payload.get("result")
            reason = exec_payload.get("reason", "executed" if executed else "execution_failed")
        except RECOVERABLE_ERRORS as exc:
            logger.exception("语音指令自动执行失败: tool=%s error=%s", tool_key, exc)
            reason = "execution_failed"
            result = {"error": str(exc)}

    return {
        "success": True,
        "data": {
            "text": text,
            "intent": tool_key,
            "primary_intent": intent_data.get("primary_intent"),
            "confidence": confidence,
            "executed": executed,
            "result": result,
            "reason": reason,
            "session_id": session_id,
            "slots": slots,
            "intent_hints": intent_data.get("intent_hints", []),
            "is_negated": is_negated,
            "is_high_risk": tool_key in HIGH_RISK_INTENTS if tool_key else False,
            "elapsed_ms_asr": elapsed_asr_ms,
        },
    }
