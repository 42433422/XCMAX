"""Vision-in helpers: OpenAI-style chat messages with multipart ``content``."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional

# Rough vision token budget per image when upstream does not return usage.prompt_tokens.
VISION_IMAGE_TOKEN_ESTIMATE = int(os.environ.get("MODSTORE_VISION_IMAGE_TOKEN_ESTIMATE", "1024"))
MULTIMODAL_MAX_TOTAL_BYTES = int(
    os.environ.get("MODSTORE_MULTIMODAL_MAX_TOTAL_BYTES", str(12 * 1024 * 1024))
)


def message_has_image_parts(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    for p in content:
        if isinstance(p, dict) and p.get("type") == "image_url":
            return True
    return False


def messages_have_multimodal_images(messages: Iterable[Dict[str, Any]]) -> bool:
    for m in messages:
        if message_has_image_parts(m.get("content")):
            return True
    return False


def messages_use_openai_multipart_content(messages: Iterable[Dict[str, Any]]) -> bool:
    """True if any message uses OpenAI-style ``content`` as a list of parts (text / image_url)."""
    for m in messages:
        if isinstance(m.get("content"), list):
            return True
    return False


def approximate_multimodal_payload_bytes(messages: Iterable[Dict[str, Any]]) -> int:
    """Sum byte length of embedded base64 in data URLs (does not decode)."""
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c.encode("utf-8"))
        elif isinstance(c, list):
            for p in c:
                if not isinstance(p, dict):
                    continue
                if p.get("type") == "text":
                    total += len(str(p.get("text") or "").encode("utf-8"))
                    continue
                if p.get("type") != "image_url":
                    continue
                iu = p.get("image_url") or {}
                url = str(iu.get("url") or "")
                if "base64," in url:
                    b64 = url.split("base64,", 1)[-1]
                    total += len(b64)
                else:
                    total += len(url.encode("utf-8"))
    return total


def validate_multimodal_payload_size(messages: Iterable[Dict[str, Any]]) -> Optional[str]:
    n = approximate_multimodal_payload_bytes(messages)
    if n > MULTIMODAL_MAX_TOTAL_BYTES:
        return (
            f"多模态请求体积过大（约 {n // 1024 // 1024}MB），"
            f"上限 {MULTIMODAL_MAX_TOTAL_BYTES // 1024 // 1024}MB；请压缩图片或减少数量。"
        )
    return None


def flatten_message_content_for_risk(content: Any) -> str:
    """Strip base64 from blocked-word scan (no huge strings)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for p in content:
            if not isinstance(p, dict):
                continue
            if p.get("type") == "text":
                parts.append(str(p.get("text") or ""))
            elif p.get("type") == "image_url":
                parts.append("[image]")
        return "\n".join(parts)
    return ""


def redact_message_content_for_storage(content: Any) -> str:
    """Persist chat history without embedding base64 blobs."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        safe: List[Dict[str, Any]] = []
        for p in content:
            if not isinstance(p, dict):
                continue
            if p.get("type") == "text":
                safe.append({"type": "text", "text": str(p.get("text") or "")[:8000]})
            elif p.get("type") == "image_url":
                iu = p.get("image_url") or {}
                url = str(iu.get("url") or "")
                if url.startswith("data:") and "base64," in url:
                    safe.append({"type": "image_url", "image_url": {"url": "[redacted:data-url]"}})
                else:
                    safe.append({"type": "image_url", "image_url": {"url": url[:500]}})
            else:
                safe.append({"type": str(p.get("type")), "note": "[omitted]"})
        return json.dumps(safe, ensure_ascii=False)
    return str(content)


def first_user_text_preview(messages: Iterable[Dict[str, Any]], *, max_len: int = 80) -> str:
    for m in messages:
        if (m.get("role") or "") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return (c or "").strip()[:max_len]
        if isinstance(c, list):
            texts = [
                str(p.get("text") or "")
                for p in c
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            return "\n".join(texts).strip()[:max_len]
    return ""
