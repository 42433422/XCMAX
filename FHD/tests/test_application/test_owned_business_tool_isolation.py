"""Two authenticated tool paths only; no HTTP/CRUD or raw-DML admission claim."""

from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import insert, select

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.db.models import Product, PurchaseUnit
from app.infrastructure.tenant_scope import (
    TenantScopeError,
    current_tenant_id,
    owned_tenant_id,
    owned_tenant_scope,
    tenant_scope,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def stores(trusted_actor, monkeypatch):
    from app.application.customer_app_service import CustomerApplicationService

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(permissions=["product.view", "customer.edit"])
    foreign = trusted_actor(tenant_id=8)
    service = CustomerApplicationService()
    monkeypatch.setattr(service, "_get_session", actor.factory)
    monkeypatch.setattr("app.application.get_customer_app_service", lambda: service)
    engine = actor.factory.kw["bind"]
    # Test-owned synthetic seed, including historical unowned rows; no filter bypass.
    with engine.begin() as db:
        for model, column in ((Product, "name"), (PurchaseUnit, "unit_name")):
            db.execute(
                insert(model.__table__),
                [
                    {"id": 70, "tenant_id": 7, column: "own-only"},
                    {"id": 80, "tenant_id": 8, column: "foreign-only"},
                    {"id": 90, "tenant_id": None, column: "legacy-only"},
                ],
            )
    return actor, foreign, service, engine


def product(actor, name="own-only", context=None):
    return AgentToolExecutor().execute(
        AgentStep(node_id="exists", tool_id="products", action="exists", params={"name": name}),
        runtime_context=actor.context if context is None else context,
    )


def customer(actor, name="new-customer", context=None, **params):
    from app.domain.shared_services.tools_workflow_dispatch import execute_registered_workflow_tool

    return execute_registered_workflow_tool(
        "customers",
        "ensure_exists",
        {
            "name": name,
            **params,
            "_runtime_context": actor.context if context is None else context,
        },
    )


def rows(engine):
    with engine.connect() as db:
        return [
            tuple(r) for r in db.execute(select(PurchaseUnit.__table__).order_by(PurchaseUnit.id))
        ]


def test_two_enterprises_real_read_and_create_readback(stores):
    actor, foreign, _, engine = stores
    for user, own, other in (
        (actor, "own-only", "foreign-only"),
        (foreign, "foreign-only", "own-only"),
    ):
        with tenant_scope(999):
            assert product(user, own)["exists"] is True
            assert product(user, other)["exists"] is False
            assert product(user, "legacy-only")["exists"] is False
            result = customer(user, "same-new-name")
            assert result["success"] is True and result["created"] is True
            assert current_tenant_id() == 999 and owned_tenant_id() is None
        with engine.connect() as db:
            saved = (
                db.execute(select(PurchaseUnit.__table__).where(PurchaseUnit.id == result["id"]))
                .mappings()
                .one()
            )
        assert saved["tenant_id"] == user.tenant_id
        assert customer(user, "same-new-name")["id"] == result["id"]
    assert customer(actor, "legacy-only")["id"] != 90
    with engine.connect() as db:
        assert (
            db.execute(select(PurchaseUnit.tenant_id).where(PurchaseUnit.id == 90)).scalar_one()
            is None
        )


@pytest.mark.parametrize(
    "kind",
    ["anonymous", "forged", "expired", "tenant", "mod", "grant", "tenant-role", "tenantless"],
)
def test_identity_and_permissions_deny_without_effect(stores, trusted_actor, kind):
    from app.db.models.user import Session
    from app.utils.time import utc_now_naive

    actor, _, _, engine = stores
    ctx = deepcopy(actor.context)
    if kind == "anonymous":
        ctx = {}
    elif kind == "forged":
        ctx["_actor_authorization"]["proof"] = "forged"
    elif kind == "expired":
        with actor.factory.begin() as db:
            db.get(Session, actor.session_row_id).expires_at = utc_now_naive() - timedelta(
                seconds=1
            )
    elif kind == "tenant":
        ctx["tenant_id"] = "8"
    elif kind == "mod":
        ctx["mod_id"] = "unentitled"
    else:
        ctx = trusted_actor(
            tenant_id=None if kind == "tenantless" else 7,
            role="tenant:7:reader" if kind == "tenant-role" else "no-grants",
            permissions=["customer.edit", "product.view"] if kind == "tenant-role" else [],
        ).context
    before = rows(engine)
    assert customer(actor, context=ctx)["success"] is False
    assert product(actor, context=ctx)["success"] is False
    assert rows(engine) == before


@pytest.mark.parametrize(
    "override",
    [
        {"tenant_id": 8},
        {"user_id": "8"},
        {"mod_id": "other"},
        {"id": 80},
        {"customer_id": 80},
        {"payload": {"tenant_id": 8}},
    ],
)
def test_customer_override_or_foreign_selector_has_zero_effect(stores, override):
    actor, _, _, engine = stores
    before = rows(engine)
    assert customer(actor, **override)["success"] is False
    assert rows(engine) == before


def test_ambiguity_never_creates(stores):
    actor, _, _, engine = stores
    with engine.begin() as db:
        db.execute(
            insert(PurchaseUnit.__table__),
            [
                {"tenant_id": 7, "unit_name": "ambiguous-a"},
                {"tenant_id": 7, "unit_name": "ambiguous-b"},
            ],
        )
    before = rows(engine)
    result = customer(actor, "ambiguous")
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert rows(engine) == before


@pytest.mark.parametrize(
    "operation",
    [
        "new-foreign",
        "dirty-foreign",
        "delete-foreign",
        "relabel-own",
        "adopt-foreign",
        "adopt-null",
    ],
)
def test_owned_flush_independent_of_identity_map(stores, operation):
    actor, _, _, engine = stores
    before = rows(engine)
    with actor.factory() as db:
        with tenant_scope(7 if operation == "relabel-own" else 8):
            obj = db.get(PurchaseUnit, 70 if operation == "relabel-own" else 80)
        if operation == "adopt-null":
            from sqlalchemy.orm import make_transient_to_detached

            # A stale detached object cannot turn an existing NULL row into ownership.
            obj = PurchaseUnit(id=90, tenant_id=None, unit_name="legacy-only")
            make_transient_to_detached(obj)
            db.add(obj)
        with pytest.raises(TenantScopeError), owned_tenant_scope(7):
            if operation == "new-foreign":
                db.add(PurchaseUnit(tenant_id=8, unit_name="forbidden"))
            elif operation == "delete-foreign":
                db.delete(obj)
            elif operation == "relabel-own":
                obj.tenant_id = 8
            elif operation in {"adopt-foreign", "adopt-null"}:
                obj.tenant_id = 7
            else:
                obj.unit_name = "forbidden"
            db.flush()
        db.rollback()
    assert rows(engine) == before
    assert owned_tenant_id() is None


def test_scopes_nest_and_restore_on_failure(stores):
    with tenant_scope(99):
        with pytest.raises(RuntimeError), owned_tenant_scope(7):
            assert current_tenant_id() == 7
            with owned_tenant_scope(8):
                assert current_tenant_id() == 8
            assert current_tenant_id() == 7
            raise RuntimeError("synthetic")
        assert current_tenant_id() == 99 and owned_tenant_id() is None


def test_real_instant_customer_path_and_routing_hint_is_not_adapter_authority(stores):
    from app.application.ai_chat_app_service import AIChatApplicationService

    actor, _, _, engine = stores
    ctx = {
        **actor.context,
        "service_source": "fastapi_customer_route",
        "route_module": "untrusted.module",
    }
    app = object.__new__(AIChatApplicationService)
    result = app._build_response(
        {
            "action": "tool_call",
            "data": {
                "tool_key": "customers",
                "params": {"unit_name": "instant-owned"},
                "slots": {},
            },
        },
        "pro",
        "新增单位 instant-owned",
        runtime_context=ctx,
    )
    assert result["success"] is True
    with engine.connect() as db:
        assert (
            db.execute(
                select(PurchaseUnit.tenant_id).where(PurchaseUnit.unit_name == "instant-owned")
            ).scalar_one()
            == 7
        )
    assert (
        product(
            actor,
            context={
                **actor.context,
                "service_source": "fastapi_product_compat_route",
                "route_module": "untrusted.module",
            },
        )["exists"]
        is True
    )


def test_owned_flush_allows_only_own_update_and_delete(stores):
    actor, _, _, engine = stores
    with owned_tenant_scope(7), actor.factory.begin() as db:
        obj = db.get(PurchaseUnit, 70)
        obj.unit_name = "own-updated"
    with engine.connect() as db:
        assert (
            db.execute(select(PurchaseUnit.unit_name).where(PurchaseUnit.id == 70)).scalar_one()
            == "own-updated"
        )
    with owned_tenant_scope(7), actor.factory.begin() as db:
        db.delete(db.get(PurchaseUnit, 70))
    with engine.connect() as db:
        assert list(db.execute(select(PurchaseUnit.id).order_by(PurchaseUnit.id)).scalars()) == [
            80,
            90,
        ]


def test_owned_query_does_not_reuse_legacy_visibility_cache(stores, monkeypatch):
    from app.services import get_products_service

    actor, _, _, _ = stores
    keys = []

    class LegacyCache:
        def get(self, key):
            keys.append(key)
            if "owned=True:" not in key:
                return {"success": True, "data": [{"name": "legacy-only"}]}
            return None

        def set(self, key, value, **kwargs):
            keys.append(key)

    monkeypatch.setattr(get_products_service(), "_cache", LegacyCache())
    assert product(actor, "legacy-only")["exists"] is False
    assert keys and all("products:list:7::owned=True:" in key for key in keys)


def test_scope_rejects_explicit_foreign_predicate(stores):
    from app.infrastructure.tenant_scope import apply_tenant_filter, tenant_id_for_write

    actor, _, _, _ = stores
    with owned_tenant_scope(7), actor.factory() as db:
        with pytest.raises(TenantScopeError):
            apply_tenant_filter(db.query(PurchaseUnit), PurchaseUnit, tenant_id=8)
        with pytest.raises(TenantScopeError):
            tenant_id_for_write(8)


def test_canonical_tool_permissions_and_obsolete_grant_denial(trusted_actor, monkeypatch):
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    assert get_tool_action_spec("products", "exists").permission == "product.view"
    assert get_tool_action_spec("customers", "ensure_exists").permission == "customer.edit"
    actor = trusted_actor(permissions=["tool.products.exists"])
    assert product(actor)["error_code"] == "tool_permission_denied"


@pytest.mark.parametrize("sku", ["personal", "unknown"])
def test_unreviewed_sku_denies_both_tools_without_effect(stores, monkeypatch, sku):
    actor, _, _, engine = stores
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", sku)
    before = rows(engine)
    assert product(actor)["error_code"] == "tool_permission_denied"
    assert customer(actor)["success"] is False
    assert rows(engine) == before


def test_application_and_legacy_dispatch_preserve_authorization(stores):
    from app.application.tools.workflow_tools.dispatch import execute_registered_workflow_tool
    from app.domain.shared_services.tools_workflow_dispatch import (
        execute_registered_workflow_tool as legacy_execute,
    )

    actor, _, _, engine = stores
    before = rows(engine)
    for execute in (execute_registered_workflow_tool, legacy_execute):
        denied = execute("customers", "ensure_exists", {"name": "anonymous-denied"})
        assert denied["error_code"] == "customer_action_not_authorized"
        assert rows(engine) == before
    params = {"name": "same-application-customer", "_runtime_context": actor.context}
    created = execute_registered_workflow_tool("customers", "ensure_exists", params)
    repeated = legacy_execute("customers", "ensure_exists", params)
    assert created["success"] and created["created"]
    assert repeated["success"] and repeated["id"] == created["id"]
