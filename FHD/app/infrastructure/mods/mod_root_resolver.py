from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def default_mods_root() -> str:
    """Resolve the source, packaged, or explicitly configured mods root."""
    logger.debug("[default_mods_root] resolving mods root, cwd=%s", os.getcwd())
    env = (os.environ.get("XCAGI_MODS_ROOT") or os.environ.get("XCAGI_MODS_DIR") or "").strip()
    if env:
        path = os.path.abspath(env)
        if os.path.isdir(path):
            return path
        logger.warning("configured mods root is not a directory: %s", path)

    file_here = os.path.abspath(__file__)
    package_root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(file_here)))), "mods"
    )
    if os.path.isdir(package_root):
        return package_root

    cwd_root = os.path.join(os.getcwd(), "mods")
    if os.path.isdir(cwd_root):
        return cwd_root

    current = os.path.abspath(os.getcwd())
    for _ in range(8):
        candidate = os.path.join(current, "mods")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    logger.warning(
        "no mods directory found; using package-relative path %s; set XCAGI_MODS_ROOT",
        package_root,
    )
    return package_root
