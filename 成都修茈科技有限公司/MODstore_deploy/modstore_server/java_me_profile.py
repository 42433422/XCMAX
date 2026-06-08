"""Java 支付服务上的用户档案片段：在 PAYMENT_BACKEND=java 时与 Python /api/auth/me 合并。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from modstore_server.application.payment_gateway import PaymentGatewayService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JavaUserOverlay:
    """从 Java GET /api/auth/me 解析出的、可安全写回前端的字段。"""

    experience: int
    level_profile: Optional[Dict[str, Any]]
    phone: Optional[str] = None


def fetch_java_user_overlay(
    authorization: str, *, expect_user_id: int
) -> Optional[JavaUserOverlay]:
    """在 PAYMENT_BACKEND=java 时请求 Java ``/api/auth/me``，与钱包 / LLM 经验同源。

    - 校验 ``user.id`` 与当前 Python 会话用户一致，避免错合并。
    - 仅当 JSON 中带有可解析的 ``experience``（或 ``level_profile.experience``）时才覆盖经验，避免旧网关缺字段时把本地经验误改成 0。
    """
    raw = (authorization or "").strip()
    if not raw.lower().startswith("bearer "):
        return None
    gw = PaymentGatewayService()
    if gw.backend != "java":
        return None
    base = gw.target_base_url().rstrip("/")
    url = f"{base}/api/auth/me"
    try:
        from modstore_server.infrastructure.http_clients import get_java_sync_client

        timeout = min(30.0, float(gw.connect_timeout_seconds) + float(gw.read_timeout_seconds))
        resp = get_java_sync_client().get(url, headers={"Authorization": raw}, timeout=timeout)
    except Exception as exc:
        logger.warning("Java /api/auth/me 不可达，经验字段保留 Python 库: %s", exc)
        return None
    if resp.status_code != 200:
        logger.warning("Java /api/auth/me 非 200(%s)，经验字段保留 Python 库", resp.status_code)
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    inner = data.get("user")
    if not isinstance(inner, dict):
        if isinstance(data.get("experience"), (int, float, str)) and data.get("id") is not None:
            inner = data
        else:
            return None
    try:
        jid = int(inner.get("id"))
    except (TypeError, ValueError):
        return None
    if jid != int(expect_user_id):
        logger.warning(
            "Java /api/auth/me 的 user.id=%s 与当前会话 user.id=%s 不一致，跳过合并",
            jid,
            expect_user_id,
        )
        return None

    exp: Optional[int] = None
    if "experience" in inner:
        try:
            exp = int(inner.get("experience") or 0)
        except (TypeError, ValueError):
            exp = 0
    lp_raw = inner.get("level_profile")
    lp: Optional[Dict[str, Any]] = lp_raw if isinstance(lp_raw, dict) else None
    if exp is None and isinstance(lp, dict) and "experience" in lp:
        try:
            exp = int(lp.get("experience") or 0)
        except (TypeError, ValueError):
            exp = 0
    if exp is None:
        return None

    exp = max(int(exp), 0)
    if lp is not None and not lp:
        lp = None
    if lp is not None and not isinstance(lp, dict):
        lp = None

    phone_raw = inner.get("phone")
    phone: Optional[str] = None
    if isinstance(phone_raw, str) and phone_raw.strip():
        phone = phone_raw.strip()

    return JavaUserOverlay(experience=exp, level_profile=lp, phone=phone)
