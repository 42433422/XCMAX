"""Exercise the actual paired-device listener without an internet service."""

from __future__ import annotations

import errno
import itertools
import json
import socket
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest
import uvicorn
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import local_workspace as routes
from app.middleware.csrf import CSRFMiddleware

DESK = "1" * 32
PHONE = "2" * 32
CAPABILITY = "a" * 64
LOCAL_HEADERS = {
    "X-XCAGI-Desktop-Local": "1",
    "X-XCAGI-Workspace-Capability": CAPABILITY,
}


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
    monkeypatch.setenv("XCAGI_DESKTOP_WORKSPACE_TOKEN", CAPABILITY)
    monkeypatch.setattr(routes, "_lan_address", lambda: "127.0.0.1")
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)
    app.include_router(routes.router)
    with TestClient(
        app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 1234),
        headers=LOCAL_HEADERS.copy(),
    ) as client:
        yield client
    stop_peer()


@contextmanager
def loopback_http(app):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        server = uvicorn.Server(
            uvicorn.Config(
                app, access_log=False, proxy_headers=False, lifespan="off", log_level="error"
            )
        )
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 3
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline
                time.sleep(0.01)
            with httpx.Client(
                base_url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                headers={"X-XCAGI-Desktop-Local": "1"},
                trust_env=False,
                timeout=3,
            ) as client:
                yield client
        finally:
            server.should_exit = True
            thread.join(5)
            assert not thread.is_alive()


def stop_peer():
    peer = routes._current_peer()
    if peer.server:
        peer.server.should_exit = True
        assert peer.thread is not None
        peer.thread.join(5)
    routes._peer.cache_clear()


def phone_connection(qr):
    cipher = AESGCM(routes._decode(qr["key"]))
    url = qr["endpoint"]
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


def test_desktop_seed_bidirectional_exchange_replay_conflict_and_unbind(local_desktop, monkeypatch):
    desktop = local_desktop
    initial = desktop.get("/api/local-workspace/status").json()
    workspace_id = initial["workspace_id"]
    assert desktop.post(
        "/api/local-workspace/records",
        json={"workspace_id": workspace_id, "operations": [change("a", DESK, "Desktop")]},
    ).json()["accepted"] == ["a" * 32]
    qr = desktop.post("/api/local-workspace/pairing").json()["qr"]
    assert qr["endpoint"].startswith("http://127.0.0.1:")
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
        assert routes._current_peer().store.peer_binding()["host"] == "127.0.0.1"
        stop_peer()
        # A changed default route must not move a saved pairing to another interface.
        monkeypatch.setattr(routes, "_lan_address", lambda: "127.0.0.2")
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


def test_listener_only_accepts_connections_to_the_advertised_interface(local_desktop):
    qr = local_desktop.post("/api/local-workspace/pairing").json()["qr"]
    client, call = phone_connection(qr)
    with client:
        assert call("bind", origin="desktop")["success"]
        unselected = qr["endpoint"].replace("127.0.0.1", "127.0.0.2")
        with pytest.raises(httpx.ConnectError):
            client.post(unselected, json={})


@pytest.mark.parametrize(
    "host", ["", "0.0.0.0", "::", "::1", "localhost", "203.0.113.4", "not-an-address"]
)
def test_listener_rejects_nonlocal_or_non_ipv4_addresses_before_opening_socket(
    tmp_path, monkeypatch, host
):
    peer = routes.LocalPeer(tmp_path)
    monkeypatch.setattr(routes, "_lan_address", lambda: host)

    def unexpected_socket(*args, **kwargs):
        pytest.fail("An invalid IPv4 listener address must not allocate a socket")

    monkeypatch.setattr(routes.socket, "socket", unexpected_socket)
    with pytest.raises(OSError, match="No local interface"):
        peer.start()
    assert peer.server is None and peer.thread is None
    assert peer.host == "" and peer.port == 0


def test_repair_on_a_new_interface_retires_the_old_listener(local_desktop, monkeypatch):
    qr = local_desktop.post("/api/local-workspace/pairing").json()["qr"]
    client, _ = phone_connection(qr)
    peer = routes._current_peer()
    old_thread = peer.thread
    monkeypatch.setattr(routes, "_lan_address", lambda: "127.0.0.2")
    replacement = local_desktop.post("/api/local-workspace/pairing").json()["qr"]
    assert urlsplit(replacement["endpoint"]).port == urlsplit(qr["endpoint"]).port
    assert peer.thread is not old_thread
    assert old_thread is not None
    old_thread.join(5)
    assert not old_thread.is_alive()
    with client, pytest.raises(httpx.ConnectError):
        client.post(qr["endpoint"], json={})
    new_client, call = phone_connection(replacement)
    with new_client:
        assert call("bind", origin="desktop")["success"]


@pytest.mark.parametrize("unavailable", ["wildcard", "occupied"])
def test_unavailable_interface_does_not_replace_an_active_invitation(
    local_desktop, monkeypatch, unavailable
):
    qr = local_desktop.post("/api/local-workspace/pairing").json()["qr"]
    client, call = phone_connection(qr)
    peer = routes._current_peer()
    old_thread, invitation = peer.thread, peer.invitation
    with routes.socket.socket(routes.socket.AF_INET, routes.socket.SOCK_STREAM) as occupied:
        if unavailable == "occupied":
            occupied.bind(("127.0.0.2", peer.port))
            occupied.listen(1)
        host = "127.0.0.2" if unavailable == "occupied" else "0.0.0.0"
        monkeypatch.setattr(routes, "_lan_address", lambda: host)
        assert local_desktop.post("/api/local-workspace/pairing").status_code == 503
    assert peer.thread is old_thread and peer.invitation == invitation
    with client:
        assert call("bind", origin="desktop")["success"]


def test_legacy_binding_without_host_resumes_on_selected_interface(local_desktop):
    qr = local_desktop.post("/api/local-workspace/pairing").json()["qr"]
    client, call = phone_connection(qr)
    with client:
        bound = call("bind", origin="desktop")
        store = routes._current_peer().store
        legacy = store.peer_binding()
        legacy.pop("host")
        with sqlite3.connect(store.path) as db:
            db.execute("UPDATE peer_binding SET binding = ?", (json.dumps(legacy),))
        stop_peer()
        routes.resume_local_workspace()
        assert call("pull", workspace_id=bound["workspace_id"], after=0)["success"]


@pytest.mark.parametrize("access", ["status", "records"])
def test_paired_workspace_access_retries_offline_start_without_repairing(
    local_desktop, monkeypatch, access
):
    qr = local_desktop.post("/api/local-workspace/pairing").json()["qr"]
    phone, call = phone_connection(qr)
    with phone:
        bound = call("bind", origin="desktop")
    saved = routes._current_peer().store.peer_binding()
    address = (saved["host"], saved["port"])
    stop_peer()

    clock = [1000.0]
    monkeypatch.setattr(routes, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(routes, "_lan_address", lambda: "127.0.0.2")
    bind = socket.socket.bind
    attempts = []
    online = [False]

    def unavailable_until_reconnected(listener, requested):
        if requested == address:
            attempts.append(listener)
            if not online[0]:
                raise OSError(errno.EADDRNOTAVAIL, "Saved LAN interface is offline")
        return bind(listener, requested)

    monkeypatch.setattr(socket.socket, "bind", unavailable_until_reconnected)
    try:
        routes.resume_local_workspace()
    except OSError as exc:
        # Infrastructure mounting already catches this startup failure.
        assert exc.errno == errno.EADDRNOTAVAIL
    peer = routes._peer(routes.get_desktop_data_dir())
    assert len(attempts) == 1 and attempts[0].fileno() == -1
    assert peer.server is None and peer.store.peer_binding() == saved

    # Local reads/writes remain available without restarting or discarding pairing.
    response = local_desktop.post(
        "/api/local-workspace/records",
        json={
            "workspace_id": bound["workspace_id"],
            "operations": [change("a", DESK, "Written while offline")],
        },
    )
    assert response.status_code == 200 and response.json()["accepted"] == ["a" * 32]
    clock[0] += 1
    assert local_desktop.get("/api/local-workspace/status").json()["paired"]
    assert local_desktop.get("/api/local-workspace/records").json()["records"][0]["id"] == DESK
    assert local_desktop.post("/api/local-workspace/pairing").status_code == 409
    assert len(attempts) == 1

    clock[0] += 60
    assert (
        local_desktop.get(
            f"/api/local-workspace/{access}",
            headers={"X-XCAGI-Workspace-Capability": "b" * 64},
        ).status_code
        == 403
    )
    assert len(attempts) == 1
    with ThreadPoolExecutor(max_workers=4) as requests:
        responses = list(
            requests.map(lambda _: local_desktop.get(f"/api/local-workspace/{access}"), range(8))
        )
    assert all(response.status_code == 200 for response in responses)
    assert len(attempts) == 2 and attempts[1].fileno() == -1 and peer.server is None

    online[0] = True
    clock[0] += 60
    local_desktop.get(f"/api/local-workspace/{access}").raise_for_status()
    assert len(attempts) == 3 and peer.host == saved["host"] and peer.port == saved["port"]
    assert peer.store.peer_binding() == saved and peer.invitation is None

    # The original phone key and endpoint still exchange the persisted offline write.
    phone, call = phone_connection(qr)
    with phone:
        pulled = call("pull", workspace_id=bound["workspace_id"], after=bound["cursor"])
    assert pulled["success"] and len(pulled["changes"]) == 1
    assert pulled["changes"][0]["record"]["data"] == {"name": "Written while offline"}
    assert len(attempts) == 3


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


@pytest.mark.parametrize(
    "capability",
    [
        pytest.param(None, id="missing"),
        pytest.param("b" * 64, id="wrong"),
        pytest.param("a" * 63, id="short"),
        pytest.param("g" * 64, id="nonhex"),
        pytest.param(b"\xe9" * 64, id="nonascii"),
    ],
)
def test_other_loopback_clients_cannot_read_write_or_issue_pairing(local_desktop, capability):
    workspace_id = local_desktop.get("/api/local-workspace/status").json()["workspace_id"]
    local_desktop.post(
        "/api/local-workspace/records",
        json={"workspace_id": workspace_id, "operations": [change("a", DESK, "Private customer")]},
    ).raise_for_status()
    headers = {} if capability is None else {"X-XCAGI-Workspace-Capability": capability}
    with loopback_http(local_desktop.app) as outsider:
        responses = [
            outsider.get("/api/local-workspace/records", headers=headers),
            outsider.post(
                "/api/local-workspace/records",
                headers=headers,
                json={"workspace_id": workspace_id, "operations": [change("b", PHONE, "Intruder")]},
            ),
            outsider.post("/api/local-workspace/pairing", headers=headers),
        ]
    assert [response.status_code for response in responses] == [403, 403, 403]
    assert all("Private customer" not in response.text for response in responses)
    peer = routes._current_peer()
    assert peer.store.status()["record_count"] == 1
    assert peer.invitation is None and peer.server is None


@pytest.mark.parametrize(
    "configured",
    [
        pytest.param(None, id="missing"),
        pytest.param("", id="empty"),
        pytest.param("a" * 63, id="short"),
        pytest.param("g" * 64, id="nonhex"),
        pytest.param("\xe9" * 64, id="nonascii"),
    ],
)
def test_workspace_fails_closed_without_a_valid_main_capability(
    local_desktop, monkeypatch, configured
):
    if configured is None:
        monkeypatch.delenv("XCAGI_DESKTOP_WORKSPACE_TOKEN")
    else:
        monkeypatch.setenv("XCAGI_DESKTOP_WORKSPACE_TOKEN", configured)
    with loopback_http(local_desktop.app) as client:
        assert client.get("/api/local-workspace/status", headers=LOCAL_HEADERS).status_code == 403
        assert client.post("/api/local-workspace/pairing", headers=LOCAL_HEADERS).status_code == 403


def test_main_capability_keeps_offline_workspace_and_paired_restart(local_desktop, monkeypatch):
    with loopback_http(local_desktop.app) as client:
        client.headers.update(LOCAL_HEADERS)
        workspace_id = client.get("/api/local-workspace/status").json()["workspace_id"]
        assert "authorization" not in client.headers and set(client.cookies) <= {"csrf_token"}
        client.post(
            "/api/local-workspace/records",
            json={"workspace_id": workspace_id, "operations": [change("a", DESK, "Offline desk")]},
        ).raise_for_status()
        response = client.post("/api/local-workspace/pairing")
        response.raise_for_status()
        assert CAPABILITY not in response.text
        phone, call = phone_connection(response.json()["qr"])
        with phone:
            assert call("bind", origin="desktop")["records"][0]["id"] == DESK
    stop_peer()
    routes.resume_local_workspace()
    with loopback_http(local_desktop.app) as restarted:
        snapshot = restarted.get("/api/local-workspace/records", headers=LOCAL_HEADERS)
        assert snapshot.json()["records"][0]["id"] == DESK
        monkeypatch.setenv("XCAGI_DESKTOP_WORKSPACE_TOKEN", "b" * 64)
        assert (
            restarted.get("/api/local-workspace/status", headers=LOCAL_HEADERS).status_code == 403
        )
        assert (
            restarted.get(
                "/api/local-workspace/status", headers={"X-XCAGI-Workspace-Capability": "b" * 64}
            ).status_code
            == 200
        )
    assert CAPABILITY.encode() not in routes._current_peer().store.path.read_bytes()


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


@pytest.mark.parametrize("failure", [RuntimeError("thread start failed"), KeyboardInterrupt()])
def test_listener_is_released_when_start_is_interrupted(tmp_path, monkeypatch, failure):
    peer = routes.LocalPeer(tmp_path)
    monkeypatch.setattr(routes, "_lan_address", lambda: "127.0.0.1")

    def fail_start(_thread):
        raise failure

    monkeypatch.setattr(routes.threading.Thread, "start", fail_start)
    with pytest.raises(type(failure)):
        peer.start()
    assert peer.port > 0
    # The actual listening socket must be released even for cancellation.
    with routes.socket.socket(routes.socket.AF_INET, routes.socket.SOCK_STREAM) as retry:
        retry.bind(("127.0.0.1", peer.port))
