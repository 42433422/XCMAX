"""Deterministic, read-only intake deduplication and routing planner."""

from __future__ import annotations

import hashlib
from typing import Any


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    requests = dict(payload or {}).get("requests")
    if not isinstance(requests, list) or not requests:
        return _failed("requests must be a non-empty list", "missing_requests")
    planned: list[dict[str, str]] = []
    seen: set[str] = set()
    issues: list[dict[str, str]] = []
    for index, raw in enumerate(requests[:200]):
        item = raw if isinstance(raw, dict) else {}
        request_id = str(item.get("id") or "").strip()[:160]
        text = " ".join(str(item.get("text") or "").split())[:2000]
        owner = str(item.get("route_hint") or "task-router-officer").strip()[:160]
        if not request_id or not text:
            issues.append({"code": "missing_request_context", "path": f"requests[{index}]"})
            continue
        fingerprint = hashlib.sha256(text.lower().encode("utf-8")).hexdigest()[:16]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        planned.append({"request_id": request_id, "fingerprint": fingerprint, "proposed_owner": owner})
    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": f"需求入口已只读核对：{len(requests[:200])} 条输入归并为 {len(planned)} 条唯一需求，{len(issues)} 个缺口；未派发或回复。",
        "routing_plan": planned,
        "duplicate_count": max(0, len(requests[:200]) - len(planned) - len(issues)),
        "issues": issues,
        "evidence": ["input.requests"],
        "read_only": True,
        "side_effects": [],
    }


def _failed(message: str, code: str) -> dict[str, Any]:
    return {"ok": False, "status": "failed", "summary": message, "error_code": code, "evidence": [], "read_only": True, "side_effects": []}
