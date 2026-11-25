"""The two browser entry points retain exact destinations and locator contracts."""

import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.application.tools.browser import allowed_origins
from app.desktop_automation.computer_browser import BrowserTarget, PlaywrightComputer
from app.desktop_automation.computer_browser import _locator as computer_locator
from app.domain.browser_contract import BrowserLocator
from app.infrastructure.browser.runtime import _locator as agent_locator
from app.infrastructure.browser.runtime import _origin


@pytest.mark.parametrize(
    "configured,canonical",
    [
        ("https://BÜCHER.example:443/", "https://xn--bcher-kva.example"),
        ("http://EXAMPLE.test:80", "http://example.test"),
        ("https://example.test:8443", "https://example.test:8443"),
        ("https://[2001:0DB8:0:0:0:0:0:1]:443", "https://[2001:db8::1]"),
        ("http://[::1]:0", "http://[::1]:0"),
    ],
)
def test_both_browser_policies_use_the_same_exact_origin(monkeypatch, configured, canonical):
    monkeypatch.setenv("XCAGI_BROWSER_ALLOWED_ORIGINS", json.dumps({"tenant-a": [configured]}))
    computer = PlaywrightComputer((configured,))
    assert computer.allowed_origins == allowed_origins("tenant-a") == frozenset({canonical})
    assert computer._allowed(canonical + "/page?request=one")
    assert _origin(canonical + "/page?request=one") == canonical
    assert not computer._allowed("https://another.example/page")


@pytest.mark.parametrize(
    "configured",
    [
        "https://user:secret@example.test",
        "https://example.test\\@another.example",
        "https://*.example.test",
        "https://%65xample.test",
        "https://example.test\x7f",
        "https://example.test/path",
        "https://example.test?token=secret",
        "https://example.test#fragment",
        "file:///tmp/page.html",
    ],
)
def test_invalid_configured_origins_are_rejected_by_both_entry_points(monkeypatch, configured):
    monkeypatch.setenv("XCAGI_BROWSER_ALLOWED_ORIGINS", json.dumps({"tenant-a": [configured]}))
    with pytest.raises(ValueError):
        allowed_origins("tenant-a")
    with pytest.raises(ValueError):
        PlaywrightComputer((configured,))


def test_shared_locator_keeps_css_engine_and_each_entry_point_constraints():
    page = Mock()
    agent_locator(page, {"selector": "#save"})
    computer_locator(page, BrowserTarget(selector="#save"))
    assert page.locator.call_args_list == [(("css=#save",),), (("css=#save",),)]
    for schema in (BrowserLocator, BrowserTarget):
        with pytest.raises(ValidationError):
            schema(selector="#form >> text=Save")
        with pytest.raises(ValidationError):
            schema(role="button", label="Save")
    with pytest.raises(ValidationError):
        BrowserLocator(test_id="save")
    with pytest.raises(ValidationError):
        BrowserTarget(text="Save")
    with pytest.raises(ValidationError):
        BrowserTarget(role="tree")
    assert BrowserLocator(role="tree").role == "tree"
