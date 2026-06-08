#!/usr/bin/env python3
"""补拍 P-W 新增页（AI 市场 / 软件下载）并写入 manifest。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("MODSTORE_DEPLOY_ROOT", "/root/modstore-git/MODstore_deploy"))
sys.path.insert(0, str(ROOT))

NEW_PAGES = [
    ("AI 市场", "/market/ai-store"),
    ("软件下载", "/market/workbench/download"),
]


async def main() -> None:
    from modstore_server.daily_digest_surface_audit import (
        _base_url,
        _capture_one,
        _save_dir,
    )

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = _save_dir(day)
    if out_dir is None:
        raise SystemExit("save dir unavailable")

    manifest_path = out_dir / "manifest.json"
    manifest: dict = {"results": []}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    kept = [
        r
        for r in (manifest.get("results") or [])
        if not (r.get("lane") == "P-W" and r.get("name") in {n for n, _ in NEW_PAGES})
    ]
    start = len([r for r in kept if r.get("lane") == "P-W"])

    from playwright.async_api import async_playwright

    new_rows: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for i, (name, path) in enumerate(NEW_PAGES):
            url = _base_url().rstrip("/") + path
            slug = f"{start + i:03d}_P-W_{name}".replace("/", "-")
            save = out_dir / f"{slug}.png"
            row = await _capture_one(
                page,
                url=url,
                viewport="desktop",
                timeout_ms=60_000,
                save_path=save,
                prepare="",
            )
            row["lane"] = "P-W"
            row["lane_label"] = "网站 P-W"
            row["name"] = name
            row["url"] = url
            new_rows.append(row)
            print(name, row.get("status"), save.name, flush=True)
        await browser.close()

    manifest["results"] = kept + new_rows
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE added", len(new_rows), "P-W total", len([r for r in manifest["results"] if r.get("lane") == "P-W"]))


if __name__ == "__main__":
    asyncio.run(main())
