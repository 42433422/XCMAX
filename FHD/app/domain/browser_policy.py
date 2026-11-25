"""Shared destination and locator rules for the existing Playwright adapters."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit


def canonical_origin(url: str, *, configured: bool = False) -> str:
    """Normalize one exact HTTP(S) origin without accepting ambiguous authorities."""
    if not isinstance(url, str) or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise ValueError("invalid_browser_destination")
    if "\\" in url:
        raise ValueError("invalid_browser_destination")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("http_origin_without_credentials_required")
    if configured and (parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("configure_exact_browser_origins")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    if "*" in host or "%" in host:
        raise ValueError("invalid_browser_host")
    if ":" in host:
        host = f"[{ipaddress.IPv6Address(host).compressed}]"
    port = parsed.port
    default = {"http": 80, "https": 443}[parsed.scheme]
    return f"{parsed.scheme}://{host}" + (
        f":{port}" if port is not None and port != default else ""
    )


def receipt_url(url: str) -> str:
    """Keep the document path while omitting query and fragment credentials."""
    return urlsplit(url)._replace(query="", fragment="").geturl()


def css_selector(value: str) -> str:
    """Select the CSS engine explicitly; plans cannot chain locator engines."""
    if not isinstance(value, str) or not value or ">>" in value:
        raise ValueError("single_css_selector_required")
    return "css=" + value


def locator_strategy(spec: Mapping[str, Any]) -> str:
    keys = [key for key in ("role", "label", "text", "test_id", "selector") if spec.get(key)]
    if len(keys) != 1 or (spec.get("name") is not None and keys[0] != "role"):
        raise ValueError("browser_locator_requires_one_strategy")
    key = keys[0]
    if not isinstance(spec[key], str):
        raise ValueError("browser_locator_requires_text")
    if key == "selector":
        css_selector(spec[key])
    return key
