"""Local installation predicates shared by Mod loading and mount policy."""

from __future__ import annotations

from pathlib import Path


def mod_is_installed_locally(manager: object, mod_id: str) -> bool:
    """Allow older adapters that cannot expose an installation directory."""
    resolver = getattr(manager, "resolve_mod_directory", None)
    if callable(resolver):
        return bool(resolver(mod_id))
    mods_root = getattr(manager, "mods_root", None)
    return (Path(str(mods_root)) / mod_id).is_dir() if mods_root else True


def filter_installed_mod_ids(manager: object, mod_ids: set[str]) -> set[str]:
    return {mod_id for mod_id in mod_ids if mod_is_installed_locally(manager, mod_id)}
