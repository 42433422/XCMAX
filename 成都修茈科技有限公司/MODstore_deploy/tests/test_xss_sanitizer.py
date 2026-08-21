from __future__ import annotations

import pytest

from modstore_server.api.xss_sanitizer import _sanitize_value, _strip_script_elements


@pytest.mark.parametrize(
    "payload",
    [
        "before<script>alert(1)</script>after",
        "before<ScRiPt src=x>ignored</sCrIpT>after",
        "before<script>alert(1)</script\t\n ignored>after",
    ],
)
def test_strip_script_elements_handles_browser_end_tag_variants(payload: str) -> None:
    assert _strip_script_elements(payload) == "beforeafter"


def test_sanitize_value_recurses_without_html_escaping_legitimate_text() -> None:
    value = {
        "nested": [
            "a & b",
            "<!DOCTYPE html><b>kept</b><script>removed</script>",
        ],
    }

    assert _sanitize_value(value) == {
        "nested": ["a & b", "<!DOCTYPE html><b>kept</b>"]
    }
