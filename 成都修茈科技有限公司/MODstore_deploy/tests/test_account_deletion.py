"""Account deletion must persist and reject every existing credential."""

from __future__ import annotations

import uuid

from modstore_server.auth_service import generate_pat, resolve_pat_identity, resolve_user_from_pat
from modstore_server.models import DeveloperToken, User, get_session_factory


def test_account_delete_revokes_access_and_refresh_without_touching_other_user(client):
    password = "delete-me-pass-12"
    first = client.post(
        "/api/auth/register",
        json={"username": f"delete_{uuid.uuid4().hex[:12]}", "password": password},
    )
    second = client.post(
        "/api/auth/register",
        json={"username": f"active_{uuid.uuid4().hex[:12]}", "password": password},
    )
    assert first.status_code == second.status_code == 200
    first_user = first.json()["user"]
    second_user = second.json()["user"]
    access = first.json()["access_token"]
    refresh = first.json()["refresh_token"]
    first_headers = {"Authorization": f"Bearer {access}"}
    second_headers = {"Authorization": f"Bearer {second.json()['access_token']}"}
    pat, prefix, digest = generate_pat()
    with get_session_factory()() as session:
        session.add(
            DeveloperToken(
                user_id=first_user["id"], name="delete-test", token_prefix=prefix, token_hash=digest
            )
        )
        session.commit()
    assert resolve_user_from_pat(pat) is not None

    deleted = client.post(
        "/api/auth/account/delete", json={"password": password}, headers=first_headers
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["ok"] is True
    with get_session_factory()() as session:
        removed = session.get(User, first_user["id"])
        active = session.get(User, second_user["id"])
        assert removed.deleted_at is not None
        assert active.deleted_at is None

    assert client.get("/api/auth/export", headers=first_headers).status_code == 401
    assert resolve_user_from_pat(pat) is None
    assert resolve_pat_identity(pat) is None
    assert client.post("/api/auth/refresh", json={"refresh_token": refresh}).status_code == 401
    assert (
        client.post(
            "/api/auth/login",
            json={"username": first_user["username"], "password": password},
        ).status_code
        == 401
    )
    assert client.get("/api/auth/export", headers=second_headers).status_code == 200
    assert (
        client.post(
            "/api/auth/login",
            json={"username": second_user["username"], "password": password},
        ).status_code
        == 200
    )
