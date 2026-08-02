from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def mod_is_installed_locally(manager: object, mod_id: str) -> bool:
    resolver = getattr(manager, "resolve_mod_directory", None)
    if callable(resolver):
        return bool(resolver(mod_id))
    mods_root = getattr(manager, "mods_root", None)
    if mods_root:
        return (Path(str(mods_root)) / mod_id).is_dir()
    return True


def skip_uninstalled_mod_api(manager: object, mod_id: str, retry_at: dict[str, float]) -> bool:
    if mod_is_installed_locally(manager, mod_id):
        return False
    retry_at.pop(mod_id, None)
    from app.runtime_integrity import clear_runtime_issue

    clear_runtime_issue(f"industry_mod:{mod_id}")
    logger.debug("entitled mod %s is not installed locally; skip API load", mod_id)
    return True
