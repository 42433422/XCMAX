# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib
from dataclasses import dataclass


def _facade():
    return importlib.import_module("modstore_server.openapi_connector_runtime")


def _ip_is_blocked(ip: str) -> bool:
    try:
        addr = _facade().ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_loopback or addr.is_link_local or addr.is_multicast:
        return True
    if addr.is_private or addr.is_reserved or addr.is_unspecified:
        return True
    return False


@dataclass(frozen=True)
class PinnedOutboundTarget:
    """A validated URL whose network destination is pinned to one public IP."""

    request_url: str
    host_header: str
    server_hostname: str


def pin_url_outbound_safe(url: str) -> PinnedOutboundTarget:
    """Validate an outbound URL and pin the connection to one public IP."""
    if not url:
        raise _facade().OutboundBlocked("url 为空")
    if len(url) > 2048:
        raise _facade().OutboundBlocked("url 过长")
    parsed = _facade().urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise _facade().OutboundBlocked(f"不允许的协议: {scheme or '未指定'}")
    if parsed.username or parsed.password:
        raise _facade().OutboundBlocked("url 不得包含用户凭据")
    if parsed.fragment:
        raise _facade().OutboundBlocked("url 不得包含 fragment")
    host = (parsed.hostname or "").strip()
    if not host:
        raise _facade().OutboundBlocked("缺少 host")
    host_lower = host.lower()
    if host_lower in _facade()._BLOCKED_HOSTS:
        raise _facade().OutboundBlocked(f"host {host_lower} 已被禁用")
    try:
        addr = _facade().ipaddress.ip_address(host)
        if _facade()._ip_is_blocked(str(addr)):
            raise _facade().OutboundBlocked(f"目标 IP {addr} 位于禁用网段")
        addresses = [str(addr)]
    except ValueError:
        try:
            port = parsed.port or (443 if scheme == "https" else 80)
        except ValueError as exc:
            raise _facade().OutboundBlocked("端口无效") from exc
        try:
            infos = _facade().socket.getaddrinfo(host, port, type=_facade().socket.SOCK_STREAM)
        except _facade().socket.gaierror as exc:
            raise _facade().OutboundBlocked(f"主机 {host} 无法安全解析") from exc
        addresses = []
        for info in infos:
            sockaddr = info[4]
            if not sockaddr:
                continue
            ip = str(sockaddr[0])
            if _facade()._ip_is_blocked(ip):
                raise _facade().OutboundBlocked(f"主机 {host} 解析到禁用 IP {ip}")
            if ip not in addresses:
                addresses.append(ip)
        if not addresses:
            raise _facade().OutboundBlocked(f"主机 {host} 无解析结果")

    pinned_ip = addresses[0]
    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise _facade().OutboundBlocked("端口无效") from exc
    pinned_authority = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
    if explicit_port is not None:
        pinned_authority = f"{pinned_authority}:{explicit_port}"
    ascii_host = host.encode("idna").decode("ascii")
    host_header = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    if explicit_port is not None:
        host_header = f"{host_header}:{explicit_port}"
    request_url = _facade().urlunparse(
        (scheme, pinned_authority, parsed.path or "/", parsed.params, parsed.query, "")
    )
    return PinnedOutboundTarget(
        request_url=request_url,
        host_header=host_header,
        server_hostname=ascii_host,
    )


def assert_url_outbound_safe(url: str) -> None:
    """Reject non-web, local, private, reserved, and unresolvable targets."""

    pin_url_outbound_safe(url)


@_facade().dataclass
class CredentialPayload:
    auth_type: str
    config: _facade().Dict[str, _facade().Any]


def encrypt_credential_payload(
    auth_type: str, config: _facade().Mapping[str, _facade().Any]
) -> str:
    """把鉴权配置 JSON 序列化后用 Fernet 加密。"""
    if auth_type not in _facade().SUPPORTED_AUTH_TYPES:
        raise ValueError(f"不支持的 auth_type: {auth_type}")
    safe_cfg = dict(config or {})
    if auth_type == "none":
        safe_cfg = {}
    serialized = _facade().json.dumps(safe_cfg, ensure_ascii=False)
    return _facade().encrypt_secret(serialized)


def decrypt_credential_payload(auth_type: str, ciphertext: str) -> CredentialPayload:
    if not ciphertext:
        return _facade().CredentialPayload(auth_type=auth_type or "none", config={})
    try:
        data = _facade().json.loads(_facade().decrypt_secret(ciphertext))
    except (ValueError, RuntimeError) as exc:
        raise ValueError("鉴权配置解密失败") from exc
    if not isinstance(data, dict):
        raise ValueError("鉴权配置解密结果不是对象")
    return _facade().CredentialPayload(auth_type=auth_type or "none", config=data)


def _apply_auth(
    auth_type: str,
    cfg: _facade().Mapping[str, _facade().Any],
    *,
    headers: _facade().Dict[str, str],
    params: _facade().Dict[str, _facade().Any],
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
        token = _facade().base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        headers.setdefault("Authorization", f"Basic {token}")
        return
    if auth_type == "oauth2_client_credentials":
        token = _facade()._oauth_client_credentials_token(cfg)
        if token:
            headers.setdefault("Authorization", f"Bearer {token}")
        return
