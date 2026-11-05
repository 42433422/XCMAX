"""Fresh-process guarded catalog acceptance driver; synthetic files only.

Provisioning is an explicit, separate offline phase. The serving phases use the
ordinary factory, authentication dependency, approval endpoint and dispatcher.
No principal, repository, writer or readiness implementation is replaced.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path


def _audit(event, args):
    if event == "socket.connect":
        (Path(sys.argv[-1]) / f"network-blocked-{os.getpid()}.txt").write_text("blocked\n")
        raise AssertionError("external network is forbidden in catalog startup acceptance")
    if event == "open" and isinstance(args[0], (str, bytes)):
        mode, flags = args[1:3]
        writing = isinstance(mode, str) and any(c in mode for c in "wax+")
        writing |= isinstance(flags, int) and bool(
            flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        )
        if writing:
            path = Path(os.fsdecode(args[0])).absolute()
            if path != Path("/dev/null") and not path.is_relative_to(Path(sys.argv[-1]).resolve()):
                raise AssertionError("test runtime attempted a write outside its synthetic root")
            if str(path) == os.environ.get("CATALOG_TEST_READER_LOCK") and str(
                os.getpid()
            ) != os.environ.get("CATALOG_TEST_READER_PID"):
                (Path(sys.argv[-1]) / "worker-source-lock-attempt.txt").write_text("observed\n")


sys.addaudithook(_audit)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BASE = "/api/elt/owned-mixed-v1/products"
GRANTS = {
    "product.view",
    "product.edit",
    "etl.execute",
    "dataset.read",
    "dataset.write",
    "etl.template.manage",
}


def _seed(root):
    # The setup interpreter is not a serving process. Enrollment is intentional
    # and occurs before guarded mode is enabled, never during app startup.
    os.environ.pop("XCAGI_OWNED_SOURCE_PROFILE", None)
    mod = root / "mods/test-mod"
    mod.mkdir(parents=True)
    (mod / "manifest.json").write_text(
        json.dumps(
            {
                "id": "test-mod",
                "name": "Synthetic metadata-only catalog Mod",
                "version": "1.0.0",
            }
        )
    )
    from datetime import date, timedelta
    from decimal import Decimal
    from types import SimpleNamespace
    from uuid import uuid4

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from starlette.requests import Request

    import app.db.models  # noqa: F401 - register canonical fixture schemas
    from app.application.elt.batch_owned_source import OwnedSqlSessions
    from app.db.db_base import Base
    from app.db.models.agent_business_action import AgentBusinessActionRecord
    from app.db.models.owned_source import EltPriceDimension, ProductPriceHistory
    from app.db.models.permission import Permission, Role
    from app.db.models.product import Product
    from app.db.models.product_edit_claim import ProductEditClaimRecord
    from app.db.models.purchase_unit import PurchaseUnit
    from app.db.models.tenant import Tenant
    from app.db.models.user import Session as UserSession
    from app.db.models.user import User
    from app.desktop_runtime import database_generation_registry as registry
    from app.infrastructure.auth.agent_principal import require_agent_principal
    from app.infrastructure.tenant_scope import tenant_scope
    from app.mod_sdk.owned_price_catalog import provision_owned_price_catalog
    from app.utils.time import utc_now_naive

    engine = create_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    AgentBusinessActionRecord.__table__.create(engine, checkfirst=True)
    ProductEditClaimRecord.__table__.create(engine)
    with engine.connect() as db:
        assert db.exec_driver_sql("PRAGMA journal_mode=WAL").scalar() == "wal"
    factory = sessionmaker(bind=engine)
    session_id = uuid4().hex
    with factory.begin() as db:
        role = Role(name="admin")
        for code in sorted(GRANTS):
            role.permissions.append(Permission(code=code, name=code))
        user = User(
            username="synthetic-guarded-owner",
            password="unused",
            tenant_id=7,
            role="admin",
            tier="enterprise",
        )
        db.add_all([role, user])
        db.flush()
        user_id = user.id
        db.add(
            Tenant(
                id=7,
                code="synthetic-guarded",
                name="Synthetic guarded tenant",
                owner_user_id=user_id,
            )
        )
        db.add(
            UserSession(
                session_id=session_id,
                user_id=user_id,
                tenant_id=7,
                created_at=utc_now_naive(),
                expires_at=utc_now_naive() + timedelta(hours=1),
                entitled_mod_ids_json='["test-mod"]',
                account_kind="enterprise",
            )
        )
    headers = {"Authorization": "Bearer " + session_id, "X-XCAGI-Active-Mod-Id": "test-mod"}
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": BASE,
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
    )
    principal = require_agent_principal(request, x_user_id=None)
    config = SimpleNamespace(OWNED_SOURCE_PROFILE="guarded-host-v1", DATABASE_URL=str(engine.url))
    registry.configure_owned_source_profile(config)
    provision_owned_price_catalog(principal, confirmed=True, mixed=True)
    source = OwnedSqlSessions(principal, mixed=True)
    with tenant_scope(7), source() as db:
        db.add(PurchaseUnit(tenant_id=7, unit_name="synthetic customer"))
        product = Product(
            tenant_id=7,
            name="Synthetic startup product",
            model_number="START-1",
            unit="synthetic customer",
            price=Decimal("10.00"),
        )
        db.add(product)
        db.flush()
        pid = product.id
        db.add(
            EltPriceDimension(
                tenant_id=7,
                product_id=pid,
                currency="CNY",
                price_unit="kg",
                source_digest="a" * 64,
                reviewer_id=user_id,
            )
        )
        db.add(
            ProductPriceHistory(
                tenant_id=7,
                product_id=pid,
                owner_user_id=user_id,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 2, 1),
                period_label="January",
                price=Decimal("10.00"),
                source_key="b" * 64,
                provenance_json='[{"kind":"synthetic_import"}]',
            )
        )
        db.commit()
    info = {
        "headers": headers,
        "product_id": pid,
        "source": str(source.target),
        "operation_id": str(uuid4()),
        "user_id": user_id,
    }
    (root / "fixture.json").write_text(json.dumps(info))
    source.engine.dispose()
    engine.dispose()


def _snapshot(host):
    with sqlite3.connect(host.as_uri() + "?mode=ro", uri=True) as db:
        session_columns = [
            row[1]
            for row in db.execute("PRAGMA table_info(sessions)")
            if row[1] not in {"created_at", "expires_at"}
        ]
        return {
            "schema": db.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
            ).fetchall(),
            "users": db.execute("SELECT * FROM users ORDER BY id").fetchall(),
            "tenants": db.execute("SELECT * FROM tenants ORDER BY id").fetchall(),
            "tenant_invitations": db.execute(
                "SELECT * FROM tenant_invitations ORDER BY id"
            ).fetchall(),
            "session_authority": db.execute(
                "SELECT " + ",".join(session_columns) + " FROM sessions ORDER BY id"
            ).fetchall(),
            "roles": db.execute("SELECT * FROM roles ORDER BY id").fetchall(),
            "permissions": db.execute("SELECT * FROM permissions ORDER BY id").fetchall(),
            "role_permissions": db.execute(
                "SELECT * FROM role_permissions ORDER BY role_id,permission_id"
            ).fetchall(),
        }


def _source_state(info):
    with sqlite3.connect(Path(info["source"]).as_uri() + "?mode=ro", uri=True) as db:
        return db.execute(
            "SELECT price FROM products WHERE id=?", (info["product_id"],)
        ).fetchone()[0], db.execute("SELECT count(*) FROM product_price_history").fetchone()[0]


def _logical_digest(path):
    with sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True) as db:
        return hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()


def _assert_terminal_host(root):
    with sqlite3.connect((root / "host.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        claims = db.execute(
            "SELECT plan_json FROM workflow_plans WHERE intent='catalog_products_v1' AND status='verified'"
        ).fetchall()
        assert len(claims) == 1
        claim = json.loads(claims[0][0])
        assert db.execute(
            "SELECT status,runtime_context FROM workflow_plans WHERE plan_id=?", (claim["head"],)
        ).fetchone() == ("idle", "")
        assert db.execute("SELECT state FROM agent_business_actions").fetchall() == [("completed",)]


@contextmanager
def _existing_reader(info):
    """A real authorized physical READ connection, used only as a concurrent reader."""
    from starlette.requests import Request

    from app.application.elt.batch_owned_source import OwnedSqlSessions
    from app.desktop_runtime.database_generation_registry import _epoch_paths
    from app.infrastructure.auth.agent_principal import require_agent_principal
    from app.mod_sdk.owned_price_catalog import CatalogPurpose

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": BASE,
            "headers": [(k.lower().encode(), v.encode()) for k, v in info["headers"].items()],
        }
    )
    principal = require_agent_principal(request, x_user_id=None)
    factory = OwnedSqlSessions(principal, mixed=True, purpose=CatalogPurpose.READ)
    try:
        with factory.guard(), factory() as db:
            assert db.connection().exec_driver_sql("PRAGMA query_only").scalar() == 1
            lock = _epoch_paths(factory.target, None, create=False)[1]
            os.environ["CATALOG_TEST_READER_LOCK"] = str(lock)
            os.environ["CATALOG_TEST_READER_PID"] = str(os.getpid())
            yield
    finally:
        os.environ.pop("CATALOG_TEST_READER_LOCK", None)
        os.environ.pop("CATALOG_TEST_READER_PID", None)
        factory.engine.dispose()


def _serve(root, *, restart, contention=False):
    from fastapi.testclient import TestClient
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from app.fastapi_app.factory import create_fastapi_app
    from app.fastapi_app.guarded_catalog import CatalogAdmissionMiddleware

    def forbid_ddl(_conn, _cursor, statement, _params, _context, _many):
        assert statement.lstrip().split(None, 1)[0].upper() not in {"CREATE", "ALTER", "DROP"}, (
            statement
        )

    event.listen(Engine, "before_cursor_execute", forbid_ddl)
    info = json.loads((root / "fixture.json").read_text())
    before = _snapshot(root / "host.sqlite")
    (root / "authority-before.json").write_text(json.dumps(before))
    original_source = _logical_digest(info["source"])
    original_host = _logical_digest(root / "host.sqlite")
    app = create_fastapi_app(enable_docs=False)
    assert app.user_middleware[0].cls is CatalogAdmissionMiddleware
    with TestClient(app) as client:
        assert _snapshot(root / "host.sqlite") == before, "startup changed schema or grants"
        assert _logical_digest(info["source"]) == original_source, "startup changed source storage"
        if not restart:
            assert _logical_digest(root / "host.sqlite") == original_host, (
                "fresh startup changed HOST rows"
            )
        # Genuine pre-existing session through the normal HTTP authentication
        # path. This is not a claim that market-first password login was tested.
        me = client.get("/api/auth/me", headers={"Authorization": info["headers"]["Authorization"]})
        assert me.status_code == 200 and me.json().get("success") is True, me.text
        after_auth = _snapshot(root / "host.sqlite")
        (root / "authority-after-auth.json").write_text(json.dumps(after_auth))
        assert after_auth == before, "session authentication changed schema or grants"
        assert set(me.json()["data"]["permissions"]) == GRANTS, me.text
        cookie = {
            "Cookie": "session_id=" + info["headers"]["Authorization"].removeprefix("Bearer ")
        }
        selected_cookie = {**cookie, "X-XCAGI-Active-Mod-Id": "test-mod"}
        read_headers = [
            {"Authorization": info["headers"]["Authorization"]},
            info["headers"],
            cookie,
            selected_cookie,
        ]

        def identity(headers):
            response = client.get("/api/auth/me", headers=headers)
            assert response.status_code == 200 and response.json()["success"], response.text
            data = response.json()["data"]
            assert set(data["permissions"]) == GRANTS, response.text
            assert data["account_kind"] == "enterprise" and data["market_is_admin"] is False

        for _ in range(2):
            identity(selected_cookie)
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(identity, read_headers))
        for headers in [info["headers"], selected_cookie]:
            validation = client.get("/api/auth/session/validate", headers=headers)
            payload = validation.json()
            assert validation.status_code == 200 and payload["valid"] is False, validation.text
            assert payload["error"]["code"] == "MARKET_NOT_BOUND", validation.text
        after_reads = _snapshot(root / "host.sqlite")
        (root / "authority-after-auth-reads.json").write_text(json.dumps(after_reads))
        assert after_reads == before, "repeated/concurrent auth reads changed stored authority"
        assert client.get(BASE).status_code in {401, 403}
        listing = client.get(BASE, headers=info["headers"])
        assert listing.status_code == 200 and listing.json()["success"], listing.text
        row = next(r for r in listing.json()["data"] if r["id"] == info["product_id"])
        if not restart:
            body = {
                "operation_id": info["operation_id"],
                "revision": row["revision"],
                "action": "append_price",
                "price": "12.00",
                "period_start": "2026-02-01",
                "period_end": "2026-03-01",
                "selected_sources": [],
                "reason": "Synthetic factory acceptance",
                "confirmed": True,
            }
            created = client.post(f"{BASE}/{row['id']}/edits", headers=info["headers"], json=body)
            assert created.status_code == 202, created.text
            payload = created.json()
            info.update(request=body, run_id=payload["data"]["run_id"])
            (root / "fixture.json").write_text(json.dumps(info))

            def approve():
                continued = client.post(
                    f"/api/agent/runs/{info['run_id']}/continue",
                    headers=info["headers"],
                    json={"approval_grant": payload["approval"]["grant"]},
                )
                assert continued.status_code == 202 and continued.json()["success"], continued.text

            if contention:
                with _existing_reader(info):
                    approve()
                    until = time.monotonic() + 30
                    while not (root / "worker-source-lock-attempt.txt").exists():
                        assert time.monotonic() < until, (
                            "real worker never reached held source lock"
                        )
                        time.sleep(0.02)
                    time.sleep(0.15)
                    busy = client.get(
                        f"{BASE}/edits/{info['operation_id']}", headers=info["headers"]
                    )
                    assert busy.status_code == 409 and busy.json()["retryable"] is False, busy.text
                    with sqlite3.connect(
                        (root / "host.sqlite").as_uri() + "?mode=ro", uri=True
                    ) as db:
                        assert (
                            db.execute("SELECT count(*) FROM agent_business_actions").fetchone()[0]
                            == 0
                        )
                    assert _source_state(info) == (10, 1), (
                        "effect occurred while READ owner held source"
                    )
            else:
                approve()
        deadline = time.monotonic() + 60
        while True:
            # Catalog lookup also acquires the physical source lock. Observe the
            # original HOST run while its worker owns that lock, never race it
            # with a new write or interpret lock contention as replay permission.
            progress = client.get(f"/api/agent/runs/{info['run_id']}", headers=info["headers"])
            assert progress.status_code == 200, progress.text
            status = progress.json()["data"]["status"]
            if status in {"completed", "failed", "blocked", "cancelled"}:
                assert status == "completed", progress.text
                break
            assert time.monotonic() < deadline, progress.text
            time.sleep(0.05)
        lookup = client.get(f"{BASE}/edits/{info['operation_id']}", headers=info["headers"])
        assert lookup.status_code == 200 and lookup.json()["operation"]["state"] == "verified", (
            lookup.text
        )
        verified = client.get(
            f"{BASE}/edits/{info['operation_id']}/verification", headers=info["headers"]
        )
        assert verified.status_code == 200 and verified.json()["success"], verified.text
        proof = verified.json()["data"]
        assert (
            proof["verified"] and proof["historical_effect_verified"] and proof["current_matches"]
        )
        assert proof["fresh_save"] is False and proof["outcome"] == "saved"
        assert proof["run_id"] == info["run_id"] and "_tool_approval_grants" not in lookup.text
        assert _source_state(info) == (12, 2)
        _assert_terminal_host(root)
        retry = client.post(f"/api/agent/runs/{info['run_id']}/retry", headers=info["headers"])
        assert retry.status_code == 409, retry.text
        repeated = client.post(
            f"{BASE}/{row['id']}/edits", headers=info["headers"], json=info["request"]
        )
        assert (
            repeated.status_code == 202 and repeated.json()["data"]["run_id"] == info["run_id"]
        ), repeated.text
        assert _source_state(info) == (12, 2)
        _assert_terminal_host(root)
        assert _snapshot(root / "host.sqlite") == before, "operation changed schema or grants"
        (root / ("restart-proof.json" if restart else "save-proof.json")).write_text(
            json.dumps(proof)
        )
        assert not list(root.glob("network-blocked-*.txt")), "a process attempted external network"


def _reject(root):
    from app.fastapi_app.factory import create_fastapi_app

    try:
        create_fastapi_app(enable_docs=False)
    except (RuntimeError, ValueError, OSError):
        return
    raise AssertionError("invalid explicitly guarded startup was admitted")


if __name__ == "__main__":
    mode, target = sys.argv[1:]
    root = Path(target)
    if mode == "seed":
        _seed(root)
    elif mode == "reject":
        _reject(root)
    else:
        _serve(root, restart=mode == "restart", contention=mode == "contention")
