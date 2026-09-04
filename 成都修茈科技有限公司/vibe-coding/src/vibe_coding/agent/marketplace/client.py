"""Thin HTTP client for the MODstore admin marketplace API.

Wraps three endpoints from ``modstore_server.market_api``:

- ``POST /api/auth/login``           — exchange (username, password) for tokens.
- ``POST /api/admin/catalog``        — multipart upload of a packaged ``.xcmod``.
- ``GET  /api/admin/catalog``        — list catalog rows (paginated).

Auth model: every protected call accepts an ``access_token``. Convenience
helpers (:meth:`login`, :meth:`from_token`) take care of pulling the
token out of the login response, but you can also pass an existing
token directly.

Pure ``urllib`` so we don't add a network library to the package's hard
dependency list. ``requests`` users are still welcome — write their own
client subclassing :class:`MODstoreClient`.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import mimetypes
import os
import secrets
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..._internals.tls import ssl_context_for_endpoint

DEFAULT_TIMEOUT_S: float = 30.0
_RESERVED_TEST_SUFFIXES = (".example", ".example.com", ".example.test")


class MODstoreError(RuntimeError):
    """Base class for marketplace HTTP errors."""


class MODstoreAuthError(MODstoreError):
    """Raised when login fails or a protected call returns 401."""


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a validated address while retaining origin-host TLS SNI."""

    def __init__(self, host: str, pinned_ip: str, *, port: int, timeout: float, context):
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address
        )
        if self._tunnel_host:
            self._tunnel()
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def _open_no_redirect(
    request: urllib.request.Request,
    *,
    timeout: float,
    context,
):
    """Open one origin request on the exact address that passed policy checks."""

    parsed = urllib.parse.urlsplit(request.full_url)
    host = str(parsed.hostname or "")
    pinned_ip = str(getattr(request, "_xcagi_pinned_ip", ""))
    # Reject a missing/tampered pin even if a caller bypassed MODstoreClient.
    ipaddress.ip_address(pinned_ip)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if parsed.scheme == "https":
        connection: http.client.HTTPConnection = _PinnedHTTPSConnection(
            host, pinned_ip, port=port, timeout=timeout, context=context
        )
    else:
        connection = http.client.HTTPConnection(pinned_ip, port=port, timeout=timeout)
    target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    headers = dict(request.header_items())
    default_port = 443 if parsed.scheme == "https" else 80
    headers["Host"] = host if port == default_port else f"{host}:{port}"
    connection.request(
        request.get_method(),
        target,
        body=request.data,
        headers=headers,
    )
    response = connection.getresponse()
    if response.status >= 300:
        raise urllib.error.HTTPError(
            request.full_url,
            response.status,
            response.reason,
            response.headers,
            response,
        )
    return response


@dataclass(slots=True)
class UploadResult:
    """Outcome of a successful ``POST /api/admin/catalog`` call."""

    item_id: int
    pkg_id: str
    stored_filename: str
    raw: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "pkg_id": self.pkg_id,
            "stored_filename": self.stored_filename,
            "raw": self.raw,
        }


class MODstoreClient:
    """HTTP client for ``modstore_server`` admin endpoints.

    ``base_url`` is the server origin (e.g. ``https://modstore.example.com``);
    the client appends the ``/api`` prefix that ``market_api`` mounts.
    """

    def __init__(
        self,
        base_url: str,
        *,
        access_token: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        verify_ssl: bool = True,
        allow_private_network: bool = False,
    ) -> None:
        self.allow_private_network = bool(allow_private_network)
        self.base_url = _validated_base_url(
            base_url,
            allow_private_network=self.allow_private_network,
        )
        self.access_token = access_token
        self.timeout_s = float(timeout_s)
        self.verify_ssl = bool(verify_ssl)

    # ----------------------------------------------------------------- factory

    @classmethod
    def from_token(
        cls,
        base_url: str,
        access_token: str,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        verify_ssl: bool = True,
        allow_private_network: bool = False,
    ) -> MODstoreClient:
        return cls(
            base_url=base_url,
            access_token=access_token,
            timeout_s=timeout_s,
            verify_ssl=verify_ssl,
            allow_private_network=allow_private_network,
        )

    @classmethod
    def from_env(
        cls,
        *,
        base_url_var: str = "MODSTORE_BASE_URL",
        token_var: str = "MODSTORE_ADMIN_TOKEN",
    ) -> MODstoreClient:
        base = os.environ.get(base_url_var, "").strip()
        token = os.environ.get(token_var, "").strip()
        if not base or not token:
            raise MODstoreAuthError(f"set {base_url_var} and {token_var} or pass them explicitly")
        allow_private = os.environ.get("MODSTORE_ALLOW_PRIVATE_NETWORK", "").strip().lower()
        return cls(
            base_url=base,
            access_token=token,
            allow_private_network=allow_private in {"1", "true", "yes", "on"},
        )

    # -------------------------------------------------------------------- auth

    def login(self, username: str, password: str) -> str:
        """Exchange credentials for an access_token and store it on the client."""
        body = json.dumps({"username": username, "password": password}).encode("utf-8")
        try:
            data = self._request(
                "POST",
                "/api/auth/login",
                body=body,
                headers={"Content-Type": "application/json"},
            )
        except MODstoreAuthError:
            raise
        except MODstoreError as exc:
            raise MODstoreAuthError(f"login failed: {exc}") from exc
        token = str(data.get("access_token") or "")
        if not token:
            raise MODstoreAuthError("login response missing access_token")
        self.access_token = token
        return token

    # --------------------------------------------------------------- catalog

    def upload_catalog(
        self,
        archive_path: str | Path,
        *,
        pkg_id: str,
        version: str,
        name: str,
        description: str = "",
        price: float = 0.0,
        artifact: str = "mod",
        industry: str = "通用",
    ) -> UploadResult:
        """Upload a packaged ``.xcmod`` zip to the marketplace.

        Mirrors the :func:`modstore_server.market_api.api_admin_upload_catalog`
        contract: same form fields, same file size limit (100 MiB).
        """
        # Validate auth before touching disk so the missing-token diagnostic
        # is what callers see (file checks would otherwise mask it).
        if not self.access_token:
            raise MODstoreAuthError("access_token required; call login() first")
        path = Path(archive_path)
        if not path.is_file():
            raise MODstoreError(f"archive not found: {path}")
        try:
            stat_result = path.stat()
            size_bytes = int(getattr(stat_result, "st_size", 0))
        except OSError as exc:
            raise MODstoreError(f"cannot stat archive {path}: {exc}") from exc
        if size_bytes > 100 * 1024 * 1024:
            raise MODstoreError(f"archive {path} exceeds the 100 MiB upload limit")

        boundary = "----vibe-coding-" + secrets.token_hex(16)
        body, content_type = _build_multipart(
            boundary=boundary,
            fields={
                "pkg_id": pkg_id,
                "version": version,
                "name": name,
                "description": description,
                "price": str(price),
                "artifact": artifact,
                "industry": industry,
            },
            file_field="file",
            file_path=path,
        )
        headers = {"Content-Type": content_type}
        data = self._request(
            "POST",
            "/api/admin/catalog",
            body=body,
            headers=headers,
            require_auth=True,
        )
        if not data.get("ok"):
            raise MODstoreError(f"upload rejected: {data}")
        return UploadResult(
            item_id=int(data.get("id") or 0),
            pkg_id=str(data.get("pkg_id") or pkg_id),
            stored_filename=str(data.get("stored_filename") or ""),
            raw=dict(data),
        )

    def list_catalog(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        path = f"/api/admin/catalog?limit={int(limit)}&offset={int(offset)}"
        return self._request("GET", path, require_auth=True)

    # ------------------------------------------------------------------ core

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        require_auth: bool = False,
    ) -> dict[str, Any]:
        if not path.startswith("/") or path.startswith("//"):
            raise MODstoreError("request path must be an origin-relative path")
        parsed_path = urllib.parse.urlsplit(path)
        if parsed_path.scheme or parsed_path.netloc:
            raise MODstoreError("request path must not override the configured origin")
        url = self.base_url + path
        pinned_ip = _assert_outbound_destination_safe(
            self.base_url,
            allow_private_network=self.allow_private_network,
        )
        h = dict(headers or {})
        if require_auth:
            if not self.access_token:
                raise MODstoreAuthError("access_token required; call login() first")
            h.setdefault("Authorization", f"Bearer {self.access_token}")
        req = urllib.request.Request(url=url, data=body, method=method, headers=h)
        req._xcagi_pinned_ip = pinned_ip
        try:
            ctx = self._ssl_context()
            with _open_no_redirect(req, timeout=self.timeout_s, context=ctx) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return _parse_json_response(raw)
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            if exc.code in (401, 403):
                raise MODstoreAuthError(f"{exc.code} {exc.reason}: {text}") from exc
            raise MODstoreError(f"{exc.code} {exc.reason}: {text}") from exc
        except urllib.error.URLError as exc:
            raise MODstoreError(f"network error: {exc.reason}") from exc
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise MODstoreError(f"network error: {exc}") from exc

    def _ssl_context(self):
        return ssl_context_for_endpoint(self.base_url, verify_ssl=self.verify_ssl)


# ---------------------------------------------------------------------- pure


def _validated_base_url(base_url: str, *, allow_private_network: bool) -> str:
    raw = str(base_url or "").strip().rstrip("/")
    if not raw or len(raw) > 2048:
        raise MODstoreError("base_url is missing or too long")
    parsed = urllib.parse.urlsplit(raw)
    host = str(parsed.hostname or "").strip().lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise MODstoreError("base_url must be an absolute http/https origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise MODstoreError("base_url must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise MODstoreError("base_url must not contain a path")
    if parsed.scheme != "https" and not allow_private_network:
        raise MODstoreError("plain HTTP requires allow_private_network=True")
    _assert_outbound_destination_safe(raw, allow_private_network=allow_private_network)
    return raw


def _assert_outbound_destination_safe(
    base_url: str,
    *,
    allow_private_network: bool,
) -> str:
    host = str(urllib.parse.urlsplit(base_url).hostname or "").strip().lower()
    if not host:
        raise MODstoreError("base_url is missing a host")
    if host.endswith(_RESERVED_TEST_SUFFIXES):
        return "192.0.2.1"
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address]
    if literal is not None:
        addresses = [literal]
    else:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise MODstoreError(f"base_url host cannot be safely resolved: {host}") from exc
        addresses = []
        for info in infos:
            sockaddr = info[4]
            if sockaddr:
                addresses.append(ipaddress.ip_address(sockaddr[0]))
        if not addresses:
            raise MODstoreError(f"base_url host has no addresses: {host}")
    if allow_private_network:
        return str(addresses[0])
    for address in addresses:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise MODstoreError(f"base_url resolves to a blocked network: {address}")
    return str(addresses[0])


def _parse_json_response(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MODstoreError(f"non-JSON response: {raw[:200]!r}") from exc
    if not isinstance(data, dict):
        raise MODstoreError(f"expected JSON object, got: {type(data).__name__}")
    return data


def _build_multipart(
    *,
    boundary: str,
    fields: dict[str, str],
    file_field: str,
    file_path: Path,
) -> tuple[bytes, str]:
    """Compose a ``multipart/form-data`` body matching FastAPI's expectations."""
    crlf = b"\r\n"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(b"--" + boundary.encode("ascii") + crlf)
        disp = f'Content-Disposition: form-data; name="{key}"'.encode()
        parts.append(disp + crlf + crlf)
        parts.append((value or "").encode("utf-8") + crlf)
    parts.append(b"--" + boundary.encode("ascii") + crlf)
    filename = file_path.name
    content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    disp = (f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"').encode()
    parts.append(disp + crlf)
    parts.append(f"Content-Type: {content_type}".encode() + crlf + crlf)
    parts.append(file_path.read_bytes())
    parts.append(crlf)
    parts.append(b"--" + boundary.encode("ascii") + b"--" + crlf)
    body = b"".join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "MODstoreAuthError",
    "MODstoreClient",
    "MODstoreError",
    "UploadResult",
]
