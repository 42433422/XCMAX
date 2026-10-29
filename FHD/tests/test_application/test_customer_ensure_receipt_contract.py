import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.application.customer_app_service import CustomerApplicationService
from app.db.db_base import Base
from app.db.models.purchase_unit import PurchaseUnit
from app.domain.shared_services.business_db_customer_mutations import _ensure_customer
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'customers.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    svc = CustomerApplicationService()
    monkeypatch.setattr(svc, "_get_session", sessions)
    calls = []
    original = svc.create

    def create(data):
        calls.append(data)
        return original(data)

    monkeypatch.setattr(svc, "create", create)
    try:
        yield svc, sessions, calls
    finally:
        engine.dispose()


def ensure(svc):
    return _ensure_customer({"unit_name": "Alpha"}, svc)


@pytest.mark.parametrize("names", [("Alpha", "Alpha"), ("Alpha North", "Alpha South")])
def test_ambiguous_candidates_never_choose_or_create(store, names):
    svc, sessions, calls = store
    with tenant_scope(7), sessions.begin() as db:
        db.add_all([PurchaseUnit(unit_name=name, tenant_id=7) for name in names])
    with tenant_scope(7):
        result = ensure(svc)
    assert result["success"] is False and result["error_code"] == "customer_lookup_ambiguous"
    assert calls == []


def test_query_failure_never_authorizes_create(store):
    svc, sessions, calls = store

    def unavailable(conn, cursor, statement, params, context, many):
        if statement.lstrip().startswith("SELECT") and "purchase_units" in statement:
            raise OperationalError(statement, params, RuntimeError("synthetic unavailable"))

    engine = sessions.kw["bind"]
    event.listen(engine, "before_cursor_execute", unavailable)
    try:
        with tenant_scope(7):
            result = ensure(svc)
    finally:
        event.remove(engine, "before_cursor_execute", unavailable)
    assert result["success"] is False and calls == []


@pytest.mark.parametrize(
    "reply",
    [
        {"success": False, "message": "客户名称已存在"},
        {"success": True, "data": {}},
        {"success": True, "data": {"id": 999}},
    ],
)
def test_message_or_unreadable_receipt_never_proves_success(store, monkeypatch, reply):
    svc, _, _ = store
    monkeypatch.setattr(svc, "create", lambda data: reply)
    with tenant_scope(7):
        result = ensure(svc)
    assert result["success"] is False and result.get("exists") is not True
    if reply["success"]:
        assert result["outcome"] == "unknown" and result["retryable"] is False
        assert result["reconciliation_required"] is True


@pytest.mark.parametrize(
    "readback",
    [None, {"success": False}, {"success": True, "data": {"id": 41, "customer_name": "different"}}],
)
def test_matched_receipt_uses_independent_readback_and_preserves_fuzzy_api(
    store, monkeypatch, readback
):
    svc, sessions, calls = store
    with tenant_scope(7), sessions.begin() as db:
        db.add(PurchaseUnit(id=41, unit_name="Alpha North", tenant_id=7))
    with tenant_scope(8), sessions.begin() as db:
        db.add(PurchaseUnit(id=42, unit_name="Alpha Foreign", tenant_id=8))
    with tenant_scope(7):
        assert svc.match_purchase_unit("Alpha").id == 41
        result = ensure(svc)
        assert result["success"] and result["exists"] and result["id"] == 41
        assert result["unit_name"] == result["data"]["customer_name"] == "Alpha North"
        monkeypatch.setattr(svc, "get_by_id", lambda ident: readback)
        assert ensure(svc)["success"] is False
    assert calls == []


def test_tenantless_lookup_is_unknown_without_create(store):
    svc, sessions, calls = store
    with tenant_scope(None):
        assert ensure(svc)["success"] is False
    assert calls == []
    with sessions() as db:
        assert db.query(PurchaseUnit).count() == 0


def test_postcommit_refresh_failure_is_unknown_not_retryable(store, monkeypatch):
    svc, sessions, calls = store

    def refresh_failed(*args, **kwargs):
        raise OperationalError("refresh", {}, RuntimeError("synthetic unavailable"))

    monkeypatch.setattr(sessions.class_, "refresh", refresh_failed)
    with tenant_scope(7):
        result = ensure(svc)
        with sessions() as db:
            assert db.query(PurchaseUnit).one().id > 0
    assert len(calls) == 1 and result["success"] is False
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert result["reconciliation_required"] is True
