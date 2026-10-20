from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.workspace_prefs_routes import (
    WorkspacePrefsPatch,
    patch_workspace_prefs_endpoint,
    router,
)


@pytest.mark.parametrize("industry_id", ["业" * 33, "x" * 128])
def test_oversized_industry_is_rejected_before_any_write(monkeypatch, industry_id):
    app = FastAPI()
    app.include_router(router)
    user = SimpleNamespace(id=7)
    monkeypatch.setattr(
        "app.fastapi_routes.workspace_prefs_routes.get_logged_in_user",
        lambda _request: user,
    )
    writes = MagicMock()
    monkeypatch.setattr("app.fastapi_routes.workspace_prefs_routes.patch_workspace_prefs", writes)
    with TestClient(app) as client:
        response = client.patch("/api/workspace/prefs", json={"selected_industry_id": industry_id})
    assert response.status_code == 422
    writes.assert_not_called()


def test_industry_name_at_database_limit_is_not_truncated():
    industry_id = "业" * 32
    assert WorkspacePrefsPatch(selected_industry_id=industry_id).selected_industry_id == industry_id


@pytest.mark.asyncio
async def test_patch_workspace_prefs_keeps_success_when_market_sync_fails(monkeypatch):
    user = SimpleNamespace(id=7)

    monkeypatch.setattr(
        "app.fastapi_routes.workspace_prefs_routes.get_logged_in_user",
        lambda _request: user,
    )
    monkeypatch.setattr(
        "app.fastapi_routes.workspace_prefs_routes.resolve_workspace_owner_id",
        lambda _request, _user: "tenant:42",
    )
    monkeypatch.setattr(
        "app.fastapi_routes.workspace_prefs_routes.session_id_from_request",
        lambda _request: "sid-42",
    )
    monkeypatch.setattr(
        "app.fastapi_routes.workspace_prefs_routes.patch_workspace_prefs",
        lambda _owner_id, partial: dict(partial),
    )
    monkeypatch.setattr(
        "app.fastapi_routes.workspace_prefs_routes.bind_selected_industry_for_user",
        lambda _user, industry_id, *, industry_mod_id="", owner_id=None: {
            "selected_industry_id": industry_id,
            "industry_mod_id": industry_mod_id,
            "owner_id": owner_id,
        },
    )

    async def fail_market_sync(_session_id: str, _industry_id: str):
        return {"success": False, "message": "market failed"}

    monkeypatch.setattr(
        "app.fastapi_routes.market_account.grant_market_enterprise_entitlements_for_session",
        fail_market_sync,
    )

    result = await patch_workspace_prefs_endpoint(
        WorkspacePrefsPatch(
            selected_industry_id="涂料",
            industry_mod_id="coating-industry",
        ),
        MagicMock(),
    )

    assert result["success"] is True
    assert result["owner_id"] == "tenant:42"
    assert result["data"]["selected_industry_id"] == "涂料"
    assert result["market_entitlements"]["success"] is False


@pytest.mark.asyncio
async def test_locked_prefs_write_does_not_block_upload_commit(monkeypatch, tmp_path):
    import asyncio
    import sqlite3
    import threading

    from app.fastapi_routes import workspace_prefs_routes as routes

    database = tmp_path / "concurrent.db"
    upload = sqlite3.connect(database)
    upload.execute("CREATE TABLE writes (kind TEXT)")
    upload.execute("INSERT INTO writes VALUES ('upload')")  # Hold the upload transaction open.
    entered = threading.Event()
    loop_thread = threading.get_ident()
    monkeypatch.setattr(routes, "get_logged_in_user", lambda _request: SimpleNamespace(id=7))
    monkeypatch.setattr(routes, "resolve_workspace_owner_id", lambda *_args: "tenant:42")
    monkeypatch.setattr(routes, "session_id_from_request", lambda _request: "sid-42")

    def write_prefs(owner_id, partial):
        assert threading.get_ident() != loop_thread
        assert owner_id == "tenant:42"
        with sqlite3.connect(database, timeout=10) as db:
            entered.set()
            db.execute("INSERT INTO writes VALUES ('prefs')")
        return partial

    monkeypatch.setattr(routes, "patch_workspace_prefs", write_prefs)
    pending = asyncio.create_task(
        patch_workspace_prefs_endpoint(
            WorkspacePrefsPatch(product_flow_completed=True), MagicMock()
        )
    )
    try:
        async with asyncio.timeout(5):
            while not entered.is_set():
                if pending.done():
                    await pending
                await asyncio.sleep(0.005)
            await asyncio.sleep(0.02)
            assert not pending.done()  # The DB write waits, but this event loop still advances.
            upload.commit()
            result = await pending
        assert result["success"] is True
        assert upload.execute("SELECT kind FROM writes ORDER BY rowid").fetchall() == [
            ("upload",),
            ("prefs",),
        ]
    finally:
        upload.rollback()
        upload.close()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_concurrent_prefs_patches_preserve_local_merge_order(monkeypatch):
    import asyncio
    import time

    from app.fastapi_routes import workspace_prefs_routes as routes

    saved = {}
    active = []
    concurrency = []
    monkeypatch.setattr(routes, "get_logged_in_user", lambda _request: SimpleNamespace(id=7))
    monkeypatch.setattr(routes, "resolve_workspace_owner_id", lambda *_args: "tenant:42")
    monkeypatch.setattr(routes, "session_id_from_request", lambda _request: "sid-42")

    def read_merge_write(_owner, partial):
        active.append(True)
        concurrency.append(len(active))
        snapshot = dict(saved)
        time.sleep(0.05)
        snapshot.update(partial)
        saved.clear()
        saved.update(snapshot)
        active.pop()
        return snapshot

    monkeypatch.setattr(routes, "patch_workspace_prefs", read_merge_write)
    results = await asyncio.gather(
        patch_workspace_prefs_endpoint(
            WorkspacePrefsPatch(product_flow_completed=True), MagicMock()
        ),
        patch_workspace_prefs_endpoint(
            WorkspacePrefsPatch(host_pack_acknowledged=True), MagicMock()
        ),
    )
    assert all(result["success"] for result in results)
    assert max(concurrency) == 1
    assert saved == {"product_flow_completed": True, "host_pack_acknowledged": True}


@pytest.mark.asyncio
async def test_cancelled_request_keeps_write_serial_until_worker_finishes(monkeypatch):
    import asyncio
    import threading

    from app.fastapi_routes import workspace_prefs_routes as routes

    started, release, second_started = threading.Event(), threading.Event(), threading.Event()
    calls = []
    monkeypatch.setattr(routes, "get_logged_in_user", lambda _request: SimpleNamespace(id=7))
    monkeypatch.setattr(routes, "resolve_workspace_owner_id", lambda *_args: "tenant:42")
    monkeypatch.setattr(routes, "session_id_from_request", lambda _request: "sid-42")

    def write(_owner, partial):
        calls.append(partial)
        if len(calls) == 1:
            started.set()
            assert release.wait(5)
        else:
            second_started.set()
        return partial

    monkeypatch.setattr(routes, "patch_workspace_prefs", write)
    first = asyncio.create_task(
        patch_workspace_prefs_endpoint(
            WorkspacePrefsPatch(product_flow_completed=True), MagicMock()
        )
    )
    pending = [first]
    try:
        async with asyncio.timeout(5):
            while not started.is_set():
                await asyncio.sleep(0.005)
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            second = asyncio.create_task(
                patch_workspace_prefs_endpoint(
                    WorkspacePrefsPatch(host_pack_acknowledged=True), MagicMock()
                )
            )
            cancelled_waiter = asyncio.create_task(
                patch_workspace_prefs_endpoint(WorkspacePrefsPatch(), MagicMock())
            )
            pending.extend([second, cancelled_waiter])
            await asyncio.sleep(0.03)
            cancelled_waiter.cancel()
            await asyncio.gather(cancelled_waiter, return_exceptions=True)
            assert not second_started.is_set()
            release.set()
            assert (await second)["success"] is True
            assert len(calls) == 2  # A cancelled queued request must never start its write.
    finally:
        release.set()
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.gather(*tuple(routes._PREFS_JOBS), return_exceptions=True)


@pytest.mark.asyncio
async def test_cancel_at_idle_limiter_checkpoint_does_not_leak_token(monkeypatch):
    import asyncio

    from app.fastapi_routes import workspace_prefs_routes as routes

    monkeypatch.setattr(
        routes, "_patch_local_prefs", lambda *_args: ({}, "tenant:42", "", "sid-42")
    )
    first = asyncio.create_task(patch_workspace_prefs_endpoint(WorkspacePrefsPatch(), MagicMock()))
    await asyncio.sleep(0)  # Cancel at acquire's fast-path checkpoint, before a worker starts.
    first.cancel()
    outcome = (await asyncio.gather(first, return_exceptions=True))[0]
    assert isinstance(outcome, asyncio.CancelledError)
    async with asyncio.timeout(5):
        result = await patch_workspace_prefs_endpoint(WorkspacePrefsPatch(), MagicMock())
    assert result["success"] is True
