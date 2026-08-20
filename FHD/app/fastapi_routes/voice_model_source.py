"""ASR model selection and recoverable download-source resolution."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_MODEL_ALLOW_PATTERNS = (
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
)
_DEFAULT_MODEL_ENDPOINTS = ("https://huggingface.co", "https://hf-mirror.com")


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def resolve_device() -> str:
    configured = env("XCAGI_CHAT_ASR_DEVICE").lower()
    if configured in ("cpu", "cuda"):
        return configured
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except RECOVERABLE_ERRORS:
        return "cpu"


def resolve_compute_type(device: str) -> str:
    configured = env("XCAGI_CHAT_ASR_COMPUTE_TYPE").lower()
    return configured or ("float16" if device == "cuda" else "int8")


def resolve_model_name() -> str:
    return env("XCAGI_CHAT_ASR_MODEL", "small")


def model_download_endpoints() -> tuple[str, ...]:
    raw = env("XCAGI_CHAT_ASR_MODEL_ENDPOINTS")
    values = raw.split(",") if raw else list(_DEFAULT_MODEL_ENDPOINTS)
    endpoints: list[str] = []
    for value in values:
        endpoint = value.strip().rstrip("/")
        if endpoint and endpoint not in endpoints:
            endpoints.append(endpoint)
    return tuple(endpoints)


def resolve_model_source(model_name: str) -> str:
    """Resolve a cached model or download it through a recoverable endpoint chain."""
    model_path = Path(model_name).expanduser()
    if model_path.exists():
        return str(model_path)
    try:
        from faster_whisper.utils import _MODELS, download_model
    except ImportError:
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
    for endpoint in model_download_endpoints():
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
