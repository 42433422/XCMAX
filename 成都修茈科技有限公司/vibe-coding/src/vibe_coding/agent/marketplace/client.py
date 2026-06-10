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

import json
import mimetypes
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_S: float = 30.0


class MODstoreError(RuntimeError):
    """Base class for marketplace HTTP errors."""


class MODstoreAuthError(MODstoreError):
    """Raised when login fails or a protected call returns 401."""


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
    ) -> None:
        self.base_url = base_url.rstrip("/")
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
    ) -> MODstoreClient:
        return cls(
            base_url=base_url,
            access_token=access_token,
            timeout_s=timeout_s,
            verify_ssl=verify_ssl,
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
            raise MODstoreAuthError(
                f"set {base_url_var} and {token_var} or pass them explicitly"
            )
        return cls(base_url=base, access_token=token)

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
            raise MODstoreError(
                f"archive {path} exceeds the 100 MiB upload limit"
            )

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
        url = self.base_url + path
        h = dict(headers or {})
        if require_auth:
            if not self.access_token:
                raise MODstoreAuthError("access_token required; call login() first")
            h.setdefault("Authorization", f"Bearer {self.access_token}")
        req = urllib.request.Request(url=url, data=body, method=method, headers=h)
        try:
            ctx = self._ssl_context()
            with urllib.request.urlopen(req, timeout=self.timeout_s, context=ctx) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return _parse_json_response(raw)
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            if exc.code in (401, 403):
                raise MODstoreAuthError(f"{exc.code} {exc.reason}: {text}") from exc
            raise MODstoreError(f"{exc.code} {exc.reason}: {text}") from exc
        except urllib.error.URLError as exc:
            raise MODstoreError(f"network error: {exc.reason}") from exc

    def _ssl_context(self):
        if self.verify_ssl:
            return None
        import ssl

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


# ---------------------------------------------------------------------- pure


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
        disp = f'Content-Disposition: form-data; name="{key}"'.encode("utf-8")
        parts.append(disp + crlf + crlf)
        parts.append((value or "").encode("utf-8") + crlf)
    parts.append(b"--" + boundary.encode("ascii") + crlf)
    filename = file_path.name
    content_type = (
        mimetypes.guess_type(str(file_path))[0]
        or "application/octet-stream"
    )
    disp = (
        f'Content-Disposition: form-data; name="{file_field}"; '
        f'filename="{filename}"'
    ).encode("utf-8")
    parts.append(disp + crlf)
    parts.append(f"Content-Type: {content_type}".encode("utf-8") + crlf + crlf)
    parts.append(file_path.read_bytes())
    parts.append(crlf)
    parts.append(b"--" + boundary.encode("ascii") + b"--" + crlf)
    body = b"".join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


__all__ = [
    "MODstoreAuthError",
    "MODstoreClient",
    "MODstoreError",
    "UploadResult",
    "DEFAULT_TIMEOUT_S",
]
