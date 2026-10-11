"""事故小组每个岗位的 handler 输出摘要（脱敏），持久化进 _team_claim，让 ok=false 可追溯。"""

from __future__ import annotations

import re
from typing import Any, Dict, List

_SECRET_KEY_RE = re.compile(r"(?i)(key|token|secret|password|passwd|credential|authorization)")
_SECRET_VALUE_RE = re.compile(
    r"(?i)(bearer\s+|(?:api[_-]?key|password|passwd|token|secret|authorization)\s*[:=]\s*)"
    r"[^\s,;'\"]+"
)
_TOKEN_SHAPES_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKID[A-Za-z0-9]{12,}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+)"
)
_SCALAR_KEYS = (
    "handler",
    "ok",
    "success",
    "status",
    "execution_status",
    "skipped",
    "reason",
    "error",
    "error_code",
    "failure_kind",
    "summary",
    "para_task_id",
    "task_id",
    "tool_name",
    "tool_fallback_used",
)
_TEXT_LIMIT = 300


def redact_text(value: Any, limit: int = _TEXT_LIMIT) -> str:
    text = _SECRET_VALUE_RE.sub(r"\1[redacted]", str(value))
    text = _TOKEN_SHAPES_RE.sub("[redacted]", text)
    return text[:limit]


def _scalar(key: str, value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    return redact_text(value)


def _row_digest(row: Any) -> Dict[str, Any]:
    if not isinstance(row, dict):
        return {"handler": "?", "type": type(row).__name__}
    out: Dict[str, Any] = {}
    for key in _SCALAR_KEYS:
        if key in row and not _SECRET_KEY_RE.search(key) and row.get(key) not in ("", None):
            out[key] = _scalar(key, row.get(key))
    nested = row.get("output")
    if isinstance(nested, dict):
        for key in ("status", "error", "error_code", "summary"):
            if nested.get(key) not in ("", None):
                out[f"output_{key}"] = _scalar(key, nested.get(key))
    elif nested not in ("", None):
        out["output_chars"] = len(str(nested))
    attempts = row.get("tool_fallback_attempts")
    if isinstance(attempts, list):
        out["tool_fallback_attempts"] = [
            {
                k: _scalar(k, a.get(k))
                for k in ("tool_name", "status", "error")
                if isinstance(a, dict) and a.get(k) not in ("", None)
            }
            for a in attempts[:5]
        ]
    return out


def handler_output_digest(result: Any) -> Dict[str, Any]:
    """返回 {status, llm_tokens, cognition_error, outputs:[...]}，不含原始 payload 与密钥。"""
    if not isinstance(result, dict):
        return {"outputs": [], "invalid_result": True}
    nested = result.get("result") if isinstance(result.get("result"), dict) else {}
    outputs = nested.get("outputs") if isinstance(nested.get("outputs"), list) else []
    digest: Dict[str, Any] = {
        "outputs": [_row_digest(row) for row in outputs[:12]],
    }
    for key in ("status", "execution_status", "error", "failure_kind"):
        if result.get(key) not in ("", None):
            digest[key] = _scalar(key, result.get(key))
    if result.get("handler_failed"):
        digest["handler_failed"] = True
    if "llm_tokens" in result:
        try:
            digest["llm_tokens"] = int(result.get("llm_tokens") or 0)
        except (TypeError, ValueError):
            digest["llm_tokens"] = 0
    if result.get("cognition_error"):
        digest["cognition_error"] = redact_text(result.get("cognition_error"))
    handlers: List[str] = [str(h) for h in nested.get("handlers") or [] if h][:12]
    if handlers:
        digest["handlers"] = handlers
    return digest
