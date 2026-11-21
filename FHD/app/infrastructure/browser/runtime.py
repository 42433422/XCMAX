"""Thin Playwright adapter; task authorization and durable receipts belong to the caller.

Origins are operator-approved network destinations, not an operating-system sandbox.
The caller owns the artifact directory and must persist it before deleting the worker.
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import re
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from app.infrastructure.browser.snapshot import redacted_page_snapshot

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page

MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
MAX_SNAPSHOT_CHARS = 30_000
ACTIONS = frozenset({"click", "fill", "select", "check", "press", "upload", "download"})


class BrowserPolicyError(ValueError):
    """A browser destination is outside the operator's approved origins."""


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(ord(char) < 32 for char in url)
    ):
        raise BrowserPolicyError("unsupported_browser_destination")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    default = 443 if parsed.scheme == "https" else 80
    return f"{parsed.scheme}://{host}" + (
        f":{port}" if port is not None and port != default else ""
    )


def _timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("browser_deadline_exceeded")
    return max(1, remaining * 1000)


def _receipt_url(url: str) -> str:
    """Do not persist redirect query/fragment credentials in the result receipt."""
    return urlsplit(url)._replace(query="", fragment="").geturl()


def _locator(page: Any, spec: dict[str, Any], frame: str | None = None) -> Any:
    target = page.frame_locator(frame) if frame else page
    keys = [key for key in ("role", "label", "text", "selector") if spec.get(key)]
    if len(keys) != 1 or (spec.get("name") is not None and keys[0] != "role"):
        raise ValueError("browser_locator_requires_one_strategy")
    key = keys[0]
    if key == "role":
        return target.get_by_role(spec[key], name=spec.get("name"), exact=True)
    if key == "selector":
        return target.locator(spec[key])
    return getattr(target, f"get_by_{key}")(spec[key], exact=True)


def _validate_checks(checks: Any, *, required: bool = False) -> None:
    if not isinstance(checks, list) or not int(required) <= len(checks) <= 30:
        raise ValueError("browser_verification_required")
    for check in checks:
        if not isinstance(check, dict) or check.get("kind") not in {
            "text",
            "value",
            "visible",
            "url",
        }:
            raise ValueError("invalid_browser_verification")
        if check["kind"] != "url" and not isinstance(check.get("locator"), dict):
            raise ValueError("browser_verification_locator_required")
        if check["kind"] == "visible":
            if check.get("expected", "true") not in {"true", "false"}:
                raise ValueError("visibility_expectation_requires_boolean_text")
        elif not isinstance(check.get("expected"), str):
            raise ValueError("verification_expectation_requires_text")


def _validate(plan: dict[str, Any]) -> None:
    steps = plan.get("steps", [])
    if not isinstance(steps, list) or len(steps) > 30:
        raise ValueError("invalid_browser_steps")
    if plan.get("observe"):
        if steps:
            raise ValueError("observation_cannot_execute_steps")
    else:
        _validate_checks(plan.get("verify"), required=True)
    for step in steps:
        if (
            not isinstance(step, dict)
            or step.get("action") not in ACTIONS
            or not isinstance(step.get("locator"), dict)
        ):
            raise ValueError("invalid_browser_action")
        _validate_checks(step.get("verify", []))
        if step["action"] == "upload":
            files = step.get("files", [])
            if not isinstance(files, list) or not files:
                raise ValueError("upload_requires_resolved_files")
            for file in files:
                if not isinstance(file, dict) or not isinstance(file.get("buffer"), bytes):
                    raise ValueError("upload_requires_resolved_bytes")
                name = file.get("name", "")
                if not name or "/" in name or "\\" in name:
                    raise ValueError("invalid_upload_name")
            if sum(len(file["buffer"]) for file in files) > MAX_ARTIFACT_BYTES:
                raise ValueError("upload_too_large")


def _artifact(path: Path, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    size = path.stat().st_size
    if size <= 0 or size + sum(item["size"] for item in artifacts) > MAX_ARTIFACT_BYTES:
        path.unlink(missing_ok=True)
        raise ValueError("artifact_size_limit")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(128 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path),
        "name": path.name,
        "size": size,
        "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "sha256": digest.hexdigest(),
    }


async def execute_browser_plan(
    plan: dict[str, Any],
    *,
    artifact_dir: Path,
    allowed_origins: frozenset[str],
    deadline_monotonic: float,
    executable_path: str | None = None,
    before_action: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Execute once, verify explicitly, and release this run's isolated context.

    Never replay failed writes. After an attempted action any failure is uncertain.
    Cancellation propagates after cleanup; the caller's durable ledger owns recovery.
    No model-provided script, local filename, credential profile, or browser flags run.
    """
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright, expect

    result: dict[str, Any] = {
        "success": False,
        "outcome": "failed",
        "verified": False,
        "retryable": False,
        "reconciliation_required": False,
        "steps": [],
        "verification": [],
        "artifacts": [],
    }
    attempted = False
    browser: Browser | None = None
    context: BrowserContext | None = None
    page: Page | None = None
    blocked: set[str] = set()

    def require_allowed(url: str) -> None:
        if _origin(url) not in allowed:
            raise BrowserPolicyError("browser_origin_not_allowed")

    def check_network() -> Page:
        if blocked:
            raise BrowserPolicyError("browser_network_blocked")
        if page is None:
            raise RuntimeError("browser_page_unavailable")
        require_allowed(page.url)
        return page

    async def verify(checks: list[dict[str, Any]]) -> list[dict[str, str]]:
        receipts = []
        for check in checks:
            active_page = check_network()
            timeout = _timeout(deadline_monotonic)
            kind = check["kind"]
            if kind == "url":
                await expect(active_page).to_have_url(check["expected"], timeout=timeout)
            else:
                locator = _locator(active_page, check["locator"], check.get("frame"))
                if kind == "visible":
                    visibility = (
                        "to_be_hidden" if check.get("expected") == "false" else "to_be_visible"
                    )
                    await getattr(expect(locator), visibility)(timeout=timeout)
                else:
                    await getattr(expect(locator), f"to_have_{kind}")(
                        check["expected"],
                        timeout=timeout,
                    )
            receipts.append({"kind": kind, "status": "passed"})
        return receipts

    async def route_request(route: Any) -> None:
        nonlocal attempted
        response = None
        try:
            require_allowed(route.request.url)
            if plan.get("observe") and route.request.method not in {"GET", "HEAD"}:
                raise BrowserPolicyError("observation_cannot_write")
            if route.request.method not in {"GET", "HEAD", "OPTIONS"}:
                if before_action is not None:
                    before_action()
                attempted = True
            # Fulfil one hop so a redirect is a new browser request and rechecked.
            response = await route.fetch(max_redirects=0, timeout=_timeout(deadline_monotonic))
            location = response.headers.get("location")
            if 300 <= response.status < 400 and location:
                require_allowed(urljoin(route.request.url, location))
            size = response.headers.get("content-length", "")
            if size.isdecimal() and int(size) > MAX_ARTIFACT_BYTES:
                raise BrowserPolicyError("browser_response_size_limit")
            await route.fulfill(response=response)
        except (
            BrowserPolicyError,
            ValueError,
            PlaywrightError,
            TimeoutError,
            OSError,
            RuntimeError,
        ):
            blocked.add("request_denied_or_failed")
            with suppress(PlaywrightError):
                await route.abort("blockedbyclient")
        finally:
            if response is not None:
                with suppress(PlaywrightError):
                    await response.dispose()

    async def block_websocket(socket: Any) -> None:
        blocked.add("websocket_denied")
        await socket.close(code=1008, reason="browser_policy")

    def watch_page(new_page: Any) -> None:
        async def navigated(frame: Any) -> None:
            if frame == new_page.main_frame and frame.url != "about:blank":
                try:
                    require_allowed(frame.url)
                except (BrowserPolicyError, ValueError):
                    blocked.add("navigation_denied")
                    with suppress(PlaywrightError):
                        await new_page.close()

        new_page.on("framenavigated", navigated)

    try:
        _validate(plan)
        allowed = frozenset(_origin(origin) for origin in allowed_origins)
        require_allowed(plan["url"])
        artifact_dir.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as playwright:
            try:
                async with asyncio.timeout(_timeout(deadline_monotonic) / 1000):
                    browser = await playwright.chromium.launch(
                        headless=True,
                        chromium_sandbox=True,
                        executable_path=executable_path,
                        timeout=_timeout(deadline_monotonic),
                    )
                    context = await browser.new_context(
                        accept_downloads=True,
                        service_workers="block",
                    )
                    await context.route("**/*", route_request)
                    await context.route_web_socket("**/*", block_websocket)
                    context.on("page", watch_page)
                    page = await context.new_page()
                    response = await page.goto(
                        plan["url"],
                        wait_until="domcontentloaded",
                        timeout=_timeout(deadline_monotonic),
                    )
                    check_network()
                    if response is not None and response.status >= 400:
                        raise PlaywrightError("browser_navigation_http_error")
                    if plan.get("observe"):
                        snapshot = await redacted_page_snapshot(
                            page, timeout=_timeout(deadline_monotonic)
                        )
                        check_network()
                        result.update(
                            snapshot=snapshot[:MAX_SNAPSHOT_CHARS],
                            truncated=len(snapshot) > MAX_SNAPSHOT_CHARS,
                            form_values_redacted=True,
                        )
                    else:
                        for index, step in enumerate(plan.get("steps", [])):
                            check_network()
                            timeout = _timeout(deadline_monotonic)
                            action = step["action"]
                            locator = _locator(page, step["locator"], step.get("frame"))
                            receipt = {"index": index, "action": action, "status": "running"}
                            result["steps"].append(receipt)
                            if before_action is not None:
                                before_action()
                            attempted = True
                            if action == "download":
                                async with page.expect_download(timeout=timeout) as pending:
                                    await locator.click(timeout=timeout)
                                download = await pending.value
                                suffix = Path(download.suggested_filename).suffix
                                suffix = (
                                    suffix
                                    if re.fullmatch(r"\.[A-Za-z0-9]{1,10}", suffix)
                                    else ".bin"
                                )
                                path = artifact_dir / f"download-{uuid4().hex}{suffix}"
                                await download.save_as(path)
                                result["artifacts"].append(_artifact(path, result["artifacts"]))
                            elif action == "upload":
                                await locator.set_input_files(
                                    [
                                        {
                                            "name": file["name"],
                                            "mimeType": file.get(
                                                "mime_type", "application/octet-stream"
                                            ),
                                            "buffer": file["buffer"],
                                        }
                                        for file in step["files"]
                                    ],
                                    timeout=timeout,
                                )
                            elif action == "click":
                                await locator.click(timeout=timeout)
                            elif action == "select":
                                await locator.select_option(step["value"], timeout=timeout)
                            elif action == "check":
                                await locator.set_checked(step["value"], timeout=timeout)
                            else:
                                await getattr(locator, action)(step["value"], timeout=timeout)
                            check_network()
                            receipt["verification"] = await verify(step.get("verify", []))
                            receipt["status"] = "completed"
                        result["verification"] = await verify(plan["verify"])
                        result["verified"] = True
                    check_network()
                    result.update(
                        success=True,
                        outcome="observed" if plan.get("observe") else "succeeded",
                        url=_receipt_url(page.url),
                        title=await page.title(),
                    )
            finally:
                if page is not None and not page.is_closed() and plan.get("screenshot"):
                    with suppress(PlaywrightError, TimeoutError, ValueError, OSError):
                        path = artifact_dir / f"screenshot-{uuid4().hex}.png"
                        await page.screenshot(
                            path=path,
                            full_page=False,
                            mask=[
                                page.locator(
                                    "input, select, textarea, [contenteditable], "
                                    "iframe, frame, object, embed"
                                )
                            ],
                            timeout=min(_timeout(deadline_monotonic), 2000),
                        )
                        result["artifacts"].append(_artifact(path, result["artifacts"]))
                for owned in (context, browser):
                    if owned is not None:
                        with suppress(PlaywrightError, TimeoutError):
                            await asyncio.wait_for(owned.close(), timeout=2)
            if blocked:
                raise BrowserPolicyError("browser_network_blocked")
    except (
        BrowserPolicyError,
        ValueError,
        KeyError,
        TypeError,
        OSError,
        RuntimeError,
        PlaywrightError,
        TimeoutError,
        AssertionError,
    ) as exc:
        if isinstance(exc, BrowserPolicyError) or blocked:
            code = "browser_policy_denied"
        elif isinstance(exc, (TimeoutError, PlaywrightTimeoutError)):
            code = "browser_timeout"
        elif isinstance(exc, AssertionError):
            code = "browser_verification_failed"
        elif isinstance(exc, (ValueError, KeyError, TypeError)):
            code = "invalid_browser_plan"
        else:
            code = "browser_execution_failed"
        result.update(
            success=False,
            verified=False,
            error_code=code,
            outcome="unknown" if attempted else "failed",
            reconciliation_required=attempted,
        )
        if result["steps"] and result["steps"][-1]["status"] == "running":
            result["steps"][-1]["status"] = result["outcome"]
    return result
