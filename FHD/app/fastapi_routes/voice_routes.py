"""
Voice / ASR Routes - FastAPI Implementation

为前端主聊天输入栏提供"按住说话"语音转写能力，独立于专业模式 phone_agent 链路：
- POST /api/voice/transcribe      短录音（MediaRecorder blob）→ 文本

与 mods/sz-qsm-pro/phone_agent/asr_processor.py 的差异：
- 那边针对电话采音流（float32 numpy + 双阈值 VAD 分段），这里直接接受 webm/ogg/wav 文件。
- 为避免互相污染模型实例和环境变量，这里使用独立的 XCAGI_CHAT_ASR_* 命名空间。
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB；等同于 OpenAI Whisper 官方上限，足够覆盖一次按住说话

# 懒加载：第一次调用才把 faster-whisper 模型加载进内存，避免服务冷启动时白耗几百 MB
_model_holder: dict[str, Any] = {"instance": None, "signature": None}

_MODEL_ALLOW_PATTERNS = (
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
)
_DEFAULT_MODEL_ENDPOINTS = (
    "https://huggingface.co",
    "https://hf-mirror.com",
)


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return (v or default).strip()


def _resolve_device() -> str:
    d = _env("XCAGI_CHAT_ASR_DEVICE").lower()
    if d in ("cpu", "cuda"):
        return d
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except RECOVERABLE_ERRORS:
        return "cpu"


def _resolve_compute_type(device: str) -> str:
    ct = _env("XCAGI_CHAT_ASR_COMPUTE_TYPE").lower()
    if ct:
        return ct
    return "float16" if device == "cuda" else "int8"


def _resolve_model_name() -> str:
    # 主聊天用短语音，默认 small 在中英文混合时命中率/速度平衡较好；可以在环境变量覆盖成 tiny / medium
    return _env("XCAGI_CHAT_ASR_MODEL", "small")


def _model_download_endpoints() -> tuple[str, ...]:
    raw = _env("XCAGI_CHAT_ASR_MODEL_ENDPOINTS")
    values = raw.split(",") if raw else list(_DEFAULT_MODEL_ENDPOINTS)
    endpoints: list[str] = []
    for value in values:
        endpoint = value.strip().rstrip("/")
        if endpoint and endpoint not in endpoints:
            endpoints.append(endpoint)
    return tuple(endpoints)


def _resolve_model_source(model_name: str) -> str:
    """Resolve a cached model or download it through a recoverable endpoint chain."""
    model_path = Path(model_name).expanduser()
    if model_path.exists():
        return str(model_path)

    try:
        from faster_whisper.utils import _MODELS, download_model
    except ImportError:
        # Unit-test doubles and older faster-whisper builds can omit utils. In
        # that case retain WhisperModel's native resolution behaviour.
        return model_name

    try:
        return str(download_model(model_name, local_files_only=True))
    except RECOVERABLE_ERRORS:
        pass

    repo_id = model_name if "/" in model_name else _MODELS.get(model_name)
    if not repo_id:
        raise RuntimeError(f"不支持的语音模型：{model_name}")

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("语音模型下载组件未安装") from exc

    errors: list[str] = []
    for endpoint in _model_download_endpoints():
        logger.info("准备语音识别模型：model=%s endpoint=%s", model_name, endpoint)
        try:
            return str(
                snapshot_download(
                    repo_id,
                    allow_patterns=list(_MODEL_ALLOW_PATTERNS),
                    endpoint=endpoint,
                    etag_timeout=5,
                    max_workers=4,
                )
            )
        except RECOVERABLE_ERRORS as exc:
            errors.append(f"{endpoint}: {exc}")
            logger.warning("语音模型源不可用：endpoint=%s error=%s", endpoint, exc)

    detail = errors[-1] if errors else "没有可用下载源"
    raise RuntimeError(
        f"语音模型尚未缓存，且官方源与备用源均不可用；请检查网络后重试。最后错误：{detail}"
    )


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
