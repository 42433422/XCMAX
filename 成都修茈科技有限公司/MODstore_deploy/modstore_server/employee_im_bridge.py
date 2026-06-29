"""员工 → 老板 IM 桥接。

员工执行管道在关键节点（cognition/verification/handoff/Phase-D ask）调本模块，
通过 HTTP 调 FHD 后端的内部 endpoint `POST /api/internal/employee-im/send`，
让员工在 IM 系统里像真人一样主动给老板发一条消息。

设计为 best-effort：FHD 故障/超时只 log，不抛错，不影响员工主流程。
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _internal_im_url() -> str:
    """FHD 后端的员工 IM 推送 endpoint URL。

    通过环境变量 `FHD_INTERNAL_EMPLOYEE_IM_URL` 配置，未配则返回空字符串（禁用推送）。
    """
    return os.environ.get("FHD_INTERNAL_EMPLOYEE_IM_URL", "").strip()


def _internal_api_key() -> str:
    """调 FHD 内部 API 用的 Bearer key。"""
    return (
        os.environ.get("FHD_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or ""
    ).strip()


def _boss_user_id() -> int:
    """Phase 1：全局老板 user_id（env 配置）。Phase 3 改 per-employee owner 表。"""
    raw = os.environ.get("FHD_BOSS_USER_ID", "").strip()
    try:
        return int(raw) if raw else 0
    except ValueError:
        logger.warning("FHD_BOSS_USER_ID 非法值：%r，跳过 IM 推送", raw)
        return 0


def _enabled() -> bool:
    """是否启用员工 IM 推送。三项都配齐才算启用。"""
    return bool(_internal_im_url() and _internal_api_key() and _boss_user_id())


def notify_boss(
    employee_id: str,
    *,
    mod_id: str = "",
    display_name: str = "",
    avatar_url: str = "",
    body: str,
    hook: str = "",
) -> bool:
    """员工主动给老板发一条 IM 消息。

    参数：
        employee_id: 员工 ID（如 llm-ops-engineer）
        mod_id: 员工所属 mod_id（用于 FHD 端建虚拟用户时元数据）
        display_name: 员工显示名（如 "LLM 运维工程师"）
        avatar_url: 员工头像 URL
        body: 消息正文（必填，非空）
        hook: 触发源标记（cognition/verification/handoff/ask 等，用于日志追踪）

    返回 True 表示推送成功；False 表示失败或被禁用。任何异常都不抛出。
    """
    body_text = (body or "").strip()
    if not body_text:
        return False
    if not _enabled():
        logger.debug(
            "employee_im_bridge 跳过推送：env 未配齐（url/key/boss_uid），employee=%s hook=%s",
            employee_id,
            hook,
        )
        return False

    url = _internal_im_url()
    payload: dict[str, Any] = {
        "boss_user_id": _boss_user_id(),
        "employee_id": str(employee_id or "").strip(),
        "mod_id": mod_id or "",
        "display_name": display_name or "",
        "avatar_url": avatar_url or "",
        "body": body_text[:4000],
        "hook": hook or "",
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Internal-Api-Key": _internal_api_key(),
    }
    try:
        import httpx

        # 内部 endpoint（127.0.0.1/localhost）必须绕过 HTTP_PROXY/HTTPS_PROXY，
        # 否则 dev 机的 clash/v2ray 等本地代理会把请求转发出去导致 502。
        with httpx.Client(timeout=5.0, trust_env=False) as client:
            resp = client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            logger.warning(
                "employee_im_bridge 推送失败 HTTP %s：employee=%s hook=%s body=%.200s",
                resp.status_code,
                employee_id,
                hook,
                resp.text,
            )
            return False
        logger.info(
            "employee_im_bridge 推送成功：employee=%s hook=%s body=%.80s",
            employee_id,
            hook,
            body_text,
        )
        return True
    except Exception as exc:
        logger.warning(
            "employee_im_bridge 推送异常：employee=%s hook=%s err=%s",
            employee_id,
            hook,
            exc,
        )
        return False
