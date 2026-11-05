"""Resolve library roots and enforce package directory boundaries."""

from __future__ import annotations

import logging
import ntpath
import os
from collections.abc import Callable

from .ports import RootState, TrustedChild


def is_package_directory_name(value: str) -> bool:
    """A local identity names one child, never the library or a path to another child."""
    return (
        bool(value)
        and value not in {".", ".."}
        and not any(c in value for c in "/\\\0")
        and not ntpath.splitdrive(value)[0]
    )


def is_mods_disabled() -> bool:
    """为 true 时不加载任何 Mod（扩展蓝图、行业覆盖、Hooks 等），仅用核心与原始配置/数据库。"""
    v = (os.environ.get("XCAGI_DISABLE_MODS") or "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def default_mods_root(source_file: str, logger: logging.Logger) -> str:
    """Resolve the MOD root across source and packaged layouts."""
    env = (os.environ.get("XCAGI_MODS_ROOT") or os.environ.get("XCAGI_MODS_DIR") or "").strip()
    if env:
        p = os.path.abspath(env)
        if os.path.isdir(p):
            logger.debug("[_default_mods_root] Mods root from env: %s", p)
            return p
        logger.warning(
            "[_default_mods_root] XCAGI_MODS_ROOT / XCAGI_MODS_DIR is set but not a directory: %s",
            p,
        )
    file_here = os.path.abspath(source_file)
    from_pkg_layout = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(file_here)))),
        "mods",
    )
    logger.debug(
        "[_default_mods_root] Checking package-relative path: %s, exists: %s",
        from_pkg_layout,
        os.path.isdir(from_pkg_layout),
    )
    if os.path.isdir(from_pkg_layout):
        logger.debug("[_default_mods_root] Mods root (next to app package): %s", from_pkg_layout)
        return from_pkg_layout
    cwd_mods = os.path.join(os.getcwd(), "mods")
    logger.debug(
        "[_default_mods_root] Checking CWD mods: %s, exists: %s",
        cwd_mods,
        os.path.isdir(cwd_mods),
    )
    if os.path.isdir(cwd_mods):
        logger.debug("[_default_mods_root] Mods root (./mods from cwd): %s", cwd_mods)
        return cwd_mods
    cur = os.path.abspath(os.getcwd())
    for i in range(8):
        trial = os.path.join(cur, "mods")
        logger.debug("[_default_mods_root] Walking up: %s, exists: %s", trial, os.path.isdir(trial))
        if os.path.isdir(trial):
            logger.debug("[_default_mods_root] Mods root (walk up from cwd): %s", trial)
            return trial
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    logger.warning(
        "[_default_mods_root] No mods directory found; using package-relative path (may be empty): %s. Set XCAGI_MODS_ROOT or run from project root.",
        from_pkg_layout,
    )
    return from_pkg_layout


def repo_layout_mods_candidates(source_file: str) -> list[str]:
    """Find additional repository MOD roots missing from a packaged deployment."""
    file_here = os.path.abspath(source_file)
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(file_here))))
    out: list[str] = []
    for rel in ("mods", os.path.join("XCAGI", "mods")):
        p = os.path.abspath(os.path.join(repo_root, rel))
        if os.path.isdir(p) and p not in out:
            out.append(p)
    return out


def all_mods_roots(primary: str, candidates: Callable[[], list[str]]) -> list[str]:
    """主 mods_root + 仓库内其它 mods 目录（去重，主目录优先）。"""
    roots: list[str] = []
    primary_abs = os.path.abspath((primary or "").strip())
    if primary_abs and os.path.isdir(primary_abs) and (primary_abs not in roots):
        roots.append(primary_abs)
    env = (os.environ.get("XCAGI_MODS_ROOT") or os.environ.get("XCAGI_MODS_DIR") or "").strip()
    if env:
        p = os.path.abspath(env)
        if os.path.isdir(p) and p not in roots:
            roots.append(p)
    for p in candidates():
        if p not in roots:
            roots.append(p)
    return roots


def trusted_child_path(parent: str, child_name: str, *, directory: bool) -> str | None:
    try:
        with os.scandir(parent) as entries:
            for entry in entries:
                if entry.name != child_name or entry.is_symlink():
                    continue
                if directory and entry.is_dir(follow_symlinks=False):
                    return entry.path
                if not directory and entry.is_file(follow_symlinks=False):
                    return entry.path
    except OSError:
        return None
    return None


def trusted_relative_file(parent: str, relative_path: str, child: TrustedChild) -> str | None:
    """Resolve a nested regular file using names returned by directory scans."""
    parts = relative_path.replace("\\", "/").split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    current = parent
    for index, part in enumerate(parts):
        is_last = index == len(parts) - 1
        resolved = child(current, part, directory=not is_last)
        if resolved is None:
            return None
        current = resolved
    return current


def refresh_mods_root(
    state: RootState, default_root: Callable[[], str], logger: logging.Logger
) -> None:
    """
    显式指定的目录始终固定，创建失败时向调用方报告，禁止回退到其它库。
    未指定目录时：优先采用有效的 XCAGI_MODS_ROOT / XCAGI_MODS_DIR；
    若当前路径不存在则重新 default_root()。
    避免进程早期 import 顺序或 cwd 导致单例锁死在空目录，之后即使用户改环境变量也无法加载。
    """
    if state._explicit_mods_root:
        os.makedirs(state.mods_root, exist_ok=True)
        return
    env_raw = (os.environ.get("XCAGI_MODS_ROOT") or os.environ.get("XCAGI_MODS_DIR") or "").strip()
    if env_raw:
        p = os.path.abspath(env_raw)
        if os.path.isdir(p):
            if state.mods_root != p:
                logger.info(
                    "[ModManager] Updating mods_root from env: %s -> %s", state.mods_root, p
                )
                state.mods_root = p
                state._ensure_attempts = 0
            return
        logger.warning(
            "[ModManager] XCAGI_MODS_ROOT / XCAGI_MODS_DIR is set but not a directory: %s (keeping %s)",
            p,
            state.mods_root,
        )
    if not os.path.isdir(state.mods_root):
        fb = default_root()
        if fb != state.mods_root:
            logger.warning(
                "[ModManager] mods_root was missing or invalid (%s), re-resolved -> %s",
                state.mods_root,
                fb,
            )
            state.mods_root = fb
            state._ensure_attempts = 0
