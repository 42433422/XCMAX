"""Behavior at the optional Playwright boundary; never operate a user's browser."""

from __future__ import annotations

import sys
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from app.desktop_automation.computer_browser import PlaywrightComputer

ORIGIN = "https://app.example.test"
NAVIGATE = {"action": "navigate", "url": ORIGIN + "/form"}
VERIFY = {"kind": "value", "target": {"label": "姓名"}, "expected": "张三"}


@pytest.fixture
def browser_api(monkeypatch):
    class Error(Exception):
        pass

    locator = Mock()
    locator.input_value.return_value = "张三"
    locator.text_content.return_value = "张三"
    locator.is_visible.return_value = True
    locator.is_checked.return_value = True
    locator.aria_snapshot.return_value = '- textbox "姓名": 张三'
    page = Mock(url="about:blank")
    page.goto.side_effect = lambda url, **kwargs: setattr(page, "url", url)
    page.locator.return_value = locator
    page.get_by_label.return_value = locator
    page.get_by_role.return_value = locator
    page.get_by_test_id.return_value = locator
    page.screenshot.return_value = b"jpeg-observation"
    page.title.return_value = "表单"
    context = Mock()
    context.new_page.return_value = page
    browser = Mock()
    browser.new_context.return_value = context
    playwright = Mock()
    playwright.chromium.launch.return_value = browser
    assertion = Mock()
    module = ModuleType("playwright.sync_api")
    module.Error = Error
    module.expect = Mock(return_value=assertion)
    module.sync_playwright = Mock(return_value=nullcontext(playwright))
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    return SimpleNamespace(
        page=page,
        locator=locator,
        context=context,
        browser=browser,
        playwright=playwright,
        assertion=assertion,
        module=module,
        Error=Error,
    )


@pytest.mark.parametrize(
    "tail,verification",
    [
        ({"action": "evaluate", "javascript": "document.cookie"}, None),
        ({"action": "click", "target": {"role": "button", "label": "保存"}}, None),
        ({"action": "fill", "target": {"selector": "#name"}, "text": 42}, None),
        ({"action": "press", "target": {"label": "姓名"}, "key": "Control+L"}, None),
        (
            {"action": "click", "target": {"selector": "#save"}},
            {"kind": "value", "target": {"label": "姓名"}, "expected": True},
        ),
    ],
)
def test_entire_plan_and_assertion_validated_before_browser_start(browser_api, tail, verification):
    result = PlaywrightComputer((ORIGIN,)).execute([NAVIGATE, tail], verification, lambda: False)
    assert result["error_code"] == "computer_invalid_arguments"
    assert result["executed"] is False
    browser_api.module.sync_playwright.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "http://app.example.test/form",
        "https://app.example.test:8443/form",
        "https://other.test/",
        "https://user:secret@app.example.test/",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://app.example.test\\@other.test/",
    ],
)
def test_navigation_does_not_expand_authorized_origins(browser_api, url):
    result = PlaywrightComputer((ORIGIN,)).execute(
        [{"action": "navigate", "url": url}], None, lambda: False
    )
    assert result["error_code"] == "computer_invalid_arguments"
    browser_api.module.sync_playwright.assert_not_called()


def test_real_locator_actions_and_assertion_are_required_for_success(browser_api):
    result = PlaywrightComputer((ORIGIN,)).execute(
        [NAVIGATE, {"action": "fill", "target": {"label": "姓名"}, "text": "张三"}],
        VERIFY,
        lambda: False,
    )
    assert result["success"] is True and result["verified"] is True
    assert result["steps_completed"] == 2
    assert result["observation"]["aria_snapshot"] == '- textbox "姓名": 张三'
    browser_api.locator.fill.assert_called_once_with("张三", timeout=5000.0)
    browser_api.assertion.to_have_value.assert_called_once_with("张三", timeout=5000.0)
    assert browser_api.playwright.chromium.launch.call_args.kwargs["chromium_sandbox"] is True
    assert browser_api.browser.new_context.call_args.kwargs["service_workers"] == "block"
    browser_api.context.close.assert_called_once()
    browser_api.browser.close.assert_called_once()


def test_call_success_without_verification_is_not_task_success(browser_api):
    result = PlaywrightComputer((ORIGIN,)).execute([NAVIGATE], None, lambda: False)
    assert result["executed"] is True
    assert result["success"] is False and result["verified"] is False
    assert result["status"] == "needs_verification"
    assert result["observation"]["data_url"].startswith("data:image/jpeg;base64,")


def test_failed_verification_retains_observation_and_releases_context(browser_api):
    browser_api.assertion.to_have_value.side_effect = AssertionError("value was wrong")
    result = PlaywrightComputer((ORIGIN,)).execute([NAVIGATE], VERIFY, lambda: False)
    assert result["status"] == "verification_failed"
    assert result["verified"] is False
    assert result["observation"]["url"] == ORIGIN + "/form"
    browser_api.context.close.assert_called_once()


def test_timeout_after_possible_click_is_unknown_and_never_retries(browser_api):
    browser_api.locator.click.side_effect = browser_api.Error("possibly clicked")
    result = PlaywrightComputer((ORIGIN,)).execute(
        [NAVIGATE, {"action": "click", "target": {"role": "button", "name": "保存"}}],
        VERIFY,
        lambda: False,
    )
    assert result["status"] == "outcome_unknown"
    assert result["outcome_unknown"] is True
    assert result["steps_completed"] == 1
    browser_api.locator.click.assert_called_once()
    browser_api.context.close.assert_called_once()
    browser_api.browser.close.assert_called_once()


def test_cancel_during_navigation_stops_following_action(browser_api):
    stopped = False

    def navigate(url, **kwargs):
        nonlocal stopped
        browser_api.page.url = url
        stopped = True

    browser_api.page.goto.side_effect = navigate
    result = PlaywrightComputer((ORIGIN,)).execute(
        [NAVIGATE, {"action": "click", "target": {"selector": "#save"}}], VERIFY, lambda: stopped
    )
    assert result["status"] == "cancelled"
    browser_api.locator.click.assert_not_called()
    browser_api.context.close.assert_called_once()


def test_cross_origin_subresource_is_aborted_and_receipt_fails(browser_api):
    route = Mock()
    route.request.url = "https://unauthorized.test/pixel"

    def navigate(url, **kwargs):
        browser_api.page.url = url
        handler = browser_api.context.route.call_args.args[1]
        handler(route)

    browser_api.page.goto.side_effect = navigate
    result = PlaywrightComputer((ORIGIN,)).execute([NAVIGATE], VERIFY, lambda: False)
    route.abort.assert_called_once_with("blockedbyclient")
    route.continue_.assert_not_called()
    assert result["error_code"] == "computer_origin_denied"
    assert result["success"] is False


@pytest.mark.parametrize("location", [ORIGIN + "/next", "https://other.test/next"])
def test_redirect_is_never_followed_outside_interception(browser_api, location):
    route = Mock()
    route.request.url = ORIGIN + "/form"
    response = route.fetch.return_value
    response.status = 302
    response.headers = {"location": location}

    def navigate(url, **kwargs):
        browser_api.page.url = url
        browser_api.context.route.call_args.args[1](route)

    browser_api.page.goto.side_effect = navigate
    result = PlaywrightComputer((ORIGIN,)).execute([NAVIGATE], VERIFY, lambda: False)
    route.fetch.assert_called_once_with(max_redirects=0, max_retries=0, timeout=5000.0)
    route.abort.assert_called_once_with("blockedbyclient")
    route.fulfill.assert_not_called()
    route.continue_.assert_not_called()
    response.dispose.assert_called_once()
    assert result["error_code"] == "computer_redirect_blocked"


def test_unavailable_browser_does_not_claim_execution(browser_api):
    browser_api.playwright.chromium.launch.side_effect = browser_api.Error("socket denied")
    result = PlaywrightComputer((ORIGIN,)).execute([NAVIGATE], VERIFY, lambda: False)
    assert result["status"] == "unavailable"
    assert result["executed"] is False
    assert result["error_code"] == "computer_backend_unavailable"
    assert "socket" not in result["message"]


def test_popup_and_websocket_are_closed(browser_api):
    result = PlaywrightComputer((ORIGIN,)).execute([NAVIGATE], VERIFY, lambda: False)
    assert result["success"] is True
    popup, socket = Mock(), Mock()
    browser_api.context.on.call_args.args[1](popup)
    browser_api.context.route_web_socket.call_args.args[1](socket)
    popup.close.assert_called_once()
    socket.close.assert_called_once()
