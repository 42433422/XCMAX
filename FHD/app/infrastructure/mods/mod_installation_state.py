"""Local installation predicates shared by Mod loading and mount policy."""

from __future__ import annotations

import os
import re

_MOD_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def _is_safe_mod_id(mod_id: str) -> bool:
    """Keep a MOD identifier from being interpreted as a filesystem path."""
    return bool(_MOD_ID_PATTERN.fullmatch(mod_id)) and mod_id not in {".", ".."}


def mod_is_installed_locally(manager: object, mod_id: str) -> bool:
    """Allow older adapters that cannot expose an installation directory."""
    if not _is_safe_mod_id(mod_id):
        return False
    resolver = getattr(manager, "resolve_mod_directory", None)
    if callable(resolver):
        return bool(resolver(mod_id))
    mods_root = getattr(manager, "mods_root", None)
    if not mods_root:
        return True
    # Normalize both paths before comparing them, so traversal segments and
    # symlinks cannot escape the trusted MOD root.
    root = os.path.realpath(str(mods_root))
    candidate = os.path.realpath(os.path.join(root, mod_id))
    root_prefix = root if root.endswith(os.sep) else f"{root}{os.sep}"
    if not candidate.startswith(root_prefix):
        return False
    return os.path.isdir(candidate)


def filter_installed_mod_ids(manager: object, mod_ids: set[str]) -> set[str]:
    return {mod_id for mod_id in mod_ids if mod_is_installed_locally(manager, mod_id)}
