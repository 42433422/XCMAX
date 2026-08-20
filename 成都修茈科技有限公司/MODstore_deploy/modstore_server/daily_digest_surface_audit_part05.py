# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.daily_digest_surface_audit")


def _surface_capture_retry_count() -> int:
    raw = (_facade().os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_RETRIES") or "2").strip()
    try:
        return max(0, min(4, int(raw)))
    except ValueError:
        return 2


def _is_retryable_surface_row(row: _facade().Dict[str, _facade().Any]) -> bool:
    err = str(row.get("error") or "")
    if err and any((marker in err for marker in _facade()._TRANSIENT_NAV_ERROR_MARKERS)):
        return True
    try:
        status = int(row.get("status") or 0)
    except (TypeError, ValueError):
        status = 0
    return status in (408, 425, 429) or status >= 500


async def _wait_page_ready(page: _facade().Any, *, timeout_ms: int) -> None:
    """等待 SPA/静态页渲染与中文字体就绪，避免截图文字丢失。"""
    try:
        await page.add_style_tag(
            content='@import url("https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;700&display=swap");*{font-family:"Noto Sans SC","WenQuanYi Micro Hei","DejaVu Sans",sans-serif!important}'
        )
    except RECOVERABLE_ERRORS:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 25000))
    except RECOVERABLE_ERRORS:
        pass
    try:
        await page.evaluate(
            "() => (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve()"
        )
    except RECOVERABLE_ERRORS:
        pass
    await page.wait_for_timeout(1500)


async def _apply_page_prepare(page: _facade().Any, prepare: str, timeout_ms: int) -> None:
    for step in [s.strip() for s in str(prepare or "").split("|") if s.strip()]:
        await _facade()._apply_page_prepare_step(page, step, timeout_ms)


async def _apply_page_prepare_step(page: _facade().Any, prepare: str, timeout_ms: int) -> None:
    if prepare == "admin_digest":
        try:
            unlock_btn = page.get_by_role("button", name=_facade().re.compile("解锁管理端"))
            if await unlock_btn.is_visible(timeout=2500):
                await unlock_btn.click(timeout=5000)
                await page.wait_for_timeout(1000)
        except RECOVERABLE_ERRORS:
            pass
        try:
            await page.wait_for_selector(".wb-sidebar-admin-nav, #app .app-shell", timeout=12000)
        except RECOVERABLE_ERRORS:
            pass
        return
    if prepare.startswith("wb_mode:"):
        mode = prepare.split(":", 1)[1]
        labels = {"direct": "聊", "make": "做", "voice": "说"}
        label = labels.get(mode, "")
        if label:
            btn = page.locator(".wb-sidebar-modes button.wb-sidebar-mode-btn").filter(
                has_text=label
            )
            await btn.first.click(timeout=min(timeout_ms, 20000))
            await page.wait_for_timeout(800)
        return
    if prepare.startswith("ai_store_tab:"):
        tab_id = prepare.split(":", 1)[1]
        label = _facade()._AI_STORE_TAB_LABELS.get(tab_id, "")
        if not label:
            return
        btn = page.locator("button.store-nav__item").filter(has_text=label)
        await btn.first.click(timeout=min(timeout_ms, 20000))
        await page.wait_for_timeout(1200)
        return
    if prepare == "filters_open":
        try:
            btn = page.locator(".store-adv-toggle").filter(has_text="高级筛选")
            await btn.first.click(timeout=min(timeout_ms, 15000))
            await page.wait_for_selector(".store-adv-filters", state="visible", timeout=6000)
            await page.wait_for_timeout(600)
        except RECOVERABLE_ERRORS:
            pass
        return


async def _capture_one(
    page: _facade().Any,
    *,
    url: str,
    viewport: str,
    timeout_ms: int,
    save_path: _facade().Optional[_facade().Path],
    prepare: str = "",
) -> _facade().Dict[str, _facade().Any]:
    console_errors: _facade().List[str] = []
    page.on(
        "console",
        lambda msg: (console_errors.append(str(msg.text)) if msg.type == "error" else None),
    )
    vp = _facade()._MOBILE_VIEWPORT if viewport == "mobile" else _facade()._DESKTOP_VIEWPORT
    await page.set_viewport_size(vp)
    status: _facade().Optional[int] = None
    title = ""
    err: _facade().Optional[str] = None
    try:
        resp = await _facade()._goto_with_retry(page, url, timeout_ms=timeout_ms)
        status = resp.status if resp else None
        await _facade()._wait_page_ready(page, timeout_ms=timeout_ms)
        if prepare:
            await _facade()._apply_page_prepare(page, prepare, timeout_ms)
        title = await page.title()
        png = await page.screenshot(full_page=False, type="png")
        if save_path is not None:
            save_path.write_bytes(png)
    except RECOVERABLE_ERRORS as exc:
        err = str(exc)
        try:
            png = await page.screenshot(full_page=False, type="png")
            if save_path is not None:
                save_path.write_bytes(png)
        except RECOVERABLE_ERRORS:
            pass
        if not save_path or not save_path.is_file():
            return {
                "url": url,
                "status": status,
                "title": title,
                "console_errors": console_errors[:8],
                "error": err,
                "screenshot_saved": "",
                "viewport": viewport,
                "prepare": prepare or "",
            }
    if not save_path or not save_path.is_file():
        if err:
            return {
                "url": url,
                "status": status,
                "title": title,
                "console_errors": console_errors[:8],
                "error": err,
                "screenshot_saved": "",
                "viewport": viewport,
                "prepare": prepare or "",
            }
        raise RuntimeError(f"surface audit screenshot missing url={url}")
    return {
        "url": url,
        "status": status,
        "title": title,
        "console_errors": console_errors[:8],
        "error": None,
        "screenshot_saved": str(save_path),
        "viewport": viewport,
        "prepare": prepare or "",
    }
