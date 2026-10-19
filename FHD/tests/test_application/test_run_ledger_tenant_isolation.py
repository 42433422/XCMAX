"""F09：EmployeeRunLog 租户隔离（真实 SQLite + ASGI HTTP 路由）。"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.application.employee_runtime.run_ledger import (
    create_employee_run_log,
    finish_employee_run_log,
    list_employee_run_logs,
)
from app.db.models.employee_run_log import EmployeeRunLog
from app.infrastructure.tenant_scope import tenant_scope


class _DbCtx:
    def __init__(self, session: Session) -> None:
        self._session = session

    def __enter__(self) -> Session:
        return self._session

    def __exit__(self, *args) -> bool:
        return False


@pytest.fixture()
def ledger_db(monkeypatch):
    import app.db.models  # noqa: F401  安装全局租户事件

    engine = create_engine("sqlite://")
    EmployeeRunLog.__table__.create(bind=engine)
    session = Session(engine)
    monkeypatch.setattr(
        "app.application.employee_runtime.run_ledger.get_db",
        lambda: _DbCtx(session),
    )
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _asgi_app() -> FastAPI:
    import app.fastapi_routes.xcmax_admin as admin_routes

    app = FastAPI()
    app.include_router(admin_routes.router)
    return app


def _seed(employee_id: str, tenant_id: int, error: str) -> int:
    with tenant_scope(tenant_id):
        run_id = create_employee_run_log(
            employee_id=employee_id,
            input_payload={"tenant": tenant_id},
            tenant_id=tenant_id,
            session_id="sid",
            user_id=1,
        )
        finish_employee_run_log(run_id, status="failed", error=error, tenant_id=tenant_id)
    return run_id


def _list(employee_id: str, tenant_id: int | None) -> list[dict]:
    with tenant_scope(tenant_id):
        return list_employee_run_logs(employee_id)


def _session_patches(tenant_id):
    return [
        patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sid",
        ),
        patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=MagicMock(id=1),
        ),
        patch(
            "app.application.session_account_meta.enrich_session_meta_with_tenant",
            return_value={"tenant_id": tenant_id, "account_kind": "admin"},
        ),
        patch(
            "app.application.auth_permission_resolver.require_allowed",
            return_value=None,
        ),
    ]


async def _fetch_runs(tenant_id, employee_id: str = "shared-emp") -> httpx.Response:
    transport = httpx.ASGITransport(app=_asgi_app())
    with ExitStack() as stack:
        for cm in _session_patches(tenant_id):
            stack.enter_context(cm)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(f"/api/xcmax/local/employees/{employee_id}/runs")


class TestRunLedgerTenantIsolation:
    def test_same_employee_id_rows_are_not_cross_visible(self, ledger_db):
        run_one = _seed("shared-emp", 1, "tenant1 failure")
        run_two = _seed("shared-emp", 2, "tenant2 failure")

        rows_one = _list("shared-emp", 1)
        rows_two = _list("shared-emp", 2)

        assert [row["id"] for row in rows_one] == [run_one]
        assert [row["error"] for row in rows_one] == ["tenant1 failure"]
        assert [row["id"] for row in rows_two] == [run_two]
        assert [row["error"] for row in rows_two] == ["tenant2 failure"]

    def test_missing_tenant_reads_nothing(self, ledger_db):
        _seed("shared-emp", 1, "tenant1 failure")
        assert _list("shared-emp", None) == []

    def test_finish_cannot_touch_other_tenant_row(self, ledger_db):
        run_id = _seed("shared-emp", 1, "tenant1 failure")

        with tenant_scope(2):
            assert (
                finish_employee_run_log(
                    run_id, status="success", output={"forged": True}, verified=True
                )
                is False
            )

        rows = _list("shared-emp", 1)
        assert rows[0]["id"] == run_id
        assert rows[0]["status"] == "failed"
        assert rows[0]["verified"] is False
        assert rows[0]["error"] == "tenant1 failure"

    @pytest.mark.asyncio
    async def test_http_missing_tenant_rejected(self, ledger_db):
        _seed("shared-emp", 1, "tenant1 failure")
        resp = await _fetch_runs(None)
        assert resp.status_code == 403
        assert "租户" in resp.json()["message"]

    @pytest.mark.asyncio
    async def test_http_two_tenants_cannot_read_each_other(self, ledger_db):
        run_one = _seed("shared-emp", 1, "tenant1 failure")
        run_two = _seed("shared-emp", 2, "tenant2 failure")

        resp_one = await _fetch_runs(1)
        resp_two = await _fetch_runs(2)

        assert resp_one.status_code == 200
        assert resp_two.status_code == 200
        assert [row["id"] for row in resp_one.json()["data"]] == [run_one]
        assert [row["error"] for row in resp_one.json()["data"]] == ["tenant1 failure"]
        assert [row["id"] for row in resp_two.json()["data"]] == [run_two]
        assert [row["error"] for row in resp_two.json()["data"]] == ["tenant2 failure"]
