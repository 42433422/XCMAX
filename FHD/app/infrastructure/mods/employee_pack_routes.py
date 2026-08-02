"""Disk scan for employee-pack route registration."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from app.infrastructure.mods.artifact_constants import ARTIFACT_EMPLOYEE_PACK, normalize_artifact


def register_employee_pack_routes_from_root(
    app: Any, manager: Any, root: str, register_routes: Callable[[Any, Any, str], bool]
) -> None:
    employee_root = os.path.join(root, "_employees")
    if not os.path.isdir(employee_root):
        return
    for name in sorted(os.listdir(employee_root)):
        pack_path = os.path.join(employee_root, name)
        manifest_path = os.path.join(pack_path, "manifest.json")
        if not os.path.isdir(pack_path) or not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if normalize_artifact(manifest) == ARTIFACT_EMPLOYEE_PACK:
            pack_id = str(manifest.get("id") or name).strip()
            if pack_id:
                register_routes(app, manager, pack_id)
