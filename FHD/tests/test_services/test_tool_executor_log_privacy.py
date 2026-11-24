"""Public tool receipts never expose plugin exceptions or business values."""

import json
from unittest.mock import patch

import pytest

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.mark.parametrize("failure", ["exception", "receipt"])
def test_tool_execution_never_logs_or_returns_private_failure_values(
    trusted_actor, caplog, failure
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.fastapi_routes.tools_execute import router

    secret = "private-business-value-only-for-test"
    app = FastAPI()
    app.include_router(router)
    actor = trusted_actor(user_id=17, permissions=["products.query"])
    receipt = {
        "success": False,
        "execution_state": "unknown",
        "run_id": "original-run",
        "reconciliation_required": True,
        "retryable": False,
        "error": secret,
        "message": secret,
        "result": {"traceback": secret},
    }
    with patch(
        "app.application.tools.registered_capabilities.execute_registered_capability",
        side_effect=ValueError(secret) if failure == "exception" else None,
        return_value=json.dumps(receipt),
    ) as execute:
        response = TestClient(app, headers=actor.headers).post(
            "/api/tools/execute",
            json={
                "tool_id": "products",
                "action": "query",
                "params": {"keyword": secret},
            },
        )
    execute.assert_called_once()
    assert secret not in caplog.text
    assert secret not in response.text
    assert response.status_code == 202
    assert response.json()["reconciliation_required"] is True
    assert response.json()["retryable"] is False
