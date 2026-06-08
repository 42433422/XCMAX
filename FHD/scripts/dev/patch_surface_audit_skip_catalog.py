#!/usr/bin/env python3
"""去掉 surface-audit 逐 catalog 商品详情截图，仅保留 AI 市场 Tab 等聚合页。"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/daily_digest_surface_audit.py"
)

MARKER = "MODSTORE_SURFACE_AUDIT_SKIP_CATALOG"

CATALOG_LOOP = re.compile(
    r"\n    for item in catalog:.*?\n        \)\n",
    re.S,
)

DOC_OLD = '    """全量：P-W 营销静态 + P-S/P-App AI 市场公开页与全部 catalog 详情。"""'
DOC_NEW = '    """全量：P-W 营销静态 + AI 市场 Tab；不逐 catalog 商品详情截图。"""'

FETCH_OLD = "    catalog = _fetch_market_catalog_sync(base)"
FETCH_NEW = f"""    catalog: List[Dict[str, Any]] = []
    if (os.environ.get("{MARKER}", "1") or "").strip().lower() not in ("0", "false", "no", "off"):
        pass  # 默认跳过逐商品截图
    else:
        catalog = _fetch_market_catalog_sync(base)"""


def _trim_manifest(root: Path, day: str) -> None:
    manifest_path = root / day / "manifest.json"
    if not manifest_path.is_file():
        return
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = data.get("results") if isinstance(data.get("results"), list) else []
    kept: list[dict] = []
    removed = 0
    for row in rows:
        name = str(row.get("name") or "")
        url = str(row.get("url") or "")
        if name.startswith("AI商品-") or "/market/catalog/" in url:
            removed += 1
            continue
        kept.append(row)
    if removed:
        data["results"] = kept
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    pw = sum(1 for r in kept if r.get("lane") == "P-W")
    print("manifest", manifest_path, "removed", removed, "kept", len(kept), "P-W", pw)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text and CATALOG_LOOP.search(text) is None:
        print("already patched", TARGET)
    else:
        if DOC_OLD in text:
            text = text.replace(DOC_OLD, DOC_NEW, 1)
        elif 'catalog 详情' in text and DOC_NEW not in text:
            text = text.replace(
                '"""全量：P-W 营销静态 + P-S/P-App AI 市场公开页与全部 catalog 详情。"""',
                DOC_NEW,
                1,
            )

        if FETCH_OLD in text and MARKER not in text:
            text = text.replace(FETCH_OLD, FETCH_NEW, 1)

        text2, n = CATALOG_LOOP.subn("\n", text)
        if n == 0 and MARKER not in text:
            raise SystemExit(f"catalog loop not found n={n}")
        text = text2

        default_old = '    """P-W / P-S / P-App 巡检目标（全量页面 + AI 市场 catalog）。"""'
        default_new = '    """P-W / P-S / P-App 巡检目标（营销 + AI 市场 Tab，不含逐商品详情）。"""'
        if default_old in text:
            text = text.replace(default_old, default_new, 1)

        TARGET.write_text(text, encoding="utf-8")
        print("patched", TARGET, "removed_catalog_loops", n)

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for root in (
        Path("/root/成都修茈科技有限公司/MODstore_deploy/playwright-report/digest-surfaces"),
        Path("/root/modstore-git/MODstore_deploy/playwright-report/digest-surfaces"),
    ):
        if root.is_dir():
            _trim_manifest(root, day)
            break


if __name__ == "__main__":
    main()
