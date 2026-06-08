#!/usr/bin/env python3
"""Add /admin/surface-audit/page — return one PNG b64 by lane index."""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/xcmax_admin_api.py"
)

ENDPOINT = '''

@router.get("/admin/surface-audit/page", response_model=None)
async def xcmax_surface_audit_page(
    lane: str = Query("P-W"),
    index: int = Query(0, ge=0),
) -> dict[str, Any]:
    """单页 PNG（画廊翻页按需拉取，避免 lane 全量 base64）。"""
    import base64
    import json as _json
    from datetime import datetime, timezone

    lane = (lane or "P-W").strip()
    try:
        from modstore_server.daily_digest_surface_audit import _save_dir
    except ImportError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=501)

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    save_root = _save_dir(day)
    if save_root is None or not save_root.is_dir():
        return JSONResponse({"success": False, "message": "今日尚无截图目录"}, status_code=404)

    manifest_path = save_root / "manifest.json"
    rows: list[dict[str, Any]] = []
    if manifest_path.is_file():
        try:
            manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
            raw_rows = manifest.get("results") if isinstance(manifest.get("results"), list) else []
            rows = [r for r in raw_rows if isinstance(r, dict) and r.get("lane") == lane]
        except Exception as exc:
            return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    else:
        for png in sorted(save_root.glob("*.png")):
            if f"_{lane}_" not in png.name:
                continue
            slug_parts = png.stem.split("_", 2)
            name = slug_parts[2] if len(slug_parts) >= 3 else png.stem
            rows.append({"lane": lane, "name": name, "screenshot_saved": str(png)})

    if index >= len(rows):
        return JSONResponse({"success": False, "message": "index out of range"}, status_code=404)

    row = rows[index]
    thumb_b64 = ""
    saved = str(row.get("screenshot_saved") or "").strip()
    if saved:
        p = Path(saved)
        if p.is_file():
            raw = p.read_bytes()
            if len(raw) <= 1_600_000:
                thumb_b64 = base64.b64encode(raw).decode("ascii")

    return {
        "success": True,
        "data": {
            "lane": lane,
            "index": index,
            "total": len(rows),
            "name": row.get("name"),
            "url": row.get("url"),
            "status": row.get("status"),
            "title": row.get("title"),
            "viewport": row.get("viewport"),
            "screenshot_b64": thumb_b64,
            "screenshot_saved": saved,
        },
    }
'''

text = TARGET.read_text(encoding="utf-8")
if '"/admin/surface-audit/page"' in text:
    print("already patched", TARGET)
    raise SystemExit(0)

anchor = '\n__all__ = ["router"]'
if anchor not in text:
    raise SystemExit("__all__ anchor not found")

text = text.replace(anchor, ENDPOINT.strip() + anchor, 1)
TARGET.write_text(text, encoding="utf-8")
print("patched", TARGET)
