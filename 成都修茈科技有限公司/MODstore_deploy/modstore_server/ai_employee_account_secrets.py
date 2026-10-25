"""Filesystem-backed credentials for AI employee accounts.

Credentials deliberately stay outside the database and source tree. Files are
written atomically with owner-only permissions under ``_local_secrets``.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

from modstore_server.operational_errors import BOUNDARY_ERRORS

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PLATFORM_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def _secrets_root() -> Path:
    configured = (os.environ.get("MODSTORE_AI_ACCOUNT_SECRETS_DIR") or "").strip()
    return Path(configured).expanduser() if configured else _PROJECT_ROOT / "_local_secrets"


def _normalized_platform(platform: str) -> str:
    normalized = (platform or "").strip().lower()
    if not _PLATFORM_RE.fullmatch(normalized):
        raise ValueError("platform must contain only lowercase letters, digits, '_' or '-'")
    return normalized


def _normalized_account_id(account_id: int) -> int:
    normalized = int(account_id)
    if normalized <= 0:
        raise ValueError("account_id must be positive")
    return normalized


def secret_path_for(platform: str, account_id: int) -> Path:
    """Return the deterministic credential path for one account."""
    normalized_platform = _normalized_platform(platform)
    normalized_account_id = _normalized_account_id(account_id)
    return _secrets_root() / normalized_platform / f"{normalized_account_id}.json"


def validate_qq_secret(secret: Mapping[str, Any]) -> None:
    """Validate the three credentials required by QQ bot APIs."""
    required = ("app_id", "app_secret", "bot_token")
    missing = [name for name in required if not str(secret.get(name) or "").strip()]
    if missing:
        raise ValueError(f"QQ secret missing required field(s): {', '.join(missing)}")


def write_secret(
    *,
    platform: str,
    account_id: int,
    external_id: str,
    secret: Mapping[str, Any],
) -> Path:
    """Atomically write one account credential file with mode ``0600``."""
    if not isinstance(secret, Mapping) or not secret:
        raise ValueError("secret must be a non-empty mapping")

    target = secret_path_for(platform, account_id)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)
    payload = {
        "version": 1,
        "external_id": str(external_id or "").strip(),
        "secret": dict(secret),
    }

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}.", suffix=".tmp", dir=target.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, target)
        os.chmod(target, 0o600)
    except BOUNDARY_ERRORS:
        try:
            os.close(fd)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise
    return target


def read_secret(*, platform: str, account_id: int) -> dict[str, Any] | None:
    """Read credentials, accepting both the versioned and legacy flat schema."""
    target = secret_path_for(platform, account_id)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None
    secret = payload.get("secret") if "secret" in payload else payload
    return dict(secret) if isinstance(secret, dict) else None


def delete_secret(*, platform: str, account_id: int) -> bool:
    """Delete one credential file and report whether it existed."""
    target = secret_path_for(platform, account_id)
    try:
        target.unlink()
    except FileNotFoundError:
        return False
    return True


__all__ = [
    "delete_secret",
    "read_secret",
    "secret_path_for",
    "validate_qq_secret",
    "write_secret",
]
