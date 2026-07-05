"""Desktop deployment mode catalog and profile helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROFILE_VERSION = 1
CATALOG_PATH = Path(__file__).resolve().parents[2] / "config" / "deployment_modes.generated.json"
DATABASE_STORAGE_CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "database_storage_modes.generated.json"
)


def load_deployment_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        raise RuntimeError(f"deployment modes catalog missing: {CATALOG_PATH}")
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("deployment modes catalog must be a JSON object")
    modes = data.get("modes")
    if not isinstance(modes, list) or not modes:
        raise RuntimeError("deployment modes catalog must contain modes")
    return data


def load_database_storage_catalog() -> dict[str, Any]:
    if not DATABASE_STORAGE_CATALOG_PATH.is_file():
        raise RuntimeError(f"database storage catalog missing: {DATABASE_STORAGE_CATALOG_PATH}")
    data = json.loads(DATABASE_STORAGE_CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("database storage catalog must be a JSON object")
    return data


def deployment_profile_path(data_root: str | os.PathLike[str]) -> Path:
    return Path(data_root).expanduser().resolve() / "config" / "deployment.json"


def mode_by_id(catalog: dict[str, Any], mode_id: str) -> dict[str, Any] | None:
    target = str(mode_id or "").strip()
    for item in catalog.get("modes") or []:
        if isinstance(item, dict) and str(item.get("id") or "") == target:
            return item
    return None


def default_mode_id(catalog: dict[str, Any]) -> str:
    configured = str(catalog.get("defaultMode") or "").strip()
    if mode_by_id(catalog, configured):
        return configured
    first = next((m for m in catalog.get("modes") or [] if isinstance(m, dict)), None)
    return str(first.get("id")) if first else "safe"


def _normalize_profile(raw: dict[str, Any] | None, catalog: dict[str, Any]) -> dict[str, Any]:
    fallback = default_mode_id(catalog)
    mode = str((raw or {}).get("mode") or "").strip()
    if not mode_by_id(catalog, mode):
        mode = fallback
    return {"version": PROFILE_VERSION, "mode": mode}


def load_or_create_deployment_profile(
    data_root: str | os.PathLike[str], catalog: dict[str, Any] | None = None
) -> tuple[Path, dict[str, Any]]:
    cat = catalog or load_deployment_catalog()
    path = deployment_profile_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        profile = _normalize_profile(raw if isinstance(raw, dict) else None, cat)
        return path, profile
    profile = _normalize_profile(None, cat)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, profile


def save_deployment_profile(
    data_root: str | os.PathLike[str],
    mode: str,
    catalog: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    cat = catalog or load_deployment_catalog()
    if not mode_by_id(cat, mode):
        raise ValueError(f"unknown deployment mode: {mode}")
    path = deployment_profile_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {"version": PROFILE_VERSION, "mode": str(mode)}
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, profile


def resolve_effective_mode_id(
    catalog: dict[str, Any],
    profile: dict[str, Any] | None,
    *,
    storage_mode: str,
) -> str:
    mode = str((profile or {}).get("mode") or "").strip()
    if mode_by_id(catalog, mode):
        return mode
    if storage_mode == "remote_postgresql" and mode_by_id(catalog, "performance"):
        return "performance"
    return default_mode_id(catalog)


def build_sqlite_to_postgres_sync_plan(
    catalog: dict[str, Any],
    *,
    sqlite_path: str,
    postgres_url: str,
    data_root: str,
) -> dict[str, Any]:
    storage_catalog = (
        catalog if "transitions" in catalog else load_database_storage_catalog()
    )
    policy = (storage_catalog.get("transitions") or {}).get("sqlite_to_postgresql") or {}
    command = str(policy.get("sync_command") or "").strip()
    if command:
        command = (
            command.replace("<desktop-sqlite-db>", sqlite_path)
            .replace("<postgres-url>", postgres_url)
            .replace("<desktop-data-dir>", data_root)
        )
    return {
        "from": "local_sqlite",
        "to": "remote_postgresql",
        "requiresBackup": bool(policy.get("requires_backup", True)),
        "requiresAlembicUpgrade": bool(policy.get("requires_alembic_upgrade", True)),
        "restartRequired": bool(policy.get("restart_required", True)),
        "syncStrategy": str(policy.get("sync_strategy") or "copy_sqlite_tables_to_postgresql_then_switch_profile"),
        "syncCommand": command,
        "profilePathTemplate": str(policy.get("profile_path") or ""),
    }
