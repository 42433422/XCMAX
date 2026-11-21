"""Bounded Playwright execution; host owns authorization, receipts and cancellation."""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.domain.browser_policy import canonical_origin as _origin
from app.domain.browser_policy import locator_strategy, receipt_url
from app.infrastructure.browser.locators import resolve_locator
from app.infrastructure.browser.snapshot import (
    SCREENSHOT_MASK_SELECTOR,
    redacted_page_snapshot_sync,
)

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Locator, Page

Text = Annotated[str, Field(strict=True, max_length=8000)]
Name = Annotated[str, Field(strict=True, min_length=1, max_length=1000)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BrowserTarget(_Model):
    role: (
        Literal[
            "button",
            "link",
            "textbox",
            "checkbox",
            "radio",
            "combobox",
            "option",
            "tab",
            "menuitem",
            "heading",
            "row",
            "cell",
            "dialog",
            "status",
            "alert",
            "searchbox",
        ]
        | None
    ) = None
    name: Text | None = None
    label: Name | None = None
    test_id: Name | None = None
    selector: Name | None = None

    @model_validator(mode="after")
    def one_locator(self) -> BrowserTarget:
        locator_strategy(self.model_dump(exclude_none=True))
        return self


class _Navigate(_Model):
    action: Literal["navigate"]
    url: Name


class _Click(_Model):
    action: Literal["click"]
    target: BrowserTarget


class _Fill(_Model):
    action: Literal["fill"]
    target: BrowserTarget
    text: Text


class _Press(_Model):
    action: Literal["press"]
    target: BrowserTarget
    key: Literal["Enter", "Tab", "Escape", "Backspace", "Delete", "ArrowDown", "ArrowUp", "Space"]


class _Select(_Model):
    action: Literal["select"]
    target: BrowserTarget
    value: Text


class _Check(_Model):
    action: Literal["check"]
    target: BrowserTarget
    checked: bool


class BrowserVerification(_Model):
    kind: Literal["url", "text", "value", "visible", "checked"]
    target: BrowserTarget | None = None
    expected: Text | bool | None = None

    @model_validator(mode="after")
    def valid_expectation(self) -> BrowserVerification:
        if (self.kind == "url") != (self.target is None):
            raise ValueError("Element assertions require a target; URL assertions do not")
        if self.kind in {"url", "text", "value"} and not isinstance(self.expected, str):
            raise ValueError("This assertion requires a string")
        if self.kind in {"visible", "checked"} and not isinstance(self.expected, bool):
            raise ValueError("This assertion requires a boolean")
        return self


class BrowserPlan(_Model):
    steps: list[
        Annotated[
            _Navigate | _Click | _Fill | _Press | _Select | _Check, Field(discriminator="action")
        ]
    ] = Field(min_length=1, max_length=20)
    verification: BrowserVerification | None = None


def _locator(page: Page, target: BrowserTarget) -> Locator:
    return cast("Locator", resolve_locator(page, target.model_dump(exclude_none=True)))


class _Cancelled(Exception):
    pass


class _Deadline(Exception):
    pass


class _OriginDenied(Exception):
    pass


class PlaywrightComputer:
    """One isolated context per call; no inherited cookies, browser profile or shell."""

    def __init__(
        self,
        allowed_origins: tuple[str, ...],
        executable_path: str | None = None,
        headless: bool = True,
    ) -> None:
        self.allowed_origins = frozenset(
            _origin(value, configured=True) for value in allowed_origins
        )
        self.executable_path, self.headless = executable_path, headless

    def _allowed(self, url: str) -> bool:
        try:
            return _origin(url) in self.allowed_origins
        except (ValueError, UnicodeError):
            return False

    def validate(self, steps: list[dict], verification: dict | None) -> BrowserPlan:
        plan: BrowserPlan = BrowserPlan.model_validate(
            {"steps": steps, "verification": verification}
        )
        if not self.allowed_origins:
            raise ValueError("Browser origins are not configured")
        if plan.steps[0].action != "navigate":
            raise ValueError("An isolated browser task must begin with navigate")
        for step in plan.steps:
            if isinstance(step, _Navigate) and not self._allowed(step.url):
                raise ValueError("Navigation origin is not allowed")
        if (
            plan.verification
            and plan.verification.kind == "url"
            and not self._allowed(str(plan.verification.expected))
        ):
            raise ValueError("Verification origin is not allowed")
        return plan

    def execute(
        self, steps: list[dict], verification: dict | None, cancelled: Callable[[], bool]
    ) -> dict:
        result: dict[str, Any] = {
            "success": False,
            "executed": False,
            "verified": False,
            "status": "failed",
            "steps_completed": 0,
        }
        try:
            plan = self.validate(steps, verification)
        except (ValueError, ValidationError):
            return {
                **result,
                "error_code": "computer_invalid_arguments",
                "message": "浏览器步骤、定位或核验参数无效",
            }
        if cancelled():
            return {
                **result,
                "status": "cancelled",
                "error_code": "computer_cancelled",
                "message": "操作已停止",
            }
        try:
            from playwright.sync_api import Error, expect, sync_playwright
        except ImportError:
            return {
                **result,
                "status": "unavailable",
                "error_code": "computer_backend_unavailable",
                "message": "Playwright 未安装",
            }
        deadline = time.monotonic() + 60
        browser: Browser | None = None
        context: BrowserContext | None = None
        page: Page | None = None
        in_action = False
        blocked = ""

        def budget() -> float:
            if cancelled():
                raise _Cancelled
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _Deadline
            if blocked:
                raise _OriginDenied
            return max(1.0, min(5000.0, remaining * 1000))

        def route_request(route: Any) -> None:
            nonlocal blocked
            if self._allowed(route.request.url) and not cancelled() and time.monotonic() < deadline:
                # Native routing can skip redirect hops. Never let fetch or the
                # browser follow a response to a URL that was not intercepted.
                response = route.fetch(max_redirects=0, max_retries=0, timeout=budget())
                try:
                    if 300 <= response.status < 400 and response.headers.get("location"):
                        blocked = "computer_redirect_blocked"
                        route.abort("blockedbyclient")
                    else:
                        route.fulfill(response=response)
                finally:
                    response.dispose()
            else:
                blocked = "computer_origin_denied"
                route.abort("blockedbyclient")

        def block_socket(socket: Any) -> None:
            nonlocal blocked
            blocked = "computer_websocket_blocked"
            socket.close()

        def observe(observed_page: Page) -> dict:
            timeout = budget()
            if not self._allowed(observed_page.url):
                raise _OriginDenied
            observed_page.set_default_timeout(timeout)
            snapshot = redacted_page_snapshot_sync(observed_page, timeout=timeout)
            shot = observed_page.screenshot(
                type="jpeg",
                quality=65,
                mask=[observed_page.locator(SCREENSHOT_MASK_SELECTOR)],
                timeout=budget(),
            )
            return {
                "url": receipt_url(observed_page.url),
                "title": observed_page.title()[:1000],
                "aria_snapshot": snapshot[:16000],
                "truncated": len(snapshot) > 16000,
                "content_trust": "untrusted_external_page",
                "form_values_redacted": True,
                "data_url": "data:image/jpeg;base64," + base64.b64encode(shot).decode("ascii"),
                "width": 1280,
                "height": 800,
            }

        try:
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch(
                        executable_path=self.executable_path,
                        headless=self.headless,
                        chromium_sandbox=True,
                        timeout=budget(),
                    )
                    context = browser.new_context(
                        viewport={"width": 1280, "height": 800},
                        service_workers="block",
                        accept_downloads=False,
                    )
                    context.route("**/*", route_request)
                    context.route_web_socket("**/*", block_socket)
                    page = context.new_page()
                    context.on("page", lambda popup: popup.close() if popup is not page else None)
                    page.on("dialog", lambda dialog: dialog.dismiss())
                    for step in plan.steps:
                        timeout = budget()
                        if page.url != "about:blank" and not self._allowed(page.url):
                            raise _OriginDenied
                        in_action = True
                        if isinstance(step, _Navigate):
                            page.goto(step.url, timeout=timeout, wait_until="domcontentloaded")
                        else:
                            locator = _locator(page, step.target)
                            if isinstance(step, _Click):
                                locator.click(timeout=timeout)
                            elif isinstance(step, _Fill):
                                locator.fill(step.text, timeout=timeout)
                            elif isinstance(step, _Press):
                                locator.press(step.key, timeout=timeout)
                            elif isinstance(step, _Select):
                                locator.select_option(value=step.value, timeout=timeout)
                            else:
                                locator.set_checked(step.checked, timeout=timeout)
                        in_action = False
                        result["steps_completed"] += 1
                        result["executed"] = True
                        budget()
                        if not self._allowed(page.url):
                            raise _OriginDenied
                    assertion = plan.verification
                    if assertion:
                        from app.domain.browser_receipt import observed_assertion

                        timeout = budget()
                        if assertion.kind == "url":
                            assert isinstance(assertion.expected, str)
                            expect(page).to_have_url(assertion.expected, timeout=timeout)
                            actual = page.url
                        else:
                            assert assertion.target is not None
                            locator = _locator(page, assertion.target)
                            check = expect(locator)
                            if assertion.kind in {"text", "value"}:
                                assert isinstance(assertion.expected, str)
                                if assertion.kind == "text":
                                    check.to_have_text(assertion.expected, timeout=timeout)
                                else:
                                    check.to_have_value(assertion.expected, timeout=timeout)
                                actual = (
                                    locator.text_content(timeout=timeout)
                                    if assertion.kind == "text"
                                    else locator.input_value(timeout=timeout)
                                )
                            else:
                                assert isinstance(assertion.expected, bool)
                                if assertion.kind == "visible":
                                    (
                                        check.to_be_visible
                                        if assertion.expected
                                        else check.to_be_hidden
                                    )(timeout=timeout)
                                else:
                                    check.to_be_checked(checked=assertion.expected, timeout=timeout)
                                actual = (
                                    locator.is_visible(timeout=timeout)
                                    if assertion.kind == "visible"
                                    else locator.is_checked(timeout=timeout)
                                )
                        result["verification"] = observed_assertion(
                            assertion.model_dump(exclude_none=True), actual
                        )
                        if result["verification"]["status"] != "passed":
                            raise AssertionError("computer browser postcondition changed")
                    result["observation"] = observe(page)
                    budget()
                    result.update(
                        success=bool(assertion),
                        verified=bool(assertion),
                        status="verified" if assertion else "needs_verification",
                        message="浏览器后置条件已核验"
                        if assertion
                        else "步骤已执行，尚无后置条件核验",
                    )
                except (Error, AssertionError):
                    if page is not None:
                        with suppress(Error, _Cancelled, _Deadline, _OriginDenied):
                            result["observation"] = observe(page)
                    raise
                finally:
                    if context is not None:
                        with suppress(Error):
                            context.close()
                    if browser is not None:
                        with suppress(Error):
                            browser.close()
        except _Cancelled:
            result.update(
                status="cancelled", error_code="computer_cancelled", message="已停止后续浏览器操作"
            )
        except _Deadline:
            result.update(
                status="outcome_unknown" if in_action else "failed",
                error_code="computer_timeout",
                message="浏览器操作超时，未自动重试",
            )
        except _OriginDenied:
            result.update(
                error_code=blocked or "computer_origin_denied",
                message="浏览器站点策略拒绝请求；重定向须改用已授权最终 URL",
            )
        except AssertionError:
            result.update(
                status="verification_failed",
                error_code="computer_verification_failed",
                message="浏览器后置条件未通过",
            )
        except ValueError:
            result.update(
                error_code="computer_observation_unavailable",
                message="页面隐私状态无法核验，未返回截图或页面快照",
            )
        except (Error, OSError):
            result.update(
                status="outcome_unknown"
                if in_action
                else "unavailable"
                if browser is None
                else "failed",
                error_code=blocked
                if blocked
                else "computer_execution_failed"
                if browser is not None
                else "computer_backend_unavailable",
                message="浏览器执行未完成；已有动作不会自动重试",
            )
        result["outcome_unknown"] = in_action
        return result
