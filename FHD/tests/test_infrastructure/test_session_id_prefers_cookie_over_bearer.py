"""session_id_from_request：本地 Cookie 优先于市场 Authorization Bearer。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.infrastructure.auth.dependencies import session_id_from_request


def _req(*, headers: dict | None = None, cookies: dict | None = None):
    return SimpleNamespace(headers=headers or {}, cookies=cookies or {})


class TestSessionIdPrefersCookieOverBearer:
    def test_cookie_wins_when_bearer_present(self):
        req = _req(
            headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.market.token"},
            cookies={"session_id": "local-desktop-session"},
        )
        assert session_id_from_request(req) == "local-desktop-session"

    def test_bearer_used_when_no_cookie(self):
        req = _req(headers={"Authorization": "Bearer only-bearer-sid"})
        assert session_id_from_request(req) == "only-bearer-sid"

    def test_x_session_id_still_highest_priority(self):
        req = _req(
            headers={
                "X-Session-ID": "mobile-sid",
                "Authorization": "Bearer eyJ.market",
            },
            cookies={"session_id": "cookie-sid"},
        )
        assert session_id_from_request(req) == "mobile-sid"

    def test_cookie_only(self):
        req = _req(cookies={"session_id": "cookie-only"})
        assert session_id_from_request(req) == "cookie-only"
