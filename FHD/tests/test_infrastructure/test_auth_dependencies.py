from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.infrastructure.auth.dependencies import resolve_session_user


def test_invalid_bearer_falls_back_to_valid_desktop_session_cookie(monkeypatch) -> None:
    """Market tokens must not hide a valid same-origin FHD desktop session."""
    session_service = MagicMock()
    desktop_user = SimpleNamespace(id=2)
    session_service.validate_session.side_effect = lambda session_id: (
        desktop_user if session_id == "desktop-session" else None
    )
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_session_service",
        lambda: session_service,
    )
    monkeypatch.setattr(
        "app.application.desktop_admin_gate.assert_desktop_allows_session_id",
        lambda _session_id: None,
    )
    monkeypatch.setattr(
        "app.security.web_jwt.resolve_user_from_web_jwt",
        lambda _token: None,
    )

    request = SimpleNamespace(
        headers={"Authorization": "Bearer market-access-token"},
        cookies={"session_id": "desktop-session"},
    )

    assert resolve_session_user(request) is desktop_user
    assert session_service.validate_session.call_args_list == [
        (("market-access-token",), {}),
        (("desktop-session",), {}),
    ]


def test_valid_bearer_session_remains_preferred_to_cookie(monkeypatch) -> None:
    session_service = MagicMock()
    bearer_user = SimpleNamespace(id=3)
    session_service.validate_session.side_effect = lambda session_id: (
        bearer_user if session_id == "bearer-session" else None
    )
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_session_service",
        lambda: session_service,
    )
    monkeypatch.setattr(
        "app.application.desktop_admin_gate.assert_desktop_allows_session_id",
        lambda _session_id: None,
    )

    request = SimpleNamespace(
        headers={"Authorization": "Bearer bearer-session"},
        cookies={"session_id": "desktop-session"},
    )

    assert resolve_session_user(request) is bearer_user
    assert session_service.validate_session.call_args_list == [
        (("bearer-session",), {}),
    ]


def test_desktop_session_cookie_is_resolved_without_authorization_header(monkeypatch) -> None:
    session_service = MagicMock()
    desktop_user = SimpleNamespace(id=2)
    session_service.validate_session.return_value = desktop_user
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_session_service",
        lambda: session_service,
    )
    monkeypatch.setattr(
        "app.application.desktop_admin_gate.assert_desktop_allows_session_id",
        lambda _session_id: None,
    )

    request = SimpleNamespace(headers={}, cookies={"session_id": "desktop-session"})

    assert resolve_session_user(request) is desktop_user
    session_service.validate_session.assert_called_once_with("desktop-session")


def test_invalid_explicit_mobile_session_does_not_fall_back_to_cookie(monkeypatch) -> None:
    session_service = MagicMock()
    session_service.validate_session.return_value = None
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_session_service",
        lambda: session_service,
    )
    monkeypatch.setattr(
        "app.application.desktop_admin_gate.assert_desktop_allows_session_id",
        lambda _session_id: None,
    )
    monkeypatch.setattr(
        "app.security.web_jwt.resolve_user_from_web_jwt",
        lambda _token: None,
    )

    request = SimpleNamespace(
        headers={"X-Session-ID": "invalid-mobile-session"},
        cookies={"session_id": "desktop-session"},
    )

    assert resolve_session_user(request) is None
    session_service.validate_session.assert_called_once_with("invalid-mobile-session")
