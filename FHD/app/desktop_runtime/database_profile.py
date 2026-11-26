"""Desktop database profile: local SQLite by default, optional remote PostgreSQL."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.fastapi_app.sqlite_paths import is_sqlite_url

PROFILE_VERSION = 1
DEFAULT_PROFILE: dict[str, Any] = {
    "version": PROFILE_VERSION,
    "mode": "local",
    "remote": {"enabled": False, "database_url": ""},
}

_REMOTE_SCHEMES = {"postgresql", "postgresql+psycopg", "postgres"}


def _as_bool(value: Any) -> bool:
    """Coerce a stored value to bool.

    JSON profile may be hand-edited, so ``"false"`` / ``"0"`` / ``"no"`` must
    not be treated as truthy (``bool("false")`` is ``True``).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def profile_path(data_root: str | os.PathLike[str]) -> Path:
    return Path(data_root).expanduser().resolve() / "config" / "database.json"


def _normalize_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    profile = dict(DEFAULT_PROFILE)
    if not isinstance(raw, dict):
        return profile
    if str(raw.get("mode") or "").strip().lower() in {"local", "remote"}:
        profile["mode"] = str(raw["mode"]).strip().lower()
    remote = raw.get("remote")
    if isinstance(remote, dict):
        profile["remote"] = {
            "enabled": _as_bool(remote.get("enabled")),
            "database_url": str(remote.get("database_url") or "").strip(),
        }
    return profile


def load_or_create_profile(data_root: str | os.PathLike[str]) -> tuple[Path, dict[str, Any]]:
    path = profile_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        profile = _normalize_profile(raw if isinstance(raw, dict) else None)
        return path, profile
    profile = dict(DEFAULT_PROFILE)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, profile


def save_profile(
    data_root: str | os.PathLike[str], profile: dict[str, Any]
) -> tuple[Path, dict[str, Any]]:
    """Validate and persist a desktop database profile."""
    path = profile_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_profile(profile)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, normalized


def is_valid_remote_database_url(url: str) -> bool:
    """Return True when ``url`` is a usable PostgreSQL DSN (has scheme + host)."""
    text = (url or "").strip()
    if not text or is_sqlite_url(text):
        return False
    try:
        parsed = urlparse(text)
    except ValueError:
        return False
    return parsed.scheme in _REMOTE_SCHEMES and bool(parsed.hostname)


def _require_reconciled_mod_databases(data_root: Path, local_sqlite_url: str) -> None:
    """Never silently detach legacy Mod data when selecting the shared database."""
    error = (
        "检测到尚未核对的旧 Mod 分库配置或持久文件；请先备份并人工核对、受控迁移，"
        "再停用旧分库配置并将已保全旧库归档。已阻止切换企业共享库，未删除或迁移任何数据。"
    )
    if _as_bool(os.environ.get("XCAGI_MOD_ISOLATED_DATABASES")) or any(
        key.startswith("XCAGI_MOD_DATABASE_URL_") and value.strip()
        for key, value in os.environ.items()
    ):
        raise RuntimeError(error)
    raw_mapping = (os.environ.get("XCAGI_MOD_DATABASE_URLS") or "").strip()
    if raw_mapping:
        try:
            mapping = json.loads(raw_mapping)
        except json.JSONDecodeError as exc:
            raise RuntimeError(error) from exc
        if not isinstance(mapping, dict) or any(mapping.values()):
            raise RuntimeError(error)

    from app.db.xcmax_sync import _DB_FILENAME as sync_database_filename

    candidates = set()
    for directory in (data_root, data_root / "data"):
        for suffix in ("db", "sqlite", "sqlite3"):
            candidates.update(directory.glob(f"*__*.{suffix}"))
            candidates.update(
                path
                for path in (directory / "mod_dbs").glob(f"*.{suffix}")
                if path.name != sync_database_filename
            )
    # An explicitly selected SQLite database may live outside userData.
    from sqlalchemy.engine import make_url

    for raw_url in (
        local_sqlite_url,
        os.environ.get("XCAGI_DESKTOP_DATABASE_URL", ""),
        os.environ.get("DATABASE_URL", ""),
    ):
        if raw_url and is_sqlite_url(raw_url):
            database = make_url(raw_url).database
            if database and database != ":memory:":
                path = Path(database).expanduser()
                candidates.update(path.parent.glob(f"{path.stem}__*{path.suffix}"))
    for path in candidates:
        if any(item.is_file() and item.stat().st_size for item in (path, Path(f"{path}-wal"))):
            raise RuntimeError(error)


def apply_database_profile_to_env(
    data_root: str | os.PathLike[str],
    *,
    local_sqlite_url: str,
) -> tuple[Path, dict[str, Any]]:
    """Apply profile to process env. Default is local SQLite; remote only when explicitly enabled."""
    _require_reconciled_mod_databases(Path(data_root).expanduser().resolve(), local_sqlite_url)
    path, profile = load_or_create_profile(data_root)
    os.environ["XCAGI_MOD_ISOLATED_DATABASES"] = "0"

    remote = profile.get("remote") if isinstance(profile.get("remote"), dict) else {}
    if not isinstance(remote, dict):
        remote = {}
    remote_url = str(remote.get("database_url") or "").strip()
    use_remote = _as_bool(remote.get("enabled")) and is_valid_remote_database_url(remote_url)

    if use_remote:
        os.environ["XCAGI_DESKTOP_KEEP_DATABASE_URL"] = "1"
        os.environ["DATABASE_URL"] = remote_url
        os.environ["VECTOR_DB_URL"] = os.environ.get("XCAGI_DESKTOP_VECTOR_DB_URL") or remote_url
        profile["mode"] = "remote"
    else:
        os.environ.pop("XCAGI_DESKTOP_KEEP_DATABASE_URL", None)
        desktop_db_url = os.environ.get("XCAGI_DESKTOP_DATABASE_URL") or local_sqlite_url
        os.environ["DATABASE_URL"] = desktop_db_url
        os.environ["VECTOR_DB_URL"] = (
            os.environ.get("XCAGI_DESKTOP_VECTOR_DB_URL") or desktop_db_url
        )
        profile["mode"] = "local"

    return path, profile


def resolve_storage_mode(database_url: str | None, profile: dict[str, Any] | None = None) -> str:
    if is_sqlite_url(database_url):
        return "local_sqlite"
    url = str(database_url or "").strip()
    if url and is_valid_remote_database_url(url):
        return "remote_postgresql"
    mode = str((profile or {}).get("mode") or "").strip().lower()
    if mode == "remote":
        return "remote_postgresql"
    return "local_sqlite"


def redact_database_url(database_url: str | None) -> str:
    url = str(database_url or "").strip()
    if not url:
        return ""
    if is_sqlite_url(url):
        return url
    try:
        from sqlalchemy.engine import make_url

        return make_url(url).render_as_string(hide_password=True)
    except (ValueError, TypeError, ImportError):
        return url.split("@", 1)[-1] if "@" in url else url
