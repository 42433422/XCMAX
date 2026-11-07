#!/usr/bin/env python3
"""
导出当前配置完成注册后的 FastAPI 路由快照（规范化路径）。

同步装配宿主并等待 Mod 注册；不启动 lifespan 或业务后台任务。
请在隔离测试配置中运行：工厂会读取配置及已安装 Mod，不能用于证明线上接口无人调用。

用法（在项目根目录）::

    python scripts/route_inventory_diff.py
    python scripts/route_inventory_diff.py --json-out scripts/output/route_inventory.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _norm_method(m: str) -> str:
    return (m or "").upper()


def _norm_path(p: str) -> str:
    if not p or p == "/":
        return "/"
    return p.rstrip("/") or "/"


def _fastapi_route_pairs(app) -> set[tuple[str, str]]:
    from app.legacy.routes.openapi_route_compat import iter_effective_routes
    from app.utils.openapi_path import normalize_path_template

    return {
        (_norm_method(method), _norm_path(normalize_path_template(route.path)))
        for route in iter_effective_routes(app.routes)
        for method in route.methods or ()
        if _norm_method(method) not in {"HEAD", "OPTIONS", "TRACE"}
    }


def _mod_registration_failures() -> dict[str, list[str]]:
    from app.infrastructure.mods.mod_manager import get_mod_manager, is_mods_disabled

    if is_mods_disabled():
        return {}
    manager = get_mod_manager()
    return {
        phase: [str(item.get("mod_id") or "unknown") for item in failures]
        for phase, failures in (
            ("blueprint", manager.get_blueprint_failures()),
            ("load", manager.get_recent_load_failures()),
            ("manifest", manager.get_scan_manifest_errors()),
        )
        if failures
    }


def _build_app(*, timeout: float = 30.0):
    from app.fastapi_app import create_fastapi_app
    from app.fastapi_app.mod_startup import wait_for_background_mod_load

    previous = os.environ.get("XCAGI_DESKTOP_FAST_START")
    os.environ["XCAGI_DESKTOP_FAST_START"] = "0"
    try:
        app = create_fastapi_app(enable_docs=True, enable_cors=False)
        if not wait_for_background_mod_load(app, timeout=timeout):
            raise RuntimeError("Mod route registration timed out; inventory is incomplete")
        if (
            getattr(app.state, "deferred_routes_pending", False)
            or getattr(app.state, "mods_deferred_bootstrap", False)
            or getattr(app.state, "mods_background_load_error", None)
            or not getattr(app.state, "mods_full_load_done", False)
        ):
            raise RuntimeError("Route registration is incomplete; refusing a partial inventory")
        app.state.route_inventory_mod_failures = _mod_registration_failures()
        return app
    finally:
        if previous is None:
            os.environ.pop("XCAGI_DESKTOP_FAST_START", None)
        else:
            os.environ["XCAGI_DESKTOP_FAST_START"] = previous


def _inventory_report(app) -> dict:
    from app.fastapi_routes.registry import detect_app_route_conflicts

    pairs = sorted(_fastapi_route_pairs(app))
    failures = [
        name
        for name, status in (getattr(app.state, "runtime_components", {}) or {}).items()
        if not status.get("ok")
    ]
    mod_failures = getattr(app.state, "route_inventory_mod_failures", {})
    return {
        "scope": "configured_startup_routes",
        "complete": not failures and not mod_failures,
        "failed_components": sorted(failures),
        "mod_registration_failures": mod_failures,
        "configuration": {
            key: os.environ.get(key, "")
            for key in (
                "XCAGI_EDITION",
                "XCAGI_DEFAULT_EDITION",
                "XCAGI_MINIMAL_EDITION",
                "XCAGI_GENERIC_EDITION",
                "XCAGI_PRODUCT_SKU",
                "XCAGI_DISABLE_MODS",
                "XCAGI_SKIP_LEGACY_COMPAT_ROUTES",
                "XCAGI_REGISTER_LEGACY_ROUTES",
            )
        },
        "limitations": [
            "No production usage evidence; only this configuration's mounted routes.",
            "Post-login entitlement mounts and independently deployed services are excluded.",
            "Conflict checks cover exact paths and static paths shadowed by parameters or ASGI mounts; parameter-to-parameter overlaps are not exhaustive.",
        ],
        "fastapi_route_count": len(pairs),
        "routes_sample": pairs[:80],
        "routes": pairs,
        "conflicts": [asdict(conflict) for conflict in detect_app_route_conflicts(app)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="List FastAPI routes (normalized paths)")
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write full report JSON to this path (parent dirs created).",
    )
    args = parser.parse_args()

    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    report = _inventory_report(_build_app())
    print(
        json.dumps({k: v for k, v in report.items() if k != "routes"}, indent=2, ensure_ascii=False)
    )
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {args.json_out}", file=sys.stderr)

    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
