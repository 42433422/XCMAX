#!/usr/bin/env python3
"""Add /admin/surface-audit/image — stream one PNG file (no base64 JSON)."""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/xcmax_admin_api.py"
)

ENDPOINT = '''

@router.get("/admin/surface-audit/image")
async def xcmax_surface_audit_image(
    lane: str = Query("P-W"),
    index: int = Query(0, ge=0),
):
    """单页 PNG 文件流（画廊/终端 img src 直链）。"""
    import json as _json
    from datetime import datetime, timezone

    from fastapi.responses import FileResponse, Response

    lane = (lane or "P-W").strip()
    try:
        from modstore_server.daily_digest_surface_audit import _save_dir
    except ImportError as exc:
        return Response(content=str(exc), status_code=501, media_type="text/plain")

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    save_root = _save_dir(day)
    if save_root is None or not save_root.is_dir():
        return Response(content="no save dir", status_code=404, media_type="text/plain")

    manifest_path = save_root / "manifest.json"
    rows: list[dict] = []
    if manifest_path.is_file():
        try:
            manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
            raw_rows = manifest.get("results") if isinstance(manifest.get("results"), list) else []
            rows = [r for r in raw_rows if isinstance(r, dict) and r.get("lane") == lane]
        except Exception as exc:
            return Response(content=str(exc), status_code=500, media_type="text/plain")
    else:
        for png in sorted(save_root.glob("*.png")):
            if f"_{lane}_" not in png.name:
                continue
            rows.append({"screenshot_saved": str(png)})

    if index >= len(rows):
        return Response(content="index out of range", status_code=404, media_type="text/plain")

    saved = str(rows[index].get("screenshot_saved") or "").strip()
    if not saved:
        return Response(content="no screenshot", status_code=404, media_type="text/plain")
    p = Path(saved)
    if not p.is_file():
        return Response(content="file missing", status_code=404, media_type="text/plain")
    return FileResponse(p, media_type="image/png", filename=p.name)
'''

text = TARGET.read_text(encoding="utf-8")
if '"/admin/surface-audit/image"' in text:
    print("already patched", TARGET)
    raise SystemExit(0)

anchor = '\n__all__ = ["router"]'
if anchor not in text:
    raise SystemExit("__all__ anchor not found")
text = text.replace(anchor, ENDPOINT.strip() + anchor, 1)
TARGET.write_text(text, encoding="utf-8")
print("patched", TARGET)
