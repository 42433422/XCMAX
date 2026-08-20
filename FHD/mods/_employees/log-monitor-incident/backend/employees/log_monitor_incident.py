"""Deterministic, read-only incident fingerprint aggregator."""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    events = dict(payload or {}).get("events")
    if not isinstance(events, list) or not events:
        return _failed("events must be a non-empty list", "missing_events")
    fingerprints: list[str] = []
    issues: list[dict[str, str]] = []
    for index, raw in enumerate(events[:1000]):
        event = raw if isinstance(raw, dict) else {}
        service = str(event.get("service") or "").strip()[:160]
        error_type = str(event.get("error_type") or "").strip()[:160]
        message = " ".join(str(event.get("message") or "").split())[:1000]
        if not service or not error_type or not message:
            issues.append({"code": "invalid_event", "path": f"events[{index}]"})
            continue
        fingerprints.append(
            hashlib.sha256(f"{service}|{error_type}|{message}".encode()).hexdigest()[:16]
        )
    counts = Counter(fingerprints)
    incidents = [{"fingerprint": key, "count": count} for key, count in sorted(counts.items())]
    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": f"错误事件已只读聚合：{len(events[:1000])} 条日志形成 {len(incidents)} 个故障指纹，{len(issues)} 个无效事件；未读取主机日志或创建工单。",
        "incidents": incidents,
        "issues": issues,
        "evidence": ["input.events"],
        "read_only": True,
        "side_effects": [],
    }


def _failed(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message,
        "error_code": code,
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }
