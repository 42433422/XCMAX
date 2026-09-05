"""Refresh already installed industry packages while retaining recoverable backups."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def refresh_installed_industry_mods_from_bundle(
    *,
    mods_root: str | Path | None = None,
) -> list[dict[str, str]]:
    """Atomically refresh installed official industry Mods from the desktop bundle.

    Only an already-installed open industry Mod is refreshed. Unselected industry
    packages are left in the read-only seed pool, and every replaced copy is
    archived outside the active Mods directory for recovery.
    """
    from app.infrastructure.mods.mod_manager import get_mod_manager
    from app.mod_sdk import industry_seed
    from app.mod_sdk.edition_policy import refresh_bundled_mod

    mm = get_mod_manager()
    root = Path(mods_root or mm.mods_root)
    pool = industry_seed.bundled_industry_seeds_dir()
    if pool is None or not root.is_dir():
        return []

    results: list[dict[str, str]] = []
    cache_changed = False
    for mod_id in industry_seed.open_industry_seed_mod_ids():
        dst = industry_seed._existing_mod_directory(str(root), mod_id)
        if dst is None:
            continue
        src = industry_seed._resolve_seed_source(mod_id, pool)
        if src is None:
            results.append(
                {
                    "mod_id": mod_id,
                    "status": "missing",
                    "message": f"not in industry seed pool: {pool / mod_id}",
                }
            )
            continue
        try:
            status, message = refresh_bundled_mod(src, dst, root)
            cache_changed = cache_changed or status == "refreshed"
            results.append({"mod_id": mod_id, "status": status, "message": message})
        except OSError:
            logger.exception("refresh installed industry seed %s failed", mod_id)
            results.append(
                {"mod_id": mod_id, "status": "error", "message": "industry seed refresh failed"}
            )
    if cache_changed:
        mm.invalidate_scan_cache()
    return results
