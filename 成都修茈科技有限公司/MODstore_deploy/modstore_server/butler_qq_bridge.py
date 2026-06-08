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


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _bridge_user_id() -> int:
    """可选：把 QQ 来访都挂在哪个真实用户名下做审计/计费。0 = 不挂任何人。"""
    raw = _env("BUTLER_QQ_BRIDGE_USER_ID", "0")
    try:
        return max(int(raw), 0)
    except ValueError:
        return 0


class _CredsState:
    __slots__ = ("data", "expires_at")

    def __init__(self) -> None:
        self.data: Dict[str, Any] = {}
        self.expires_at: float = 0.0


_creds_state = _CredsState()


def _load_creds_from_pool() -> Optional[Dict[str, Any]]:
    """从账号池（DB + 密钥文件）拉一份当前生效的 QQ 凭证。

    任何环节出错都吞回 ``None``——让上层自动 fallback 到 ENV。这样即使
    DB 还没建表、字段缺失，也不至于让模块导入或 webhook 处理炸掉。
    """
    try:
        from modstore_server.ai_employee_account_api import lookup_active_account_for

        rec = lookup_active_account_for(_BUTLER_EMPLOYEE_ID, "qq")
        if not rec:
            return None
        secret = rec.get("secret") or {}
        app_id = str(secret.get("app_id") or rec.get("external_id") or "").strip()
        app_secret = str(secret.get("app_secret") or "").strip()
        bot_token = str(secret.get("bot_token") or "").strip()
        if not (app_id and app_secret and bot_token):
            return None
        return {
            "app_id": app_id,
            "app_secret": app_secret,
            "bot_token": bot_token,
            "sandbox": bool(rec.get("sandbox")),
            "source": "pool",
            "account_id": rec.get("id"),
        }
    except Exception as exc:
        logger.debug("从账号池读取 QQ 凭证失败，降级到 ENV：%s", exc)
        return None


def _load_creds_from_env() -> Dict[str, Any]:
    return {
        "app_id": _env("BUTLER_QQ_APP_ID"),
        "app_secret": _env("BUTLER_QQ_APP_SECRET"),
        "bot_token": _env("BUTLER_QQ_BOT_TOKEN"),
        "sandbox": _env("BUTLER_QQ_SANDBOX", "0") in ("1", "true", "yes", "on"),
        "source": "env",
        "account_id": None,
    }


def _resolve_creds() -> Dict[str, Any]:
    """统一入口：优先账号池、缺则 ENV，30s 一次缓存。"""
    now = time.time()
    if _creds_state.data and _creds_state.expires_at > now:
        return _creds_state.data
    creds = _load_creds_from_pool() or _load_creds_from_env()
    _creds_state.data = creds
    _creds_state.expires_at = now + _CREDS_CACHE_TTL_SECONDS
    return creds


def invalidate_creds_cache() -> None:
    """让下一次 ``_resolve_creds`` 重新查 DB——admin API 改完账号后可调用。"""
    _creds_state.data = {}
    _creds_state.expires_at = 0.0


def _qq_app_id() -> str:
    return _resolve_creds().get("app_id", "")


def _qq_app_secret() -> str:
    return _resolve_creds().get("app_secret", "")


def _qq_bot_token() -> str:
    return _resolve_creds().get("bot_token", "")


def _qq_sandbox() -> bool:
    return bool(_resolve_creds().get("sandbox", False))


def _qq_credential_source() -> str:
    """诊断用：当前凭证从哪来——pool / env / none。"""
    src = _resolve_creds().get("source") or ""
    if not _qq_app_id():
        return "none"
    return src


def _qq_api_base() -> str:
    return "https://sandbox.api.sgroup.qq.com" if _qq_sandbox() else "https://api.sgroup.qq.com"


def _qq_token_endpoint() -> str:
    return "https://bots.qq.com/app/getAppAccessToken"


def _own_llm() -> Tuple[str, str, str, Optional[str]]:
    """数字管家自带的"脑子"——这位 AI 员工的私人 LLM 凭证。

    返回 ``(provider, model, api_key, base_url)``。任一项缺失就返回空串/None；
    上层再决定是回退到 bridge_user 还是直接报错。
    """
    return (
        _env("BUTLER_QQ_LLM_PROVIDER"),
        _env("BUTLER_QQ_LLM_MODEL"),
        _env("BUTLER_QQ_LLM_API_KEY"),
        _env("BUTLER_QQ_LLM_BASE_URL") or None,
    )


def is_configured() -> bool:
    """是否已经配齐能正常跑的最小凭证集合。"""
    return bool(_qq_app_id() and _qq_app_secret() and _qq_bot_token())


# ─── Ed25519 签名 / 验签 ──────────────────────────────────────────────
#
# QQ 开放平台 V2 的官方派生方式：把 BotSecret 重复填充到 32 字节作为
# Ed25519 SigningKey 的 seed。生产/沙箱共用此规则。


def _derive_seed(secret: str) -> bytes:
    raw = secret.encode("utf-8")
    if not raw:
        raise ValueError("BUTLER_QQ_APP_SECRET 不能为空")
    while len(raw) < 32:
        raw = raw + raw
    return raw[:32]


def _signing_key_for(app_secret: str):
    from nacl.signing import SigningKey

    return SigningKey(_derive_seed(app_secret))


def _signing_key():
    """默认（数字管家）签名密钥。"""
    return _signing_key_for(_qq_app_secret())


def sign_payload(payload: bytes) -> bytes:
    return _signing_key().sign(payload).signature


def _sign_payload_for(payload: bytes, app_secret: str) -> bytes:
    return _signing_key_for(app_secret).sign(payload).signature


def verify_inbound(timestamp: str, body: bytes, signature_hex: str) -> bool:
    return _verify_inbound_for(timestamp, body, signature_hex, _qq_app_secret())


def _verify_inbound_for(timestamp: str, body: bytes, signature_hex: str, app_secret: str) -> bool:
    from nacl.exceptions import BadSignatureError

    if not (timestamp and signature_hex):
        return False
    try:
        sig = bytes.fromhex(signature_hex)
    except ValueError:
        return False
    msg = timestamp.encode("utf-8") + body
    verify_key = _signing_key_for(app_secret).verify_key
    try:
        verify_key.verify(msg, sig)
        return True
    except BadSignatureError:
        return False
    except Exception:
        return False


def _all_known_app_secrets() -> Dict[str, str]:
    """返回 ``{app_id: app_secret}``：ENV 默认 + 账号池中所有 QQ 机器人 +
    两位老员工（``_SPECIFIC_WEBHOOKS``）的静态条目。

    前两个来源已经覆盖大多数情况，第三个来源只是兜底——保证 webhook
    在 DB 没建表 / 账号还没建好时，老员工的 op=13 握手与业务事件
    验签依然能跑通。
    """
    result: Dict[str, str] = {}
    default_id = _qq_app_id()
    default_secret = _qq_app_secret()
    if default_id and default_secret:
        result[default_id] = default_secret
    try:
        from modstore_server.ai_employee_account_secrets import read_secret
        from modstore_server.models import get_session_factory
        from modstore_server.models_ai_accounts import AIEmployeeAccount

        sf = get_session_factory()
        with sf() as session:
            rows = (
                session.query(AIEmployeeAccount)
                .filter(
                    AIEmployeeAccount.platform == "qq",
                    AIEmployeeAccount.status == "active",
                )
                .all()
            )
        for row in rows:
            sec = read_secret(platform="qq", account_id=int(row.id))
            if sec:
                aid = str(sec.get("app_id") or row.external_id or "").strip()
                asecret = str(sec.get("app_secret") or "").strip()
                if aid and asecret:
                    result[aid] = asecret
    except Exception as exc:
        logger.debug("_all_known_app_secrets 读账号池失败: %s", exc)
    # 两位老员工：必须用 ``_specific_app_secret``（ENV 优先）覆盖账号池里
    # 可能写错 external_id / 密钥未同步的旧行，否则 op=13 会一直用错 Secret。
    for webhook_key, spec in _SPECIFIC_WEBHOOKS.items():
        aid = str(spec.get("app_id") or "").strip()
        if not aid:
            continue
        secret = _specific_app_secret(webhook_key)
        if secret:
            if result.get(aid) and result[aid] != secret:
                logger.info(
                    "QQ AppSecret 覆盖：app_id=%s 以 ENV/老员工专用解析为准（账号池值已忽略）",
                    aid,
                )
            result[aid] = secret
    return result


# ─── AccessToken 缓存 ────────────────────────────────────────────────


class _TokenState:
    __slots__ = ("token", "expires_at", "_lock")

    def __init__(self) -> None:
        self.token: str = ""
        self.expires_at: float = 0.0
        self._lock: Optional[asyncio.Lock] = None

    def _lock_or_create(self) -> asyncio.Lock:
        """Defer Lock() until an async caller has a running event loop (Py3.9 import-safe)."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock


_token_state = _TokenState()
_TOKEN_REFRESH_LEAD_SECONDS = 300


async def get_access_token(force_refresh: bool = False) -> str:
    """取或刷新 AccessToken。提前 5 分钟续期，单飞防雪崩。"""
    now = time.time()
    if (
        not force_refresh
        and _token_state.token
        and _token_state.expires_at - now > _TOKEN_REFRESH_LEAD_SECONDS
    ):
        return _token_state.token

    async with _token_state._lock_or_create():
        now = time.time()
        if (
            not force_refresh
            and _token_state.token
            and _token_state.expires_at - now > _TOKEN_REFRESH_LEAD_SECONDS
        ):
            return _token_state.token

        app_id = _qq_app_id()
        app_secret = _qq_app_secret()
        if not (app_id and app_secret):
            raise HTTPException(503, "BUTLER_QQ_APP_ID / BUTLER_QQ_APP_SECRET 未配置")

        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                _qq_token_endpoint(),
                json={"appId": app_id, "clientSecret": app_secret},
            )
            if r.status_code >= 400:
                raise HTTPException(
                    502, f"QQ getAppAccessToken 失败: {r.status_code} {r.text[:200]}"
                )
            data = r.json()

        token = str(data.get("access_token") or "").strip()
        if not token:
            raise HTTPException(502, f"QQ access_token 缺失：{data}")
        try:
            ttl = int(data.get("expires_in") or 7200)
        except Exception:
            ttl = 7200
        _token_state.token = token
        _token_state.expires_at = now + max(ttl, 60)
        return token


# ─── 出站消息客户端 ─────────────────────────────────────────────────


MsgKind = Literal["group", "c2c", "channel"]


class _SeqRegistry:
    """同一 ``msg_id`` 下 ``msg_seq`` 必须递增；进程内简单去重计数。"""

    def __init__(self) -> None:
        self._counts: Dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def next(self, msg_id: str) -> int:
        if not msg_id:
            return 1
        async with self._lock:
            n = self._counts.get(msg_id, 0) + 1
            if n > 5:
                n = 5  # QQ 同一 msg_id 上限较小，超出会被拒；保护性截断
            self._counts[msg_id] = n
            return n


_seq_registry = _SeqRegistry()


async def _send(
    kind: MsgKind,
    target_id: str,
    content: str,
    *,
    msg_id: str = "",
    msg_seq: Optional[int] = None,
) -> Dict[str, Any]:
    """统一出站发送。``content`` 已是要展示的文本。"""
    if not target_id:
        raise HTTPException(400, "缺少 target_id")
    token = await get_access_token()
    base = _qq_api_base()
    if kind == "group":
        url = f"{base}/v2/groups/{target_id}/messages"
        body: Dict[str, Any] = {"content": content, "msg_type": 0}
    elif kind == "c2c":
        url = f"{base}/v2/users/{target_id}/messages"
        body = {"content": content, "msg_type": 0}
    elif kind == "channel":
        url = f"{base}/channels/{target_id}/messages"
        body = {"content": content}
    else:
        raise HTTPException(400, f"未知消息类型 kind={kind}")
    if msg_id:
        body["msg_id"] = msg_id
        if kind in ("group", "c2c"):
            body["msg_seq"] = msg_seq if msg_seq else await _seq_registry.next(msg_id)

    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
        "X-Union-Appid": _qq_app_id(),
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, headers=headers, json=body)
        if r.status_code == 401:
            await get_access_token(force_refresh=True)
            token = _token_state.token
            headers["Authorization"] = f"QQBot {token}"
            r = await client.post(url, headers=headers, json=body)
        if r.status_code >= 400:
            logger.warning(
                "QQ 出站失败 kind=%s url=%s status=%s body=%s",
                kind,
                url,
                r.status_code,
                r.text[:300],
            )
            raise HTTPException(r.status_code, f"QQ 接口失败: {r.text[:300]}")
        try:
            return r.json()
        except Exception:
            return {"ok": True}


# ─── 多员工 Bot 上下文 ──────────────────────────────────────────────
#
# 每个挂到 DB 账号池的 QQ 机器人都有独立的 token 缓存和 seq 注册表，
# 发消息时用自己的 AppID / AppSecret，不会互相串号。


class _BotContext:
    """单个 QQ 机器人的运行时上下文（凭证 + token 缓存 + seq）。"""

    def __init__(
        self,
        employee_id: str,
        app_id: str,
        app_secret: str,
        sandbox: bool = False,
        bot_token: str = "",
    ) -> None:
        self.employee_id = employee_id
        self.app_id = app_id
        self.app_secret = app_secret
        self.sandbox = sandbox
        # QQ 控制台「机器人 Token」：若提供则直接作为 ``Authorization: QQBot …``
        # 的值出站（与若干官方示例一致）；留空则走 ``getAppAccessToken`` OAuth。
        self._bot_token_static = (bot_token or "").strip()
        self._token = ""
        self._token_expires: float = 0.0
        self._lock = asyncio.Lock()
        self._seq = _SeqRegistry()

    def api_base(self) -> str:
        return "https://sandbox.api.sgroup.qq.com" if self.sandbox else "https://api.sgroup.qq.com"

    async def access_token(self, force: bool = False) -> str:
        if self._bot_token_static:
            return self._bot_token_static
        now = time.time()
        if not force and self._token and self._token_expires - now > 300:
            return self._token
        async with self._lock:
            now = time.time()
            if not force and self._token and self._token_expires - now > 300:
                return self._token
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.post(
                    _qq_token_endpoint(),
                    json={"appId": self.app_id, "clientSecret": self.app_secret},
                )
                d = r.json()
            tok = str(d.get("access_token") or "").strip()
            if not tok:
                raise RuntimeError(f"QQ token 获取失败 app_id={self.app_id}: {d}")
            self._token = tok
            self._token_expires = now + max(int(d.get("expires_in") or 7200), 60)
            return self._token

    async def send(
        self,
        kind: MsgKind,
        target_id: str,
        content: str,
        *,
        msg_id: str = "",
        msg_seq: Optional[int] = None,
    ) -> Dict[str, Any]:
        token = await self.access_token()
        base = self.api_base()
        if kind == "group":
            url = f"{base}/v2/groups/{target_id}/messages"
            body: Dict[str, Any] = {"content": content, "msg_type": 0}
        elif kind == "c2c":
            url = f"{base}/v2/users/{target_id}/messages"
            body = {"content": content, "msg_type": 0}
        else:
            url = f"{base}/channels/{target_id}/messages"
            body = {"content": content}
        if msg_id:
            body["msg_id"] = msg_id
            if kind in ("group", "c2c"):
                body["msg_seq"] = msg_seq if msg_seq else await self._seq.next(msg_id)
        headers = {
            "Authorization": f"QQBot {token}",
            "Content-Type": "application/json",
            "X-Union-Appid": self.app_id,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, headers=headers, json=body)
            if r.status_code == 401:
                token = await self.access_token(force=True)
                headers["Authorization"] = f"QQBot {token}"
                r = await client.post(url, headers=headers, json=body)
            if r.status_code >= 400:
                logger.warning(
                    "QQ 出站失败 app_id=%s kind=%s status=%s body=%s",
                    self.app_id,
                    kind,
                    r.status_code,
                    r.text[:300],
                )
                raise HTTPException(r.status_code, f"QQ 接口失败: {r.text[:300]}")
            try:
                return r.json()
            except Exception:
                return {"ok": True}


# 进程内按 app_id 缓存 BotContext，启动时惰性填充
_bot_ctx_cache: Dict[str, "_BotContext"] = {}
_bot_ctx_lock = asyncio.Lock()


def invalidate_bot_ctx_cache() -> None:
    """admin 改完账号 / 轮换密钥后，让下一次 _get_bot_ctx 重新查 DB。"""
    _bot_ctx_cache.clear()


async def _get_bot_ctx(app_id: str) -> Optional["_BotContext"]:
    """按 app_id 从账号池找对应员工凭证，缓存 BotContext。

    匹配优先级：
    1) ``external_id == app_id``（DB 用 QQ AppID 当对外标识时最直接）
    2) 遍历所有 active 的 QQ 账号，比对密钥文件里的 ``secret.app_id``——
       支持运维把 ``external_id`` 写成 QQ 号、邮箱等"业务标识"的场景。
    """
    if app_id in _bot_ctx_cache:
        return _bot_ctx_cache[app_id]
    async with _bot_ctx_lock:
        if app_id in _bot_ctx_cache:
            return _bot_ctx_cache[app_id]
        try:
            from modstore_server.ai_employee_account_secrets import read_secret
            from modstore_server.models import get_session_factory
            from modstore_server.models_ai_accounts import AIEmployeeAccount

            sf = get_session_factory()
            row = None
            secret: Dict[str, Any] = {}
            with sf() as session:
                row = (
                    session.query(AIEmployeeAccount)
                    .filter(
                        AIEmployeeAccount.platform == "qq",
                        AIEmployeeAccount.external_id == app_id,
                        AIEmployeeAccount.status == "active",
                    )
                    .first()
                )
                if row:
                    secret = read_secret(platform="qq", account_id=int(row.id)) or {}

                if not row or not secret:
                    rows = (
                        session.query(AIEmployeeAccount)
                        .filter(
                            AIEmployeeAccount.platform == "qq",
                            AIEmployeeAccount.status == "active",
                        )
                        .all()
                    )
                    for r in rows:
                        sec = read_secret(platform="qq", account_id=int(r.id)) or {}
                        if str(sec.get("app_id") or "").strip() == app_id:
                            row = r
                            secret = sec
                            break

            if row and secret:
                ctx = _BotContext(
                    employee_id=row.employee_id,
                    app_id=str(secret.get("app_id") or app_id),
                    app_secret=str(secret.get("app_secret") or ""),
                    sandbox=bool(row.sandbox),
                    bot_token=str(secret.get("bot_token") or ""),
                )
                _bot_ctx_cache[app_id] = ctx
                return ctx
        except Exception as exc:
            logger.debug("_get_bot_ctx 失败 app_id=%s: %s", app_id, exc)

        for webhook_key, spec in _SPECIFIC_WEBHOOKS.items():
            if spec.get("app_id") == app_id:
                secret = _specific_app_secret(webhook_key)
                eid = spec.get("employee_id", "")
                if secret and eid:
                    ctx = _BotContext(
                        employee_id=eid,
                        app_id=app_id,
                        app_secret=secret,
                        sandbox=False,
                        bot_token=_specific_bot_token(webhook_key),
                    )
                    _bot_ctx_cache[app_id] = ctx
                    return ctx
        return None


def _specific_ctx_for_employee(employee_id: str) -> Optional["_BotContext"]:
    """从 ``_SPECIFIC_WEBHOOKS`` 静态表里查一份兜底 ctx；DB 都没建好时也能跑。"""
    eid = (employee_id or "").strip()
    if not eid:
        return None
    for webhook_key, spec in _SPECIFIC_WEBHOOKS.items():
        if spec.get("employee_id") == eid:
            secret = _specific_app_secret(webhook_key)
            app_id = spec.get("app_id", "")
            if app_id and secret:
                return _BotContext(
                    employee_id=eid,
                    app_id=app_id,
                    app_secret=secret,
                    sandbox=False,
                    bot_token=_specific_bot_token(webhook_key),
                )
    return None


async def _get_bot_ctx_by_employee(employee_id: str) -> Optional["_BotContext"]:
    """按 employee_id 找对应 QQ 机器人 ctx——给"按员工"的通用 webhook 使用。

    DB 上同一员工可能挂多个 QQ 账号，取最新一条 active；查不到再尝试
    ``_SPECIFIC_WEBHOOKS`` 静态兜底（覆盖 ``task-router-officer`` /
    ``employee-interview-assistant`` 这两位老员工）；都没有返回 None。
    """
    eid = (employee_id or "").strip()
    if not eid:
        return None
    try:
        from modstore_server.ai_employee_account_api import lookup_active_account_for

        rec = lookup_active_account_for(eid, "qq")
        if rec:
            secret = rec.get("secret") or {}
            app_id = str(secret.get("app_id") or rec.get("external_id") or "").strip()
            app_secret = str(secret.get("app_secret") or "").strip()
            if app_id and app_secret:
                if app_id in _bot_ctx_cache:
                    return _bot_ctx_cache[app_id]
                ctx = _BotContext(
                    employee_id=eid,
                    app_id=app_id,
                    app_secret=app_secret,
                    sandbox=bool(rec.get("sandbox")),
                    bot_token=str(secret.get("bot_token") or ""),
                )
                _bot_ctx_cache[app_id] = ctx
                return ctx
    except Exception as exc:
        logger.debug("_get_bot_ctx_by_employee 失败 employee_id=%s: %s", employee_id, exc)

    static_ctx = _specific_ctx_for_employee(eid)
    if static_ctx is not None:
        if static_ctx.app_id not in _bot_ctx_cache:
            _bot_ctx_cache[static_ctx.app_id] = static_ctx
        return static_ctx
    return None


# ─── 入站 → 多员工分发 ───────────────────────────────────────────────


_KIND_BY_EVENT: Dict[str, MsgKind] = {
    "GROUP_AT_MESSAGE_CREATE": "group",
    "C2C_MESSAGE_CREATE": "c2c",
    "AT_MESSAGE_CREATE": "channel",
    "DIRECT_MESSAGE_CREATE": "channel",
}


def _strip_at(text: str) -> str:
    """去掉 ``<@!12345>`` / ``@机器人`` 这种前导 mention。"""
    s = (text or "").strip()
    while s.startswith("<@") and ">" in s:
        s = s.split(">", 1)[1].lstrip()
    return s


def _extract_target_id(kind: MsgKind, payload: Dict[str, Any]) -> str:
    """根据事件类型从 payload 取回复目标。"""
    if kind == "group":
        return str(payload.get("group_openid") or "")
    if kind == "c2c":
        author = payload.get("author") or {}
        return str(author.get("user_openid") or author.get("id") or "")
    return str(payload.get("channel_id") or "")


async def dispatch_to_butler(event_type: str, payload: Dict[str, Any]) -> None:
    """兼容旧调用入口（数字管家默认上下文）。"""
    await dispatch_to_employee(event_type, payload, app_id=_qq_app_id())


async def dispatch_to_employee(
    event_type: str,
    payload: Dict[str, Any],
    *,
    app_id: str,
    employee_id_hint: str = "",
) -> None:
    """把一条 QQ 消息路由到对应 AI 员工，跑完整执行器并把回复送回 QQ。

    路由顺序：

    1) ``employee_id_hint`` 非空（按 employee_id 的通用 webhook 进来时）→ 直接定位；
    2) 否则按 ``app_id`` 在账号池里找；
    3) 都失败再降级到管家。

    回复来源（按可用性回退）：

    - 数字管家：仍走 ``_employee_chat``（轻量 LLM persona）保持原行为；
    - 其它员工：先跑 ``execute_employee_task`` 全链路（perception/cognition/actions），
      抽 ``reasoning_excerpt`` 或 ``echo`` 输出当作 QQ 回复；执行器异常或抽不出文本，
      再回退到 ``_employee_chat`` 保命，避免静默吞消息。
    """
    kind = _KIND_BY_EVENT.get(event_type)
    if not kind:
        logger.info("跳过未支持的 QQ 事件类型: %s", event_type)
        return
    text = _strip_at(str(payload.get("content") or ""))
    if not text:
        return
    target_id = _extract_target_id(kind, payload)
    if not target_id:
        logger.warning("QQ 事件缺少目标 id: %s payload=%s", event_type, payload)
        return
    msg_id = str(payload.get("id") or "")

    ctx: Optional[_BotContext] = None
    if employee_id_hint:
        ctx = await _get_bot_ctx_by_employee(employee_id_hint)
    if ctx is None and app_id:
        ctx = await _get_bot_ctx(app_id)
    if ctx is None:
        logger.warning(
            "找不到 employee/app_id=%s/%s 对应员工，降级到数字管家",
            employee_id_hint or "-",
            app_id or "-",
        )
        ctx = _BotContext(
            employee_id=_BUTLER_EMPLOYEE_ID,
            app_id=_qq_app_id(),
            app_secret=_qq_app_secret(),
            sandbox=_qq_sandbox(),
            bot_token=_qq_bot_token(),
        )

    reply = await _resolve_reply(ctx.employee_id, text)

    if not reply:
        reply = "（AI 员工未生成回复）"
    try:
        await ctx.send(kind, target_id, reply, msg_id=msg_id)
    except Exception:
        logger.exception(
            "QQ 出站失败 kind=%s target=%s employee=%s", kind, target_id, ctx.employee_id
        )


async def _resolve_reply(employee_id: str, user_text: str) -> str:
    """统一选择"用执行器"还是"用 persona LLM"产生回复文本。"""
    if employee_id == _BUTLER_EMPLOYEE_ID:
        try:
            return await _employee_chat(user_text, employee_id=employee_id)
        except Exception as exc:
            logger.exception("管家 chat 失败")
            return f"数字管家暂时不可用：{exc}"

    try:
        reply = await _execute_employee_for_qq(employee_id, user_text)
        if reply:
            return reply
        logger.info("执行器无文本输出 employee=%s，回退到 persona chat", employee_id)
    except Exception as exc:
        logger.exception("执行器失败 employee=%s，回退到 persona chat: %s", employee_id, exc)

    try:
        return await _employee_chat(user_text, employee_id=employee_id)
    except Exception as exc:
        logger.exception("persona chat 也失败 employee=%s", employee_id)
        return f"AI 员工暂时不可用：{exc}"


_QQ_REPLY_MAX_LEN = 800


async def _execute_employee_for_qq(employee_id: str, user_text: str) -> str:
    """把一条 QQ 用户文本喂给完整 employee 执行器，并抽出可发送的回复。

    QQ 群消息上限较小，这里截断到 ``_QQ_REPLY_MAX_LEN``。执行器自身处理
    risk gate / 计费 / metrics，与 web/工作台一致——QQ 只是一个新的输入渠道。
    """
    from modstore_server.services.employee import get_default_employee_client

    client = get_default_employee_client()

    bridge_uid = _bridge_user_id()

    def _run() -> Dict[str, Any]:
        return client.execute_task(
            employee_id=employee_id,
            task=user_text,
            input_data={"text": user_text, "channel": "qq"},
            user_id=int(bridge_uid),
        )

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, _run)
    if not isinstance(raw, dict):
        return ""

    text = ""
    result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
    outputs = result.get("outputs") if isinstance(result.get("outputs"), list) else []
    for out in outputs:
        if not isinstance(out, dict):
            continue
        if out.get("handler") in ("echo", "llm_md"):
            cand = str(out.get("output") or "").strip()
            if cand:
                text = cand
                break
    if not text:
        excerpt = str(raw.get("reasoning_excerpt") or "").strip()
        if excerpt:
            text = excerpt
    if not text:
        cog_help = str(raw.get("cognition_help") or "").strip()
        if cog_help:
            text = cog_help
    if not text:
        summary = str(result.get("summary") or "").strip()
        if summary and summary != f"executed {len(outputs)} handlers":
            text = summary

    if len(text) > _QQ_REPLY_MAX_LEN:
        text = text[: _QQ_REPLY_MAX_LEN - 1] + "…"
    return text


_EMPLOYEE_PERSONAS: Dict[str, str] = {
    "xc-digital-butler": "你是 XC AGI 数字管家，平台全站智能助手，擅长页面导航、解答平台问题、协调 AI 员工。",
    "task-router-officer": "你是任务路由员，专门接收用户/管理员的任务请求，分析意图后路由给最合适的 AI 员工处理，简洁高效。",
    "employee-interview-assistant": "你是员工访谈员，负责收集 AI 员工的工作进度、问题反馈和日报，整理后汇报给管理员。",
}

_EMPLOYEE_FALLBACK_PERSONA = "你是 XC AGI 平台 AI 员工，请专业、简洁地回答用户问题。"


async def _employee_chat(user_text: str, *, employee_id: str) -> str:
    """为指定员工跑一次 LLM 对话，返回文本。优先用管家自己的 LLM 凭证（共享）。"""
    from modstore_server.agent_butler_api import BUTLER_SYSTEM_PROMPT
    from modstore_server.llm_chat_proxy import chat_dispatch

    provider, model, api_key, base_url = await _resolve_llm_for_butler()
    persona = _EMPLOYEE_PERSONAS.get(employee_id, _EMPLOYEE_FALLBACK_PERSONA)
    msgs: List[Dict[str, Any]] = [
        {"role": "system", "content": persona},
        {
            "role": "system",
            "content": "本次对话来自 QQ 官方机器人入口。回答简洁，不超过 200 字，不要要求用户操作 web UI。",
        },
        {"role": "user", "content": user_text},
    ]
    result = await chat_dispatch(
        provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=msgs,
        max_tokens=600,
    )
    return str(result.get("content") or "").strip()


async def _resolve_llm_for_butler() -> Tuple[str, str, str, Optional[str]]:
    """解析数字管家自己用的 LLM 凭证。优先用员工自带的（``BUTLER_QQ_LLM_*``），
    其次才退回 ``BUTLER_QQ_BRIDGE_USER_ID`` 名下挂的真人钥匙。

    返回 ``(provider, model, api_key, base_url)``。
    """
    provider, model, api_key, base_url = _own_llm()
    if provider and api_key:
        return provider, (model or "gpt-4o-mini"), api_key, base_url

    bridge_uid = _bridge_user_id()
    if not bridge_uid:
        raise RuntimeError(
            "数字管家没有 LLM 钥匙：请配 BUTLER_QQ_LLM_PROVIDER + BUTLER_QQ_LLM_API_KEY"
            "（推荐，AI 员工自持），或退而求其次给 BUTLER_QQ_BRIDGE_USER_ID 指向一个有 API Key 的真人。"
        )

    from modstore_server.infrastructure.db import get_db
    from modstore_server.llm_key_resolver import (
        KNOWN_PROVIDERS,
        OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        resolve_api_key,
        resolve_base_url,
    )
    from modstore_server.models import User

    db_gen = get_db()
    db = next(db_gen)
    try:
        user = db.query(User).filter(User.id == bridge_uid).first()
        if not user:
            raise RuntimeError(f"BUTLER_QQ_BRIDGE_USER_ID={bridge_uid} 在 users 表中找不到")
        prefs: Dict[str, Any] = {}
        raw = getattr(user, "default_llm_json", None) or ""
        if raw.strip():
            try:
                prefs = json.loads(raw)
            except Exception:
                prefs = {}
        provider = str(prefs.get("provider") or "").strip()
        model = str(prefs.get("model") or "").strip()
        if not provider or provider not in KNOWN_PROVIDERS:
            for p in KNOWN_PROVIDERS:
                key, _src = resolve_api_key(db, bridge_uid, p)
                if key:
                    provider = p
                    break
        if not provider:
            raise RuntimeError("数字管家：bridge user 名下未配任何 LLM 供应商")
        if not model:
            model = "gpt-4o-mini"
        api_key, _src = resolve_api_key(db, bridge_uid, provider)
        if not api_key:
            raise RuntimeError(f"数字管家：bridge user 在 {provider} 下没有 API Key")
        base_url = (
            resolve_base_url(db, bridge_uid, provider)
            if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
            else None
        )
        return provider, model, api_key, base_url
    finally:
        try:
            next(db_gen, None)
        except Exception:
            pass


async def _butler_chat(user_text: str) -> str:
    """复用 ``agent_butler_api`` 的 system prompt，跑一次 LLM 拿一段文本回复。"""
    from modstore_server.agent_butler_api import BUTLER_SYSTEM_PROMPT
    from modstore_server.llm_chat_proxy import chat_dispatch

    provider, model, api_key, base_url = await _resolve_llm_for_butler()

    msgs: List[Dict[str, Any]] = [
        {"role": "system", "content": BUTLER_SYSTEM_PROMPT},
        {
            "role": "system",
            "content": "本次对话来自 QQ 官方机器人入口，不是网页。回答尽量简短，不要要求用户操作 web UI。",
        },
        {"role": "user", "content": user_text},
    ]
    result = await chat_dispatch(
        provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=msgs,
        max_tokens=800,
    )
    return str(result.get("content") or "").strip()


# ─── FastAPI 路由 ───────────────────────────────────────────────────


router = APIRouter(prefix="/api/agent/butler/qq", tags=["butler-qq"])


class _PushDTO(BaseModel):
    kind: MsgKind
    target_id: str
    content: str = Field(..., min_length=1, max_length=2000)
    msg_id: str = ""
    msg_seq: Optional[int] = None


def _check_admin(request: Request) -> None:
    expected = _env("MODSTORE_ADMIN_RECHARGE_TOKEN")
    if not expected:
        raise HTTPException(503, "MODSTORE_ADMIN_RECHARGE_TOKEN 未配置，拒绝主动推送")
    got = (request.headers.get("X-Modstore-Recharge-Token") or "").strip()
    if got != expected:
        raise HTTPException(403, "管理员令牌不匹配")


@router.get("/status")
async def qq_status() -> Dict[str, Any]:
    own_provider, own_model, own_key, _own_base = _own_llm()
    has_own_brain = bool(own_provider and own_key)
    creds = _resolve_creds()
    employees: List[Dict[str, Any]] = []
    for webhook_key, spec in _SPECIFIC_WEBHOOKS.items():
        eid = spec.get("employee_id", "")
        aid = spec.get("app_id", "")
        secret_present = bool(_specific_app_secret(webhook_key))
        bot_tok_present = bool(_specific_bot_token(webhook_key))
        employees.append(
            {
                "employee_id": eid,
                "app_id": aid,
                "webhook_key": webhook_key,
                "webhook_path": f"/api/agent/butler/qq/{webhook_key}/webhook",
                "by_employee_path": f"/api/agent/butler/qq/by-employee/{eid}/webhook",
                "app_secret_env": spec.get("app_secret_env", ""),
                "bot_token_env": spec.get("bot_token_env", ""),
                "app_secret_present": secret_present,
                "bot_token_present": bot_tok_present,
                "uses_executor": True,
            }
        )
    return {
        "configured": is_configured(),
        "credential_source": _qq_credential_source(),
        "account_id": creds.get("account_id"),
        "sandbox": _qq_sandbox(),
        "api_base": _qq_api_base(),
        "app_id": _qq_app_id() or None,
        # 数字管家是否拥有自己的 LLM 钥匙（推荐：AI 员工自持）
        "has_own_brain": has_own_brain,
        "own_brain_provider": own_provider or None,
        "own_brain_model": own_model or None,
        # 兜底：是否挂在某个真人名下借钥匙用
        "bridge_user_id": _bridge_user_id() or None,
        "has_cached_token": bool(_token_state.token),
        "token_expires_in": (
            max(int(_token_state.expires_at - time.time()), 0) if _token_state.token else 0
        ),
        # 一等公民 QQ 渠道：两位老员工 + 任意 admin 新挂的员工
        "first_class_employees": employees,
        "butler_employee_id": _BUTLER_EMPLOYEE_ID,
    }


@router.get("/webhook")
async def qq_webhook_probe() -> JSONResponse:
    """QQ platform GET probe for callback URL; real events use POST."""
    return JSONResponse({"ok": True})


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


def _specific_app_secret(webhook_key: str) -> str:
    """两位老员工的 AppSecret 解析：先读 ENV，再回退到密钥文件。"""
    spec = _SPECIFIC_WEBHOOKS.get(webhook_key)
    if not spec:
        return ""
    env_name = spec.get("app_secret_env") or ""
    if env_name:
        v = _env(env_name)
        if v:
            return v
    employee_id = spec.get("employee_id", "")
    if not employee_id:
        return ""
    try:
        from modstore_server.ai_employee_account_api import lookup_active_account_for

        rec = lookup_active_account_for(employee_id, "qq")
        if rec:
            secret = rec.get("secret") or {}
            v = str(secret.get("app_secret") or "").strip()
            if v:
                return v
    except Exception as exc:
        logger.debug("_specific_app_secret 查账号池失败 key=%s: %s", webhook_key, exc)
    return ""


def _specific_bot_token(webhook_key: str) -> str:
    """两位老员工的机器人 Token：先读 ENV，再回退密钥文件 ``secret.bot_token``。"""
    spec = _SPECIFIC_WEBHOOKS.get(webhook_key)
    if not spec:
        return ""
    env_name = spec.get("bot_token_env") or ""
    if env_name:
        v = _env(env_name)
        if v:
            return v
    employee_id = spec.get("employee_id", "")
    if not employee_id:
        return ""
    try:
        from modstore_server.ai_employee_account_api import lookup_active_account_for

        rec = lookup_active_account_for(employee_id, "qq")
        if rec:
            secret = rec.get("secret") or {}
            v = str(secret.get("bot_token") or "").strip()
            if v:
                return v
    except Exception as exc:
        logger.debug("_specific_bot_token 查账号池失败 key=%s: %s", webhook_key, exc)
    return ""


def _resolve_webhook_app_id(webhook_key: str) -> Tuple[str, str]:
    """``/api/agent/butler/qq/{webhook_key}/webhook`` → ``(app_id, employee_id)``。

    解析顺序：

    1) ``_SPECIFIC_WEBHOOKS`` 静态表：``task-router`` / ``employee-interview``
       这两位老员工的 webhook URL 已经在 QQ 后台登记，必须保持稳定；
       命中即直接返回 (app_id, employee_id)，让分发器走它们各自的执行器。
    2) 把 ``webhook_key`` 当作 ``employee_id`` 在账号池里查活跃 QQ 账号——
       这样任意新员工只要绑了 QQ 账号，都能用 ``/<employee_id>/webhook`` 收到事件。

    找不到则两个返回值都是空串，由调用方决定走 404 还是兜底。
    """
    spec = _SPECIFIC_WEBHOOKS.get(webhook_key)
    if spec:
        return spec.get("app_id", ""), spec.get("employee_id", "")
    try:
        from modstore_server.ai_employee_account_api import lookup_active_account_for

        rec = lookup_active_account_for(webhook_key, "qq")
    except Exception as exc:
        logger.debug("_resolve_webhook_app_id 查 employee 失败 key=%s: %s", webhook_key, exc)
        rec = None
    if not rec:
        return "", ""
    secret = rec.get("secret") or {}
    app_id = str(secret.get("app_id") or rec.get("external_id") or "").strip()
    return app_id, webhook_key


@router.get("/{webhook_key}/webhook")
async def qq_specific_webhook_probe(webhook_key: str) -> JSONResponse:
    """Per-employee QQ callback probe.

    QQ's validation request is tied to one BotSecret. Dedicated URLs let us know
    which AppSecret to use even if QQ does not send X-Union-Appid during op=13.
    """
    app_id, employee_id = _resolve_webhook_app_id(webhook_key)
    if not app_id:
        raise HTTPException(404, "unknown webhook")
    return JSONResponse({"ok": True, "app_id": app_id, "employee_id": employee_id or None})


@router.post("/{webhook_key}/webhook")
async def qq_specific_webhook(webhook_key: str, request: Request) -> JSONResponse:
    app_id, employee_id = _resolve_webhook_app_id(webhook_key)
    if not app_id:
        raise HTTPException(404, "unknown webhook")
    return await _qq_webhook_impl(
        request,
        forced_app_id=app_id,
        forced_employee_id=employee_id,
    )


@router.get("/by-employee/{employee_id}/webhook")
async def qq_employee_webhook_probe(employee_id: str) -> JSONResponse:
    """通用版"按员工"探活：admin 给员工绑了 QQ 账号即可立刻有 URL。"""
    rec = None
    try:
        from modstore_server.ai_employee_account_api import lookup_active_account_for

        rec = lookup_active_account_for(employee_id, "qq")
    except Exception:
        rec = None
    if not rec:
        raise HTTPException(404, "employee 未绑定 QQ 账号")
    secret = rec.get("secret") or {}
    app_id = str(secret.get("app_id") or rec.get("external_id") or "")
    return JSONResponse({"ok": True, "employee_id": employee_id, "app_id": app_id})


@router.post("/by-employee/{employee_id}/webhook")
async def qq_employee_webhook(employee_id: str, request: Request) -> JSONResponse:
    """通用入站渠道：``/api/agent/butler/qq/by-employee/{employee_id}/webhook``。

    无需改代码、无需 ENV，只要 admin 在账号池里把 QQ 账号挂到这个员工名下，
    URL 就会自动生效。是 ``/{webhook_key}/webhook`` 的命名空间安全版本，
    避免和静态 ``task-router`` / ``employee-interview`` 撞车。
    """
    try:
        from modstore_server.ai_employee_account_api import lookup_active_account_for

        rec = lookup_active_account_for(employee_id, "qq")
    except Exception as exc:
        logger.warning("by-employee webhook 查账号失败 employee=%s: %s", employee_id, exc)
        rec = None
    if not rec:
        raise HTTPException(404, "employee 未绑定 QQ 账号")
    secret = rec.get("secret") or {}
    app_id = str(secret.get("app_id") or rec.get("external_id") or "").strip()
    if not app_id:
        raise HTTPException(500, "账号缺 app_id 字段，密钥文件未正确写入")
    return await _qq_webhook_impl(
        request,
        forced_app_id=app_id,
        forced_employee_id=employee_id,
    )


@router.post("/webhook")
async def qq_webhook(request: Request) -> JSONResponse:
    return await _qq_webhook_impl(request, forced_app_id=None, forced_employee_id="")


async def _qq_webhook_impl(
    request: Request,
    *,
    forced_app_id: Optional[str],
    forced_employee_id: str = "",
) -> JSONResponse:
    body_bytes = await request.body()
    timestamp = request.headers.get("X-Signature-Timestamp") or ""
    sig = request.headers.get("X-Signature-Ed25519") or ""

    try:
        envelope = json.loads(body_bytes or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "无效 JSON")

    op = envelope.get("op")

    # op=13 回调地址校验：QQ 不带 X-Signature-* 头，载荷里有 plain_token / event_ts。
    # 需要用 QQ 后台配的那个机器人的 AppSecret 签名，用请求头里的 X-Union-Appid 区分。
    #
    # ★ 关键约束：op=13 必须用"正确那个机器人"的 AppSecret 签名，QQ 用我们返回
    #   的 hex 签名比对 plain_token 才放过。如果错用了管家的密钥去给其它机器人
    #   签名，QQ 后台会把 webhook 标成"验签失败/未连接"——这是历史上为什么
    #   "三个机器人都填同一个 URL，只有管家通过"的根本原因。
    if op == 13:
        d = envelope.get("d") or {}
        plain_token = str(d.get("plain_token") or "")
        event_ts = str(d.get("event_ts") or "")
        if not (plain_token and event_ts):
            raise HTTPException(400, "op=13 缺少 plain_token / event_ts")

        secrets_map = _all_known_app_secrets()
        inbound_app_id_13 = (forced_app_id or request.headers.get("X-Union-Appid") or "").strip()

        # 如果是按 employee_id 进来的（``/by-employee/{eid}/webhook`` 或老员工
        # ``/task-router/webhook``），forced_app_id 已经定死；优先用它对应的
        # secret，避免被默认管家密钥误签。
        if forced_app_id and forced_app_id in secrets_map:
            use_secret = secrets_map[forced_app_id]
            chosen_for = f"forced app_id={forced_app_id}"
        elif inbound_app_id_13 and inbound_app_id_13 in secrets_map:
            use_secret = secrets_map[inbound_app_id_13]
            chosen_for = f"X-Union-Appid={inbound_app_id_13}"
        elif inbound_app_id_13:
            # X-Union-Appid 给了但我们不认识——这才是用户最常踩的坑：
            # 在 QQ 后台把这个机器人的回调挂到了管家 URL，但服务端没有它的
            # AppSecret，落回管家密钥签名 100% 验签失败。直接 503 + 明确告诉
            # admin 该如何修，不要静默回退假装握手成功。
            logger.error(
                "op=13 收到未知 X-Union-Appid=%s；当前已注册 app_id=%s。"
                "请在 /admin/ai-accounts 给该机器人补一个 AI 员工账号"
                "（platform=qq + 正确的 app_secret），或给两位老员工设置 "
                "TASK_ROUTER_QQ_APP_SECRET / EMPLOYEE_INTERVIEW_QQ_APP_SECRET。",
                inbound_app_id_13,
                sorted(secrets_map.keys()),
            )
            raise HTTPException(
                503,
                f"AppID {inbound_app_id_13} 未在本服务注册凭证；"
                f"请到管理后台 AI 员工账号池补建账号或配 ENV，再让 QQ 重新校验",
            )
        else:
            # X-Union-Appid 缺失（极少数代理可能剥头）→ 退到默认管家凭证，
            # 同时打 warning，让 admin 在日志里能看到。
            logger.warning(
                "op=13 缺少 X-Union-Appid 头，落回默认管家 AppSecret 签名；"
                "若该机器人不是管家会握手失败"
            )
            use_secret = _qq_app_secret()
            chosen_for = "fallback=butler (no X-Union-Appid)"

        try:
            sig_bytes = _sign_payload_for((event_ts + plain_token).encode("utf-8"), use_secret)
        except Exception as exc:
            logger.exception("op=13 签名失败 app_id=%s", inbound_app_id_13)
            raise HTTPException(500, f"签名失败: {exc}")
        logger.info(
            "op=13 握手成功 app_id=%s chosen_secret=%s",
            inbound_app_id_13 or "unknown",
            chosen_for,
        )
        return JSONResponse({"plain_token": plain_token, "signature": sig_bytes.hex()})

    # 业务事件：尝试所有已知 AppSecret 验签（任一通过即可）。
    secrets_map = _all_known_app_secrets()
    verified = (
        any(_verify_inbound_for(timestamp, body_bytes, sig, s) for s in secrets_map.values())
        if secrets_map
        else verify_inbound(timestamp, body_bytes, sig)
    )
    if not verified:
        logger.warning("QQ webhook 签名校验失败 ts=%s sig=%s", timestamp, sig[:16])
        raise HTTPException(401, "签名校验失败")

    if op == 0:
        event_type = str(envelope.get("t") or "")
        payload = envelope.get("d") or {}
        inbound_app_id = (
            forced_app_id
            or request.headers.get("X-Union-Appid")
            or str((payload.get("bot") or {}).get("id") or "")
            or _qq_app_id()
        ).strip()
        asyncio.create_task(
            dispatch_to_employee(
                event_type,
                payload,
                app_id=inbound_app_id,
                employee_id_hint=forced_employee_id or "",
            )
        )
    return JSONResponse({})


@router.post("/push")
async def qq_push(body: _PushDTO, request: Request) -> Dict[str, Any]:
    _check_admin(request)
    return await _send(
        body.kind,
        body.target_id,
        body.content,
        msg_id=body.msg_id,
        msg_seq=body.msg_seq,
    )


@router.post("/cache/reload")
async def qq_reload_cache(request: Request) -> Dict[str, Any]:
    """让凭证 / BotContext 缓存立刻失效；admin CRUD 之后会自动调，
    这里也提供手动触发（运维侧排障用）。"""
    _check_admin(request)
    invalidate_creds_cache()
    invalidate_bot_ctx_cache()
    return {"ok": True}


# ─── 启动期自检：缺 pynacl 就清掉 router；凭证可后续从账号池补 ────────
#
# 注意：本模块在 app_factory 注册时 **总是** 暴露 ``/api/agent/butler/qq/*``
# 路由（除非 pynacl 都没装）。凭证未配齐不会让模块自我屏蔽——这样
# admin 在通过 ``/api/admin/ai-accounts`` 给数字管家挂上 QQ 账号后，无需
# 重启进程，``invalidate_creds_cache()`` 一调用，新凭证 30 秒内就会生效。


def _ensure_runtime_ready() -> bool:
    try:
        import nacl  # noqa: F401
    except Exception:
        logger.warning("未安装 pynacl，butler_qq_bridge 不挂载（pip install pynacl 后可启用）")
        return False
    if not is_configured():
        logger.info(
            "butler_qq_bridge：当前没有 QQ 凭证（账号池 + ENV 都空）；"
            "router 保留，发起请求时再次校验"
        )
    return True


if not _ensure_runtime_ready():
    # 缺 pynacl 时让 app_factory 的 include_router 仍能跑，但路由表保持空。
    router = APIRouter(prefix="/api/agent/butler/qq", tags=["butler-qq"])
