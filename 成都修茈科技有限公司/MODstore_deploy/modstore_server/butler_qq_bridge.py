# ruff: noqa: E402, F401
"""数字管家 ↔ QQ 官方机器人 V2 桥接。

把数字管家（``xc-digital-butler`` 这位虚拟 AI 员工）作为一个真实的 QQ 机器人
身份接到 QQ 开放平台。所有 QQ 群/单聊里 @机器人 的消息都会被路由到现有
``agent_butler_api`` 的 LLM 调用链，回复再用同一个机器人身份送回 QQ。

关键事实：
- QQ 开放平台 V2 走 ``api.sgroup.qq.com`` (生产) 或 ``sandbox.api.sgroup.qq.com``。
- AccessToken 通过 ``https://bots.qq.com/app/getAppAccessToken`` 用 AppID +
  AppSecret 换取，约 7200 秒过期。本模块在内存里缓存并提前 5 分钟续期。
- 入站事件由 QQ 主动 POST 到我们配置的 webhook，需要 Ed25519 验签。
- 注册新 webhook 时，QQ 会先发一次 ``op=13`` 校验包，载荷里有 ``plain_token``
  和 ``event_ts``，必须用同一对 Ed25519 密钥签 ``event_ts + plain_token`` 并
  原样回 ``{plain_token, signature}``。

Ed25519 密钥按 QQ 文档约定派生：把 ``BotSecret`` 字节串自我重复延展到 32
字节作为 seed，``SigningKey(seed)`` 即得。

本模块的 router 只在 ``BUTLER_QQ_APP_ID`` / ``BUTLER_QQ_APP_SECRET`` 都配齐时才
真正注册路由，否则导入即跳过——这样开发机不需要装 ``pynacl`` 也能跑测试。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Literal, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ─── 配置读取（账号池优先，ENV 作 fallback） ─────────────────────────
#
# 凭证有两种来源：
#
# 1. AI 员工账号池（DB 表 ``ai_employee_accounts`` + 密钥文件
#    ``_local_secrets/qq/<id>.json``）——首选；
# 2. 进程 ENV ``BUTLER_QQ_APP_ID / BUTLER_QQ_APP_SECRET / BUTLER_QQ_BOT_TOKEN
#    / BUTLER_QQ_SANDBOX``——单租户/极简部署的 fallback。
#
# 真正下游使用的入口函数仍是 ``_qq_app_id() / _qq_app_secret() / _qq_bot_token()
# / _qq_sandbox()``——签名、AccessToken 拉取、出站三类发送都从这里取，
# 切换实现不需要动其它代码。


_BUTLER_EMPLOYEE_ID = "xc-digital-butler"
_CREDS_CACHE_TTL_SECONDS = 30


from modstore_server.butler_qq_bridge_part01 import (
    _env as _env,
    _bridge_user_id as _bridge_user_id,
    _CredsState as _CredsState,
)


_creds_state = _CredsState()


from modstore_server.butler_qq_bridge_part02 import (
    _load_creds_from_pool as _load_creds_from_pool,
    _load_creds_from_env as _load_creds_from_env,
    _resolve_creds as _resolve_creds,
    invalidate_creds_cache as invalidate_creds_cache,
    _qq_app_id as _qq_app_id,
    _qq_app_secret as _qq_app_secret,
    _qq_bot_token as _qq_bot_token,
    _qq_sandbox as _qq_sandbox,
    _qq_credential_source as _qq_credential_source,
    _qq_api_base as _qq_api_base,
    _qq_token_endpoint as _qq_token_endpoint,
    _own_llm as _own_llm,
    is_configured as is_configured,
    _derive_seed as _derive_seed,
    _signing_key_for as _signing_key_for,
    _signing_key as _signing_key,
    sign_payload as sign_payload,
    _sign_payload_for as _sign_payload_for,
    verify_inbound as verify_inbound,
    _verify_inbound_for as _verify_inbound_for,
    _all_known_app_secrets as _all_known_app_secrets,
    _TokenState as _TokenState,
)


_token_state = _TokenState()
_TOKEN_REFRESH_LEAD_SECONDS = 300


from modstore_server.butler_qq_bridge_part03 import (
    get_access_token as get_access_token,
)


# ─── 出站消息客户端 ─────────────────────────────────────────────────


MsgKind = Literal["group", "c2c", "channel"]


from modstore_server.butler_qq_bridge_part04 import (
    _SeqRegistry as _SeqRegistry,
)


_seq_registry = _SeqRegistry()


from modstore_server.butler_qq_bridge_part05 import (
    _send as _send,
    _BotContext as _BotContext,
)


# 进程内按 app_id 缓存 BotContext，启动时惰性填充
_bot_ctx_cache: Dict[str, "_BotContext"] = {}
_bot_ctx_lock = asyncio.Lock()


from modstore_server.butler_qq_bridge_part06 import (
    invalidate_bot_ctx_cache as invalidate_bot_ctx_cache,
    _get_bot_ctx as _get_bot_ctx,
    _specific_ctx_for_employee as _specific_ctx_for_employee,
    _get_bot_ctx_by_employee as _get_bot_ctx_by_employee,
)


# ─── 入站 → 多员工分发 ───────────────────────────────────────────────


_KIND_BY_EVENT: Dict[str, MsgKind] = {
    "GROUP_AT_MESSAGE_CREATE": "group",
    "C2C_MESSAGE_CREATE": "c2c",
    "AT_MESSAGE_CREATE": "channel",
    "DIRECT_MESSAGE_CREATE": "channel",
}


from modstore_server.butler_qq_bridge_part07 import (
    _strip_at as _strip_at,
    _extract_target_id as _extract_target_id,
    dispatch_to_butler as dispatch_to_butler,
    dispatch_to_employee as dispatch_to_employee,
    _resolve_reply as _resolve_reply,
)


_QQ_REPLY_MAX_LEN = 800


from modstore_server.butler_qq_bridge_part08 import (
    _execute_employee_for_qq as _execute_employee_for_qq,
)


_EMPLOYEE_PERSONAS: Dict[str, str] = {
    "xc-digital-butler": "你是 XC AGI 数字管家，平台全站智能助手，擅长页面导航、解答平台问题、协调 AI 员工。",
    "task-router-officer": "你是任务路由员，专门接收用户/管理员的任务请求，分析意图后路由给最合适的 AI 员工处理，简洁高效。",
    "employee-interview-assistant": "你是员工访谈员，负责收集 AI 员工的工作进度、问题反馈和日报，整理后汇报给管理员。",
}

_EMPLOYEE_FALLBACK_PERSONA = "你是 XC AGI 平台 AI 员工，请专业、简洁地回答用户问题。"


from modstore_server.butler_qq_bridge_part09 import (
    _employee_chat as _employee_chat,
    _resolve_llm_for_butler as _resolve_llm_for_butler,
    _butler_chat as _butler_chat,
)


# ─── FastAPI 路由 ───────────────────────────────────────────────────


router = APIRouter(prefix="/api/agent/butler/qq", tags=["butler-qq"])


from modstore_server.butler_qq_bridge_part10 import (
    _PushDTO as _PushDTO,
    _check_admin as _check_admin,
    qq_status as qq_status,
    qq_webhook_probe as qq_webhook_probe,
)


# ─── 已配 QQ 的两位员工：webhook_key → (app_id, employee_id, app_secret) ──
#
# 这两位员工已经在 QQ 开放平台后台注册了独立 BotAppID，并且 admin 也希望
# 它们具备一等公民的 QQ 渠道：每条入站消息都跑各自的执行器（不是简单
# LLM persona），出站时也用自己的机器人身份回复。
#
# 字段语义：
#   - ``app_id``     QQ 开放平台分配的 BotAppID
#   - ``employee_id`` 与 catalog/manifest 里登记的员工 ID 严格一致
#   - ``app_secret_env`` 该 BotAppSecret 所在的环境变量名；运维填了即用，
#                       未填则尝试从账号池密钥文件回退
#
# 这样三件事都被绑死：webhook URL → 哪位员工 → 用谁的 AppSecret 验签。
_SPECIFIC_WEBHOOKS: Dict[str, Dict[str, str]] = {
    "task-router": {
        "app_id": "1903978019",
        "employee_id": "task-router-officer",
        "app_secret_env": "TASK_ROUTER_QQ_APP_SECRET",
        "bot_token_env": "TASK_ROUTER_QQ_BOT_TOKEN",
    },
    "employee-interview": {
        "app_id": "1903979052",
        "employee_id": "employee-interview-assistant",
        "app_secret_env": "EMPLOYEE_INTERVIEW_QQ_APP_SECRET",
        "bot_token_env": "EMPLOYEE_INTERVIEW_QQ_BOT_TOKEN",
    },
}

# 兼容旧调用：仍允许其他模块/测试按 webhook_key 拿 app_id 字符串。
_SPECIFIC_WEBHOOK_APP_IDS: Dict[str, str] = {k: v["app_id"] for k, v in _SPECIFIC_WEBHOOKS.items()}


from modstore_server.butler_qq_bridge_part11 import (
    _specific_app_secret as _specific_app_secret,
    _specific_bot_token as _specific_bot_token,
    _resolve_webhook_app_id as _resolve_webhook_app_id,
    qq_specific_webhook_probe as qq_specific_webhook_probe,
    qq_specific_webhook as qq_specific_webhook,
    qq_employee_webhook_probe as qq_employee_webhook_probe,
    qq_employee_webhook as qq_employee_webhook,
    qq_webhook as qq_webhook,
    _qq_webhook_impl as _qq_webhook_impl,
    qq_push as qq_push,
    qq_reload_cache as qq_reload_cache,
    _ensure_runtime_ready as _ensure_runtime_ready,
)


if not _ensure_runtime_ready():
    # 缺 pynacl 时让 app_factory 的 include_router 仍能跑，但路由表保持空。
    router = APIRouter(prefix="/api/agent/butler/qq", tags=["butler-qq"])
