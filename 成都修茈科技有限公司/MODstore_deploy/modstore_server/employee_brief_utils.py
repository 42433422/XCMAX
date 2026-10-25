"""Shared brief extraction for employee pipeline routing and validation."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

_INITIAL_IDEA = re.compile(r"【初始想法】\s*([\s\S]*?)(?=---|\n\n【|$)", re.I)
_PLACEHOLDER_MARKERS = re.compile(
    r"（无回复）|相处报备|开始写吧|若无疑问，将按此方案",
    re.I,
)


def extract_initial_idea_block(text: str) -> str:
    """Pull the 【初始想法】 section when present."""
    raw = (text or "").strip()
    if not raw:
        return ""
    m = _INITIAL_IDEA.search(raw)
    if m:
        return m.group(1).strip()
    if raw.startswith("【初始想法】"):
        return raw.replace("【初始想法】", "", 1).split("---")[0].strip()
    return ""


def compact_routing_brief(text: str, *, max_len: int = 200) -> str:
    """Strip planning blocks and placeholders; keep first meaningful line(s)."""
    full = (text or "").strip()
    if not full:
        return ""
    idea = extract_initial_idea_block(full)
    chunks = [idea] if idea and not _PLACEHOLDER_MARKERS.search(idea.strip()) else []
    for sep in ("【执行清单】", "【澄清对话】", "【语音规划记录】"):
        if sep in full:
            chunks.append(full.split(sep, 1)[-1].strip())
    if not chunks:
        chunks = [full]
    lines: list[str] = []
    for chunk in chunks:
        for line in chunk.splitlines():
            s = line.strip()
            if not s or _PLACEHOLDER_MARKERS.search(s) or s in ("---",):
                continue
            if s.startswith("【") and s.endswith("】"):
                continue
            lines.append(s)
            if len("\n".join(lines)) >= max_len:
                break
        if lines:
            break
    out = "\n".join(lines).strip()
    return out[:max_len] if out else ""


def extract_routing_brief(payload: Optional[Dict[str, Any]], *, fallback: str = "") -> str:
    """Best-effort brief for is_word_full_extract / asset routing."""
    if not isinstance(payload, dict):
        return compact_routing_brief(fallback)
    candidates = [
        payload.get("employee_brief"),
        payload.get("brief"),
        fallback,
    ]
    plan = payload.get("employee_orchestration_plan")
    if isinstance(plan, dict):
        candidates.insert(0, plan.get("employee_brief"))
    for c in candidates:
        s = compact_routing_brief(str(c or ""))
        if s:
            return s
    return ""


def is_contract_doc_review_brief(text: str) -> bool:
    bl = (text or "").lower()
    return any(
        k in bl
        for k in (
            "合同",
            "法务",
            "合规",
            "审核",
            "条款",
            "contract",
            "legal",
            "compliance",
            "review",
        )
    )
