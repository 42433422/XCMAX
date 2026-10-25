"""LLM response parsing and transcript preparation for the Kellai copilot."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any


class KellaiCopilotError(RuntimeError):
    """A safe client-facing copilot error."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def content_from_completion(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    choices = result.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict):
            return str(message.get("content") or "").strip()
    return str(result.get("content") or "").strip()


def parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise KellaiCopilotError("AI 没有返回可用的结构化草稿，请重试")
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise KellaiCopilotError("AI 草稿格式无效，请重试") from exc
    if not isinstance(value, dict):
        raise KellaiCopilotError("AI 草稿格式无效，请重试")
    return value


def conversation_input(messages: list[dict[str, Any]]) -> tuple[str, list[str], str]:
    usable: list[dict[str, Any]] = []
    for message in messages[-24:]:
        if not isinstance(message, dict):
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        usable.append(
            {
                "id": str(message.get("id") or ""),
                "direction": (
                    "我方" if str(message.get("direction") or "") == "outbound" else "客户"
                ),
                "content": content[:1200],
                "created_at": str(message.get("created_at") or ""),
            }
        )
    if not usable:
        raise KellaiCopilotError("该客户还没有可用于分析的真实会话")
    fingerprint_source = "\n".join(
        f"{item['id']}|{item['direction']}|{item['created_at']}|{item['content']}"
        for item in usable
    )
    fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
    evidence_ids = [item["id"] for item in usable[-8:] if item["id"]]
    return json.dumps(usable, ensure_ascii=False), evidence_ids, fingerprint
