"""「无邮箱」企业账号的单一真相源（SSOT）。

无邮箱注册不再"只在本地建号"——而是统一走市场注册（``register_market_user``），
只是用一个**占位邮箱** ``{username}@auto.xiu-ci.com`` 顶替真实邮箱，从而：

- 账号在市场（单一鉴权源）里存在 → market-first 登录认得，注册=登录账号打通；
- 占位后缀 ``@auto.xiu-ci.com`` 即「无邮箱」的判据，前端据此显示「无邮箱」。

判据极简：邮箱以 ``@auto.xiu-ci.com`` 结尾 ⇔ 该账号无真实邮箱。
"""

from __future__ import annotations

# 占位邮箱域名。改这里即改全局「无邮箱」判据与生成。
NO_EMAIL_DOMAIN = "auto.xiu-ci.com"
_SUFFIX = f"@{NO_EMAIL_DOMAIN}"

# 账号页对「无邮箱」账号展示的文案。
NO_EMAIL_DISPLAY = "无邮箱"


def synth_no_email_address(username: str) -> str:
    """为无邮箱注册生成占位邮箱 ``{username}@auto.xiu-ci.com``。"""
    uname = (username or "").strip()
    return f"{uname}{_SUFFIX}"


def is_no_email_address(email: str | None) -> bool:
    """该邮箱是否为占位（无邮箱）邮箱。判据=后缀，大小写不敏感。"""
    return str(email or "").strip().lower().endswith(_SUFFIX)


def email_display(email: str | None) -> str:
    """账号页展示用：占位邮箱显示「无邮箱」，真实邮箱原样返回。"""
    raw = str(email or "").strip()
    return NO_EMAIL_DISPLAY if is_no_email_address(raw) else raw


__all__ = [
    "NO_EMAIL_DOMAIN",
    "NO_EMAIL_DISPLAY",
    "synth_no_email_address",
    "is_no_email_address",
    "email_display",
]
