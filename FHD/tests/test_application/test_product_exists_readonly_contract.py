"""Failed existence reads must not produce confirmed-absence facts."""

from types import SimpleNamespace

import pytest
from sqlalchemy import event
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


def test_failed_probe_is_not_a_composer_fact(product_context, monkeypatch):
    from app.application.workflow.planning_loop import PlanningLoop
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.services.tools_execution.registry import get_workflow_tool_registry

    actor, _ = product_context
    monkeypatch.setattr(get_products_service(), "_repository", None)
    plan = PlanGraph(
        plan_id="p",
        intent="test",
        nodes=[WorkflowNode(node_id="exists", tool_id="products", action="exists", params={})],
    )
    contexts = []

    def generate(**kwargs):
        contexts.append(kwargs["context"])
        return plan

    loop = PlanningLoop(
        generate,
        lambda **kw: None,
        lambda **kw: execute(actor),
        lambda plan: None,
        lambda plan, registry: None,
    )
    assert (
        loop.plan("p", str(actor.user_id), "probe", get_workflow_tool_registry(), actor.context)
        is plan
    )
    assert len(contexts) == 2 and "tool_probe_outputs" not in contexts[1]
