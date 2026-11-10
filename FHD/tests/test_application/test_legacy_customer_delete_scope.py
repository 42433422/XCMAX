"""Legacy workflow-tool dispatch must not turn employee labels into write authority."""

import json

import pytest

from app.application.tools.workflow import execute_workflow_tool
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_customer_cascade_authority import deletion as deletion
from tests.test_application.test_customer_cascade_authority import snapshot


@pytest.mark.parametrize(
    "context", [{}, {"employee_id": "synthetic-worker", "source": "employee_runtime"}]
)
def test_legacy_delete_customer_without_bound_scope_cannot_delete_any_tenant(deletion, context):
    _, full, _ = deletion
    before = snapshot(full)
    with tenant_scope(None):
        raw = execute_workflow_tool(
            "delete_customer",
            {
                "customer_id": 3,
                "confirm": True,
                "force": False,
                "_runtime_context": full.context,
            },
            runtime_context=context,
        )
    result = json.loads(raw)
    assert result["success"] is False
    assert result["deleted_count"] == 0
    assert snapshot(full) == before
