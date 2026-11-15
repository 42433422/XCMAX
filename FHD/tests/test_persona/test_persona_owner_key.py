"""拟人 Persy 的持久化键必须是账号级，而不是按对话会话分片。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.application.planner_compat.persona import resolve_persona_owner_id


def _request(headers: dict[str, str] | None = None) -> MagicMock:
    request = MagicMock()
    request.headers = headers or {}
    return request


def test_prefers_authenticated_account_over_chat_session():
    body = SimpleNamespace(user_id="web_normal_mwi61n1zjnant9bb6o")
    with patch(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        return_value=SimpleNamespace(id=2),
    ):
        assert resolve_persona_owner_id(_request(), body) == "2"


def test_falls_back_to_numeric_header_then_legacy_body():
    body = SimpleNamespace(user_id="web_normal_session")
    with patch(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        return_value=None,
    ):
        assert resolve_persona_owner_id(_request({"X-User-ID": "7"}), body) == "7"
        assert resolve_persona_owner_id(_request(), body) == "web_normal_session"
