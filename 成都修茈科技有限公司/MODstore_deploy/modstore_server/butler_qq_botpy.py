"""数字管家 QQ 官方机器人 — botpy WebSocket Gateway 集成

在 QQ 开放平台后台不提供 Webhook 入口时（通常是"频道机器人"模式），
本模块通过 qq-botpy SDK 建立 WebSocket 长连接，接收以下事件并转交
butler_qq_bridge.dispatch_to_butler 处理：

- AT_MESSAGE_CREATE      频道内 @ 机器人
- MESSAGE_CREATE         频道内全量消息（需私域权限）
- DIRECT_MESSAGE_CREATE  私信/DM
- GROUP_AT_MESSAGE_CREATE QQ群 @ 机器人（V2 公域群）
- C2C_MESSAGE_CREATE     QQ单聊消息（V2 C2C）

集成方式：
  在 app_factory.create_app() 里加一行
      "modstore_server.butler_qq_botpy"
  到 _optional 列表。模块加载时注册一个空 router（占位），
  并向 FastAPI app 注册 on_event("startup") 钩子启动 botpy 后台任务。

依赖：qq-botpy>=1.2.1（已在 pyproject.toml 中加入 pynacl 旁边）
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter

logger = logging.getLogger(__name__)

# 空 router，让 app_factory 的 include_router 正常通过
router = APIRouter(prefix="/api/agent/butler/qqbot", tags=["butler-qqbot"])

_botpy_task: Optional[asyncio.Task] = None


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _is_configured() -> bool:
    return bool(_env("BUTLER_QQ_APP_ID") and _env("BUTLER_QQ_APP_SECRET"))


# ─── botpy MyClient ────────────────────────────────────────────────────────


def _make_client():
    """动态创建 botpy Client，避免在 import 时就初始化事件循环。"""
    import botpy
    from botpy.message import C2CMessage, DirectMessage, GroupMessage, Message

    # 引用 bridge 的 dispatch 函数（懒加载避免循环依赖）
    from modstore_server.butler_qq_bridge import dispatch_to_butler  # type: ignore

    class _ButlerClient(botpy.Client):
        # ── 频道 @ 消息 ──────────────────────────────────────────────────
        async def on_at_message_create(self, message: Message):
            text = (message.content or "").strip()
            payload = {
                "id": message.id,
                "content": text,
                "channel_id": getattr(message, "channel_id", ""),
                "guild_id": getattr(message, "guild_id", ""),
                "author": {
                    "id": getattr(message.author, "id", ""),
                    "username": getattr(message.author, "username", ""),
                },
                "_botpy_msg": message,  # 传下去给 send 用
                "_channel": "guild_at",
            }
            asyncio.create_task(dispatch_to_butler("AT_MESSAGE_CREATE", payload))

        # ── 频道全量消息（私域）──────────────────────────────────────────
        async def on_message_create(self, message: Message):
            text = (message.content or "").strip()
            payload = {
                "id": message.id,
                "content": text,
                "channel_id": getattr(message, "channel_id", ""),
                "guild_id": getattr(message, "guild_id", ""),
                "author": {
                    "id": getattr(message.author, "id", ""),
                    "username": getattr(message.author, "username", ""),
                },
                "_botpy_msg": message,
                "_channel": "guild",
            }
            asyncio.create_task(dispatch_to_butler("MESSAGE_CREATE", payload))

        # ── 私信 DM ─────────────────────────────────────────────────────
        async def on_direct_message_create(self, message: DirectMessage):
            text = (message.content or "").strip()
            payload = {
                "id": message.id,
                "content": text,
                "guild_id": getattr(message, "guild_id", ""),
                "author": {
                    "id": getattr(message.author, "id", ""),
                    "username": getattr(message.author, "username", ""),
                },
                "_botpy_msg": message,
                "_channel": "dm",
            }
            asyncio.create_task(dispatch_to_butler("DIRECT_MESSAGE_CREATE", payload))

        # ── QQ 群 @ 消息（V2 公域群）────────────────────────────────────
        async def on_group_at_message_create(self, message: GroupMessage):
            text = (getattr(message, "content", None) or "").strip()
            payload = {
                "id": getattr(message, "id", ""),
                "content": text,
                "group_openid": getattr(message, "group_openid", ""),
                "author": {
                    "member_openid": (
                        getattr(message.author, "member_openid", "") if message.author else ""
                    )
                },
                "_botpy_msg": message,
                "_channel": "group",
            }
            asyncio.create_task(dispatch_to_butler("GROUP_AT_MESSAGE_CREATE", payload))

        # ── QQ 单聊 C2C ──────────────────────────────────────────────────
        async def on_c2c_message_create(self, message: C2CMessage):
            text = (getattr(message, "content", None) or "").strip()
            payload = {
                "id": getattr(message, "id", ""),
                "content": text,
                "author": {
                    "user_openid": (
                        getattr(message.author, "user_openid", "") if message.author else ""
                    )
                },
                "_botpy_msg": message,
                "_channel": "c2c",
            }
            asyncio.create_task(dispatch_to_butler("C2C_MESSAGE_CREATE", payload))

        async def on_ready(self):
            logger.info(
                "butler-qqbot: WebSocket ready, robot=%s", self.robot.name if self.robot else "?"
            )

        async def on_error(self, event_name: str, *args, **kwargs):
            logger.error("butler-qqbot: error in event %s args=%s", event_name, args[:1])

    return _ButlerClient


async def _run_botpy_forever() -> None:
    """后台协程：启动 botpy WebSocket，断线自动重连。"""
    import botpy

    app_id = _env("BUTLER_QQ_APP_ID")
    app_secret = _env("BUTLER_QQ_APP_SECRET")
    is_sandbox = _env("BUTLER_QQ_SANDBOX", "0") in ("1", "true", "yes", "on")

    intents = botpy.Intents(
        public_messages=True,  # QQ 群 @ + C2C（V2 公域必须）
        public_guild_messages=True,  # 频道 @ 消息
        direct_message=True,  # 私信
        guilds=True,
        guild_members=True,
    )

    _ClientClass = _make_client()

    backoff = 5
    while True:
        try:
            client = _ClientClass(
                intents=intents,
                is_sandbox=is_sandbox,
                bot_log=False,  # 由项目统一 logging 管理
            )
            logger.info("butler-qqbot: connecting (sandbox=%s) ...", is_sandbox)
            await client.start(app_id, app_secret)
        except asyncio.CancelledError:
            logger.info("butler-qqbot: cancelled, stopping.")
            break
        except Exception as exc:
            logger.error("butler-qqbot: connection error: %s, retry in %ss", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)
        else:
            backoff = 5  # 正常退出后重置退避


def start_botpy_background(app) -> None:
    """在 FastAPI startup 时调用，挂载 botpy 后台任务。"""
    if not _is_configured():
        logger.info("butler-qqbot: BUTLER_QQ_APP_ID/SECRET 未配，跳过 botpy 启动。")
        return

    try:
        import botpy  # noqa: F401
    except ImportError:
        logger.warning("butler-qqbot: qq-botpy 未安装，跳过（pip install qq-botpy）。")
        return

    @app.on_event("startup")
    async def _botpy_startup():
        global _botpy_task
        loop = asyncio.get_event_loop()
        _botpy_task = loop.create_task(_run_botpy_forever())
        logger.info("butler-qqbot: background WebSocket task started.")

    @app.on_event("shutdown")
    async def _botpy_shutdown():
        global _botpy_task
        if _botpy_task and not _botpy_task.done():
            _botpy_task.cancel()
            try:
                await _botpy_task
            except asyncio.CancelledError:
                pass
        logger.info("butler-qqbot: background task stopped.")
