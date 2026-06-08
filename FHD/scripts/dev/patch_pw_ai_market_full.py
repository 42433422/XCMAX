#!/usr/bin/env python3
"""P-W AI 市场全量补全：高级筛选 + 钱包/已购/订单 + 全部 catalog 详情。"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/daily_digest_surface_audit.py",
)

MARKER = "_PW_AI_MARKET_EXTRA_PAGES"

EXTRA_CONST = '''
_PW_AI_MARKET_EXTRA_PAGES: Tuple[Tuple[str, str, str], ...] = (
    ("AI市场-高级筛选", "/market/ai-store", "ai_store_tab:all|filters_open"),
    ("钱包", "/market/wallet", ""),
    ("已购商品", "/market/wallet/purchased", ""),
    ("订单列表", "/market/orders", ""),
)
'''

BUILD_INSERT = '''
    for name, path, prepare in _PW_AI_MARKET_EXTRA_PAGES:
        out.append(
            SurfaceTarget(
                "P-W",
                "网站 P-W",
                name,
                path,
                "desktop",
                prepare=prepare or None,
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
        )

'''

DOC_OLD = '    """全量：P-W 营销静态 + AI 市场 Tab；不逐 catalog 商品详情截图。"""'
DOC_NEW = '    """全量：P-W 营销静态 + AI 市场 Tab/筛选/钱包/订单 + 全部 catalog 详情。"""'

DEFAULT_OLD = '    """P-W / P-S / P-App 巡检目标（营销 + AI 市场 Tab，不含逐商品详情）。"""'
DEFAULT_NEW = '    """P-W / P-S / P-App 巡检目标（营销 + AI 市场全链路 + catalog 详情）。"""'

SKIP_OLD = '    if (os.environ.get("MODSTORE_SURFACE_AUDIT_SKIP_CATALOG", "1") or "").strip().lower() not in ("0", "false", "no", "off"):'
SKIP_NEW = '    if (os.environ.get("MODSTORE_SURFACE_AUDIT_SKIP_CATALOG", "0") or "").strip().lower() not in ("0", "false", "no", "off"):'

PREPARE_OLD = '''async def _apply_page_prepare(page: Any, prepare: str, timeout_ms: int) -> None:
    if prepare == "admin_digest":'''

PREPARE_NEW = '''async def _apply_page_prepare(page: Any, prepare: str, timeout_ms: int) -> None:
    for step in [s.strip() for s in str(prepare or "").split("|") if s.strip()]:
        await _apply_page_prepare_step(page, step, timeout_ms)


async def _apply_page_prepare_step(page: Any, prepare: str, timeout_ms: int) -> None:
    if prepare == "admin_digest":'''

FILTERS_BRANCH = '''    if prepare.startswith("ai_store_tab:"):
        tab_id = prepare.split(":", 1)[1]
        label = _AI_STORE_TAB_LABELS.get(tab_id, "")
        if not label:
            return
        btn = page.locator("button.store-nav__item").filter(has_text=label)
        await btn.first.click(timeout=min(timeout_ms, 20_000))
        await page.wait_for_timeout(1200)'''

FILTERS_NEW = '''    if prepare.startswith("ai_store_tab:"):
        tab_id = prepare.split(":", 1)[1]
        label = _AI_STORE_TAB_LABELS.get(tab_id, "")
        if not label:
            return
        btn = page.locator("button.store-nav__item").filter(has_text=label)
        await btn.first.click(timeout=min(timeout_ms, 20_000))
        await page.wait_for_timeout(1200)
        return
    if prepare == "filters_open":
        try:
            btn = page.locator(".store-adv-toggle").filter(has_text="高级筛选")
            await btn.first.click(timeout=min(timeout_ms, 15_000))
            await page.wait_for_selector(".store-adv-filters", state="visible", timeout=6000)
            await page.wait_for_timeout(600)
        except Exception:
            pass
        return'''


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    changed = False

    if MARKER not in text:
        anchor = "_AI_STORE_TAB_LABELS: Dict[str, str] = {"
        idx = text.find(anchor)
        if idx < 0:
            raise SystemExit("_AI_STORE_TAB_LABELS anchor not found")
        end = text.find("\n}\n", idx)
        if end < 0:
            raise SystemExit("_AI_STORE_TAB_LABELS block end not found")
        text = text[: end + 2] + EXTRA_CONST + text[end + 2 :]
        changed = True

    loop_anchor = "    for name, path, mode in _PW_WB_MODE_PAGES:"
    if "for item in catalog:" not in text and loop_anchor in text:
        insert_at = text.find(loop_anchor)
        text = text[:insert_at] + BUILD_INSERT + text[insert_at:]
        changed = True

    for old, new in ((DOC_OLD, DOC_NEW), (DEFAULT_OLD, DEFAULT_NEW), (SKIP_OLD, SKIP_NEW)):
        if old in text:
            text = text.replace(old, new, 1)
            changed = True

    if "_apply_page_prepare_step" not in text and PREPARE_OLD in text:
        text = text.replace(PREPARE_OLD, PREPARE_NEW, 1)
        changed = True

    if 'prepare == "filters_open"' not in text and FILTERS_BRANCH in text:
        text = text.replace(FILTERS_BRANCH, FILTERS_NEW, 1)
        changed = True

    if changed:
        TARGET.write_text(text, encoding="utf-8")
        print("patched", TARGET)
    else:
        print("already patched", TARGET)


if __name__ == "__main__":
    main()
