"""Event publication is an observation, not verified OCR business completion."""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_business_ocr_preserves_original_task_and_bound_actor(
    tmp_path, monkeypatch, trusted_actor, local_tools
):
    from app.fastapi_routes.business_api import router

    actor = trusted_actor(user_id=7, permissions=["tool.ocr.request"])
    repo = InMemoryAgentRunRepository()
    domain = Mock()
    domain.emit_ocr_requested.return_value = True
    monkeypatch.delenv("FHD_BUSINESS_API_KEY", raising=False)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    app = FastAPI()
    app.include_router(router)
    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch("app.neuro_bus.domains.ocr_domain.get_ocr_domain", return_value=domain),
        TestClient(app, headers=actor.headers) as client,
    ):
        body = {
            "request_id": "ocr-req-1",
            "image_url": "https://example.invalid/label.png",
            "ocr_type": "invoice",
            "user_id": "999",
        }
        response = client.post("/api/business/ocr/recognize", json=body)
        repeated = client.post("/api/business/ocr/recognize", json=body)
    payload = response.json()
    run = repo.get(payload["run_id"])
    assert response.status_code == repeated.status_code == 202, json.dumps(
        {
            "receipt": payload,
            "run_status": run.status,
            "output": run.steps[0].output,
            "verification": run.metadata.get("verification"),
            "tool_outputs": [call.output for call in run.tool_calls],
        },
        ensure_ascii=False,
    )
    assert payload["success"] is False and payload["retryable"] is False
    observed = repo.get(payload["run_id"])
    assert payload["execution_state"] == "pending", {
        "receipt": payload,
        "outputs": [step.output for step in observed.steps],
        "verification": observed.metadata.get("verification"),
        "recovery": observed.metadata.get("recovery"),
    }
    assert payload.get("reconciliation_required") is not True
    assert repeated.json()["run_id"] == payload["run_id"]
    assert run.user_id == "7" and run.status == "blocked"
    assert run.metadata["recovery"]["state"] == "result_pending"
    assert run.tool_calls[0].output["execution_state"] == "pending"
    assert run.tool_calls[0].metadata["verification"]["accepted"] is False
    assert (
        run.steps[0].output["event"] == "ocr.requested" and run.steps[0].output["published"] is True
    )
    domain.emit_ocr_requested.assert_called_once_with(
        request_id="ocr-req-1",
        image_url="https://example.invalid/label.png",
        ocr_type="invoice",
        user_id="7",
    )
