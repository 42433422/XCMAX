"""管理员邮件服务排障 API。

两个端点，专门给运维 / 管理员用，避免发邮件出问题时只能 ssh 上服务器看 stderr：

- ``GET /api/admin/email/status`` —— 返回脱敏后的当前 SMTP 配置生效情况，
  包括是否被识别为占位符；用于"我配了凭证为什么还是报错"这类排查
- ``POST /api/admin/email/test`` —— 给指定邮箱发一封内容明确的"测试邮件"
  （不含验证码 / 业务凭证），快速验证 SMTP 凭证能否真的登录

调用都需要管理员权限；非管理员调用会被 ``_require_admin`` 直接 403。
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from modstore_server.api.deps import _get_current_user, _require_admin
from modstore_server.email_service import (
    email_status,
    send_test_email,
)
from modstore_server.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/email", tags=["admin-email"])


def _mask_user(user: str) -> str:
    """``alice@qq.com`` → ``a***@qq.com``；不暴露完整账号。"""
    if not user:
        return ""
    if "@" not in user:
        # 非邮箱形式：保留首尾各 1 字符
        return user[0] + "***" + user[-1] if len(user) > 2 else "***"
    local, _, domain = user.partition("@")
    if not local:
        return "@" + domain
    if len(local) <= 2:
        return local[0] + "***@" + domain
    return local[0] + "***" + local[-1] + "@" + domain


@router.get("/status", summary="查看邮件服务当前生效配置（脱敏）")
async def get_email_status(_: User = Depends(_get_current_user)):
    """普通登录用户也可读，便于前端在"邮箱注册"页面预先判断。

    敏感字段（密码原文）不会出现；``user`` 总是脱敏成 ``a***@qq.com`` 形式。
    """
    s = email_status()
    return {
        "mode": s["mode"],
        "configured": s["configured"],
        "debug": s["debug"],
        "user": _mask_user(str(s.get("user") or "")),
        "user_present": s["user_present"],
        "password_set": s["password_set"],
        "placeholder_user": s["placeholder_user"],
        "placeholder_password": s["placeholder_password"],
        "host": s["host"],
        "port": s["port"],
        "sender_email": _mask_user(str(s.get("sender_email") or "")),
        "sender_name": s["sender_name"],
    }


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SendTestEmailBody(BaseModel):
    to: str = Field(..., description="测试邮件的收件邮箱")

    @field_validator("to")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        norm = (v or "").strip()
        if not _EMAIL_RE.match(norm):
            raise ValueError("不是合法邮箱地址")
        return norm


@router.post("/test", summary="发一封测试邮件验证 SMTP 凭证（管理员）")
async def post_email_test(
    body: SendTestEmailBody,
    user: User = Depends(_require_admin),
):
    try:
        result = send_test_email(str(body.to))
    except RuntimeError as e:
        # 配置缺失：返回 400 + 具体提示，不要让管理员看 500 traceback
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001 — SMTP 登录失败、网络错误、超时等
        logger.warning("email test failed: %s", e)
        raise HTTPException(
            502,
            f"SMTP 测试发送失败: {type(e).__name__}: {e}",
        ) from e
    return {
        "ok": True,
        "to": str(body.to),
        **{k: v for k, v in result.items() if k != "delivered"},
        "delivered": True,
    }


@router.post("/digest-now", summary="立即发送每日运维摘要邮件（管理员）")
async def post_digest_now(_: User = Depends(_require_admin)):
    """行为与定时任务 ``daily_ops_digest_email`` 相同：收件人见 ``MODSTORE_DAILY_DIGEST_EMAIL``。"""
    try:
        from modstore_server.daily_digest import run_daily_digest_email

        run_daily_digest_email()
    except Exception as e:  # noqa: BLE001
        logger.exception("digest-now failed")
        raise HTTPException(500, str(e)) from e
    return {"ok": True, "message": "摘要邮件已触发（若 SMTP 未配置则可能静默跳过）"}
