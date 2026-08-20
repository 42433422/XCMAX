"""老板 IM 回复 → MODstore 员工闭环的出站回流客户端。

老板在某 AI 员工的 1:1 聊天页发消息后，把消息转发给 MODstore 的
``POST /api/admin/employee-autonomy/internal/answer-latest``。MODstore 侧决定去向：
该员工有 pending phase-D 问题则解阻塞；否则把消息转成该员工的新任务
（boss_im）并以 IM 回音——老板的话永远有下文。

供手机端 ``internal_im.im_post_message`` 与桌面/Web 端 ``im_routes.im_send_message``
共用（此前仅手机端回流，桌面/Web 发的消息到不了员工）。best-effort：
MODstore 故障/未配置只 log，不影响 IM 主流程。
"""

from __future__ import annotations

import logging
import os

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _modstore_internal_base() -> str:
    return (
        (
            os.environ.get("XCAGI_MODSTORE_INTERNAL_URL")
            or os.environ.get("MODSTORE_INTERNAL_BASE_URL")
            or os.environ.get("MODSTORE_PUBLIC_API_BASE")
            or "http://127.0.0.1:9999"
        )
        .strip()
        .rstrip("/")
    )


def _internal_api_key() -> str:
    return (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()


def relay_boss_reply_to_employee(boss_user_id: int, employee_id: str, answer: str) -> bool:
    """把老板在员工聊天页的回复回流给 MODstore（同步、best-effort、不抛错）。

    异步路由中请用 ``asyncio.to_thread`` 调用，避免阻塞事件循环。
    返回 True 表示 MODstore 已受理（2xx）；False 表示未配置 / 失败。
    """
    key = _internal_api_key()
    text = (answer or "").strip()
    if not key or int(boss_user_id or 0) <= 0 or not str(employee_id or "").strip() or not text:
        return False
    try:
        import httpx

        # 内部 endpoint（127.0.0.1/localhost）必须绕过 HTTP_PROXY/HTTPS_PROXY，
        # 否则本地代理会把请求转发出去导致 502。
        with httpx.Client(timeout=5, trust_env=False) as client:
            resp = client.post(
                f"{_modstore_internal_base()}/api/admin/employee-autonomy/internal/answer-latest",
                headers={"X-Internal-Api-Key": key},
                json={
                    "user_id": int(boss_user_id),
                    "employee_id": str(employee_id),
                    "answer": text,
                },
            )
        if resp.status_code >= 400:
            logger.warning(
                "relay_boss_reply_to_employee HTTP %s",
                resp.status_code,
            )
            return False
        return True
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - 回流失败不影响 IM 主流程
        logger.debug("relay_boss_reply_to_employee failed", exc_info=True)
        return False


__all__ = ["relay_boss_reply_to_employee"]
