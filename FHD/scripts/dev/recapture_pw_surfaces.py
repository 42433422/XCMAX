#!/usr/bin/env python3
"""重拍 P-W 营销站截图（修复中文方框后更新 manifest）。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("MODSTORE_DEPLOY_ROOT", "/root/modstore-git/MODstore_deploy"))
sys.path.insert(0, str(ROOT))

from modstore_server.daily_digest_surface_audit import (  # noqa: E402
    _base_url,
    _capture_one,
    _save_dir,
    build_surface_targets,
)


async def main() -> None:
    from playwright.async_api import async_playwright

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = _save_dir(day)
    if out_dir is None:
        raise SystemExit("save dir unavailable")
    targets = [t for t in build_surface_targets() if t.lane == "P-W"]
    results: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for i, t in enumerate(targets):
            url = _base_url().rstrip("/") + t.path
            slug = f"{i:03d}_{t.lane}_{t.name}".replace("/", "-")
            save = out_dir / f"{slug}.png"
            row = await _capture_one(
                page,
                url=url,
                viewport=t.viewport,
                timeout_ms=60_000,
                save_path=save,
                prepare=t.prepare,
            )
            row["lane"] = t.lane
            row["lane_label"] = t.lane_label
            row["name"] = t.name
            results.append(row)
            print(i, t.name, row.get("status"), save.name, flush=True)
        await browser.close()

    manifest_path = out_dir / "manifest.json"
    manifest: dict = {"results": []}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    kept = [r for r in manifest.get("results", []) if r.get("lane") != "P-W"]
    manifest["results"] = kept + results
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE P-W", len(results), "manifest total", len(manifest["results"]))


if __name__ == "__main__":
    asyncio.run(main())
