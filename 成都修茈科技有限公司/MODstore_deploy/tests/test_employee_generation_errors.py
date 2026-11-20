"""Generation diagnostics must remain safe when surfaced by owned ticket views."""

from __future__ import annotations

import json
import logging
import re
import uuid

import pytest

from modstore_server import llm_chat_proxy, llm_key_resolver, workbench_api
from modstore_server.employee_ai_pipeline import stage_generate_code
from modstore_server.models import get_session_factory
from modstore_server.script_agent.llm_client import StubLlmClient
from tests.test_customer_service_api import _as_user, _make_ticket, _make_user


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "brief", "fallback", "failure_type"),
    [
        (
            "direct_python",
            "读取 CSV 表格并提取全部字段",
            "asset_pipeline_builtin_fallback",
            "RuntimeError",
        ),
        ("agent", "协助整理客户问题并生成摘要", "agent_fallback", "RuntimeError"),
        (
            "direct_python",
            "读取 CSV 表格并提取全部字段",
            "asset_pipeline_builtin_fallback",
            "ProviderError",
        ),
    ],
)
async def test_generation_failure_stays_private_through_persisted_ticket_snapshot(
    client, monkeypatch, tmp_path, caplog, handler, brief, fallback, failure_type
):
    secret = "test-private-provider-credential"
    private_path = "/workspace/private/customer-contract.xlsx"

    async def unavailable(*_args, **_kwargs):
        if failure_type == "ProviderError":
            return {"ok": False, "error": f"api_key={secret}; input={private_path}"}
        raise RuntimeError(f"upstream failed: api_key={secret}; input={private_path}")

    monkeypatch.setattr(llm_chat_proxy, "chat_dispatch", unavailable)
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _provider: secret)
    monkeypatch.setattr(
        llm_key_resolver, "platform_base_url", lambda _provider: "https://provider.invalid/v1"
    )
    with caplog.at_level(logging.WARNING):
        generated = await stage_generate_code(
            brief,
            {
                "id": "owned-test-employee",
                "name": "客服助手",
                "employee_config_v2": {"actions": {"handlers": [handler]}},
            },
            StubLlmClient([]),
        )
    assert generated.code_source == fallback
    assert generated.employee_py
    assert generated.warnings

    owner = _make_user("generation_owner")
    admin = _make_user("generation_admin", admin=True)
    outsider = _make_user("generation_outsider")
    sid = uuid.uuid4().hex
    with get_session_factory().begin() as db:
        ticket = _make_ticket(
            db,
            owner,
            ticket_no=f"CS-{sid}",
            intent="custom_delivery",
            status="processing",
            evidence_json=json.dumps(
                {
                    "kind": "employee",
                    "delivery_generation": sid,
                    "runs": [{"session_id": sid, "attempt": 1, "status": "running"}],
                }
            ),
        )
        ticket_id = ticket.id
    snapshots = {
        sid: {
            "id": sid,
            "user_id": owner.id,
            "ticket_id": ticket_id,
            "intent": "employee",
            "status": "running",
            "steps": [
                {
                    "id": "code",
                    "label": "代码生成",
                    "status": "done",
                    "message": "；".join(generated.warnings),
                }
            ],
            "artifact": {"code_source": generated.code_source, "warnings": generated.warnings},
        }
    }
    monkeypatch.setattr(workbench_api, "WORKBENCH_SESSIONS", snapshots)
    monkeypatch.setattr(workbench_api, "_workbench_session_store_dir", lambda: tmp_path)
    workbench_api._session_store().persist(sid)
    snapshots.clear()  # The route must read the persisted snapshot, not this test's objects.

    with _as_user(admin):
        response = client.get(f"/api/customer-service/tickets/{ticket_id}")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ticket"]["status"] == "processing"
    delivery = payload["custom_delivery"]
    assert delivery["stage"] == "production"
    assert delivery["runs"][0]["artifact"]["code_source"] == fallback
    assert delivery["runs"][0]["steps"][0]["message"] == "；".join(generated.warnings)
    for private_value in (secret, private_path, "Traceback", "RuntimeError:"):
        assert private_value not in response.text
        assert private_value not in caplog.text

    diagnostics = [
        record for record in caplog.records if "employee_codegen_failed" in record.getMessage()
    ]
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic.exc_info is None
    assert diagnostic.stack_info is None
    assert f"exception_type={failure_type}" in diagnostic.getMessage()
    event = re.search(r"event_id=([0-9a-f]{32})", diagnostic.getMessage())
    assert event is not None
    assert event.group(1) in "；".join(generated.warnings)

    with _as_user(owner):
        own_response = client.get(f"/api/customer-service/tickets/{ticket_id}")
    assert own_response.status_code == 200
    assert "custom_delivery" not in own_response.json()
    with _as_user(outsider):
        assert client.get(f"/api/customer-service/tickets/{ticket_id}").status_code == 404
