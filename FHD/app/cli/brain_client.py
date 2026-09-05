"""One-attempt HTTP transport. All authorization remains on the HTTP server."""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote

from .brain_session import BrainError, SessionStore


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BrainError("服务端返回重定向；未转发账号凭据，请检查 --origin")


def _business_error(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    error = result.get("error")
    if (
        result.get("success") is False
        or result.get("valid") is False
        or result.get("degraded")
        or error
    ):
        if isinstance(error, dict):
            return str(error.get("message") or error.get("detail") or error.get("code") or error)
        return str(result.get("message") or error or "服务暂时不可用")
    for key in ("data", "result", "response"):
        message = _business_error(result.get(key))
        if message:
            return message
    return None


def _invalid_session(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("valid") is False or result.get("code") in {
        "UNAUTHORIZED",
        "NO_SESSION",
        "INVALID_SESSION",
        "ACCOUNT_DISABLED",
    }:
        return True
    return any(_invalid_session(result.get(key)) for key in ("error", "data", "result", "response"))


class BrainClient:
    def __init__(self, store: SessionStore, timeout: float = 30):
        self.store = store
        self.timeout = timeout
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(store.cookies),
            _NoRedirect(),
        )

    def request(
        self, method: str, path: str, body: dict | None = None, *, p2_token: str = ""
    ) -> dict:
        if not path.startswith("/api/") or "?" in path or "#" in path:
            raise BrainError("无效 API 路径")
        headers = {"Accept": "application/json", "User-Agent": "xcagi-brain/1"}
        if method != "GET":
            if not self.store.csrf_token():
                self.request("GET", "/api/health")
            token = self.store.csrf_token()
            if not token:
                raise BrainError("服务端未提供 CSRF cookie，写操作未发送")
            headers["X-CSRF-Token"] = token
            headers["Content-Type"] = "application/json"
        if p2_token:
            headers["X-XCAGI-AI-Tier"] = "p2"
            headers["X-XCAGI-Elevated-Token"] = p2_token
        request = urllib.request.Request(
            self.store.origin + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            hints = {
                401: "登录已失效，请重新 login",
                403: "权限或 CSRF/P2 校验未通过",
                404: "接口、文件或提案不存在",
                409: "状态冲突；重新读取文件并创建提案，勿重试旧 apply",
            }
            invalid_session = exc.code == 401
            try:
                payload = json.loads(exc.read())
                detail = _business_error(payload) or payload.get("detail") or ""
                invalid_session = invalid_session or _invalid_session(payload)
            except (ValueError, UnicodeError, AttributeError):
                detail = ""
            if p2_token:
                detail = str(detail).replace(p2_token, "[redacted]")
            if body and body.get("password"):
                detail = str(detail).replace(str(body["password"]), "[redacted]")
            if invalid_session:
                self.store.clear()
            raise BrainError(
                f"HTTP {exc.code}: {hints.get(exc.code, '服务请求失败')} {detail}".strip(),
                kind="auth" if invalid_session else "http",
                status=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            suffix = "；写入结果可能未知，请核查后再操作，未自动重试" if method != "GET" else ""
            raise BrainError(f"连接失败或超时{suffix}", kind="transport") from exc
        finally:
            self.store.save()
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            suffix = "；写入结果可能未知，未自动重试" if method != "GET" else ""
            raise BrainError(f"服务端未返回有效 JSON{suffix}", kind="protocol") from exc
        # AuthAppService.logout returns bool, and the existing route serializes it directly.
        if method == "POST" and path == "/api/auth/logout" and isinstance(result, bool):
            result = {"success": result}
        if not isinstance(result, dict):
            suffix = "；写入结果可能未知，未自动重试" if method != "GET" else ""
            raise BrainError(f"服务端返回格式不正确{suffix}", kind="protocol")
        message = _business_error(result)
        if message:
            if p2_token:
                message = message.replace(p2_token, "[redacted]")
            if body and body.get("password"):
                message = message.replace(str(body["password"]), "[redacted]")
            invalid_session = _invalid_session(result)
            if invalid_session:
                self.store.clear()
            raise BrainError(
                f"服务未完成请求: {message}", kind="auth" if invalid_session else "business"
            )
        return result

    def require_login(self) -> dict:
        try:
            result = self.request("GET", "/api/auth/me")
            raw_data = result.get("data")
            data = raw_data if isinstance(raw_data, dict) else result
            user = data.get("user")
            if result.get("success") is not True or not isinstance(user, dict) or not user:
                raise BrainError("服务端未确认有效账号", kind="protocol")
        except BrainError as exc:
            prefix = (
                "请先 login" if exc.kind == "auth" else "暂时无法校验账号，保留原会话，请稍后重试"
            )
            raise BrainError(f"{prefix}: {exc}", kind=exc.kind, status=exc.status) from exc
        username = user.get("username")
        identity = [data.get("tenant_id"), data.get("local_user_id") or user.get("id"), username]
        if identity != self.store.state.get("identity"):
            self.store.state.pop("conversation_id", None)
            self.store.state["username"] = username
            self.store.state["identity"] = identity
            self.store.save()
        return result

    def login(self, username: str, password: str, account_kind: str, totp_code: str = "") -> dict:
        self.store.clear()
        result = self.request(
            "POST",
            "/api/auth/login",
            {
                "username": username,
                "password": password,
                "account_kind": account_kind,
                "totp_code": totp_code,
            },
        )
        if result.get("success") is not True or not any(
            cookie.name != "csrf_token" for cookie in self.store.cookies
        ):
            self.store.clear()
            raise BrainError("登录未建立 cookie 会话")
        self.store.state["username"] = username
        self.store.save()
        # Login may return JWTs/session identifiers: never print its raw payload.
        return {"success": True, "username": username, "origin": self.store.origin}

    def logout(self) -> dict:
        try:
            self.request("POST", "/api/auth/logout", {})
        finally:
            self.store.clear()
        return {"success": True, "message": "已退出登录并清除本地会话"}

    def chat(self, message: str | None, *, new: bool = False) -> dict:
        self.require_login()
        session_id = self.store.state.get("conversation_id")
        if new or not session_id:
            result = self.request("POST", "/api/ai/conversation/new", {})
            session_id = result.get("session_id") or (result.get("data") or {}).get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise BrainError("服务端未返回会话 ID")
            self.store.state["conversation_id"] = session_id
            self.store.save()
        if message is None:
            return {"success": True, "session_id": session_id}
        return self.request(
            "POST",
            "/api/ai/unified_chat",
            {
                "message": message,
                "session_id": session_id,
                "source": "brain_cli",
            },
        )

    def proposal(self, action: str, edit_id: str, *, p2_token: str = "") -> dict:
        return self.request(
            "GET" if action == "diff" else "POST",
            f"/api/code-editor/{action}/{quote(edit_id, safe='')}",
            None if action == "diff" else {},
            p2_token=p2_token,
        )
