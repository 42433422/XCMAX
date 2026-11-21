"""Allowed browser actions and bounded autonomy rules, independent of adapters."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

MAX_BROWSER_STEPS = 32
MAX_BROWSER_DECISIONS = 12
MAX_BROWSER_SECONDS = 300
BROWSER_ACTIONS = frozenset(
    {
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_fill_form",
        "browser_select_option",
        "browser_press_key",
        "browser_wait_for",
        "browser_tabs",
        "browser_navigate_back",
        "browser_take_screenshot",
    }
)
BROWSER_OBSERVATIONS = frozenset(
    {"browser_snapshot", "browser_wait_for", "browser_take_screenshot"}
)


def browser_action_allowed(action: str, params: dict[str, Any]) -> bool:
    if action not in BROWSER_ACTIONS:
        return False
    if any(str(key).startswith("_") or key in {"filename", "files", "file_path"} for key in params):
        return False
    if action == "browser_navigate" or "url" in params:
        try:
            url = urlsplit(str(params.get("url") or ""))
            return bool(
                url.scheme in {"http", "https"}
                and url.hostname
                and url.username is None
                and url.password is None
            )
        except ValueError:
            return False
    return True
