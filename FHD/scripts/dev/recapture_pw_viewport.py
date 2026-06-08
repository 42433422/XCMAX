#!/usr/bin/env python3
"""按 manifest 重拍 P-W 全部页为 1280×720 视口 PNG。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("MODSTORE_DEPLOY_ROOT", "/root/modstore-git/MODstore_deploy"))
sys.path.insert(0, str(ROOT))


async def main() -> None:
    from modstore_server.daily_digest_surface_audit import (
        _base_url,
        _capture_one,
        _inject_market_auth,
        _login_surface_audit_sync,
        _path_needs_market_auth,
        _save_dir,
        build_surface_targets,
    )

    auth = _login_surface_audit_sync()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = _save_dir(day)
    if out_dir is None:
        raise SystemExit("save dir unavailable")

    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = manifest.get("results") if isinstance(manifest.get("results"), list) else []
    targets = {(t.lane, t.path): t for t in build_surface_targets()}
    site_base = _base_url().rstrip("/")

    from playwright.async_api import async_playwright

    updated = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for row in rows:
            if row.get("lane") != "P-W":
                continue
            url = str(row.get("url") or "").strip()
            if not url:
                continue
            path = url[len(site_base) :] if url.startswith(site_base) else url
            saved = str(row.get("screenshot_saved") or "").strip()
            if not saved:
                continue
            save_path = Path(saved)
            if not save_path.is_file():
                save_path = out_dir / Path(saved).name
            target = targets.get(("P-W", path))
            prepare = (target.prepare if target else None) or row.get("prepare") or ""
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                ignore_https_errors=True,
            )
            if auth and _path_needs_market_auth(path):
                await _inject_market_auth(ctx, auth)
            page = await ctx.new_page()
            cap = await _capture_one(
                page,
                url=url,
                viewport="desktop",
                timeout_ms=60_000,
                save_path=save_path,
                prepare=str(prepare or ""),
            )
            await ctx.close()
            row.update(
                {
                    "status": cap.get("status"),
                    "title": cap.get("title"),
                    "viewport": "desktop",
                    "error": cap.get("error"),
                    "screenshot_saved": str(save_path),
                }
            )
            updated += 1
            from PIL import Image

            sz = Image.open(save_path).size if save_path.is_file() else (0, 0)
            print(row.get("name"), sz, save_path.name, flush=True)
        await browser.close()

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE P-W viewport", updated)


if __name__ == "__main__":
    asyncio.run(main())
