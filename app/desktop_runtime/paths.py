"""Cross-platform data paths and environment bootstrap for desktop builds."""

from __future__ import annotations

import os
import platform
from pathlib import Path

DESKTOP_ENV = "XCAGI_DESKTOP_MODE"
DATA_DIR_ENV = "XCAGI_DATA_DIR"
LEGACY_DATA_DIR_ENV = "XCAGI_DESKTOP_DATA_DIR"


def get_desktop_mode() -> str:
    return (os.environ.get(DESKTOP_ENV) or "0").strip().lower()


def is_desktop_mode() -> bool:
    return get_desktop_mode() in {"1", "true", "yes", "on"}


def _default_user_data_dir() -> Path:
    system = platform.system().lower()
    if system == "windows":
        root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(root) / "XCAGI"
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / "XCAGI"
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "XCAGI"


def get_desktop_data_dir(data_dir: str | os.PathLike[str] | None = None) -> Path:
    raw = (
        str(data_dir)
        if data_dir is not None
        else os.environ.get(DATA_DIR_ENV) or os.environ.get(LEGACY_DATA_DIR_ENV)
    )
    return Path(raw).expanduser().resolve() if raw else _default_user_data_dir().resolve()


def ensure_desktop_dirs(data_dir: str | os.PathLike[str] | None = None) -> dict[str, Path]:
    root = get_desktop_data_dir(data_dir)
    dirs = {
        "root": root,
        "data": root / "data",
        "uploads": root / "uploads",
        "logs": root / "logs",
        "mods": root / "mods",
        "models": root / "models",
        "cache": root / "cache",
        "backups": root / "backups",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def sqlite_database_url(data_dir: str | os.PathLike[str] | None = None) -> str:
    dirs = ensure_desktop_dirs(data_dir)
    return "sqlite:///" + dirs["data"].joinpath("xcagi.db").as_posix()


def configure_desktop_environment(data_dir: str | os.PathLike[str] | None = None) -> Path:
    """Set process environment defaults for the local desktop runtime.

    The function is intentionally idempotent and only fills missing values for
    mutable infrastructure such as DATABASE_URL, so explicit operator settings
    still win in enterprise deployments.
    """

    os.environ[DESKTOP_ENV] = "1"
    dirs = ensure_desktop_dirs(data_dir)
    root = dirs["root"]
    os.environ[DATA_DIR_ENV] = str(root)
    os.environ[LEGACY_DATA_DIR_ENV] = str(root)

    if os.environ.get("XCAGI_DESKTOP_KEEP_DATABASE_URL", "").lower() not in {"1", "true", "yes", "on"}:
        desktop_db_url = os.environ.get("XCAGI_DESKTOP_DATABASE_URL") or sqlite_database_url(root)
        os.environ["DATABASE_URL"] = desktop_db_url
        os.environ["VECTOR_DB_URL"] = os.environ.get("XCAGI_DESKTOP_VECTOR_DB_URL") or desktop_db_url
    else:
        os.environ.setdefault("DATABASE_URL", sqlite_database_url(root))
        os.environ.setdefault("VECTOR_DB_URL", os.environ["DATABASE_URL"])
    os.environ.setdefault("DATABASE_PATH", str(dirs["data"]))
    os.environ.setdefault("UPLOAD_FOLDER", str(dirs["uploads"]))
    os.environ.setdefault("EXCEL_VECTOR_DB_PATH", str(dirs["data"] / "excel_vectors.db"))
    os.environ.setdefault("XCAGI_MODS_ROOT", str(dirs["mods"]))
    os.environ.setdefault("XCAGI_MODELS_DIR", str(dirs["models"]))
    os.environ.setdefault("XCAGI_LOG_DIR", str(dirs["logs"]))

    # Desktop mode should not require Redis/Celery to be installed or running.
    os.environ.setdefault("XCAGI_FORCE_SYNC_TASKS", "1")
    os.environ.setdefault("XCAGI_DISABLE_REDIS", "1")
    os.environ.setdefault("CACHE_REDIS_URL", "")
    os.environ.setdefault("CELERY_BROKER_URL", "memory://")
    os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")

    # The Electron shell owns the browser window; uvicorn reload subprocesses
    # make packaged desktop shutdown unreliable.
    os.environ.setdefault("FASTAPI_HOST", "127.0.0.1")
    os.environ.setdefault("XCAGI_UVICORN_RELOAD", "0")
    os.environ.setdefault("PYTHONUTF8", "1")
    return root
