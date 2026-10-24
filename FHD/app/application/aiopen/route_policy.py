"""Route authorization and the canonical target shared with the HTTP gateway."""

from __future__ import annotations

import posixpath
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from .runtime import RuntimeState


@dataclass(frozen=True)
class ApiTarget:
    policy_path: str
    request_url: str


def canonical_api_target(path: str) -> ApiTarget | None:
    raw = str(path or "").strip()
    if not raw or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        return None
    try:
        parts = urlsplit(raw)
        if parts.scheme or parts.netloc or raw.startswith("//"):
            return None
        decoded = unquote(parts.path, errors="strict")
        # HTTP transports may decode twice. Reject nested escapes so that the
        # checked path and the ASGI scope cannot disagree after URL encoding.
        if unquote(decoded, errors="strict") != decoded:
            return None
    except (ValueError, UnicodeError):
        return None
    if (
        not decoded
        or "\\" in decoded
        or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
    ):
        return None
    normalized = posixpath.normpath("/" + decoded.lstrip("/"))
    trailing_slash = decoded.endswith(("/", "/.", "/.."))
    request_path = normalized + ("/" if trailing_slash and normalized != "/" else "")
    request_url = quote(request_path, safe="/")
    if parts.query:
        request_url += "?" + parts.query
    return ApiTarget(normalized, request_url)


def normalize_api_path(path: str) -> str:
    target = canonical_api_target(path)
    return target.policy_path if target else ""


class RoutePolicy:
    def __init__(
        self,
        state: RuntimeState,
        prefixes: Callable[[], tuple[str, ...]],
        normalize: Callable[[str], str],
    ) -> None:
        self._state = state
        self._prefixes = prefixes
        self._normalize = normalize

    def defaults(self) -> dict[str, bool]:
        return dict.fromkeys(self._prefixes(), True)

    def allows(self, path: str, whitelist: dict[str, bool] | None = None) -> bool:
        wl = whitelist if whitelist is not None else self._state.values.get("whitelist", {})
        if not isinstance(wl, dict):
            return False
        target = self._normalize(path)
        if not target:
            return False
        for prefix, enabled in wl.items():
            if enabled:
                normalized = self._normalize(str(prefix or ""))
                if normalized and (target == normalized or target.startswith(normalized + "/")):
                    return True
        return False

    def seed(self, *, enable: bool = True, merge: bool = True) -> dict[str, Any]:
        wl = self._state.values.setdefault("whitelist", {})
        if not isinstance(wl, dict):
            wl = {}
            self._state.values["whitelist"] = wl
        if not merge:
            wl.clear()
        wl.update(dict.fromkeys(self._prefixes(), bool(enable)))
        return {
            "success": True,
            "enabled": bool(enable),
            "merge": bool(merge),
            "enabled_count": sum(1 for enabled in wl.values() if enabled),
            "total_count": len(wl),
            "routes": self.catalog()["routes"],
        }

    def catalog(self) -> dict[str, Any]:
        whitelist = self._state.values.get("whitelist", {})
        return {
            "success": True,
            "match_mode": "exact_or_prefix",
            "routes": [
                {"path": path, "enabled": bool(enabled)}
                for path, enabled in sorted(whitelist.items())
            ],
        }

    def pick_probe(
        self, routes: list[dict[str, Any]], preferred: str, allowed: Callable[[str], bool]
    ) -> str | None:
        pref = self._normalize(preferred)
        if pref and allowed(pref):
            return pref
        enabled = [
            self._normalize(str(r.get("path") or ""))
            for r in routes
            if isinstance(r, dict) and r.get("enabled")
        ]
        enabled = [p for p in enabled if p]
        for candidate in (
            "/api/auth/me",
            "/api/products/list",
            "/api/customers/list",
            "/api/mods/",
            "/api/print/printers",
        ):
            n = self._normalize(candidate)
            if any(n == p or n.startswith(p + "/") or p.startswith(n) for p in enabled):
                if allowed(n):
                    return n if n != "/api/mods" else "/api/mods/"
        return enabled[0] if enabled else None
