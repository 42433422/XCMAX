# -*- coding: utf-8 -*-
"""
微信小程序：兼容导出（无 Flask 蓝图）。

HTTP 由 FastAPI 路由（``legacy_gaps_batch1/2``）提供；此处仅保留归档/脚本可用的符号。
"""

from __future__ import annotations

from app.decorators.mp_auth import (
    get_current_mp_user_id,
    mp_auth_required,
    verify_jwt_token,
)
from app.http.wechat_miniprogram_responses import jsonify_response
from app.services.wechat_miniprogram_auth import (
    WechatMiniProgramError,
    get_wechat_config,
    miniprogram_login_data_for_wx_username_binding,
    wechat_login_code2session,
)

miniprogram_auth_required = mp_auth_required

__all__ = [
    "WechatMiniProgramError",
    "get_current_mp_user_id",
    "get_wechat_config",
    "jsonify_response",
    "miniprogram_auth_required",
    "miniprogram_login_data_for_wx_username_binding",
    "mp_auth_required",
    "verify_jwt_token",
    "wechat_login_code2session",
]
