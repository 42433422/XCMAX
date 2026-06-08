#!/usr/bin/env python3
"""重拍需登录的 /market/* 页（注入 modstore_token 后更新 manifest PNG）。"""
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
    if not auth:
        raise SystemExit("market login failed — set MODSTORE_SURFACE_AUDIT_USER/PASSWORD")

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = _save_dir(day)
    if out_dir is None:
        raise SystemExit("save dir unavailable")

    manifest_path = out_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"manifest missing: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = manifest.get("results") if isinstance(manifest.get("results"), list) else []
    targets = {(t.lane, t.path): t for t in build_surface_targets()}

    from playwright.async_api import async_playwright

    updated = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for row in rows:
            path = str(row.get("url") or "").replace(_base_url().rstrip("/"), "")
            if not path.startswith("/"):
                # row.url may be full URL
                base = _base_url().rstrip("/")
                full = str(row.get("url") or "")
                path = full[len(base) :] if full.startswith(base) else path
            lane = str(row.get("lane") or "").strip()
            if not _path_needs_market_auth(path):
                continue
            saved = str(row.get("screenshot_saved") or "").strip()
            if not saved:
                continue
            save_path = Path(saved)
            if not save_path.is_file():
                save_path = out_dir / Path(saved).name
            target = targets.get((lane, path))
            viewport = (target.viewport if target else None) or row.get("viewport") or "desktop"
            prepare = (target.prepare if target else None) or row.get("prepare") or ""
            url = f"{_base_url().rstrip('/')}{path}"
            ctx_kwargs: dict = {"ignore_https_errors": True}
            if viewport == "mobile":
                ctx_kwargs.update(
                    {
                        "viewport": {"width": 390, "height": 844},
                        "is_mobile": True,
                        "has_touch": True,
                    }
                )
            else:
                ctx_kwargs["viewport"] = {"width": 1280, "height": 720}
            context = await browser.new_context(**ctx_kwargs)
            await _inject_market_auth(context, auth)
            page = await context.new_page()
            cap = await _capture_one(
                page,
                url=url,
                viewport=str(viewport),
                timeout_ms=60_000,
                save_path=save_path,
                prepare=str(prepare or ""),
            )
            await context.close()
            row.update(
                {
                    "status": cap.get("status"),
                    "title": cap.get("title"),
                    "console_errors": cap.get("console_errors"),
                    "error": cap.get("error"),
                    "screenshot_saved": str(save_path),
                }
            )
            updated += 1
            print(row.get("name"), cap.get("title"), save_path.name, flush=True)
        await browser.close()

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE updated", updated, "rows")


if __name__ == "__main__":
    asyncio.run(main())
