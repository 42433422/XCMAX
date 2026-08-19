# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.butler_qq_bridge")


async def _send(
    kind: _facade().MsgKind,
    target_id: str,
    content: str,
    *,
    msg_id: str = "",
    msg_seq: _facade().Optional[int] = None,
) -> _facade().Dict[str, _facade().Any]:
    """统一出站发送。``content`` 已是要展示的文本。"""
    if not target_id:
        raise _facade().HTTPException(400, "缺少 target_id")
    token = await _facade().get_access_token()
    base = _facade()._qq_api_base()
    if kind == "group":
        url = f"{base}/v2/groups/{target_id}/messages"
        body: _facade().Dict[str, _facade().Any] = {"content": content, "msg_type": 0}
    elif kind == "c2c":
        url = f"{base}/v2/users/{target_id}/messages"
        body = {"content": content, "msg_type": 0}
    elif kind == "channel":
        url = f"{base}/channels/{target_id}/messages"
        body = {"content": content}
    else:
        raise _facade().HTTPException(400, f"未知消息类型 kind={kind}")
    if msg_id:
        body["msg_id"] = msg_id
        if kind in ("group", "c2c"):
            body["msg_seq"] = msg_seq if msg_seq else await _facade()._seq_registry.next(msg_id)
    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
        "X-Union-Appid": _facade()._qq_app_id(),
    }
    async with _facade().httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, headers=headers, json=body)
        if r.status_code == 401:
            await _facade().get_access_token(force_refresh=True)
            token = _facade()._token_state.token
            headers["Authorization"] = f"QQBot {token}"
            r = await client.post(url, headers=headers, json=body)
        if r.status_code >= 400:
            _facade().logger.warning(
                "QQ 出站失败 kind=%s url=%s status=%s body=%s",
                kind,
                url,
                r.status_code,
                r.text[:300],
            )
            raise _facade().HTTPException(r.status_code, f"QQ 接口失败: {r.text[:300]}")
        try:
            return r.json()
        except Exception:
            return {"ok": True}


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
        self._bot_token_static = (bot_token or "").strip()
        self._token = ""
        self._token_expires: float = 0.0
        self._lock = _facade().asyncio.Lock()
        self._seq = _facade()._SeqRegistry()

    def api_base(self) -> str:
        return "https://sandbox.api.sgroup.qq.com" if self.sandbox else "https://api.sgroup.qq.com"

    async def access_token(self, force: bool = False) -> str:
        if self._bot_token_static:
            return self._bot_token_static
        now = _facade().time.time()
        if not force and self._token and (self._token_expires - now > 300):
            return self._token
        async with self._lock:
            now = _facade().time.time()
            if not force and self._token and (self._token_expires - now > 300):
                return self._token
            async with _facade().httpx.AsyncClient(timeout=15.0) as c:
                r = await c.post(
                    _facade()._qq_token_endpoint(),
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
        kind: _facade().MsgKind,
        target_id: str,
        content: str,
        *,
        msg_id: str = "",
        msg_seq: _facade().Optional[int] = None,
    ) -> _facade().Dict[str, _facade().Any]:
        token = await self.access_token()
        base = self.api_base()
        if kind == "group":
            url = f"{base}/v2/groups/{target_id}/messages"
            body: _facade().Dict[str, _facade().Any] = {"content": content, "msg_type": 0}
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
        async with _facade().httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, headers=headers, json=body)
            if r.status_code == 401:
                token = await self.access_token(force=True)
                headers["Authorization"] = f"QQBot {token}"
                r = await client.post(url, headers=headers, json=body)
            if r.status_code >= 400:
                _facade().logger.warning(
                    "QQ 出站失败 app_id=%s kind=%s status=%s body=%s",
                    self.app_id,
                    kind,
                    r.status_code,
                    r.text[:300],
                )
                raise _facade().HTTPException(r.status_code, f"QQ 接口失败: {r.text[:300]}")
            try:
                return r.json()
            except Exception:
                return {"ok": True}
