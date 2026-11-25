"""The same strict locator construction for Playwright's sync and async APIs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.domain.browser_policy import css_selector, locator_strategy


def resolve_locator(page: Any, spec: Mapping[str, Any], frame: str | None = None) -> Any:
    key = locator_strategy(spec)
    target = page.frame_locator(css_selector(frame)) if frame else page
    if key == "role":
        return target.get_by_role(spec[key], name=spec.get("name"), exact=True)
    if key == "selector":
        return target.locator(css_selector(spec[key]))
    if key == "test_id":
        return target.get_by_test_id(spec[key])
    return getattr(target, f"get_by_{key}")(spec[key], exact=True)
