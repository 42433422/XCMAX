"""Fresh host process for the real signed SUNBIRD delivery integration test.

Only the app/DB composition is a fixture. Installation, login lookup, runtime
loading, Excel probe, HTTP requests and durable receipts are production code.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import sys
from datetime import timedelta
from pathlib import Path


async def run(config: dict) -> dict:
    import app.db as database
    import app.db.session as db_session
    import app.fastapi_app.factory as factory
    import httpx
    from app.application.mod_delivery_receipt_outbox import retry_delivery_receipts
    from app.application.private_mod_delivery_artifacts import install_custom_delivery_artifact
    from app.db.base import Base
    from app.db.models.tenant import Tenant
    from app.db.models.user import Session, User
    from app.fastapi_routes.delivery_sync_routes import router as sync_router
    from app.infrastructure.mods import install_receipts, mod_manager
    from app.mod_sdk.attendance_roster import initialize_roster_once
    from app.mod_sdk.owner_workspace import attendance_database_path, owner_context
    from app.utils.time import utc_now_naive
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    root = Path(config["root"])
    engine = create_engine(f"sqlite:///{root / 'accounts.db'}")
    sessions = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    database.HostSessionLocal = sessions
    db_session.SessionLocal = sessions
    with sessions.begin() as db:
        if db.get(User, 1) is None:
            for uid in (1, 2):
                db.add(Tenant(id=uid, code=f"isolated-{uid}", name=f"Synthetic {uid}"))
                db.add(
                    User(
                        id=uid,
                        username="SUNBIRD" if uid == 1 else "OTHER",
                        password="unused",
                        role="user",
                        tier="enterprise",
                        is_active=True,
                        tenant_id=uid,
                        market_user_id=100 + uid,
                    )
                )
                db.add(
                    Session(
                        session_id=f"fixture-session-{uid}",
                        user_id=uid,
                        tenant_id=uid,
                        account_kind="enterprise",
                        market_user_id=100 + uid,
                        entitled_mod_ids_json=(
                            "[]" if config["action"] == "autosync" else '["taiyangniao-pro"]'
                        ),
                        market_access_token=config["token"] if uid == 1 else None,
                        expires_at=utc_now_naive() + timedelta(hours=1),
                    )
                )
    factory._app_singleton = FastAPI()
    factory._app_singleton.include_router(sync_router, prefix="/api/mod-store")
    mod_manager._mod_manager = mod_manager.ModManager(str(root / "mods"))
    manager = mod_manager.get_mod_manager()
    # Model a packaged main host: public dependency installed, private sources
    # absent until the signed owner download (development fallback is broader).
    public_root = root / "main-host-mods"
    dependency = public_root / "attendance-industry"
    if not dependency.exists():
        source = manager.resolve_mod_directory("attendance-industry")
        assert source, "Main public attendance dependency must be available"
        shutil.copytree(source, dependency, ignore=shutil.ignore_patterns("__pycache__"))
    manager.all_mods_roots = lambda: [str(root / "mods"), str(public_root)]
    assert manager.load_mod("attendance-industry"), manager._recent_load_failures
    mid = "sunbird-attendance-custom"
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/mod-store/receipts/retry",
            "headers": [(b"x-session-id", b"fixture-session-1")],
        }
    )
    before = install_receipts.read_verified_install(mid)
    if config["action"] in {"install", "autosync"} and config["roster"]:
        with owner_context("tenant:1"):
            if not attendance_database_path().exists():
                assert initialize_roster_once([{"name": "Synthetic employee", "dept": "Fixture"}])
    if config["action"] == "autosync":
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=factory._app_singleton), base_url="http://host.test"
        ) as client:
            response = await client.post(
                "/api/mod-store/private-delivery/sync",
                headers={"x-session-id": "fixture-session-1"},
                json={},
            )
            assert response.status_code == 200, response.text
            result = response.json()["data"]
    elif config["action"] == "install":
        result = await install_custom_delivery_artifact(
            config["token"], config["ticket"], "module", owner_scope="tenant:1"
        )
    else:
        result = await retry_delivery_receipts(request, config["token"])
    current = install_receipts.read_verified_install(mid)
    api_status = {}
    if current and current["runtime_status"] == "running":
        client = TestClient(factory._app_singleton)
        for uid in (1, 2):
            response = client.get(
                f"/api/mod/{mid}/attendance/rules",
                headers={"x-session-id": f"fixture-session-{uid}"},
            )
            api_status[str(uid)] = response.status_code
        client.close()
    with owner_context("tenant:1"):
        roster_exists = attendance_database_path().exists()
    rows = [
        json.loads(path.read_text())
        for path in (root / "data/mod-delivery-receipts").rglob("*.json")
    ]
    with sessions() as db:
        rights = json.loads(
            db.query(Session).filter_by(session_id="fixture-session-1").one().entitled_mod_ids_json
        )
    engine.dispose()
    return {
        "rights": rights,
        "pid": os.getpid(),
        "process_id": install_receipts.PROCESS_ID,
        "before": before,
        "current": current,
        "result": result,
        "api_status": api_status,
        "roster_exists": roster_exists,
        "rows": rows,
    }


def _loopback_only_connect(original):
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise OSError("Delivery integration fixture forbids non-loopback networking")
        return original(sock, address)

    return connect


if __name__ == "__main__":
    socket.socket.connect = _loopback_only_connect(socket.socket.connect)
    socket.socket.connect_ex = _loopback_only_connect(socket.socket.connect_ex)
    settings = json.load(sys.stdin)
    sys.path.insert(0, settings["fhd"])
    outcome = asyncio.run(run(settings))
    Path(settings["output"]).write_text(json.dumps(outcome, ensure_ascii=False, indent=2))
