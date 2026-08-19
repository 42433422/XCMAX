"""Environment and repository-path resolution for surface-audit dependencies."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse


def auto_start_enabled() -> bool:
    return (os.environ.get("MODSTORE_SURFACE_AUDIT_AUTO_START", "1") or "").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def repo_root() -> Path:
    mono = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if mono:
        return Path(mono).expanduser().resolve()
    repo = (os.environ.get("MODSTORE_REPO_ROOT") or "").strip()
    if repo:
        path = Path(repo).expanduser().resolve()
        if (path / "FHD").is_dir():
            return path
    try:
        from modstore_server.daily_digest import _repo_root as root_fn

        return Path(root_fn())
    except Exception:
        return Path(__file__).resolve().parents[3]


def fhd_root() -> Path:
    candidates: List[Path] = []
    explicit = (
        os.environ.get("XCAGI_FHD_ROOT") or os.environ.get("MODSTORE_DAILY_FHD_ROOT") or ""
    ).strip()
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    mono = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if mono:
        candidates.append(Path(mono).expanduser().resolve() / "FHD")
    root = repo_root()
    candidates.extend((root / "FHD", root.parent / "FHD"))
    for fhd in candidates:
        if fhd.is_dir():
            return fhd
    return candidates[0] if candidates else root / "FHD"


def modstore_deploy_root() -> Path:
    root = repo_root()
    deploy = root / "成都修茈科技有限公司" / "MODstore_deploy"
    if deploy.is_dir():
        return deploy
    local = root / "MODstore_deploy"
    return local if local.is_dir() else deploy


def runtime_state_root() -> Optional[Path]:
    for key in ("MODSTORE_RUNTIME_STATE_ROOT", "MODSTORE_RUNTIME_DIR"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
    return None


def is_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")
