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

# 启动时读取一次提权令牌，避免每个 p2 请求都访问 ``os.environ``。
_ELEVATED_TOKEN: str = (os.environ.get("FHD_AI_ELEVATED_TOKEN") or "").strip()


def _elevated_token() -> str:
    """返回提权令牌（启动时缓存）。

    若启动时未配置（缓存为空），回退到实时读取，以兼容运行时通过 monkeypatch /
    动态注入设置该变量的测试与场景；生产环境在启动时配置后即走缓存、不再读 env。
    """
    return _ELEVATED_TOKEN or (os.environ.get("FHD_AI_ELEVATED_TOKEN") or "").strip()


def _header(request: Request | None, name: str) -> str:
    if request is None:
        return ""
    return (request.headers.get(name) or "").strip()


def resolve_ai_tier(request: Request | None) -> str:
    claimed = _header(request, "X-XCAGI-AI-Tier").lower()
    if claimed != "p2":
        return "p1"
    secret = _elevated_token()
    token = _header(request, "X-XCAGI-Elevated-Token")
    # 恒定时间比较，避免按字符短路导致的时序侧信道（与 mobile_jwt 校验一致）。
    if secret and token and hmac.compare_digest(token.encode("utf-8"), secret.encode("utf-8")):
        return "p2"
    return "p1"


def assert_p2_elevated_claim_or_raise(request: Request | None) -> None:
    claimed = _header(request, "X-XCAGI-AI-Tier").lower()
    strict = (os.environ.get("FHD_AI_TIER_STRICT") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if claimed == "p2" and strict and resolve_ai_tier(request) != "p2":
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
