# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.planner_compat_execute")._facade()


def _request_session_candidates(request: _facade().Request) -> list[str]:
    """Return possible *host* session ids without mistaking the market token for one.

    Desktop chat requests intentionally carry both the local ``session_id`` cookie
    and a 修茈市场 bearer token.  The generic compatibility extractor prefers the
    bearer value, which is correct for model proxying but is not a host session id.
    Industry/persona lookup must therefore try the explicit host session sources
    before that compatibility value.
    """
    candidates: list[str] = []

    def _append(raw: _facade().Any) -> None:
        value = raw.strip() if isinstance(raw, str) else ""
        if value and value not in candidates:
            candidates.append(value)

    headers = getattr(request, "headers", {}) or {}
    cookies = getattr(request, "cookies", {}) or {}
    try:
        _append(headers.get("X-Session-ID"))
    except (AttributeError, TypeError):
        pass
    cookie_name = (_facade().os.environ.get("SESSION_COOKIE_NAME") or "session_id").strip()
    try:
        _append(cookies.get(cookie_name))
    except (AttributeError, TypeError):
        pass
    try:
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

        _append(_session_id_from_request(request))
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("planner session candidate extraction failed", exc_info=True)
    return candidates
