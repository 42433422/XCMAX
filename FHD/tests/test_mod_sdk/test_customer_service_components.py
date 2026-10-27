"""Customer-service bridge contracts across actual ASGI and local persistence."""

from __future__ import annotations

import importlib.util
import inspect
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.mod_sdk import host_services as host
from app.services import user_cs_change_request as changes
from app.services import user_cs_pipeline as pipelines

FHD = Path(__file__).resolve().parents[2]
PREFIX = "/api/mod/synthetic-customer-service"


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    root = tmp_path / "pipelines"
    root.mkdir()
    monkeypatch.setattr(pipelines, "_pipeline_roots", lambda: [root])
    monkeypatch.setattr(changes, "_pipeline_roots", lambda: [root])
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    path = FHD / "mods/xcagi-customer-service-bridge/backend/blueprints.py"
    name = "synthetic_customer_service_components"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    app = FastAPI()
    module.register_fastapi_routes(app, "synthetic-customer-service")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield SimpleNamespace(client=client, module=module, app=app)


def test_status_reads_registry_updates_after_route_registration(bridge, monkeypatch):
    from app.mod_sdk import customer_service_pages_compat

    registry = {"synthetic_page": {"title": "Registered after route assembly"}}
    monkeypatch.setattr(
        customer_service_pages_compat, "list_customer_service_pages_registry", lambda: registry
    )

    response = bridge.client.get(PREFIX + "/status")

    assert response.status_code == 200, response.text
    assert response.json()["data"]["registry"] == registry


@pytest.mark.parametrize("advance", [False, True])
def test_contract_generation_honors_explicit_stage_choice(bridge, monkeypatch, advance):
    uid = 7411
    before = pipelines.load_pipeline(uid, username="synthetic account")
    before["stage"] = "quoted"
    pipelines.save_pipeline(before)
    monkeypatch.setattr(
        host,
        "generate_contract_docx",
        lambda user_id, **kwargs: {"filename": "synthetic.docx", "party_a_name": "Synthetic"},
    )

    response = bridge.client.post(
        PREFIX + "/user-cs/contract/generate",
        json={"market_user_id": uid, "advance_stage": advance},
    )

    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    assert response.json()["data"]["download_url"].endswith("/synthetic.docx")
    saved = pipelines.load_pipeline(uid)
    assert saved["stage"] == ("contract_pending" if advance else "quoted")
    assert bool(saved["timeline"]) is advance


@pytest.mark.parametrize("stage_input", [{"start_delivery": True}, {"stage": "delivering"}])
def test_delivery_stage_change_persists_the_new_plan(bridge, stage_input):
    uid = 7412
    milestones = [{"title": "Synthetic installation", "done": False}]
    response = bridge.client.put(
        PREFIX + "/user-cs/delivery/plan",
        json={
            "market_user_id": uid,
            "expected_delivery_at": "2026-12-01",
            "milestones": milestones,
            **stage_input,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    saved = pipelines.load_pipeline(uid)
    assert saved["stage"] == "delivering"
    assert saved.get("delivery", {}).get("expected_delivery_at") == "2026-12-01"
    assert saved["delivery"]["milestones"] == milestones
    assert saved["timeline"][-1]["source"] == "delivery_plan"


def test_manual_intake_calls_the_host_payload_contract(bridge):
    uid = 7413
    response = bridge.client.post(
        PREFIX + "/user-cs/demand-form/manual",
        json={
            "market_user_id": uid,
            "username": "synthetic owner",
            "name": " Synthetic contact ",
            "message": " Synthetic request ",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    saved = pipelines.load_pipeline(uid)
    assert saved["username"] == "synthetic owner"
    assert saved["stage"] == "intake_done"
    assert saved["intake_form"]["name"] == "Synthetic contact"
    assert saved["intake_form"]["message"] == "Synthetic request"
    assert saved["intake_form"]["intake_source"] == "manual_card"


def test_intake_notice_uses_the_host_contact_name_parameter(bridge):
    response = bridge.client.get(
        PREFIX + "/user-cs/demand-form/notice-message",
        params={
            "market_user_id": 7413,
            "client_name": "Synthetic contact",
            "brief": "Synthetic need",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert "Synthetic contact" in data["message"]
    assert "Synthetic need" in data["message"]
    assert data["form_url"] in data["message"]


def test_repair_all_uses_the_host_batch_contract(bridge):
    pipelines.load_pipeline(7417, username="Synthetic first")
    pipelines.load_pipeline(7418, username="Synthetic second")
    response = bridge.client.post(
        PREFIX + "/user-cs/pipeline/repair-all",
        json={"market_user_id": 7417, "username": "Unused legacy parameter"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"success": True, "data": {"repaired": 2}}
    assert pipelines.load_pipeline(7417)["username"] == "Synthetic first"
    assert pipelines.load_pipeline(7418)["username"] == "Synthetic second"


@pytest.mark.parametrize("market_user_id", [None, 7414])
def test_audit_code_route_matches_the_current_host_signature(bridge, market_user_id):
    query = {"audit_code": "SYNTHETIC-CODE"}
    if market_user_id is not None:
        query["market_user_id"] = str(market_user_id)
    response = bridge.client.get(PREFIX + "/user-cs/demand-form/by-audit-code", params=query)

    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    # The existing host implementation is a local stub; this only checks the boundary.
    assert response.json()["data"]["submission"]["source"] == "local_stub"
    assert response.json()["data"]["submission"]["audit_code"] == "SYNTHETIC-CODE"


@pytest.mark.parametrize("operation", ["push", "pull"])
def test_external_crm_operation_is_awaited_before_serializing(bridge, monkeypatch, operation):
    result = {"pipeline": {"market_user_id": 7415}, "completed": operation}
    action = AsyncMock(return_value=result)
    pending = []

    def tracked_action(*args, **kwargs):
        coroutine = action(*args, **kwargs)
        pending.append(coroutine)
        return coroutine

    monkeypatch.setattr(host, f"{operation}_external_crm_for_market_user", tracked_action)
    try:
        response = bridge.client.post(
            PREFIX + f"/user-cs/crm/{operation}-external",
            json={"market_user_id": 7415, "username": "synthetic owner"},
        )

        assert response.status_code == 200, response.text
        assert response.json() == {"success": True, "data": result}
        action.assert_awaited_once_with(7415, username="synthetic owner")
    finally:
        for coroutine in pending:
            coroutine.close()


@pytest.mark.parametrize("sample", [False, True])
def test_contract_download_does_not_follow_a_link_outside_its_directory(
    bridge, monkeypatch, tmp_path, sample
):
    root = tmp_path / "contracts"
    root.mkdir()
    outside = tmp_path / "synthetic-private-record.txt"
    outside.write_bytes(b"synthetic outside bytes")
    filename = "sample_party_b_prefilled.pdf" if sample else "synthetic.docx"
    (root / filename).symlink_to(outside)
    monkeypatch.setattr(
        host, "contract_assets_dir" if sample else "generated_contracts_dir", lambda: root
    )
    endpoint = "sample-pdf" if sample else f"download/{filename}"

    response = bridge.client.get(PREFIX + "/user-cs/contract/" + endpoint)

    assert b"synthetic outside bytes" not in response.content
    assert response.status_code == 200
    assert response.json()["success"] is False


def test_blank_wechat_message_never_invokes_automation(bridge, monkeypatch):
    sent = []

    class Automation:
        def send_wechat_message(self, contact, text):
            sent.append((contact, text))
            return {"success": True, "message_sent": True}

    monkeypatch.setattr(host, "get_desktop_automation_service", Automation)
    response = bridge.client.post(
        PREFIX + "/user-cs/wechat/send",
        json={"market_user_id": 7416, "contact_name": "Synthetic contact", "message": "   "},
    )

    assert response.status_code == 200, response.text
    assert response.json()["success"] is False
    assert sent == []


def test_declared_host_interfaces_match_actual_exported_call_contracts():
    from app.mod_sdk.customer_service import ports

    def inputs(function, *, remove_self=False):
        signature = inspect.signature(function)
        parameters = list(signature.parameters.values())[int(remove_self) :]
        return signature.replace(
            parameters=[p.replace(annotation=inspect.Signature.empty) for p in parameters],
            return_annotation=inspect.Signature.empty,
        )

    for interface in (
        ports.PipelineRepository,
        ports.PipelineServices,
        ports.IntakeServices,
        ports.CrmServices,
        ports.ChangesServices,
        ports.DeliveryServices,
        ports.ContractsServices,
        ports.MessagingServices,
    ):
        for name, method in vars(interface).items():
            if name.startswith("__") or not inspect.isfunction(method):
                continue
            exported = getattr(host, name)
            assert inputs(exported) == inputs(method, remove_self=True), name
            assert inspect.iscoroutinefunction(exported) == inspect.iscoroutinefunction(method), (
                name
            )


@pytest.mark.asyncio
async def test_crm_component_runs_with_independent_explicit_dependencies():
    from app.application.customer_service.protocols import Payload
    from app.mod_sdk.customer_service.crm import CrmHandlers
    from app.mod_sdk.customer_service.models import PipelineBody

    calls = []

    class Connector:
        CrmSyncError: type[Exception] = RuntimeError

        def get_crm_bundle_for_market_user(self, market_user_id: int) -> Payload:
            return {"id": market_user_id}

        def sync_crm_from_pipeline_doc(self, doc: Payload) -> Payload:
            return dict(doc, synced=True)

        async def push_external_crm_for_market_user(
            self, market_user_id: int, *, username: str = ""
        ) -> Payload:
            calls.append(("push", market_user_id, username))
            return {"completed": True}

        async def pull_external_crm_for_market_user(
            self, market_user_id: int, *, username: str = ""
        ) -> Payload:
            calls.append(("pull", market_user_id, username))
            return {"pull": {"ok": True}}

    class Records:
        def load_pipeline(self, market_user_id: int, username: str = "") -> Payload:
            return {"market_user_id": market_user_id, "username": username}

        def save_pipeline(self, doc: Payload, **kwargs) -> Payload:
            calls.append(("save", doc["market_user_id"], doc["username"]))
            return doc

    handler = CrmHandlers(Connector(), Records())
    body = PipelineBody(market_user_id=7420, username="Synthetic owner")
    assert (await handler.user_cs_crm_sync(body))["data"]["pipeline"]["synced"] is True
    assert (await handler.user_cs_crm_push_external(body))["data"] == {"completed": True}
    assert (await handler.user_cs_crm_pull_external(body))["success"] is True
    assert calls == [
        ("save", 7420, "Synthetic owner"),
        ("push", 7420, "Synthetic owner"),
        ("pull", 7420, "Synthetic owner"),
    ]


def test_domain_imports_do_not_load_host_bindings_or_numbered_routes():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib,sys; "
            "[importlib.import_module('app.mod_sdk.customer_service.'+name) for name in "
            "('models','protocols','pipeline','intake','crm','changes','delivery','contracts','messaging')]; "
            "assert 'app.mod_sdk.host_services' not in sys.modules; "
            "assert not any(name.startswith('app.mod_sdk.customer_service_bridge_routes_part') "
            "for name in sys.modules)",
        ],
        cwd=FHD,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout


def test_each_registered_mod_keeps_its_late_employee_binding(bridge, monkeypatch):
    name = "synthetic_customer_service_second_instance"
    path = FHD / "mods/xcagi-customer-service-bridge/backend/blueprints.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    app = FastAPI()
    module.register_fastapi_routes(app, "synthetic-second")
    first = AsyncMock(return_value={"success": True, "owner": "first"})
    second = AsyncMock(return_value={"success": True, "owner": "second"})
    monkeypatch.setattr(bridge.module, "_run_user_cs_employee", first)
    monkeypatch.setattr(module, "_run_user_cs_employee", second)

    with TestClient(app) as client:
        assert bridge.client.get(PREFIX + "/user-cs/status").json()["owner"] == "first"
        assert client.get("/api/mod/synthetic-second/user-cs/status").json()["owner"] == "second"
    first.assert_awaited_once_with({"action": "status"})
    second.assert_awaited_once_with({"action": "status"})


def test_rejected_delivery_stage_keeps_the_existing_plan(bridge):
    doc = pipelines.load_pipeline(7421)
    doc["delivery"] = {"expected_delivery_at": "2026-11-01", "milestones": []}
    pipelines.save_pipeline(doc)
    path = pipelines._pipeline_file(7421)
    before = path.read_bytes()

    response = bridge.client.put(
        PREFIX + "/user-cs/delivery/plan",
        json={"market_user_id": 7421, "stage": "invalid", "expected_delivery_at": "2027-01-01"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["success"] is False
    assert path.read_bytes() == before


@pytest.mark.parametrize("authorized", [False, True])
def test_webhook_secret_is_checked_before_applying_the_submission(bridge, monkeypatch, authorized):
    monkeypatch.setenv("INTAKE_WEBHOOK_SECRET", "synthetic-webhook-secret")
    apply = Mock(return_value={"market_user_id": 7422, "erp_customer_id": 7422})
    monkeypatch.setattr(host, "apply_landing_submission_to_funnel", apply)
    response = bridge.client.post(
        PREFIX + "/user-cs/demand-form/sync",
        json={"market_user_id": 7422, "message": "Synthetic request"},
        headers={"x-intake-webhook-secret": "synthetic-webhook-secret" if authorized else "wrong"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["success"] is authorized
    if authorized:
        assert apply.call_args.args[0]["market_user_id"] == 7422
        assert apply.call_args.kwargs == {"notify_wechat": True}
    else:
        apply.assert_not_called()


def test_successful_change_dispatch_is_persisted_and_not_dispatched_again(bridge, monkeypatch):
    response = bridge.client.post(
        PREFIX + "/user-cs/change-requests",
        json={"market_user_id": 7423, "change_type": "ops_support", "title": "Synthetic issue"},
    )
    assert response.status_code == 200, response.text
    ticket = response.json()["data"]["request"]["id"]
    monkeypatch.setattr(
        host, "_authorization_from_request", lambda request, body: "synthetic-token"
    )
    proxy = AsyncMock(return_value={"data": {"job_id": "synthetic-job"}})
    monkeypatch.setattr(host, "_proxy_json", proxy)
    endpoint = PREFIX + f"/user-cs/change-requests/{ticket}/ops-dispatch"
    first = bridge.client.post(endpoint, json={"market_user_id": 7423})
    second = bridge.client.post(endpoint, json={"market_user_id": 7423})

    assert first.json()["data"]["job_id"] == "synthetic-job"
    assert second.json()["data"]["already_dispatched"] is True
    assert proxy.await_count == 1
    assert proxy.call_args.args == ("POST", "/api/ops/orchestrate/async")
    assert proxy.call_args.kwargs["authorization"] == "synthetic-token"
    assert changes.list_change_requests(7423)[0]["ops_dispatch_job_id"] == "synthetic-job"


@pytest.mark.parametrize("sent", [False, True])
def test_message_acknowledgement_controls_pipeline_update(bridge, monkeypatch, sent):
    doc = pipelines.load_pipeline(7424)
    calls = []

    class Automation:
        def send_wechat_message(self, contact, message):
            calls.append((contact, message))
            return {"success": True, "message_sent": sent}

    monkeypatch.setattr(host, "get_desktop_automation_service", Automation)
    response = bridge.client.post(
        PREFIX + "/user-cs/wechat/send",
        json={"market_user_id": 7424, "contact_name": " Synthetic contact ", "message": " Hello "},
    )

    assert response.status_code == 200, response.text
    assert response.json()["success"] is sent
    assert calls == [("Synthetic contact", "Hello")]
    assert pipelines.load_pipeline(7424)["stage"] == ("connected" if sent else doc["stage"])


@pytest.mark.parametrize("sample", [False, True])
def test_contract_download_keeps_regular_files_available(bridge, monkeypatch, tmp_path, sample):
    root = tmp_path / "allowed-contracts"
    root.mkdir()
    filename = "sample_party_b_prefilled.pdf" if sample else "synthetic.docx"
    (root / filename).write_bytes(b"synthetic permitted bytes")
    monkeypatch.setattr(
        host, "contract_assets_dir" if sample else "generated_contracts_dir", lambda: root
    )
    endpoint = "sample-pdf" if sample else f"download/{filename}"
    response = bridge.client.get(PREFIX + "/user-cs/contract/" + endpoint)

    assert response.status_code == 200
    assert response.content == b"synthetic permitted bytes"
    assert "attachment" in response.headers["content-disposition"]
