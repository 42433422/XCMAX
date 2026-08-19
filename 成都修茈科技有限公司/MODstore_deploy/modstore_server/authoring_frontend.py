"""Frontend artifact regeneration for an existing authored MOD."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

from modman.manifest_util import read_manifest, save_manifest_validated
from modstore_server.application.catalog import CatalogShellService
from modstore_server.mod_snapshots import capture_manifest_snapshot


def regenerate_frontend(mod_dir: Path, mod_id: str, brief: str) -> Dict[str, Any]:
    manifest, error = read_manifest(mod_dir)
    if not manifest or error:
        raise ValueError(error or "无法读取 manifest")
    try:
        snapshot = capture_manifest_snapshot(
            mod_dir, f"重新生成前端前 {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    except Exception:  # noqa: BLE001 - snapshot failure must not block regeneration
        snapshot = None
    spec = CatalogShellService.frontend_spec_for_existing_mod(mod_dir, manifest, brief)
    mod_name = str(manifest.get("name") or mod_id)
    frontend = manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {}
    menu = frontend.get("menu")
    if not isinstance(menu, list) or not menu:
        menu = [
            {
                "id": f"{mod_id}-home",
                "label": mod_name,
                "icon": "fa-cube",
                "path": spec["entry_path"],
            }
        ]
    frontend.update(
        {
            "routes": frontend.get("routes") or "frontend/routes",
            "menu": menu,
            "pro_entry_path": spec["entry_path"],
            "app": "config/frontend_spec.json",
        }
    )
    manifest["frontend"] = frontend
    config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
    config["frontend_spec"] = "config/frontend_spec.json"
    manifest["config"] = config
    warnings = save_manifest_validated(mod_dir, manifest)
    from modstore_server.mod_scaffold_runner import (
        render_frontend_routes_js,
        render_generated_home_vue,
    )

    (mod_dir / "config").mkdir(parents=True, exist_ok=True)
    (mod_dir / "frontend" / "views").mkdir(parents=True, exist_ok=True)
    (mod_dir / "config" / "frontend_spec.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (mod_dir / "frontend" / "routes.js").write_text(
        render_frontend_routes_js(mod_id, mod_name, spec["entry_path"]), encoding="utf-8"
    )
    (mod_dir / "frontend" / "views" / "HomeView.vue").write_text(
        render_generated_home_vue(mod_id, mod_name, spec), encoding="utf-8"
    )
    return {
        "ok": True,
        "frontend_spec": spec,
        "entry_path": spec["entry_path"],
        "snapshot": snapshot,
        "manifest_warnings": warnings,
        "files": ["config/frontend_spec.json", "frontend/routes.js", "frontend/views/HomeView.vue"],
    }
