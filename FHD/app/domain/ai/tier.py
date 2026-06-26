"""AI 能力分级 (P1/P2) 与受限工具判定。

Phase 3 从 ``app.legacy.ai_tier`` 迁入。
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException, Request

P1_BLOCKED_TOOL_NAMES: frozenset[str] = frozenset({"products_bulk_import"})

_ENV_ELEVATED_TOKEN_AT_IMPORT: str = (os.environ.get("FHD_AI_ELEVATED_TOKEN") or "").strip()
_ENV_TIER_STRICT_AT_IMPORT: str = (os.environ.get("FHD_AI_TIER_STRICT") or "").strip()

# 测试可通过 monkeypatch 重新赋值 `tier._ELEVATED_TOKEN` / `tier._TIER_STRICT`。
_ELEVATED_TOKEN: str = _ENV_ELEVATED_TOKEN_AT_IMPORT
_TIER_STRICT: bool = _ENV_TIER_STRICT_AT_IMPORT.lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _header(request: Request | None, name: str) -> str:
    if request is None:
        return ""
    return (request.headers.get(name) or "").strip()


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _elevated_token() -> str:
    current_env = (os.environ.get("FHD_AI_ELEVATED_TOKEN") or "").strip()
    if current_env != _ENV_ELEVATED_TOKEN_AT_IMPORT:
        return current_env
    return _ELEVATED_TOKEN


def _tier_strict() -> bool:
    current_env = (os.environ.get("FHD_AI_TIER_STRICT") or "").strip()
    if current_env != _ENV_TIER_STRICT_AT_IMPORT:
        return _truthy(current_env)
    return _TIER_STRICT


def resolve_ai_tier(request: Request | None) -> str:
    claimed = _header(request, "X-XCAGI-AI-Tier").lower()
    if claimed != "p2":
        return "p1"
    token = _header(request, "X-XCAGI-Elevated-Token")
    secret = _elevated_token()
    # 恒定时间比较，避免按字符短路导致的时序侧信道（与 mobile_jwt 校验一致）。
    if secret and token and hmac.compare_digest(token.encode("utf-8"), secret.encode("utf-8")):
        return "p2"
    return "p1"


def assert_p2_elevated_claim_or_raise(request: Request | None) -> None:
    claimed = _header(request, "X-XCAGI-AI-Tier").lower()
    if claimed == "p2" and _tier_strict() and resolve_ai_tier(request) != "p2":
        raise HTTPException(status_code=403, detail="p2 elevated token invalid")


def runtime_context_with_tier(
    runtime_context: Mapping[str, Any] | None, tier: str
) -> dict[str, Any]:
    out = dict(runtime_context or {})
    out["ai_tier"] = "p2" if tier == "p2" else "p1"
    return out


__all__ = [
    "P1_BLOCKED_TOOL_NAMES",
    "resolve_ai_tier",
    "assert_p2_elevated_claim_or_raise",
    "runtime_context_with_tier",
]
