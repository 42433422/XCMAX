"""Customer-ticket duty input + deterministic worker shape compatibility."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from modstore_server.duty_workforce_contracts import duty_event_execution_input

REPO_ROOT = Path(__file__).resolve().parents[3]
EMPLOYEE_ROOT = REPO_ROOT / "FHD" / "mods" / "_employees"


def _load(employee_id: str, module_name: str):
    path = EMPLOYEE_ROOT / employee_id / "backend" / "employees" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{module_name}_incident", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_intake_dispatcher_accepts_customer_ticket_incident_shape():
    worker = _load("intake-dispatcher", "intake_dispatcher")
    out = worker.run(
        {
            "event_type": "ops.intake.customer_ticket",
            "source": "customer_ticket",
            "ticket_no": "CS2026072405405500610030",
            "summary": "官网首页加载不出来",
        },
        {},
    )
    assert out["ok"] is True
    assert out["routing_plan"]
    assert out["routing_plan"][0]["request_id"].startswith("CS")


def test_cs_officer_accepts_customer_ticket_incident_shape():
    worker = _load("user-customer-service-officer", "user_customer_service_officer")
    out = worker.run(
        {
            "event_type": "ops.intake.customer_ticket",
            "source": "customer_ticket",
            "ticket_id": 22,
            "ticket_no": "CS2026072405405500610030",
            "summary": "官网首页加载不出来",
        },
        {},
    )
    assert out["ok"] is True
    assert out["ticket_id"].startswith("CS")
    assert out["grounded_source_count"] >= 1


def test_duty_event_execution_input_enriches_customer_ticket(monkeypatch):
    monkeypatch.setattr(
        "modstore_server.duty_workforce_contracts.matching_duty_event_contract",
        lambda *_a, **_k: {
            "mode": "event",
            "risk_level": "low",
            "acceptance": ["read_only"],
        },
    )
    incident = {
        "ticket_no": "CS2026072405405500610030",
        "summary": "官网首页加载不出来",
        "source": "customer_ticket",
    }
    intake = duty_event_execution_input(
        "intake-dispatcher",
        event_type="ops.intake.customer_ticket",
        source="customer-service-api",
        incident=incident,
    )
    assert intake["requests"][0]["text"].startswith("官网")
    cs = duty_event_execution_input(
        "user-customer-service-officer",
        event_type="ops.intake.customer_ticket",
        source="customer-service-api",
        incident=incident,
    )
    assert cs["ticket"]["id"].startswith("CS")
    assert cs["ticket"]["knowledge_sources"]
