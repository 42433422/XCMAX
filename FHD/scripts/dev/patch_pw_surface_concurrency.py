#!/usr/bin/env python3
"""MODstore surface-audit：有限并发（默认 4），缩短 P-W 全量截图时间。"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/daily_digest_surface_audit.py",
)

MARKER = "_capture_surface_target_async"

HELPER = '''

async def _capture_surface_target_async(
    browser: Any,
    idx: int,
    target: "SurfaceTarget",
    *,
    base: str,
    save_root: Optional[Path],
    market_auth: Dict[str, str],
    timeout_ms: int,
) -> Dict[str, Any]:
    url = f"{base}{target.path}"
    save_path: Optional[Path] = None
    if save_root is not None:
        slug = f"{idx:03d}_{target.lane}_{_safe_slug_name(target.name)}"
        save_path = save_root / f"{slug}.png"
    ctx_kwargs: Dict[str, Any] = {"ignore_https_errors": True}
    if target.viewport == "mobile":
        ctx_kwargs.update(
            {
                "viewport": _MOBILE_VIEWPORT,
                "is_mobile": True,
                "has_touch": True,
                "user_agent": (
                    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
                ),
            }
        )
    else:
        ctx_kwargs["viewport"] = _DESKTOP_VIEWPORT
    context = await browser.new_context(**ctx_kwargs)
    try:
        if market_auth and _path_needs_market_auth(target.path):
            await _inject_market_auth(context, market_auth)
        if target.prepare == "admin_digest" and market_auth:
            await _prepare_admin_digest(context, market_auth)
        page = await context.new_page()
        row = await _capture_one(
            page,
            url=url,
            viewport=target.viewport,
            timeout_ms=timeout_ms,
            save_path=save_path,
            prepare=target.prepare,
        )
    finally:
        await context.close()
    row["lane"] = target.lane
    row["lane_label"] = target.lane_label
    row["name"] = target.name
    if "/market/admin/" in str(target.path or ""):
        row["admin"] = True
        row["digest_unlock_ok"] = bool(not row.get("error") and int(row.get("status") or 0) < 400)
    return row
'''

OLD_LOOP = '''            for idx, target in enumerate(default_surface_targets()):
                url = f"{base}{target.path}"
                save_path: Optional[Path] = None
                if save_root is not None:
                    slug = f"{idx:03d}_{target.lane}_{_safe_slug_name(target.name)}"
                    save_path = save_root / f"{slug}.png"
                ctx_kwargs: Dict[str, Any] = {"ignore_https_errors": True}
                if target.viewport == "mobile":
                    ctx_kwargs.update(
                        {
                            "viewport": _MOBILE_VIEWPORT,
                            "is_mobile": True,
                            "has_touch": True,
                            "user_agent": (
                                "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
                            ),
                        }
                    )
                else:
                    ctx_kwargs["viewport"] = _DESKTOP_VIEWPORT
                context = await browser.new_context(**ctx_kwargs)
                if market_auth and _path_needs_market_auth(target.path):
                    await _inject_market_auth(context, market_auth)
                page = await context.new_page()
                row = await _capture_one(
                    page,
                    url=url,
                    viewport=target.viewport,
                    timeout_ms=timeout_ms,
                    save_path=save_path,
                    prepare=target.prepare,
                )
                await context.close()
                row["lane"] = target.lane
                row["lane_label"] = target.lane_label
                row["name"] = target.name
                if "/market/admin/" in str(target.path or ""):
                    row["admin"] = True
                    row["digest_unlock_ok"] = bool(
                        not row.get("error") and int(row.get("status") or 0) < 400
                    )
                results.append(row)'''

NEW_LOOP = '''            import asyncio as _asyncio

            try:
                _conc = max(1, min(12, int(os.environ.get("MODSTORE_SURFACE_AUDIT_CONCURRENCY", "4"))))
            except ValueError:
                _conc = 4
            _sem = _asyncio.Semaphore(_conc)
            _targets = list(default_surface_targets())

            async def _run_one(idx: int, target: SurfaceTarget) -> Dict[str, Any]:
                async with _sem:
                    return await _capture_surface_target_async(
                        browser,
                        idx,
                        target,
                        base=base,
                        save_root=save_root,
                        market_auth=market_auth,
                        timeout_ms=timeout_ms,
                    )

            results = list(
                await _asyncio.gather(*[_run_one(i, t) for i, t in enumerate(_targets)])
            )'''

if __name__ == "__main__":
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("already patched", TARGET)
        sys.exit(0)
    if OLD_LOOP not in text:
        raise SystemExit("serial capture loop not found")
    if HELPER.strip() not in text:
        anchor = "async def run_surface_audit_async"
        if anchor not in text:
            raise SystemExit("run_surface_audit_async not found")
        text = text.replace(anchor, HELPER + "\n\n\n" + anchor, 1)
    text = text.replace(OLD_LOOP, NEW_LOOP, 1)
    TARGET.write_text(text, encoding="utf-8")
    print("patched surface audit concurrency", TARGET)
