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

import io
import logging
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

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
_model_lock = threading.Lock()


def _get_model():
    with _model_lock:
        return _load_model()


def _load_model():
    """返回已就绪的 faster-whisper 模型实例；未安装 faster-whisper 时抛 HTTPException 503"""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        logger.exception("faster-whisper 未安装，无法处理语音转写请求")
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
        logger.exception("加载 faster-whisper 模型失败")
        raise HTTPException(
            status_code=503,
            detail="语音识别模型暂时不可用，请稍后重试",
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


def _model_is_loaded() -> bool:
    return _model_holder.get("instance") is not None


def _run_transcribe(path: Path, language: str | None) -> dict[str, Any]:
    cold_start = not _model_is_loaded()
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
        logger.exception("faster-whisper 转写失败")
        raise HTTPException(status_code=500, detail="语音识别执行失败，请稍后重试") from exc

    parts = [(seg.text or "").strip() for seg in segments_iter]
    text = "".join(parts).strip()

    return {
        "text": text,
        "language": getattr(info, "language", lang) or "",
        "audio_seconds": float(getattr(info, "duration", 0.0) or 0.0),
        "cold_start": cold_start,
        "model_loaded": True,
    }


def _asr_wav(path: Path) -> tuple[bytes, float]:
    import av

    pcm = bytearray()
    limit = 16000 * 120 * 2
    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=16000)

    def append_frames(frames):
        for frame in frames:
            pcm.extend(frame.to_ndarray().tobytes())
            if len(pcm) > limit:
                raise HTTPException(422, "录音超过 2 分钟")

    try:
        with av.open(str(path), mode="r", metadata_errors="ignore") as container:
            for frame in container.decode(audio=0):
                append_frames(resampler.resample(frame))
            append_frames(resampler.resample(None))
    except (av.error.FFmpegError, ValueError, IndexError):
        raise HTTPException(422, "无法读取录音，请重新录制") from None
    if not pcm:
        raise HTTPException(422, "录音为空")
    out = io.BytesIO()
    with wave.open(out, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(pcm)
    return out.getvalue(), len(pcm) / 32000


async def _platform_transcribe(
    request: Request, path: Path, language: str | None
) -> dict[str, Any]:
    import httpx

    from app.fastapi_routes.ai_assistant_tts import _session_market_token
    from app.fastapi_routes.market_bridge.http_transport import _auth_header
    from app.fastapi_routes.market_bridge.settings import _market_api_base_url

    token = _session_market_token(request)
    if not token:
        raise HTTPException(401, "当前账户未连接平台")
    try:
        wav, duration = await run_in_threadpool(_asr_wav, path)
        async with httpx.AsyncClient(timeout=75.0) as client:
            response = await client.post(
                f"{_market_api_base_url()}/api/workbench/asr",
                headers={"Authorization": _auth_header(token)},
                files={"file": ("speech.wav", wav, "audio/wav")},
                data={"language": language if language in {"zh", "en"} else "auto"},
            )
        if response.status_code != 200:
            raise HTTPException(response.status_code, "平台语音识别不可用，请核对额度及服务状态")
        result = response.json()
        if (
            not isinstance(result, dict)
            or result.get("provider") != "mimo"
            or not isinstance(result.get("text"), str)
        ):
            raise ValueError("invalid platform response")
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("platform ASR failed: %s", type(exc).__name__)
        raise HTTPException(502, "平台语音识别请求失败，请勿自动重试") from None
    return {
        "text": result["text"],
        "language": result.get("language", ""),
        "audio_seconds": duration,
        "cold_start": False,
        "model_loaded": True,
    }


@router.post("/transcribe")
async def transcribe_audio(
    request: Request,
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
        result = (
            await _platform_transcribe(request, tmp_path, language)
            if _env("XCAGI_CHAT_ASR_PROVIDER", "mimo").lower() == "mimo"
            else _run_transcribe(tmp_path, language)
        )
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
    if _env("XCAGI_CHAT_ASR_PROVIDER", "mimo").lower() == "mimo":
        return {
            "success": True,
            "data": {
                "ready": False,
                "reason": "平台识别状态尚未验证",
                "model": "mimo-v2.5-asr",
                "device_hint": "platform",
                "model_loaded": False,
            },
        }
    try:
        import faster_whisper  # noqa: F401 — 仅检查可导入性，不加载模型

        ready = True
        reason = ""
    except RECOVERABLE_ERRORS:
        ready = False
        reason = "faster-whisper not installed"
    return {
        "success": True,
        "data": {
            "ready": ready,
            "reason": reason,
            "model": _resolve_model_name(),
            "device_hint": _resolve_device(),
            "model_loaded": _model_is_loaded(),
        },
    }


@router.post("/warm")
def voice_warm():
    """Best-effort model warm so the first push-to-talk is not a 6–7s cold load.

    Safe: only loads into memory; does not delete data or change config.
    Disabled when XCAGI_CHAT_ASR_WARM=0.
    """
    if _env("XCAGI_CHAT_ASR_PROVIDER", "mimo").lower() == "mimo":
        return {
            "success": True,
            "data": {"warmed": False, "skipped": True, "model_loaded": False, "provider": "mimo"},
        }
    if (_env("XCAGI_CHAT_ASR_WARM", "1") or "1").strip().lower() in {"0", "false", "off", "no"}:
        return {
            "success": True,
            "data": {
                "warmed": False,
                "skipped": True,
                "model_loaded": _model_is_loaded(),
            },
        }
    already = _model_is_loaded()
    if already:
        return {
            "success": True,
            "data": {"warmed": True, "skipped": True, "model_loaded": True, "cold_start": False},
        }
    t0 = time.monotonic()
    _get_model()
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.info("voice model warm completed in %sms", elapsed_ms)
    return {
        "success": True,
        "data": {
            "warmed": True,
            "skipped": False,
            "model_loaded": True,
            "cold_start": True,
            "elapsed_ms": elapsed_ms,
        },
    }


# ---------------------------------------------------------------------------
# 语音指令统一进入聊天应用服务与 LangGraph
# ---------------------------------------------------------------------------


def _transcribe_audio(file_path: Path, language: str | None = None) -> str:
    """把 ASR 结果压成纯文本，供 /command 与 /transcribe 共用。"""
    result = _run_transcribe(file_path, language)
    return (result.get("text") or "").strip()


@router.post("/command")
async def voice_command(
    request: Request,
    file: UploadFile = File(..., description="按住说话录制的音频（webm/ogg/wav/m4a）"),
    auto_execute: bool = Form(default=False, description="是否把识别文本交给智能对话处理"),
    session_id: str = Form(default="", description="会话 ID，用于记忆与执行链路追踪"),
    language: str | None = Form(default=None, description="ISO 语言代码，留空走默认"),
):
    """ASR 后复用智能对话：不做第二次意图判决，也不直接调用业务工具。"""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="录音内容为空")
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"录音文件过大：{len(raw)} 字节，上限 {_MAX_UPLOAD_BYTES} 字节",
        )

    tmp_path = _save_upload_to_tempfile(file, raw)
    started = time.monotonic()
    try:
        text = (
            (await _platform_transcribe(request, tmp_path, language))["text"]
            if _env("XCAGI_CHAT_ASR_PROVIDER", "mimo").lower() == "mimo"
            else _transcribe_audio(tmp_path, language)
        )
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except RECOVERABLE_ERRORS as exc:
            logger.debug("删除 ASR 临时文件失败（可忽略）: %s", exc)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if not text:
        return {
            "success": True,
            "data": {
                "text": "",
                "executed": False,
                "result": None,
                "reason": "asr_empty",
                "session_id": session_id,
                "elapsed_ms_asr": elapsed_ms,
            },
        }

    executed = False
    result: dict[str, Any] | None = None
    reason = "auto_execute_disabled"
    if auto_execute:
        try:
            from app.application.ai_chat_app_service import get_ai_chat_app_service
            from app.fastapi_routes.xcagi_compat_chat_helpers import (
                _runtime_context_with_authenticated_actor,
            )

            runtime_context = _runtime_context_with_authenticated_actor(request, {})
            if session_id:
                runtime_context["session_id"] = session_id
                runtime_context["conversation_id"] = session_id
            from app.application.ai_chat.chat_evidence import prepare_chat_evidence

            runtime_context = prepare_chat_evidence(request, runtime_context, text)
            runtime_context.pop("_chat_evidence_prepared_marker", None)
            payload = get_ai_chat_app_service().process_chat(
                user_id=str(
                    runtime_context.get("actor_id") or runtime_context.get("user_id") or "default"
                ),
                message=text,
                context=runtime_context,
                source="voice",
                file_context={},
            )
            result = payload if isinstance(payload, dict) else {"response": str(payload)}
            details = result.get("data") if isinstance(result.get("data"), dict) else {}
            inner = details.get("data") if isinstance(details.get("data"), dict) else {}
            node_results = inner.get("node_results") if isinstance(inner, dict) else []
            executed = any(
                isinstance(node, dict) and node.get("success") is True
                for node in (node_results if isinstance(node_results, list) else [])
            )
            reason = "executed" if executed else "workflow_pending_or_not_executed"
        except RECOVERABLE_ERRORS:
            logger.exception("语音命令转智能对话主链失败")
            reason = "execution_failed"
            result = {"success": False, "message": "智能对话处理暂时不可用"}

    return {
        "success": True,
        "data": {
            "text": text,
            "executed": executed,
            "result": result,
            "reason": reason,
            "session_id": session_id,
            "elapsed_ms_asr": elapsed_ms,
        },
    }
