"""Read-only extension and blueprint inspection for authoring routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List

import httpx

from modman.blueprint_scan import scan_fastapi_router_routes
from modman.manifest_util import (
    folder_name_must_match_id,
    read_manifest,
    validate_manifest_dict,
)
from modman.surface_bundle import load_bundled_extension_surface
from modstore_server.authoring import slim_openapi_paths
from modstore_server.infrastructure import library_paths


def extension_surface(merge_host: bool = False) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "ok": True,
        "bundled": load_bundled_extension_surface(),
        "host_openapi": None,
        "host_openapi_error": None,
    }
    if not merge_host:
        return result
    base = library_paths.resolved_xcagi_backend_url(library_paths.cfg()).rstrip("/")
    url = f"{base}/openapi.json"
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(url)
        if response.status_code >= 400:
            result["host_openapi_error"] = f"HTTP {response.status_code} from {url}"
        else:
            spec = response.json()
            routes = slim_openapi_paths(spec if isinstance(spec, dict) else {})
            result["host_openapi"] = {
                "base_url": base,
                "openapi_url": url,
                "route_count": len(routes),
                "routes": routes,
            }
    except httpx.RequestError:
        result["host_openapi_error"] = "宿主 OpenAPI 暂时不可用"
    except json.JSONDecodeError:
        result["host_openapi_error"] = "宿主 openapi.json 不是有效 JSON"
    return result


def blueprint_routes(mod_dir: Path) -> Dict[str, Any]:
    for relative in ("backend/blueprints.py", "blueprints.py"):
        path = mod_dir / relative
        if path.is_file():
            return {
                "ok": True,
                "file": relative,
                "routes": scan_fastapi_router_routes(path),
            }
    return {
        "ok": True,
        "file": None,
        "routes": [],
        "hint": "未找到 backend/blueprints.py 或根目录 blueprints.py（FastAPI 路由扫描）",
    }


def authoring_summary(
    mod_dir: Path,
    mod_id: str,
    user: Any,
    session_factory: Callable[..., Any],
) -> Dict[str, Any]:
    data, error = read_manifest(mod_dir)
    if error or not data:
        raise ValueError(error or "manifest 无效")
    warnings = validate_manifest_dict(data)
    folder_warning = folder_name_must_match_id(mod_dir, data)
    if folder_warning:
        warnings = list(warnings) + [folder_warning]
    blueprint_file: str | None = None
    blueprint_rows: List[Dict[str, Any]] = []
    for relative in ("backend/blueprints.py", "blueprints.py"):
        path = mod_dir / relative
        if path.is_file():
            blueprint_file = relative
            blueprint_rows = scan_fastapi_router_routes(path)
            break
    from modstore_server.mod_scaffold_runner import analyze_mod_employee_readiness

    with session_factory() as database:
        readiness = analyze_mod_employee_readiness(database, user, mod_dir)
    return {
        "ok": True,
        "id": mod_id,
        "manifest_backend": data.get("backend") if isinstance(data.get("backend"), dict) else {},
        "manifest_frontend": data.get("frontend") if isinstance(data.get("frontend"), dict) else {},
        "validation_ok": len(warnings) == 0,
        "warnings": warnings,
        "blueprint_file": blueprint_file,
        "blueprint_routes": blueprint_rows,
        "employee_readiness": readiness,
    }
