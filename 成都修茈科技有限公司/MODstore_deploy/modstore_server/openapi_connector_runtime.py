"""OpenAPI 连接器运行时：参数校验、鉴权注入、SSRF 限制、httpx 调用与日志。

调用约定：
    call_generated_operation(connector_id, user_id, operation_id, params, body, headers, timeout, source)

由生成产物 :mod:`modstore_server.openapi_connector_codegen` 中的 client.py 调用。
"""

from __future__ import annotations

import base64
import ipaddress
import json
import logging
import re
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from modstore_server.llm_crypto import decrypt_secret, encrypt_secret
from modstore_server.models import (
    OpenApiCallLog,
    OpenApiConnector,
    OpenApiCredential,
    OpenApiOperation,
    get_session_factory,
)

logger = logging.getLogger(__name__)


_MAX_REQUEST_SUMMARY = 1500
_MAX_RESPONSE_SUMMARY = 2000
_MAX_RESPONSE_BYTES = 256 * 1024
_DEFAULT_TIMEOUT = 30.0

SUPPORTED_AUTH_TYPES = (
    "none",
    "api_key",
    "bearer",
    "basic",
    "oauth2_client_credentials",
)

_SENSITIVE_HEADER_PATTERNS = re.compile(
    r"(authorization|api[-_]?key|x[-_]?api[-_]?key|x[-_]?auth[-_]?token|cookie|set-cookie|secret|token)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Outbound safety helpers
# ---------------------------------------------------------------------------


class OutboundBlocked(RuntimeError):
    """用于安全策略拦截出站请求。"""


_BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata.googleapis.com"}


def _ip_is_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_loopback or addr.is_link_local or addr.is_multicast:
        return True
    if addr.is_private or addr.is_reserved or addr.is_unspecified:
        return True
    return False


def assert_url_outbound_safe(url: str) -> None:
    """阻止 file://、内网回环、链路本地等可能被滥用的目标。

    解析过 DNS：如果主机解析到内网 IP，也会被阻止。
    """
    if not url:
        raise OutboundBlocked("url 为空")
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise OutboundBlocked(f"不允许的协议: {scheme or '未指定'}")
    host = (parsed.hostname or "").strip()
    if not host:
        raise OutboundBlocked("缺少 host")
    host_lower = host.lower()
    if host_lower in _BLOCKED_HOSTS:
        raise OutboundBlocked(f"host {host_lower} 已被禁用")
    try:
        addr = ipaddress.ip_address(host)
        if _ip_is_blocked(str(addr)):
            raise OutboundBlocked(f"目标 IP {addr} 位于禁用网段")
        return
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return  # 解析失败让 httpx 继续尝试，否则可能误伤离线开发场景
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip = sockaddr[0]
        if _ip_is_blocked(ip):
            raise OutboundBlocked(f"主机 {host} 解析到禁用 IP {ip}")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


@dataclass
class CredentialPayload:
    auth_type: str
    config: Dict[str, Any]


def encrypt_credential_payload(auth_type: str, config: Mapping[str, Any]) -> str:
    """把鉴权配置 JSON 序列化后用 Fernet 加密。"""
    if auth_type not in SUPPORTED_AUTH_TYPES:
        raise ValueError(f"不支持的 auth_type: {auth_type}")
    safe_cfg = dict(config or {})
    if auth_type == "none":
        safe_cfg = {}
    serialized = json.dumps(safe_cfg, ensure_ascii=False)
    return encrypt_secret(serialized)


def decrypt_credential_payload(auth_type: str, ciphertext: str) -> CredentialPayload:
    if not ciphertext:
        return CredentialPayload(auth_type=auth_type or "none", config={})
    try:
        data = json.loads(decrypt_secret(ciphertext))
    except (ValueError, RuntimeError) as exc:
        raise ValueError(f"鉴权配置解密失败: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("鉴权配置解密结果不是对象")
    return CredentialPayload(auth_type=auth_type or "none", config=data)


def _apply_auth(
    auth_type: str,
    cfg: Mapping[str, Any],
    *,
    headers: Dict[str, str],
    params: Dict[str, Any],
) -> None:
    if auth_type == "none":
        return
    if auth_type == "bearer":
        token = str(cfg.get("token") or "").strip()
        if token:
            headers.setdefault("Authorization", f"Bearer {token}")
        return
    if auth_type == "api_key":
        location = str(cfg.get("in") or cfg.get("location") or "header").strip().lower()
        name = str(cfg.get("name") or "X-API-Key").strip() or "X-API-Key"
        key = str(cfg.get("key") or cfg.get("api_key") or "").strip()
        if not key:
            return
        if location == "query":
            params.setdefault(name, key)
        else:
            headers.setdefault(name, key)
        return
    if auth_type == "basic":
        username = str(cfg.get("username") or "")
        password = str(cfg.get("password") or "")
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        headers.setdefault("Authorization", f"Basic {token}")
        return
    if auth_type == "oauth2_client_credentials":
        token = _oauth_client_credentials_token(cfg)
        if token:
            headers.setdefault("Authorization", f"Bearer {token}")
        return


_OAUTH_TOKEN_CACHE: Dict[Tuple[str, str], Tuple[str, float]] = {}
_OAUTH_LOCK = threading.Lock()


def _oauth_client_credentials_token(cfg: Mapping[str, Any]) -> str:
    token_url = str(cfg.get("token_url") or "").strip()
    client_id = str(cfg.get("client_id") or "").strip()
    client_secret = str(cfg.get("client_secret") or "").strip()
    if not token_url or not client_id or not client_secret:
        return ""
    cache_key = (token_url, client_id)
    now = time.time()
    with _OAUTH_LOCK:
        cached = _OAUTH_TOKEN_CACHE.get(cache_key)
        if cached and cached[1] > now + 30:
            return cached[0]
    assert_url_outbound_safe(token_url)
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    scope = str(cfg.get("scope") or "").strip()
    if scope:
        data["scope"] = scope
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(token_url, data=data)
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("oauth client_credentials failed: %s", exc)
        return ""
    token = str(body.get("access_token") or "").strip()
    expires_in = float(body.get("expires_in") or 600)
    if not token:
        return ""
    with _OAUTH_LOCK:
        _OAUTH_TOKEN_CACHE[cache_key] = (token, now + max(expires_in, 60))
    return token


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------


_TIMEOUT_MIN = 1.0
_TIMEOUT_MAX = 60.0


def _safe_timeout(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT
    return max(_TIMEOUT_MIN, min(_TIMEOUT_MAX, v))


def _resolve_full_url(base_url: str, path: str, *, override: Optional[str] = None) -> str:
    base = (override or base_url or "").strip()
    if not base:
        # 允许 path 直接是绝对 URL（少数 spec 没有 servers）
        if path.startswith(("http://", "https://")):
            return path
        raise OutboundBlocked("连接器未配置 base_url，且 operation path 不是绝对 URL")
    if not base.endswith("/"):
        base = base + "/"
    rel = path.lstrip("/")
    return urljoin(base, rel)


def _apply_path_params(
    path: str, params: Dict[str, Any], spec_params: List[Mapping[str, Any]]
) -> str:
    out = path
    consumed: List[str] = []
    for spec in spec_params:
        if str(spec.get("in") or "").lower() != "path":
            continue
        name = str(spec.get("name") or "")
        if not name:
            continue
        token = "{" + name + "}"
        if token not in out:
            continue
        if name not in params:
            raise ValueError(f"缺少 path 参数: {name}")
        value = params[name]
        out = out.replace(token, _format_path_value(value))
        consumed.append(name)
    for name in consumed:
        params.pop(name, None)
    return out


def _format_path_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _split_params(
    raw_params: Mapping[str, Any], spec_params: List[Mapping[str, Any]]
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, str]]:
    """根据 OpenAPI parameters 把传入参数拆成 path / query / header。"""
    path_params: Dict[str, Any] = {}
    query_params: Dict[str, Any] = {}
    header_params: Dict[str, str] = {}
    locations = {str(p.get("name") or ""): str(p.get("in") or "").lower() for p in spec_params}
    required_missing: List[str] = []
    for name, value in (raw_params or {}).items():
        loc = locations.get(name, "query")
        if loc == "path":
            path_params[name] = value
        elif loc == "header":
            if value is not None:
                header_params[name] = str(value)
        elif loc == "cookie":
            # 默认拒绝直接发 cookie，避免 SSRF/跨域副作用；可在未来加白名单
            continue
        else:
            query_params[name] = value
    for spec in spec_params:
        if not bool(spec.get("required")):
            continue
        name = str(spec.get("name") or "")
        loc = str(spec.get("in") or "").lower()
        if loc == "path" and name not in path_params:
            required_missing.append(f"{loc}:{name}")
        elif loc == "query" and name not in query_params:
            required_missing.append(f"{loc}:{name}")
        elif loc == "header" and name not in header_params:
            required_missing.append(f"{loc}:{name}")
    if required_missing:
        raise ValueError(f"缺少必填参数: {', '.join(required_missing)}")
    return path_params, query_params, header_params


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


def _redact_headers(headers: Mapping[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in (headers or {}).items():
        key = str(k)
        if _SENSITIVE_HEADER_PATTERNS.search(key):
            out[key] = "***"
        else:
            value = str(v)
            out[key] = value[:120] + ("…" if len(value) > 120 else "")
    return out


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"…(+{len(text) - limit} chars)"


def _summarize_request(
    method: str, url: str, params: Mapping[str, Any], headers: Mapping[str, Any], body: Any
) -> str:
    payload: Dict[str, Any] = {
        "method": method,
        "url": url,
        "params": dict(params or {}),
        "headers": _redact_headers(headers or {}),
    }
    if body is not None:
        try:
            payload["body"] = json.loads(json.dumps(body, default=str))
        except (TypeError, ValueError):
            payload["body"] = repr(body)
    return _truncate(json.dumps(payload, ensure_ascii=False), _MAX_REQUEST_SUMMARY)


def _summarize_response(resp: Optional[httpx.Response], parsed_body: Any, error: str) -> str:
    info: Dict[str, Any] = {}
    if resp is not None:
        info["status_code"] = resp.status_code
        info["headers"] = _redact_headers(dict(resp.headers))
    if parsed_body is not None:
        try:
            info["body"] = json.loads(json.dumps(parsed_body, default=str))
        except (TypeError, ValueError):
            info["body"] = repr(parsed_body)
    if error:
        info["error"] = error
    return _truncate(json.dumps(info, ensure_ascii=False), _MAX_RESPONSE_SUMMARY)


# ---------------------------------------------------------------------------
# Core call
# ---------------------------------------------------------------------------


def _load_runtime_context(
    session,
    *,
    connector_id: int,
    user_id: int,
    operation_id: str,
) -> Tuple[OpenApiConnector, OpenApiOperation, Optional[OpenApiCredential]]:
    connector = (
        session.query(OpenApiConnector)
        .filter(OpenApiConnector.id == connector_id, OpenApiConnector.user_id == user_id)
        .first()
    )
    if not connector:
        raise LookupError(f"连接器不存在或无权访问: {connector_id}")
    if connector.status == "disabled":
        raise PermissionError(f"连接器 {connector_id} 已被禁用")
    op = (
        session.query(OpenApiOperation)
        .filter(
            OpenApiOperation.connector_id == connector_id,
            OpenApiOperation.operation_id == operation_id,
        )
        .first()
    )
    if not op:
        raise LookupError(f"operation 不存在: {operation_id}")
    if not op.enabled:
        raise PermissionError(f"operation 已被禁用: {operation_id}")
    credential = (
        session.query(OpenApiCredential)
        .filter(
            OpenApiCredential.connector_id == connector_id,
            OpenApiCredential.user_id == user_id,
        )
        .first()
    )
    return connector, op, credential


def _record_log(
    session,
    *,
    user_id: int,
    connector_id: int,
    operation_id: str,
    method: str,
    path: str,
    status_code: Optional[int],
    duration_ms: float,
    request_summary: str,
    response_summary: str,
    error: str,
    source: str,
) -> None:
    try:
        entry = OpenApiCallLog(
            user_id=user_id,
            connector_id=connector_id,
            operation_id=operation_id,
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            request_summary=request_summary,
            response_summary=response_summary,
            error=error,
            source=source,
            created_at=datetime.now(timezone.utc),
        )
        session.add(entry)
        session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("openapi connector log persist failed: %s", exc)
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass


def call_generated_operation(
    *,
    connector_id: int,
    user_id: int,
    operation_id: str,
    params: Optional[Mapping[str, Any]] = None,
    body: Any = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = _DEFAULT_TIMEOUT,
    source: str = "manual",
    base_url_override: Optional[str] = None,
) -> Dict[str, Any]:
    """生成产物里的客户端函数最终都调用这里。

    返回 ``{ok, status_code, body, headers, error, duration_ms}``，不抛异常。
    """
    safe_timeout = _safe_timeout(timeout)
    safe_source = (source or "manual").strip().lower() or "manual"
    sf = get_session_factory()
    started = time.perf_counter()
    method = "GET"
    full_url = ""
    request_summary = ""
    response_summary = ""
    status_code: Optional[int] = None
    error_text = ""
    parsed_body: Any = None
    response_headers: Dict[str, str] = {}
    with sf() as session:
        try:
            connector, operation, credential = _load_runtime_context(
                session,
                connector_id=connector_id,
                user_id=user_id,
                operation_id=operation_id,
            )
            method = (operation.method or "GET").upper()
            try:
                spec_params = json.loads(operation.request_schema or "{}").get("parameters") or []
            except (TypeError, ValueError):
                spec_params = []
            if not isinstance(spec_params, list):
                spec_params = []

            mutable_params = dict(params or {})
            path_params, query_params, header_params = _split_params(mutable_params, spec_params)
            applied_path = _apply_path_params(operation.path, path_params, spec_params)
            full_url = _resolve_full_url(
                connector.base_url, applied_path, override=base_url_override
            )
            assert_url_outbound_safe(full_url)

            outgoing_headers: Dict[str, str] = {}
            outgoing_headers.update(header_params)
            for k, v in (headers or {}).items():
                outgoing_headers[str(k)] = str(v)

            outgoing_query: Dict[str, Any] = dict(query_params)
            if credential is not None:
                payload = decrypt_credential_payload(
                    credential.auth_type, credential.config_encrypted
                )
                _apply_auth(
                    payload.auth_type,
                    payload.config,
                    headers=outgoing_headers,
                    params=outgoing_query,
                )

            json_body: Any = None
            data_body: Any = None
            if body is not None and method not in ("GET", "HEAD", "DELETE"):
                try:
                    json.dumps(body)
                    json_body = body
                    outgoing_headers.setdefault("Content-Type", "application/json")
                except (TypeError, ValueError):
                    data_body = body

            request_summary = _summarize_request(
                method, full_url, outgoing_query, outgoing_headers, body
            )

            with httpx.Client(
                timeout=safe_timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                resp = client.request(
                    method,
                    full_url,
                    params=outgoing_query or None,
                    headers=outgoing_headers or None,
                    json=json_body,
                    data=data_body,
                )
            status_code = resp.status_code
            response_headers = {str(k): str(v) for k, v in resp.headers.items()}
            raw_bytes = resp.content[:_MAX_RESPONSE_BYTES]
            try:
                text_body = raw_bytes.decode(resp.encoding or "utf-8", errors="replace")
            except (LookupError, AttributeError):
                text_body = raw_bytes.decode("utf-8", errors="replace")
            content_type = (resp.headers.get("content-type") or "").lower()
            if "json" in content_type:
                try:
                    parsed_body = json.loads(text_body)
                except (ValueError, TypeError):
                    parsed_body = text_body
            else:
                parsed_body = text_body
            response_summary = _summarize_response(resp, parsed_body, "")
            ok = 200 <= resp.status_code < 400
            return _finalize(
                session,
                user_id=user_id,
                connector_id=connector_id,
                operation_id=operation_id,
                method=method,
                full_url=full_url,
                status_code=status_code,
                request_summary=request_summary,
                response_summary=response_summary,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                response_headers=response_headers,
                parsed_body=parsed_body,
                error_text="",
                source=safe_source,
                ok=ok,
            )
        except OutboundBlocked as exc:
            error_text = f"outbound_blocked: {exc}"
        except (LookupError, PermissionError) as exc:
            error_text = f"unavailable: {exc}"
        except ValueError as exc:
            error_text = f"validation_error: {exc}"
        except httpx.HTTPError as exc:
            error_text = f"http_error: {exc}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("openapi connector call crashed")
            error_text = f"internal_error: {type(exc).__name__}: {exc}"
        response_summary = _summarize_response(None, None, error_text)
        return _finalize(
            session,
            user_id=user_id,
            connector_id=connector_id,
            operation_id=operation_id,
            method=method,
            full_url=full_url,
            status_code=status_code,
            request_summary=request_summary,
            response_summary=response_summary,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            response_headers={},
            parsed_body=None,
            error_text=error_text,
            source=safe_source,
            ok=False,
        )


def _finalize(
    session,
    *,
    user_id: int,
    connector_id: int,
    operation_id: str,
    method: str,
    full_url: str,
    status_code: Optional[int],
    request_summary: str,
    response_summary: str,
    duration_ms: float,
    response_headers: Mapping[str, str],
    parsed_body: Any,
    error_text: str,
    source: str,
    ok: bool,
) -> Dict[str, Any]:
    parsed_path = urlparse(full_url).path or full_url
    _record_log(
        session,
        user_id=user_id,
        connector_id=connector_id,
        operation_id=operation_id,
        method=method,
        path=parsed_path[:512],
        status_code=status_code,
        duration_ms=duration_ms,
        request_summary=request_summary,
        response_summary=response_summary,
        error=error_text,
        source=source,
    )
    return {
        "ok": ok,
        "status_code": status_code,
        "body": parsed_body,
        "headers": dict(response_headers or {}),
        "error": error_text,
        "duration_ms": duration_ms,
        "operation_id": operation_id,
        "url": full_url,
        "method": method,
    }
