"""Library / XCAGI path helpers and persisted local state (moved from app.py)."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, cast

from modman.repo_config import (
    RepoConfig,
)
from modman.repo_config import load_config as _default_load_config
from modman.repo_config import (
    resolved_library,
    resolved_xcagi,
    resolved_xcagi_backend_url,
)
from modman.repo_config import save_config as _default_save_config
from modman.store import project_root as _default_project_root

STATE_FILENAME = "_modstore_state.json"
_MOD_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def repo_root() -> Path:
    """MODstore 仓库根（含 ``modstore_server/`` 目录）。"""
    return Path(__file__).resolve().parents[2]


def fhd_repo_root() -> Path:
    """MODstore 位于 ``<FHD>/MODstore`` 时的上级目录。"""
    return Path(__file__).resolve().parents[3]


def cfg() -> RepoConfig:
    """Prefer ``modstore_server.app.load_config`` when present (tests monkeypatch)."""

    app_mod = sys.modules.get("modstore_server.app")
    if app_mod is not None:
        fn = getattr(app_mod, "load_config", None)
        if callable(fn):
            return cast(RepoConfig, fn())
    return _default_load_config()


def save_config(cfg: RepoConfig) -> None:
    """Prefer ``modstore_server.app.save_config`` when present (tests monkeypatch)."""

    app_mod = sys.modules.get("modstore_server.app")
    if app_mod is not None:
        fn = getattr(app_mod, "save_config", None)
        if callable(fn):
            fn(cfg)
            return
    _default_save_config(cfg)


def project_root() -> Path:
    """Prefer ``modstore_server.app.project_root`` when present (tests monkeypatch)."""

    app_mod = sys.modules.get("modstore_server.app")
    if app_mod is not None:
        fn = getattr(app_mod, "project_root", None)
        if callable(fn):
            return cast(Path, fn())
    return _default_project_root()


def lib() -> Path:
    p = resolved_library(cfg())
    p.mkdir(parents=True, exist_ok=True)
    return p


def state_path() -> Path:
    return lib() / STATE_FILENAME


def load_state() -> Dict[str, Any]:
    p = state_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(updates: Dict[str, Any]) -> None:
    st = load_state()
    st.update({k: v for k, v in updates.items() if v is not None})
    p = state_path()
    p.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assert_path_inside_fhd_repo(fhd: Path, target: Path) -> None:
    fhd_text = os.path.realpath(os.path.abspath(fhd))
    target_text = os.path.realpath(os.path.abspath(target))
    fhd_prefix = fhd_text.rstrip(os.sep) + os.sep
    if target_text != fhd_text and not target_text.startswith(fhd_prefix):
        raise ValueError("output_path 必须位于 FHD 仓库根目录内")
    fhd_r = Path(fhd_text)
    tgt_r = Path(target_text)
    if not tgt_r.is_relative_to(fhd_r):
        raise ValueError("output_path 必须位于 FHD 仓库根目录内")


def mod_dir(mod_id: str) -> Path:
    normalized = (mod_id or "").strip()
    if normalized in {".", ".."} or _MOD_ID_RE.fullmatch(normalized) is None:
        raise ValueError("非法 mod id")
    root = lib().resolve()
    # Select from already-enumerated children instead of constructing a path
    # from caller input.  This makes the allow-list boundary explicit and also
    # prevents a symlinked mod directory from escaping the configured library.
    for candidate in root.iterdir():
        if candidate.name != normalized:
            continue
        resolved = candidate.resolve()
        if candidate.is_symlink() or not resolved.is_relative_to(root):
            raise ValueError("非法 mod id")
        if resolved.is_dir():
            return resolved
        break
    raise FileNotFoundError(f"Mod 不存在: {normalized}")


__all__ = [
    "STATE_FILENAME",
    "assert_path_inside_fhd_repo",
    "cfg",
    "fhd_repo_root",
    "lib",
    "load_state",
    "mod_dir",
    "repo_root",
    "save_state",
    "resolved_library",
    "resolved_xcagi",
    "resolved_xcagi_backend_url",
    "project_root",
    "save_config",
]
