"""Boundary parsing and public projections for the Kellai customer copilot."""

from __future__ import annotations

import hashlib
import json
from typing import Any


class KellaiCopilotError(RuntimeError):
    """A safe client-facing copilot error."""


def public_draft(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "draft_id": str(value.get("draft_id") or ""),
        "customer_id": int(value.get("customer_id") or 0),
        "summary": str(value.get("summary") or ""),
        "intent": str(value.get("intent") or ""),
        "risk_level": str(value.get("risk_level") or "medium"),
        "next_action": str(value.get("next_action") or ""),
        "reply_draft": str(value.get("reply_draft") or ""),
        "evidence_message_ids": list(value.get("evidence_message_ids") or []),
        "status": str(value.get("status") or "pending_approval"),
        "created_at": str(value.get("created_at") or ""),
        "decided_at": str(value.get("decided_at") or ""),
        "decision_note": str(value.get("decision_note") or ""),
        "model": str(value.get("model") or ""),
    }


def public_follow_up_task(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "task_id": str(value.get("task_id") or ""),
        "customer_id": int(value.get("customer_id") or 0),
        "source_draft_id": str(value.get("source_draft_id") or ""),
        "title": str(value.get("title") or ""),
        "description": str(value.get("description") or ""),
        "priority": str(value.get("priority") or "normal"),
        "status": str(value.get("status") or "open"),
        "due_at": str(value.get("due_at") or ""),
        "created_at": str(value.get("created_at") or ""),
        "completed_at": str(value.get("completed_at") or ""),
        "cancelled_at": str(value.get("cancelled_at") or ""),
        "outcome_result": str(value.get("outcome_result") or ""),
    }


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
