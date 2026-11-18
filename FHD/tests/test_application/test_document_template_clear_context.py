"""Template cleanup uses sealed actor identity and real isolated persistence."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, select, text

from app.application.template_app_service import TemplateApplicationService
from app.db.models.elt_archive import EltArchiveAsset, EltArchiveVersion
from app.domain.context.current_request import reset_current_request, set_current_request
from app.domain.shared_services.tools_workflow_shipments_docs_ops import (
    _clear_document_templates,
    _registered_router_document_template,
)
from app.infrastructure.tenant_scope import (
    TenantScopeError,
    current_tenant_id,
    owned_tenant_id,
    owned_tenant_scope,
    tenant_scope,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def template_store(trusted_actor, tmp_path, monkeypatch):
    from app.infrastructure.templates import template_preferences, template_store_impl
    from app.infrastructure.templates.template_store_impl import FileSystemTemplateStore

    actor = trusted_actor(user_id=2, tenant_id=7)
    trusted_actor(user_id=3, tenant_id=7)
    trusted_actor(user_id=4, tenant_id=8)
    engine = actor.factory.kw["bind"]
    monkeypatch.setattr(template_preferences, "get_app_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(template_store_impl, "get_app_data_dir", lambda: str(tmp_path))
    # The test creates the actual schema below; migration bootstrap is outside this operation.
    monkeypatch.setattr("app.db.init_db.init_template_tables", lambda: None)
    monkeypatch.setattr(
        "app.infrastructure.templates.tenant_scope.ensure_templates_tenant_column", lambda: None
    )
    service = TemplateApplicationService(FileSystemTemplateStore(str(tmp_path / "installed")))
    monkeypatch.setattr("app.application.get_template_app_service", lambda: service)
    with engine.begin() as db:
        db.execute(
            text(
                "CREATE TABLE IF NOT EXISTS templates (id INTEGER PRIMARY KEY, template_key TEXT, "
                "template_name TEXT, template_type TEXT, original_file_path TEXT, is_active INTEGER, "
                "tenant_id INTEGER, analyzed_data TEXT, editable_config TEXT, business_rules TEXT, "
                "updated_at TEXT)"
            )
        )
        for row_id, tenant in [(70, 7), (80, 8), (90, None)]:
            db.execute(
                text(
                    "INSERT INTO templates (id, template_name, tenant_id, is_active) "
                    "VALUES (:id, 'synthetic-template', :tenant, 1)"
                ),
                {"id": row_id, "tenant": tenant},
            )
        for name, tenant, owner in [("own", 7, 2), ("peer", 7, 3), ("foreign", 8, 4)]:
            db.execute(
                insert(EltArchiveAsset.__table__),
                {
                    "id": name,
                    "tenant_id": tenant,
                    "owner_user_id": owner,
                    "name": name,
                    "request_key": name,
                    "state": "active",
                },
            )
            db.execute(
                insert(EltArchiveVersion.__table__),
                {
                    "id": name,
                    "asset_id": name,
                    "tenant_id": tenant,
                    "owner_user_id": owner,
                    "version": 1,
                    "size_bytes": 3,
                    "sha256": "a" * 64,
                    "storage_path": name,
                    "status": "stored",
                    "request_key": name,
                },
            )
    return actor, service, engine, tmp_path


def _rows(engine):
    with engine.connect() as db:
        return (
            list(db.execute(text("SELECT id, is_active FROM templates ORDER BY id"))),
            list(db.execute(select(EltArchiveAsset.id).order_by(EltArchiveAsset.id))),
            list(db.execute(select(EltArchiveVersion.id).order_by(EltArchiveVersion.id))),
        )


def test_clear_uses_bound_actor_and_preserves_other_accounts_and_tenants(
    template_store, monkeypatch
):
    actor, _, engine, runtime = template_store
    monkeypatch.setenv("XCAGI_TENANT_ALLOW_LEGACY_NULL_VISIBLE", "1")
    with tenant_scope(8):
        data, status = _clear_document_templates(actor.context)
        assert current_tenant_id() == 8 and owned_tenant_id() is None
    assert status == 200 and data["success"] is True
    assert data["deleted_templates"] == 1
    assert data["deleted_archives"] == 1
    assert _rows(engine) == (
        [(70, 0), (80, 1), (90, 1)],
        [("foreign",), ("peer",)],
        [("foreign",), ("peer",)],
    )
    assert (runtime / "tenants/7/template_preferences.json").is_file()
    assert not (runtime / "tenants/8/template_preferences.json").exists()


@pytest.mark.parametrize("authorized", [True, False])
def test_clear_router_notifies_stream_with_actual_cleanup_outcome(template_store, authorized):
    from app.infrastructure.chat_stream_lifetime import StreamLifetime, current_lifetime

    actor, _, engine, _ = template_store
    before = _rows(engine)
    records = []
    lifetime = StreamLifetime()
    lifetime.observe_tools(lambda **event: records.append(event["record"]))
    token = current_lifetime.set(lifetime)
    try:
        result = _registered_router_document_template(
            "clear", {}, actor.context if authorized else {}, "", ""
        )
    finally:
        current_lifetime.reset(token)
    assert result["success"] is authorized
    assert result["http_status_code"] == (200 if authorized else 403)
    assert len(records) == 1
    assert records[0]["tool_id"] == "document_template"
    assert records[0]["action"] == "clear" and records[0]["phase"] == "finished"
    assert records[0]["success"] is authorized
    if authorized:
        assert result["deleted_archives"] == 1
        assert _rows(engine)[1] == [("foreign",), ("peer",)]
    else:
        assert _rows(engine) == before


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"tenant_id": 7},
        {"user_id": 2},
        {"tenant_id": 0, "user_id": 2},
        {"tenant_id": -7, "user_id": 2},
        {"tenant_id": True, "user_id": 2},
        {"tenant_id": 7, "user_id": 0},
        {"tenant_id": 7, "user_id": -2},
        {"tenant_id": 7, "user_id": True},
        {"tenant_id": "invalid", "user_id": 2},
        {"tenant_id": 7, "user_id": 2},
    ],
)
def test_untrusted_or_invalid_runtime_identity_never_falls_back_to_request(template_store, context):
    actor, _, engine, runtime = template_store
    actor.request.state.user = SimpleNamespace(id=2, tenant_id=7)
    actor.request.state.tenant_id = 7
    request_token = set_current_request(actor.request)
    before = _rows(engine)
    try:
        with tenant_scope(7):
            data, status = _clear_document_templates(context)
    finally:
        reset_current_request(request_token)
    assert status == 403 and data["success"] is False
    assert _rows(engine) == before
    assert not (runtime / "tenants").exists()


@pytest.mark.parametrize("change", ["proof", "tenant", "user", "expired"])
def test_forged_or_expired_actor_cannot_clear_any_rows(template_store, change):
    from app.db.models.user import Session
    from app.utils.time import utc_now_naive

    actor, _, engine, runtime = template_store
    context = deepcopy(actor.context)
    if change == "proof":
        context["_actor_authorization"]["proof"] = "forged"
    elif change == "tenant":
        context["tenant_id"] = "8"
    elif change == "user":
        context["user_id"] = "3"
    else:
        with actor.factory.begin() as db:
            db.get(Session, actor.session_row_id).expires_at = utc_now_naive() - timedelta(
                seconds=1
            )
    before = _rows(engine)
    data, status = _clear_document_templates(context)
    assert status == 403 and data["success"] is False
    assert _rows(engine) == before
    assert not (runtime / "tenants").exists()


@pytest.mark.parametrize("field", ["tenant_id", "owner_id"])
@pytest.mark.parametrize("value", [None, 0, -1, True])
def test_archive_purge_rejects_nonpositive_or_missing_explicit_scope(template_store, field, value):
    _, service, engine, _ = template_store
    scope = {"tenant_id": 7, "owner_id": 2, field: value}
    before = _rows(engine)
    with pytest.raises(TenantScopeError):
        service.purge_archive_assets(**scope)
    assert _rows(engine) == before


def test_archive_purge_cannot_escape_owned_scope(template_store):
    _, service, engine, _ = template_store
    before = _rows(engine)
    with owned_tenant_scope(8), pytest.raises(TenantScopeError):
        service.purge_archive_assets(tenant_id=7, owner_id=2)
    assert _rows(engine) == before


def test_archive_purge_failure_rolls_back_versions_and_is_not_reported_as_empty(template_store):
    from sqlalchemy import event

    _, service, engine, _ = template_store
    before = _rows(engine)

    def reject_asset_delete(connection, cursor, statement, parameters, context, many):
        if statement.startswith("DELETE FROM elt_archive_assets"):
            raise RuntimeError("synthetic storage failure")

    event.listen(engine, "before_cursor_execute", reject_asset_delete)
    try:
        with pytest.raises(RuntimeError, match="synthetic storage failure"):
            service.purge_archive_assets(tenant_id=7, owner_id=2)
    finally:
        event.remove(engine, "before_cursor_execute", reject_asset_delete)
    assert _rows(engine) == before
