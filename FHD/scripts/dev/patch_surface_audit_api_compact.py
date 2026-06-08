#!/usr/bin/env python3
"""Patch MODstore surface-audit/lane: compact=1 returns one preview PNG b64."""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/xcmax_admin_api.py"
)

HELPERS = '''

def _pick_hero_page_index(pages: list) -> int:
    for i, row in enumerate(pages):
        name = str((row or {}).get("name") or "")
        if "首页" in name or name.lower() in {"home", "index"}:
            return i
    return 0


def _attach_screenshot_b64(pages: list, *, compact: bool) -> None:
    import base64

    hero_i = _pick_hero_page_index(pages) if compact else -1
    for i, row in enumerate(pages):
        if not isinstance(row, dict):
            continue
        include = (not compact) or (i == hero_i)
        thumb_b64 = ""
        saved = str(row.get("screenshot_saved") or "").strip()
        if include and saved:
            p = Path(saved)
            if p.is_file():
                raw = p.read_bytes()
                if len(raw) <= 1_600_000:
                    thumb_b64 = base64.b64encode(raw).decode("ascii")
        row["screenshot_b64"] = thumb_b64
        if compact and i == hero_i and thumb_b64:
            row["preview_only"] = True
'''

text = TARGET.read_text(encoding="utf-8")

if "_attach_screenshot_b64" not in text:
    anchor = '@router.get("/admin/surface-audit/lane", response_model=None)'
    if anchor not in text:
        raise SystemExit("anchor not found")
    text = text.replace(anchor, HELPERS.strip() + "\n\n\n" + anchor, 1)

if 'compact: bool = Query(True)' not in text:
    text = text.replace(
        '    refresh: bool = Query(False),\n) -> dict[str, Any]:',
        '    refresh: bool = Query(False),\n    compact: bool = Query(True),\n) -> dict[str, Any]:',
        1,
    )

old_inner = '''        pages: list[dict[str, Any]] = []
        for row in report.get("results") if isinstance(report.get("results"), list) else []:
            if row.get("lane") != lane:
                continue
            thumb_b64 = ""
            saved = str(row.get("screenshot_saved") or "").strip()
            if saved:
                p = Path(saved)
                if p.is_file():
                    raw = p.read_bytes()
                    if len(raw) <= 1_600_000:
                        thumb_b64 = base64.b64encode(raw).decode("ascii")
            pages.append(
                {
                    "name": row.get("name"),
                    "url": row.get("url"),
                    "status": row.get("status"),
                    "title": row.get("title"),
                    "viewport": row.get("viewport"),
                    "console_errors": row.get("console_errors") or [],
                    "error": row.get("error"),
                    "screenshot_b64": thumb_b64,
                    "screenshot_saved": saved,
                }
            )'''

new_inner = '''        pages: list[dict[str, Any]] = []
        for row in report.get("results") if isinstance(report.get("results"), list) else []:
            if row.get("lane") != lane:
                continue
            pages.append(
                {
                    "name": row.get("name"),
                    "url": row.get("url"),
                    "status": row.get("status"),
                    "title": row.get("title"),
                    "viewport": row.get("viewport"),
                    "console_errors": row.get("console_errors") or [],
                    "error": row.get("error"),
                    "screenshot_saved": str(row.get("screenshot_saved") or "").strip(),
                }
            )
        _attach_screenshot_b64(pages, compact=compact)'''

if old_inner not in text:
    if "_attach_screenshot_b64(pages, compact=compact)" in text:
        print("inner already patched")
    else:
        raise SystemExit("inner block not found")
else:
    text = text.replace(old_inner, new_inner, 1)

text = text.replace(
    "async def _lane_payload(report: dict[str, Any], *, cached: bool) -> dict[str, Any]:",
    "async def _lane_payload(report: dict[str, Any], *, cached: bool, compact: bool = True) -> dict[str, Any]:",
    1,
)

text = text.replace(
    'return {"success": True, "data": await _lane_payload(report, cached=False)}',
    'return {"success": True, "data": await _lane_payload(report, cached=False, compact=compact)}',
)
text = text.replace(
    'return {"success": True, "data": await _lane_payload(report_stub, cached=True)}',
    'return {"success": True, "data": await _lane_payload(report_stub, cached=True, compact=compact)}',
)

glob_b64 = '''        raw = png.read_bytes()
        thumb_b64 = base64.b64encode(raw).decode("ascii") if len(raw) <= 1_600_000 else ""
        pages.append(
            {
                "lane": lane,
                "name": name,
                "url": f"{base}{path_guess}",
                "status": 200,
                "title": name,
                "viewport": "desktop",
                "console_errors": [],
                "error": None,
                "screenshot_b64": thumb_b64,
                "screenshot_saved": str(png),
            }
        )'''

glob_no_b64 = '''        pages.append(
            {
                "lane": lane,
                "name": name,
                "url": f"{base}{path_guess}",
                "status": 200,
                "title": name,
                "viewport": "desktop",
                "console_errors": [],
                "error": None,
                "screenshot_saved": str(png),
            }
        )'''

if glob_b64 in text:
    text = text.replace(glob_b64, glob_no_b64, 1)

TARGET.write_text(text, encoding="utf-8")
print("patched", TARGET)
