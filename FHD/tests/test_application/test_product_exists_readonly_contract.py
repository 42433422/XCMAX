"""Failed existence reads must not produce confirmed-absence facts."""

from types import SimpleNamespace

import pytest
from sqlalchemy import event, insert
from sqlalchemy.engine import Engine

from app.application.agent_orchestrator.business_action_ledger import BusinessActionLedger
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.db.models import Product
from app.domain.shared_services.tools_workflow_erp_master import _registered_router_products
from app.infrastructure.tenant_scope import tenant_scope
from app.services import get_products_service
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_exact_read_classification():
    spec = get_tool_action_spec("products", "exists")
    assert spec.read_only and spec.idempotent and spec.risk == "low"
    for tool, action in (
        ("products", "create"),
        ("products", "update"),
        ("customers", "ensure_exists"),
    ):
        assert not get_tool_action_spec(tool, action).read_only


@pytest.fixture
def product_context(trusted_actor, monkeypatch):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(permissions=["product.view"])
    denied = trusted_actor(role="view-only", permissions=["tool.products.exists"])
    for tenant, name in ((7, "visible"), (8, "foreign")):
        with tenant_scope(tenant), actor.factory.begin() as db:
            db.add(Product(tenant_id=tenant, name=name, model_number=name.upper()))

    def reject_claim(*args, **kwargs):
        pytest.fail("Existence read must not claim a business write")

    monkeypatch.setattr(BusinessActionLedger, "claim", reject_claim)
    return actor, denied


def execute(actor, name="visible", **params):
    params = {"product_name": name, **params}
    step = AgentStep(node_id="exists", tool_id="products", action="exists", params=params)
    return AgentToolExecutor().execute(step, runtime_context=actor.context)


def test_real_queries_are_tenant_scoped_and_nonmutating(product_context):
    actor, denied = product_context

    def dump():
        with actor.factory.kw["bind"].connect() as db:
            return list(db.connection.driver_connection.iterdump())

    def read_sql_only(connection, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().split()[0].upper() in {"SELECT", "PRAGMA"}, statement

    before = dump()
    event.listen(Engine, "before_cursor_execute", read_sql_only)
    try:
        for _ in range(2):
            for name, found in (("visible", True), ("foreign", False), ("absent", False)):
                assert execute(actor, name) == {
                    "success": True,
                    "exists": found,
                    "matched_count": int(found),
                }
        assert execute(denied)["error_code"] == "tool_permission_denied"
        assert execute(actor, tenant_id=8)["error_code"] == "tool_identity_override"
        step = AgentStep(node_id="anon", tool_id="products", action="exists", params={})
        assert AgentToolExecutor().execute(step, runtime_context={})["success"] is False
    finally:
        event.remove(Engine, "before_cursor_execute", read_sql_only)
    assert dump() == before


def test_product_list_uses_product_permission_and_owned_tenant(product_context):
    actor, denied = product_context
    spec = get_tool_action_spec("products", "query")
    assert spec.permission == "product.view"

    def query(subject, **params):
        step = AgentStep(node_id="query", tool_id="products", action="query", params=params)
        return AgentToolExecutor().execute(step, runtime_context=subject.context)

    visible = query(actor, keyword="visible")
    assert visible["success"] is True
    assert [row["name"] for row in visible["data"]] == ["visible"]
    assert query(actor, keyword="foreign")["data"] == []
    assert query(denied)["error_code"] == "tool_permission_denied"
    assert query(actor, tenant_id=8)["error_code"] == "tool_identity_override"


def test_business_db_product_read_obeys_product_permission_and_scope(product_context):
    actor, denied = product_context

    def query(subject, entity="products", **params):
        step = AgentStep(
            node_id="read",
            tool_id="business_db",
            action="read",
            params={"entity": entity, **params},
        )
        return AgentToolExecutor().execute(step, runtime_context=subject.context)

    assert query(actor, keyword="visible")["success"] is True
    assert [row["name"] for row in query(actor, keyword="visible")["data"]] == ["visible"]
    assert query(actor, keyword="foreign")["data"] == []
    assert query(denied)["error_code"] == "tool_permission_denied"
    assert query(actor, entity="customers")["error_code"] == "tool_permission_denied"
    assert query(actor, tenant_id=8)["error_code"] == "tool_identity_override"


def test_unbound_product_read_reports_denial_not_timeout(product_context):
    from app.application.agent_orchestrator.tool_executor import execute_with_tool_deadline

    step = AgentStep(
        node_id="read", tool_id="business_db", action="read", params={"entity": "products"}
    )
    executor = SimpleNamespace(execute=AgentToolExecutor().execute)
    result = execute_with_tool_deadline(executor, step, runtime_context={}, timeout_seconds=5)
    assert result["error_code"] == "tool_identity_required"
    assert result["outcome"] == "unknown"


def test_customer_product_query_checks_role_tenant_and_exact_customer(trusted_actor, monkeypatch):
    from app.db.models.shipment import ShipmentRecord

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(permissions=["shipment.view"])
    denied = trusted_actor(role="no-shipment", permissions=[])
    for tenant, unit, product in (
        (7, "宗南", "白漆"),
        (None, "宗南", "历史无主数据"),
        (8, "宗南", "其他租户"),
        (7, "中南", "其他客户"),
    ):
        with actor.factory.kw["bind"].begin() as db:
            db.execute(
                insert(ShipmentRecord.__table__),
                {
                    "tenant_id": tenant,
                    "purchase_unit": unit,
                    "product_name": product,
                    "quantity_kg": 0,
                    "quantity_tins": 1,
                },
            )

    def query(context, customer="宗南", action="query", **params):
        return AgentToolExecutor().execute(
            AgentStep(
                node_id="customer-products",
                tool_id="shipment_records",
                action=action,
                params={"unit_name": customer, **params},
            ),
            runtime_context=context,
        )

    def forbidden(*args, **kwargs):
        pytest.fail("Read must neither claim a write nor select an adapter from client hints")

    monkeypatch.setattr(BusinessActionLedger, "claim", forbidden)
    monkeypatch.setattr("app.fastapi_routes.shipment_orders._svc", forbidden)
    for action in ("query", "list"):
        spec = get_tool_action_spec("shipment_records", action)
        assert spec.permission == "shipment.view" and spec.read_only
        receipt = query(
            {
                **actor.context,
                "service_source": "fastapi_shipment_records_route",
                "route_module": "untrusted.module",
            },
            action=action,
        )
        assert receipt["success"] is True
        assert [row["product_name"] for row in receipt["data"]] == ["白漆"]
        assert (
            query(actor.context, action=action, tenant_id=8)["error_code"]
            == "tool_identity_override"
        )
        assert query(actor.context, customer="不存在的客户", action=action)["data"] == []
        assert query(denied.context, action=action)["success"] is False
        assert query({**actor.context, "tenant_id": "8"}, action=action)["success"] is False
        assert query({}, action=action)["success"] is False


@pytest.mark.parametrize(
    "upstream",
    [
        None,
        {},
        {"success": True},
        {"success": True, "data": [None]},
        {"success": False, "message": "offline", "data": []},
    ],
)
def test_failed_or_malformed_query_is_not_confirmed_absence(product_context, monkeypatch, upstream):
    actor, _ = product_context
    monkeypatch.setattr(get_products_service(), "get_products", lambda **kwargs: upstream)
    with tenant_scope(7):
        direct = _registered_router_products("exists", {"product_name": "visible"}, {}, "", "")
    assert direct["success"] is False and "exists" not in direct
    result = execute(actor)
    assert result["success"] is False and "exists" not in result
    if isinstance(upstream, dict) and upstream.get("success") is False:
        assert result == upstream


@pytest.mark.parametrize("component", ["_repository", "_cache", "_monitor"])
def test_query_backend_exception_preserves_failure(product_context, monkeypatch, component):
    actor, _ = product_context
    service = get_products_service()

    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic operational failure")

    failure = SimpleNamespace(find_all=unavailable, get=unavailable, record_metric=unavailable)
    monkeypatch.setattr(service, component, failure)
    result = execute(actor)
    assert result["success"] is False and "exists" not in result
    assert result["error_code"] == "tool_exception"
