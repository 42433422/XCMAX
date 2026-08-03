"""Runtime helpers for separately managed employee MOD packs."""

import json
import logging
import os
from collections.abc import Callable
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .artifact_constants import ARTIFACT_EMPLOYEE_PACK, normalize_artifact
from .missing_local_state import clear_mod_missing_locally

logger = logging.getLogger(__name__)


def is_installed_employee_pack(mod_manager: Any, pack_id: str) -> bool:
    """Check the separately managed ``mods/_employees`` store safely."""
    root = getattr(mod_manager, "mods_root", "")
    if not isinstance(root, (str, os.PathLike)):
        return False
    manifest_path = os.path.join(os.fspath(root), "_employees", pack_id, "manifest.json")
    if not os.path.isfile(manifest_path):
        return False
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(manifest, dict)
        and normalize_artifact(manifest) == ARTIFACT_EMPLOYEE_PACK
        and str(manifest.get("id") or pack_id).strip() == pack_id
    )


def ensure_employee_pack_api_ready(
    mod_manager: Any,
    pack_id: str,
    *,
    registered_pack_ids: set[str],
    register_routes: Callable[[Any, Any, str], bool],
) -> bool | None:
    """Mount an installed entitled employee pack, or return ``None`` when unrelated."""
    if not is_installed_employee_pack(mod_manager, pack_id):
        return None
    clear_mod_missing_locally(pack_id)
    from app.runtime_integrity import clear_runtime_issue

    clear_runtime_issue(f"industry_mod:{pack_id}")
    if pack_id in registered_pack_ids:
        return True
    try:
        from app.fastapi_app import get_fastapi_app

        app = get_fastapi_app()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("[ModManager] employee pack %s cannot get app: %s", pack_id, exc)
        return False
    return register_routes(app, mod_manager, pack_id)
