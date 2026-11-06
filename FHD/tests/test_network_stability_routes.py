"""Authentication regression checks for the locally gated stability probe."""

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.infrastructure.session import session_manager
from tests.fixtures import stability_runtime as runtime


def _request(scheme):
    return Request(
        {
            "type": "http",
            "scheme": scheme,
            "server": ("localhost", 80),
            "path": "/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
        }
    )


@pytest.mark.parametrize("scheme,secure", [("http", False), ("https", True)])
async def test_lab_session_and_refresh_cookie_match_transport(monkeypatch, scheme, secure):
    issued = {"session_id": "s1", "refresh_token": "r1", "user_id": 1, "tenant_id": 1}
    monkeypatch.setattr(runtime, "_lab_user", lambda slot: issued)
    monkeypatch.setattr(runtime, "_read_refresh", lambda token: {"jti": "j1", "uid": 1})
    monkeypatch.setattr(runtime, "_consume_refresh", lambda payload: True)
    monkeypatch.setattr(runtime, "_issue_refresh", lambda uid: "r2")
    monkeypatch.setattr(
        session_manager,
        "get_session_manager",
        lambda: SimpleNamespace(create_session=lambda uid: {"session_id": "s2"}),
    )
    for response in (
        await runtime.lab_session(_request(scheme), {}),
        await runtime.lab_refresh(_request(scheme), {"refresh_token": "r1"}),
    ):
        cookie = response.headers["set-cookie"]
        assert ("; Secure" in cookie) is secure
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie


async def test_concurrent_refreshes_do_not_share_another_users_session(monkeypatch):
    first_entered, release = threading.Event(), threading.Event()
    consumed = set()
    calls = []

    def consume(payload):
        key = payload["jti"]
        if key in consumed:
            return False
        consumed.add(key)
        return True

    def create(uid):
        calls.append(uid)
        if uid == 1:
            first_entered.set()
            assert release.wait(timeout=2)
        return {"session_id": f"session-{uid}"}

    monkeypatch.setattr(runtime, "_read_refresh", lambda token: {"jti": token, "uid": int(token)})
    monkeypatch.setattr(runtime, "_consume_refresh", consume)
    monkeypatch.setattr(runtime, "_issue_refresh", lambda uid: f"refresh-{uid}")
    monkeypatch.setattr(
        session_manager, "get_session_manager", lambda: SimpleNamespace(create_session=create)
    )
    first = asyncio.create_task(runtime.lab_refresh(_request("http"), {"refresh_token": "1"}))
    assert await asyncio.to_thread(first_entered.wait, 1)
    duplicate = asyncio.create_task(runtime.lab_refresh(_request("http"), {"refresh_token": "1"}))
    try:
        other = await runtime.lab_refresh(_request("http"), {"refresh_token": "2"})
        assert json.loads(other.body)["session_id"] == "session-2"
    finally:
        release.set()
    replies = await asyncio.gather(first, duplicate)
    assert all(json.loads(response.body)["session_id"] == "session-1" for response in replies)
    assert sorted(calls) == [1, 2]
    replay = await runtime.lab_refresh(_request("http"), {"refresh_token": "1"})
    assert replay.status_code == 401
