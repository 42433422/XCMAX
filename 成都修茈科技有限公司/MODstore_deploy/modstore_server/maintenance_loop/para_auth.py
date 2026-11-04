"""Para authentication and private credential-cache ownership."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config

_PARA_GUEST_AUTH_CACHE: Dict[str, tuple] = {}

_PARA_GUEST_AUTH_TTL_SECONDS = 1800

_PARA_GUEST_AUTH_FILE_SAFETY_SECONDS = 60


def _para_tls_verify():
    """Build a verified TLS context for Para; optionally trust an operator CA bundle."""
    ca_bundle = str(os.environ.get("MODSTORE_PARA_CA_BUNDLE") or "").strip()
    if ca_bundle:
        ca_path = Path(ca_bundle).expanduser()
        if not ca_path.is_file():
            raise FileNotFoundError(f"MODSTORE_PARA_CA_BUNDLE does not exist: {ca_path}")
        return ssl.create_default_context(cafile=str(ca_path))
    return ssl.create_default_context()


def _guest_auth_headers(api_base: str) -> Dict[str, str]:
    from modstore_server.cred_vault import get_credential

    env_token = get_credential(
        "MODSTORE_PARA_AUTH_TOKEN",
        task_id="self-maintenance-loop",
        purpose="para_status_poll",
        aliases=("DEVFLEET_AUTH_TOKEN",),
    )
    if env_token:
        return {"Authorization": f"Bearer {env_token}"}
    cache_key = api_base.rstrip("/")
    cached = _PARA_GUEST_AUTH_CACHE.get(cache_key)
    if cached:
        token, expires_at = cached
        if time.time() < expires_at:
            return {"Authorization": f"Bearer {token}"}
        _PARA_GUEST_AUTH_CACHE.pop(cache_key, None)
    file_token = _read_para_guest_auth_file(cache_key)
    if file_token:
        return {"Authorization": f"Bearer {file_token}"}
    local_token = _mint_local_para_guest_auth_token(cache_key)
    if local_token:
        return {"Authorization": f"Bearer {local_token}"}
    with httpx.Client(timeout=20.0, trust_env=False, verify=_para_tls_verify()) as client:
        resp = None
        for attempt in range(3):
            resp = client.post(f"{api_base.rstrip('/')}/api/auth/guest")
            if resp.status_code == 429 and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            break
        if resp is None:
            raise RuntimeError("Para guest auth request was not attempted")
        resp.raise_for_status()
        token = str((resp.json() or {}).get("token") or "").strip()
        if not token:
            raise RuntimeError("Para guest auth response missing token")
    expires_at = time.time() + _PARA_GUEST_AUTH_TTL_SECONDS
    _PARA_GUEST_AUTH_CACHE[cache_key] = (token, expires_at)
    _write_para_guest_auth_file(cache_key, token, expires_at)
    return {"Authorization": f"Bearer {token}"}


def para_auth_cache_path() -> Path:
    override = os.environ.get("MODSTORE_PARA_AUTH_CACHE")
    if override:
        return Path(override)
    return config._runtime_dir() / config.DEFAULT_PARA_AUTH_CACHE_NAME


def _read_para_guest_auth_file(
    api_base: str,
    *,
    min_ttl_seconds: int = _PARA_GUEST_AUTH_FILE_SAFETY_SECONDS,
) -> Optional[str]:
    path = para_auth_cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except RECOVERABLE_ERRORS:
        config.logger.warning("failed to read Para guest auth cache file", exc_info=True)
        return None
    if not isinstance(data, dict):
        return None
    cache_key = api_base.rstrip("/")
    if str(data.get("api_base") or "").rstrip("/") != cache_key:
        return None
    token = str(data.get("token") or "").strip()
    try:
        expires_at = float(data.get("expires_at") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    if not token or time.time() + min_ttl_seconds >= expires_at:
        return None
    _PARA_GUEST_AUTH_CACHE[cache_key] = (token, expires_at)
    return token


def _write_para_guest_auth_file(api_base: str, token: str, expires_at: float) -> None:
    path = para_auth_cache_path()
    payload = {
        "api_base": api_base.rstrip("/"),
        "created_at": config._utc_now().isoformat(),
        "expires_at": expires_at,
        "expires_at_iso": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        "token": token,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
        try:
            path.chmod(384)
        except OSError:
            pass
    except RECOVERABLE_ERRORS:
        config.logger.warning("failed to write Para guest auth cache file", exc_info=True)


def _base64url_json(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _base64url_bytes(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _mint_local_para_guest_auth_token(api_base: str) -> Optional[str]:
    if not config._env_bool("MODSTORE_PARA_AUTH_LOCAL_MINT", True):
        return None
    db_file = _para_db_file()
    if db_file is None or not db_file.exists():
        return None
    try:
        with sqlite3.connect(str(db_file), timeout=2.0) as conn:
            row = conn.execute(
                "\n                select id, email\n                from users\n                where email = 'guest@devfleet.local'\n                   or (email like 'guest_%@devfleet.local')\n                order by case when email = 'guest@devfleet.local' then 0 else 1 end\n                limit 1\n                "
            ).fetchone()
    except RECOVERABLE_ERRORS:
        config.logger.warning(
            "failed to read Para guest user from sqlite for local auth mint",
            exc_info=True,
        )
        return None
    if not row:
        return None
    user_id, email = (str(row[0] or "").strip(), str(row[1] or "").strip())
    if not user_id or not email:
        return None
    now = int(time.time())
    expires_at = now + 7 * 24 * 60 * 60
    secret = (
        os.environ.get("MODSTORE_PARA_JWT_SECRET")
        or os.environ.get("JWT_SECRET")
        or "devfleet-dev-secret-change-me"
    )
    header = _base64url_json({"alg": "HS256", "typ": "JWT"})
    payload = _base64url_json(
        {"email": email, "exp": expires_at, "iat": now, "id": user_id, "sub": user_id}
    )
    unsigned = f"{header}.{payload}"
    signature = _base64url_bytes(
        hmac.new(secret.encode("utf-8"), unsigned.encode("ascii"), hashlib.sha256).digest()
    )
    token = f"{unsigned}.{signature}"
    cache_key = api_base.rstrip("/")
    _PARA_GUEST_AUTH_CACHE[cache_key] = (token, float(expires_at))
    _write_para_guest_auth_file(cache_key, token, float(expires_at))
    return token


def _para_db_file() -> Optional[Path]:
    raw = os.environ.get("MODSTORE_PARA_DB_FILE") or os.environ.get("DEVFLEET_DB_FILE")
    if not raw:
        candidate = Path.home() / "XCMAX-runtime/para-api/devfleet/api/data/devfleet.db"
        return candidate if candidate.exists() else None
    path = Path(raw).expanduser()
    return path if path.exists() else None
