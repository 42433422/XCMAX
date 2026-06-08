#!/usr/bin/env python3
"""P-W 收编服务器全部网页；manifest 中 P-S 行并入 P-W（去重）。"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/daily_digest_surface_audit.py"
)

OLD_LOOP = '''    for name, path in _PS_PUBLIC_PAGES:
        out.append(SurfaceTarget("P-S", "软件 P-S", name, path, "desktop"))

    for tab_name, tab_id in _AI_STORE_TABS:
        out.append(
            SurfaceTarget(
                "P-S",
                "软件 P-S",
                tab_name,
                "/market/ai-store",
                "desktop",
                prepare=f"ai_store_tab:{tab_id}",
            )
        )

    for item in catalog:
        cid = item.get("id")
        if cid is None:
            continue
        label = str(item.get("name") or item.get("pkg_id") or cid).strip()
        out.append(
            SurfaceTarget(
                "P-S",
                "软件 P-S",
                f"AI商品-{label}",
                f"/market/catalog/{cid}",
                "desktop",
            )
        )'''

NEW_LOOP = '''    for name, path in _PS_PUBLIC_PAGES:
        out.append(SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))

    for tab_name, tab_id in _AI_STORE_TABS:
        out.append(
            SurfaceTarget(
                "P-W",
                "网站 P-W",
                tab_name,
                "/market/ai-store",
                "desktop",
                prepare=f"ai_store_tab:{tab_id}",
            )
        )

    for item in catalog:
        cid = item.get("id")
        if cid is None:
            continue
        label = str(item.get("name") or item.get("pkg_id") or cid).strip()
        out.append(
            SurfaceTarget(
                "P-W",
                "网站 P-W",
                f"AI商品-{label}",
                f"/market/catalog/{cid}",
                "desktop",
            )
        )'''

text = TARGET.read_text(encoding="utf-8")
if 'SurfaceTarget("P-W", "网站 P-W", tab_name' in text:
    print("build_surface_targets already patched")
else:
    if OLD_LOOP not in text:
        raise SystemExit("loop block not found")
    text = text.replace(OLD_LOOP, NEW_LOOP, 1)
    TARGET.write_text(text, encoding="utf-8")
    print("patched build_surface_targets", TARGET)

# manifest merge
for root in (
    Path("/root/成都修茈科技有限公司/MODstore_deploy/playwright-report/digest-surfaces"),
    Path("/root/modstore-git/MODstore_deploy/playwright-report/digest-surfaces"),
):
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    manifest_path = root / day / "manifest.json"
    if not manifest_path.is_file():
        continue
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = data.get("results") if isinstance(data.get("results"), list) else []
    pw_names = {str(r.get("name") or "") for r in rows if r.get("lane") == "P-W"}
    moved = 0
    for row in rows:
        if row.get("lane") != "P-S":
            continue
        name = str(row.get("name") or "")
        if name in pw_names:
            row["_merged_skip"] = True
            continue
        row["lane"] = "P-W"
        row["lane_label"] = "网站 P-W"
        pw_names.add(name)
        moved += 1
    data["results"] = [r for r in rows if not r.get("_merged_skip")]
    for r in data["results"]:
        r.pop("_merged_skip", None)
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    pw_n = sum(1 for r in data["results"] if r.get("lane") == "P-W")
    print("manifest", manifest_path, "moved", moved, "P-W total", pw_n)
    break
