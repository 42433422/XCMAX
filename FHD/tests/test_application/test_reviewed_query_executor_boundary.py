"""Actual two-action executor policies; no alternate executor or ledger hook."""

from copy import deepcopy
from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost
from app.infrastructure.chat_stream_lifetime import (
    StreamObservationTimeout,
    StreamReceiptPersistenceError,
)
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def dispatch_calls(monkeypatch):
    calls = []

    def dispatch(tool, action, params):
        calls.append((tool, action, current_tenant_id()))
        return {"success": True, "data": []}

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    return calls


def execute(actor=None, tool="finance", action="ledger_query", params=None, context=None):
    ctx = actor.context if actor is not None else {}
    return AgentToolExecutor().execute(
        AgentStep(node_id="reviewed-query", tool_id=tool, action=action, params=params or {}),
        runtime_context=ctx if context is None else context,
    )


def test_finance_exact_grant_restores_signed_scope_and_ambient_scope(trusted_actor, dispatch_calls):
    actor = trusted_actor(permissions=["tool.finance.ledger_query"])
    with tenant_scope(99):
        assert execute(actor)["success"]
        assert current_tenant_id() == 99
    assert dispatch_calls == [("finance", "ledger_query", 7)]


@pytest.mark.parametrize(
    "kind", ["anonymous", "forged", "expired", "tenant", "mod", "grant", "tenant-role", "admin"]
)
def test_untrusted_or_ungranted_finance_never_queries(trusted_actor, dispatch_calls, kind):
    from app.db.models.user import Session
    from app.utils.time import utc_now_naive

    actor = trusted_actor(permissions=["tool.finance.ledger_query"])
    ctx = deepcopy(actor.context)
    if kind == "anonymous":
        ctx = {}
    elif kind == "forged":
        ctx["_actor_authorization"]["proof"] = "forged"
    elif kind == "tenant":
        ctx["tenant_id"] = "8"
    elif kind == "mod":
        ctx["mod_id"] = "not-entitled"
    elif kind == "expired":
        with actor.factory.begin() as db:
            db.get(Session, actor.session_row_id).expires_at = utc_now_naive() - timedelta(
                seconds=1
            )
    elif kind == "grant":
        ctx = trusted_actor(role="no-grant", permissions=[]).context
    elif kind == "tenant-role":
        ctx = trusted_actor(
            role="tenant:7:reader", permissions=["tool.finance.ledger_query"]
        ).context
    else:
        # Existing permission row from the first actor would be visible to admin;
        # remove it in this isolated fixture to prove there is no unconditional bypass.
        from app.db.models.permission import Permission

        with actor.factory.begin() as db:
            db.query(Permission).delete()
        ctx = trusted_actor(tenant_id=None, role="admin", tier="admin", permissions=[]).context
    with tenant_scope(99):
        result = execute(context=ctx)
        assert result["success"] is False and "exists" not in result
        assert current_tenant_id() == 99
    assert dispatch_calls == []


def test_identity_override_and_mod_scope_do_not_change_principal(trusted_actor, dispatch_calls):
    actor = trusted_actor(mod_id="synthetic-mod", permissions=["tool.finance.ledger_query"])
    assert execute(actor)["success"]
    assert execute(actor, params={"tenant_id": 8})["error_code"] == "tool_identity_override"
    assert len(dispatch_calls) == 1


@pytest.mark.parametrize("sku", ["enterprise", "personal"])
def test_product_tenant_permission_is_enterprise_only(
    trusted_actor, dispatch_calls, monkeypatch, sku
):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", sku)
    actor = trusted_actor(permissions=["tool.products.exists", "product.view"])
    result = execute(actor, tool="products", action="exists")
    if sku == "enterprise":
        assert result["success"] is True
        assert dispatch_calls == [("products", "exists", 7)]
    else:
        assert result["error_code"] == "tool_permission_denied" and "exists" not in result
        assert dispatch_calls == []


def test_tenantless_product_denied_without_invented_data_scope(trusted_actor, dispatch_calls):
    actor = trusted_actor(tenant_id=None, role="admin", tier="admin", permissions=["product.view"])
    with tenant_scope(99):
        result = execute(actor, tool="products", action="exists")
        assert current_tenant_id() == 99
    assert result["error_code"] == "tool_permission_denied"
    assert (
        result["outcome"] == "unknown" and result["retryable"] is False and "exists" not in result
    )
    assert dispatch_calls == []


@pytest.mark.parametrize(
    "error", [RuntimeError("private-backend-detail"), OSError("private-io-detail")]
)
def test_operational_failure_is_unknown_without_leaking_or_replaying(
    trusted_actor, monkeypatch, error
):
    actor = trusted_actor(permissions=["tool.finance.ledger_query"])
    calls = []

    def fail(*args):
        calls.append(current_tenant_id())
        raise error

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", fail
    )
    with tenant_scope(99):
        result = execute(actor)
        assert current_tenant_id() == 99
    assert result["error_code"] == "tool_exception" and result["outcome"] == "unknown"
    assert result["retryable"] is False and "private" not in str(result)
    assert calls == [7]


@pytest.mark.parametrize(
    "error",
    [
        WorkerLeaseLost("lease"),
        TimeoutError("deadline"),
        StreamObservationTimeout("observer"),
        StreamReceiptPersistenceError("receipt"),
        HTTPException(403, "denied"),
        PermissionError("permission"),
        KeyboardInterrupt(),
    ],
)
def test_control_auth_interrupts_propagate_and_restore_scope(trusted_actor, monkeypatch, error):
    actor = trusted_actor(permissions=["tool.finance.ledger_query"])

    def fail(*args):
        raise error

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", fail
    )
    with tenant_scope(99):
        with pytest.raises(type(error)):
            execute(actor)
        assert current_tenant_id() == 99


def test_existing_write_dispatch_is_not_caught_or_newly_authorized(monkeypatch):
    def fail(*args):
        raise RuntimeError("existing-write-boundary")

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", fail
    )
    with pytest.raises(RuntimeError, match="existing-write-boundary"):
        execute(
            tool="purchase",
            action="create_supplier",
            params={"name": "synthetic"},
            context={"tenant_id": "7"},
        )
