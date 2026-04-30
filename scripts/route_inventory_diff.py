#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导出当前 FastAPI 路由集合（规范化路径）。

历史：曾对比归档 Flask ``url_map``；Flask 已从运行时移除，本脚本仅统计 FastAPI。

用法（在项目根目录）::

    python scripts/route_inventory_diff.py
    python scripts/route_inventory_diff.py --json-out scripts/output/route_inventory.json
"""

from __future__ import annotations

import argparse
import json
import sys
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
    from starlette.routing import Mount

    try:
        from fastapi.routing import APIRoute
    except ImportError:
        from starlette.routing import APIRoute  # type: ignore

    from app.utils.openapi_path import normalize_path_template

    out: set[tuple[str, str]] = set()

    def walk(routes, prefix: str = "") -> None:
        for r in routes:
            if isinstance(r, APIRoute):
                p = _norm_path(normalize_path_template(prefix + r.path))
                for m in r.methods or ():
                    if m in ("HEAD", "OPTIONS", "TRACE"):
                        continue
                    out.add((_norm_method(m), p))
            elif isinstance(r, Mount):
                walk(r.routes, prefix + str(r.path).rstrip("/"))

    walk(app.routes)
    return out


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

    from app.fastapi_app import create_fastapi_app

    app = create_fastapi_app()
    pairs = _fastapi_route_pairs(app)
    sorted_pairs = sorted(pairs)

    report = {
        "fastapi_route_count": len(pairs),
        "routes_sample": sorted_pairs[:80],
    }
    report_full = {**report, "routes": sorted_pairs}

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report_full, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Wrote {args.json_out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
