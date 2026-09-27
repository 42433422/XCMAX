"""Account deletion must persist and reject every existing credential."""

from __future__ import annotations

import asyncio
import importlib
import uuid

import pytest
from starlette.websockets import WebSocketDisconnect

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


@pytest.mark.parametrize(
    "path,first_messages",
    [
        ("/api/workbench/voice/s2s/ws", ["ready"]),
        ("/api/workbench/voice/unified/ws", ["ready", "connected"]),
        ("/api/asr/funasr", ["connected"]),
        ("/api/realtime/ws", ["ready"]),
    ],
)
def test_account_delete_revokes_existing_websocket(client, monkeypatch, path, first_messages):
    class FakeFunasr:
        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(3600)
            raise StopAsyncIteration

        async def send(self, _data):
            return None

        async def close(self):
            return None

    async def fake_connect(_urls, _ssl):
        return "ws://test.invalid", FakeFunasr()

    asr = importlib.import_module("modstore_server.asr_proxy_ws")
    unified = importlib.import_module("modstore_server.voice_unified_ws")
    monkeypatch.setattr(asr, "_connect_funasr_parallel", fake_connect)
    monkeypatch.setattr(unified, "_connect_funasr_parallel", fake_connect)

    username = f"delete_ws_{uuid.uuid4().hex[:12]}"
    password = "delete-me-pass-12"
    registered = client.post(
        "/api/auth/register", json={"username": username, "password": password}
    )
    assert registered.status_code == 200, registered.text
    token = registered.json()["access_token"]
    with client.websocket_connect(f"{path}?token={token}") as ws:
        for expected in first_messages:
            assert ws.receive_json()["type"] == expected
        deleted = client.post(
            "/api/auth/account/delete",
            json={"password": password},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert deleted.status_code == 200, deleted.text
        ws.send_json(
            {"type": "utterance", "text": "hello", "provider": "openai", "model": "test"}
            if path.endswith("/s2s/ws")
            else {"type": "ping"}
        )
        if path.endswith("/s2s/ws"):
            assert ws.receive_json()["type"] == "error"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008
