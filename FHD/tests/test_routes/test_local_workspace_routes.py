"""Exercise the actual paired-device listener without an internet service."""

from __future__ import annotations

import itertools
import time
from urllib.parse import urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import local_workspace as routes
from app.middleware.csrf import CSRFMiddleware

DESK = "1" * 32
PHONE = "2" * 32


def change(op_id, record_id, name, base=None):
    return {
        "op_id": op_id * 32,
        "id": record_id,
        "kind": "customer",
        "data": {"name": name},
        "deleted": False,
        "base_version": base,
    }


@pytest.fixture
def local_desktop(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(routes, "_lan_address", lambda: "192.168.1.19")
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)
    app.include_router(routes.router)
    with TestClient(
        app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 1234),
        headers={"X-XCAGI-Desktop-Local": "1"},
    ) as client:
        yield client
    stop_peer()


def stop_peer():
    peer = routes._current_peer()
    if peer.server:
        peer.server.should_exit = True
        assert peer.thread is not None
        peer.thread.join(5)
    routes._peer.cache_clear()


def phone_connection(qr):
    cipher = AESGCM(routes._decode(qr["key"]))
    address = urlsplit(qr["endpoint"])
    url = f"http://127.0.0.1:{address.port}{address.path}"
    client = httpx.Client(trust_env=False, timeout=3)
    ids = itertools.count(1)

    def call(action, *, request_id=None, **payload):
        n = next(ids)
        request_id = request_id or str(n)
        nonce = n.to_bytes(12, "big")
        sealed = cipher.encrypt(
            nonce,
            routes.LocalPeer._serialize({"request_id": request_id, "action": action, **payload}),
            routes._REQUEST_AAD,
        )
        response = client.post(
            url, json={"box": routes._encode(sealed), "nonce": routes._encode(nonce)}
        )
        response.raise_for_status()
        wire = response.json()
        import json

        data = json.loads(
            cipher.decrypt(
                routes._decode(wire["nonce"]), routes._decode(wire["box"]), routes._RESPONSE_AAD
            )
        )
        assert data["request_id"] == request_id
        return data

    deadline = time.monotonic() + 3
    while not routes._current_peer().server.started:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    return client, call


def test_desktop_seed_bidirectional_exchange_replay_conflict_and_unbind(local_desktop):
    desktop = local_desktop
    initial = desktop.get("/api/local-workspace/status").json()
    workspace_id = initial["workspace_id"]
    assert desktop.post(
        "/api/local-workspace/records",
        json={"workspace_id": workspace_id, "operations": [change("a", DESK, "Desktop")]},
    ).json()["accepted"] == ["a" * 32]
    qr = desktop.post("/api/local-workspace/pairing").json()["qr"]
    assert qr["endpoint"].startswith("http://192.168.1.19:")
    client, call = phone_connection(qr)
    with client:
        seed = call("bind", origin="desktop", request_id="same-binding-attempt")
        assert seed["records"][0]["id"] == DESK
        assert call("bind", origin="desktop", request_id="same-binding-attempt") == seed
        pending = {"workspace_id": workspace_id, "operations": [change("b", PHONE, "Phone")]}
        assert call("push", **pending)["accepted"] == ["b" * 32]
        assert call("push", **pending)["accepted"] == ["b" * 32]
        assert desktop.post(
            "/api/local-workspace/records",
            json={"workspace_id": workspace_id, "operations": [change("c", DESK, "New", "a" * 32)]},
        ).json()["accepted"] == ["c" * 32]
        stop_peer()
        routes.resume_local_workspace()
        assert call("bind", origin="desktop", request_id="same-binding-attempt") == seed
        assert call(
            "push", workspace_id=workspace_id, operations=[change("d", DESK, "Conflict", "a" * 32)]
        )["conflicts"][0]["current"]["data"] == {"name": "New"}
        first = call("pull", workspace_id=workspace_id, after=seed["cursor"], limit=1)
        assert first["has_more"] and first["changes"][0]["record"]["id"] == PHONE
        second = call("pull", workspace_id=workspace_id, after=first["cursor"], limit=1)
        assert not second["has_more"] and second["changes"][0]["record"]["data"] == {"name": "New"}
        assert call("unbind", workspace_id=workspace_id)["unbound"]
        with pytest.raises(httpx.HTTPStatusError, match="401"):
            call("pull", workspace_id=workspace_id, after=0)
    assert desktop.get("/api/local-workspace/status").json()["record_count"] == 2


def test_mobile_seed_archives_original_desktop_and_restore_after_unbind(local_desktop):
    desktop = local_desktop
    before = desktop.get("/api/local-workspace/status").json()["workspace_id"]
    desktop.post(
        "/api/local-workspace/records",
        json={"workspace_id": before, "operations": [change("a", DESK, "Old desk")]},
    ).raise_for_status()
    qr = desktop.post("/api/local-workspace/pairing").json()["qr"]
    client, call = phone_connection(qr)
    with client:
        request = {
            "origin": "mobile",
            "request_id": "same-binding-attempt",
            "records": [
                {
                    "id": PHONE,
                    "kind": "customer",
                    "version": "b" * 32,
                    "deleted": False,
                    "data": {"name": "Phone seed"},
                }
            ],
        }
        bound = call("bind", **request)
        assert bound["workspace_id"] != before
        assert bound["records"][0]["id"] == PHONE
        assert desktop.post(
            "/api/local-workspace/records",
            json={
                "workspace_id": bound["workspace_id"],
                "operations": [change("c", DESK, "After seed")],
            },
        ).json()["accepted"] == ["c" * 32]
        stop_peer()
        routes.resume_local_workspace()
        assert call("bind", **request) == bound
        assert len(desktop.get("/api/local-workspace/status").json()["archives"]) == 1
        followup = call("pull", workspace_id=bound["workspace_id"], after=bound["cursor"])
        assert followup["changes"][0]["record"]["data"] == {"name": "After seed"}
        assert call("unbind", workspace_id=bound["workspace_id"])["unbound"]
    stop_peer()
    routes.resume_local_workspace()
    assert routes._current_peer().server is None
    result = desktop.post(
        f"/api/local-workspace/archives/{bound['archive_id']}/restore",
        json={"workspace_id": bound["workspace_id"]},
    ).json()
    assert result["workspace_id"] not in (before, bound["workspace_id"])
    assert desktop.get("/api/local-workspace/records").json()["records"][0]["id"] == DESK


def test_management_requests_require_loopback_and_desktop_mode(local_desktop, monkeypatch):
    assert (
        local_desktop.post(
            "/api/local-workspace/pairing", headers={"x-xcagi-desktop-local": "0"}
        ).status_code
        == 403
    )
    assert (
        local_desktop.get(
            "/api/local-workspace/status", headers={"host": "external.invalid"}
        ).status_code
        == 403
    )
    assert (
        local_desktop.post(
            "/api/local-workspace/pairing", headers={"origin": "https://external.invalid"}
        ).status_code
        == 403
    )
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    assert local_desktop.get("/api/local-workspace/status").status_code == 404
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    with TestClient(
        local_desktop.app,
        base_url="http://127.0.0.1",
        client=("203.0.113.9", 1234),
        headers={"X-XCAGI-Desktop-Local": "1", "X-Forwarded-For": "127.0.0.1"},
    ) as remote:
        for resource in ("status", "records", "archives"):
            assert remote.get(f"/api/local-workspace/{resource}").status_code == 404


def test_startup_only_opens_an_existing_desktop_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    routes.resume_local_workspace()
    assert not (tmp_path / routes._DATABASE).exists()


def test_workspace_database_failure_does_not_block_desktop_startup(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    db = tmp_path / routes._DATABASE
    db.parent.mkdir()
    db.write_bytes(b"damaged database")

    routes.resume_local_workspace()

    assert "Desktop local workspace database could not open" in caplog.text
    assert db.read_bytes() == b"damaged database"


def test_archive_http_pages_are_bounded_and_device_only(local_desktop):
    store = routes._current_peer().store
    for _ in range(3):
        store.bind_peer(
            {}, records=[], workspace_id=store.status()["workspace_id"], max_snapshot_bytes=65536
        )
        store.unbind_peer()
    status = local_desktop.get("/api/local-workspace/status").json()
    first = local_desktop.get("/api/local-workspace/archives?limit=2").json()
    last = local_desktop.get("/api/local-workspace/archives?limit=2&offset=2").json()
    assert status["archives_total"] == first["total"] == last["total"] == 3
    assert first["archives"] + last["archives"] == status["archives"]
    for query in ("limit=101", "limit=0", "offset=-1", f"offset={2**63}"):
        assert local_desktop.get(f"/api/local-workspace/archives?{query}").status_code == 422
    assert (
        local_desktop.get(
            "/api/local-workspace/archives", headers={"x-xcagi-desktop-local": "0"}
        ).status_code
        == 403
    )


def test_large_pull_pages_bound_allocation_and_preserve_every_change(local_desktop, monkeypatch):
    qr = local_desktop.post("/api/local-workspace/pairing").json()["qr"]
    client, call = phone_connection(qr)
    with client:
        bound = call("bind", origin="desktop")
        store = routes._current_peer().store
        store.apply(
            [change(str(index), f"customer-{index}", "x" * 64000) for index in range(100)],
            workspace_id=bound["workspace_id"],
        )
        serialize = routes.LocalPeer._serialize
        sizes = []

        def measured(payload):
            raw = serialize(payload)
            sizes.append(len(raw))
            return raw

        monkeypatch.setattr(routes.LocalPeer, "_serialize", staticmethod(measured))
        after = 0
        seen = []
        for _ in range(5):
            page = call("pull", workspace_id=bound["workspace_id"], after=after, limit=500)
            assert max(sizes) <= routes._PAYLOAD_LIMIT
            assert len(page["changes"]) == 20
            seen.extend(row["seq"] for row in page["changes"])
            after = page["cursor"]
        assert not page["has_more"]
        assert seen == list(range(1, 101))


def test_pairing_rejects_expired_replaced_keys_and_wrong_aad(local_desktop):
    qr = local_desktop.post("/api/local-workspace/pairing").json()["qr"]
    client, call = phone_connection(qr)
    peer = routes._current_peer()
    assert peer.invitation is not None
    key, _, workspace_id = peer.invitation
    peer.invitation = (key, time.monotonic() - 1, workspace_id)
    with client:
        with pytest.raises(httpx.HTTPStatusError, match="401"):
            call("bind", origin="mobile", records=[])
        replacement = local_desktop.post("/api/local-workspace/pairing").json()["qr"]
        with pytest.raises(httpx.HTTPStatusError, match="401"):
            call("bind", origin="mobile", records=[])
        nonce = b"0" * 12
        sealed = AESGCM(routes._decode(replacement["key"])).encrypt(
            nonce,
            routes.LocalPeer._serialize({"request_id": "bad", "action": "bind"}),
            routes._RESPONSE_AAD,
        )
        reply = client.post(
            f"http://127.0.0.1:{peer.port}{routes._PEER_PATH}",
            json={"nonce": routes._encode(nonce), "box": routes._encode(sealed)},
        )
        assert reply.status_code == 401
    assert peer.store.status()["workspace_id"] == workspace_id
    assert not peer.binding and peer.store.archives() == []


def test_lan_listener_rejects_public_browser_and_oversized_requests(local_desktop):
    app = FastAPI()
    app.add_api_route(routes._PEER_PATH, routes._current_peer().exchange, methods=["POST"])
    with TestClient(app, client=("203.0.113.9", 1234)) as remote:
        assert remote.post(routes._PEER_PATH, json={}).status_code == 403
    with TestClient(app, client=("192.168.1.22", 1234)) as local:
        assert (
            local.post(
                routes._PEER_PATH, json={}, headers={"origin": "http://127.0.0.1"}
            ).status_code
            == 403
        )
        assert (
            local.post(routes._PEER_PATH, content=b"x" * (routes._PACKET_LIMIT + 1)).status_code
            == 413
        )
        assert local.post(routes._PEER_PATH, json={}).status_code == 401
