# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Image and video generation protocols for the unified LLM proxy."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from modstore_server.platform_model_transport import llm_http_response, redact_key

_MAX_IMAGE_RESPONSE_BYTES = 24 * 1024 * 1024
_MAX_VIDEO_RESPONSE_BYTES = 1024 * 1024


def validated_video_fields(result: dict) -> tuple[str, str, str] | None:
    """Bound durable provider references without truncating their identity."""
    from urllib.parse import urlsplit

    job = result.get("job_id") or ""
    status = result.get("status") or "pending"
    preview = result.get("preview_url") or ""
    if not all(isinstance(value, str) for value in (job, status, preview)):
        return None
    if len(job) > 256 or len(status) > 32 or len(preview) > 2048:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in job + status + preview):
        return None
    if preview:
        try:
            parsed = urlsplit(preview)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                return None
        except ValueError:
            return None
    return job, status, preview


def _facade() -> Any:
    from modstore_server import llm_chat_proxy

    return llm_chat_proxy


async def image_openai_compatible(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    *,
    provider: str = "openai",
    size: str = "1024x1024",
    n: int = 1,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/images/generations"
    body: Dict[str, Any] = {
        "model": model or "gpt-image-1",
        "prompt": prompt,
        "size": size,
        "n": max(1, min(int(n or 1), 4)),
    }
    async with llm_http_response(
        url,
        api_key,
        _facade()._openai_request_headers(provider, api_key),
        body,
        timeout=_facade()._LLM_TIMEOUT,
        limits=_facade()._LLM_LIMITS,
        stream=True,
    ) as r:
        if r.status_code >= 300:
            return {"ok": False, "status": r.status_code, "error": "模型供应商请求失败"}
        content = bytearray()
        async for chunk in r.aiter_bytes():
            if len(content) + len(chunk) > _MAX_IMAGE_RESPONSE_BYTES:
                raise httpx.RequestError("生图供应商响应超过允许大小")
            content.extend(chunk)
        data = redact_key(json.loads(content), api_key)
    if not isinstance(data, dict):
        return {"ok": False, "error": "模型供应商未返回有效的媒体响应"}
    items = data.get("data")
    if not isinstance(items, list) or len(items) > body["n"]:
        return {"ok": False, "error": "模型供应商返回的图片数量无效"}
    images: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("url"):
            images.append(str(item["url"]))
        elif item.get("b64_json"):
            images.append(f"data:image/png;base64,{item['b64_json']}")
    return {"ok": True, "images": images, "raw": data}


async def image_dispatch(
    provider: str,
    *,
    api_key: str,
    base_url: Optional[str],
    model: str,
    prompt: str,
    size: str = "1024x1024",
    n: int = 1,
) -> Dict[str, Any]:
    if provider == "minimax" and _facade().is_minimax_token_plan_key(api_key):
        return {
            "ok": False,
            "error": "MiniMax Token Plan 密钥不提供 OpenAI-compatible images API",
        }
    if provider not in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        return {
            "ok": False,
            "error": f"provider {provider} does not expose OpenAI-compatible images API",
        }
    b = _facade()._normalize_openai_base(provider, base_url, api_key)
    return await _facade().image_openai_compatible(
        b, api_key, model or "gpt-image-1", prompt, provider=provider, size=size, n=n
    )


def _first_video_url(data: Any) -> str:
    if isinstance(data, dict):
        for key in ("url", "video_url", "output_url", "preview_url"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        nested = data.get("data")
        if isinstance(nested, list):
            for item in nested:
                hit = _facade()._first_video_url(item)
                if hit:
                    return hit
        elif isinstance(nested, dict):
            hit = _facade()._first_video_url(nested)
            if hit:
                return hit
        output = data.get("output")
        if isinstance(output, (dict, list)):
            hit = _facade()._first_video_url(output)
            if hit:
                return hit
    if isinstance(data, list):
        for item in data:
            hit = _facade()._first_video_url(item)
            if hit:
                return hit
    return ""


async def video_openai_compatible(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    *,
    provider: str = "openai",
    size: str = "1280x720",
    seconds: int = 5,
) -> Dict[str, Any]:
    safe_seconds = max(1, min(int(seconds or 5), 30))
    if provider == "doubao":
        url = f"{base_url.rstrip('/')}/contents/generations/tasks"
        body: Dict[str, Any] = {
            "model": model,
            "content": [{"type": "text", "text": prompt}],
            "duration": safe_seconds,
            "resolution": size,
        }
    else:
        url = f"{base_url.rstrip('/')}/videos"
        body = {"model": model, "prompt": prompt, "size": size, "seconds": safe_seconds}
    async with llm_http_response(
        url,
        api_key,
        _facade()._openai_request_headers(provider, api_key),
        body,
        timeout=_facade()._LLM_TIMEOUT,
        limits=_facade()._LLM_LIMITS,
        stream=True,
    ) as r:
        if r.status_code >= 300:
            return {"ok": False, "status": r.status_code, "error": "模型供应商请求失败"}
        content = bytearray()
        async for chunk in r.aiter_bytes():
            if len(content) + len(chunk) > _MAX_VIDEO_RESPONSE_BYTES:
                raise httpx.RequestError("视频供应商响应超过允许大小")
            content.extend(chunk)
        data = redact_key(json.loads(content), api_key)
    if not isinstance(data, dict):
        return {"ok": False, "error": "模型供应商未返回有效的媒体响应"}
    job_id = data.get("id") or data.get("job_id") or data.get("task_id") or ""
    status = data.get("status") or data.get("state") or "pending"
    preview_url = _facade()._first_video_url(data)
    return {
        "ok": True,
        "job_id": str(job_id or ""),
        "status": str(status or "pending"),
        "preview_url": preview_url,
        "raw": data,
    }


async def video_dispatch(
    provider: str,
    *,
    api_key: str,
    base_url: Optional[str],
    model: str,
    prompt: str,
    size: str = "1280x720",
    seconds: int = 5,
) -> Dict[str, Any]:
    if provider not in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        return {
            "ok": False,
            "error": f"provider {provider} does not expose OpenAI-compatible video API",
        }
    if not model:
        return {"ok": False, "error": "video model is required"}
    b = _facade()._normalize_openai_base(provider, base_url, api_key)
    return await _facade().video_openai_compatible(
        b, api_key, model, prompt, provider=provider, size=size, seconds=seconds
    )
