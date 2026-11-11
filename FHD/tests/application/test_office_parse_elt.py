"""Office-file parse uses ELT, optional worksheet templates, and approval ingest."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from app.application.elt.optional_template import (
    choose_optional_template,
    initial_optional_template_index,
)
from app.application.employee_runtime.task_continuity import named_tool_timeout_seconds
from app.application.office_parse_app_service import (
    is_office_elt_chat_message,
    office_chat_elt_reply,
    parse_office_file_elt,
    save_office_file_elt,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _workbook(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    staff = book.active
    staff.title = "人员"
    staff.append(["产品名称", "数量"])
    staff.append(["甲", 1])
    dept = book.create_sheet("部门")
    dept.append(["产品名称", "数量"])
    dept.append(["乙", 2])
    hidden = book.create_sheet("隐藏")
    hidden.append(["产品名称", "数量"])
    hidden.sheet_state = "hidden"
    book.save(path)
    return path


def test_optional_worksheet_template_matches_capsule_rule():
    templates = [{"id": "人员"}, {"id": "部门"}]
    assert initial_optional_template_index(optional=True) == -1
    assert initial_optional_template_index(optional=False) == 0
    assert choose_optional_template(templates, -1) is None
    assert choose_optional_template(templates, 0)["id"] == "人员"
    assert choose_optional_template(templates, 0, busy=True) is None
    assert choose_optional_template(templates, 5) is None
    assert choose_optional_template(templates, True) is None


def test_parse_office_file_goes_through_elt(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    _workbook(tmp_path / "uploads" / "宗南.xlsx")
    seen: dict[str, str] = {}
    from app.application.elt import parsers as parser_mod

    real = parser_mod.parse_file

    def wrapped(path, **kwargs):
        seen["target"] = kwargs.get("target_type")
        return real(path, **kwargs)

    monkeypatch.setattr(parser_mod, "parse_file", wrapped)
    result = parse_office_file_elt("uploads/宗南.xlsx")
    assert seen["target"] == "products"
    assert result["pipeline"] == "elt"
    assert result["selected_template_index"] == -1
    assert [item["label"] for item in result["templates"]] == ["人员", "部门"]


def _patch_save(monkeypatch, tmp_path):
    # Resolve consumers before replacing providers: a first import while patched
    # would retain the fake provider after monkeypatch teardown.
    from app.application.elt import docking_approval

    captured: dict = {}

    class _Owned:
        storage_path = str(tmp_path / "staged.xlsx")
        sha256 = "abc"

    class _Service:
        def save_upload(self, db, **kwargs):
            captured["body"] = kwargs["stream"].read()
            captured["name"] = kwargs["file_name"]
            Path(self_owned.storage_path).write_bytes(captured["body"])
            return {"upload_id": "up-1"}

        def _owned_upload(self, db, upload_id, owner):
            return self_owned

        def create_preview(self, db, **kwargs):
            captured["preview_target"] = kwargs["target_type"]
            return {
                "id": "run-1",
                "status": "preview_ready",
                "preview_revision": "rev-1",
                "target_type": kwargs["target_type"],
                "file_sha256": "abc",
            }

    self_owned = _Owned()

    class _Ingest:
        def knowledge_plan(self, **kwargs):
            return {
                "action": "new",
                "content": "body",
                "source_text": "body",
                "model_applied": False,
            }

    @contextmanager
    def _db():
        yield object()

    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: _Service())
    monkeypatch.setattr(
        "app.application.elt.auto_ingest_service.get_auto_ingest_service", lambda: _Ingest()
    )
    monkeypatch.setattr("app.db.session.get_db", _db)
    monkeypatch.setattr("app.request_active_mod_ctx.get_request_active_mod_id", lambda: None)

    def _submit(**kwargs):
        captured["submit"] = kwargs
        return {
            "status": "awaiting_approval",
            "batch_id": "aib-1",
            "approval_request_id": "req-1",
            "success": True,
        }

    monkeypatch.setattr(docking_approval, "submit_docking_write", _submit)
    started = []
    monkeypatch.setattr(
        "app.application.elt.auto_ingest_service.AutoIngestService.start_background",
        lambda *args, **kwargs: started.append(True),
    )
    captured["started"] = started
    return captured


def test_save_queues_docking_approval_and_optional_template(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    _workbook(tmp_path / "uploads" / "宗南.xlsx")
    captured = _patch_save(monkeypatch, tmp_path)
    queued = save_office_file_elt(
        "uploads/宗南.xlsx",
        tenant_id=3,
        owner_user_id=4,
        template_index=-1,
        preview_wait_seconds=0,
        client_disconnected=True,
    )
    assert queued["status"] == "awaiting_approval"
    assert captured["submit"]["template_id"] == ""
    assert captured["submit"]["owned_upload_user_id"] == 4
    assert captured["started"] == []
    assert load_workbook(Path(captured["submit"]["source_path"])).sheetnames == [
        "人员",
        "部门",
        "隐藏",
    ]

    chosen = save_office_file_elt(
        "uploads/宗南.xlsx",
        tenant_id=3,
        owner_user_id=4,
        template_index=0,
        preview_wait_seconds=0,
    )
    assert chosen["template_id"] == "人员"
    assert captured["submit"]["template_id"] == "人员"
    assert captured["submit"]["prepared_plan"]["run_id"] == "run-1"
    assert load_workbook(Path(captured["submit"]["source_path"])).sheetnames == ["人员"]


def test_chat_import_uses_elt_and_does_not_invent_success(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.domain.shared_services.tools_workflow_excel_ocr_ops import (
        _registered_router_excel_import,
    )

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    assert is_office_elt_chat_message("@uploads/宗南.xlsx导入数据库") is True
    missing = office_chat_elt_reply(
        "@uploads/宗南.xlsx导入数据库", {"tenant_id": 1, "local_user_id": 2}
    )
    assert missing["success"] is False
    assert missing["response"].startswith("处理失败：")
    monkeypatch.setattr(
        "app.infrastructure.auth.agent_mod_scope._bound_actor",
        lambda context: SimpleNamespace(id=2, tenant_id=1),
    )
    routed = _registered_router_excel_import(
        "office_stage",
        {},
        {"tenant_id": 1, "local_user_id": 999},
        "",
        "@uploads/宗南.xlsx导入数据库",
    )
    assert routed["success"] is False
    assert routed["response"].startswith("处理失败：")
    denied = _registered_router_excel_import(
        "office_stage", {}, {"tenant_id": 2}, "", "@uploads/宗南.xlsx导入数据库"
    )
    assert denied["success"] is False
    assert "身份" in denied["message"]


def test_office_tool_submits_for_authenticated_owner(monkeypatch):
    from types import SimpleNamespace

    from app.domain.shared_services.tools_workflow_excel_ocr_ops import (
        _registered_router_excel_import,
    )

    submitted = {}
    monkeypatch.setattr(
        "app.infrastructure.auth.agent_mod_scope._bound_actor",
        lambda context: SimpleNamespace(id=2, tenant_id=1),
    )
    monkeypatch.setattr(
        "app.application.office_parse_app_service.parse_office_file_elt",
        lambda path: {"file_name": "a.xlsx", "templates": []},
    )

    def save(path, **kwargs):
        submitted.update(path=path, **kwargs)
        return {"file_name": "a.xlsx"}

    monkeypatch.setattr("app.application.office_parse_app_service.save_office_file_elt", save)
    result = _registered_router_excel_import(
        "office_stage", {}, {"tenant_id": 1, "local_user_id": 999}, "", "@uploads/a.xlsx导入数据库"
    )
    assert result["success"] is True
    assert submitted["tenant_id"] == 1 and submitted["owner_user_id"] == 2


@pytest.mark.parametrize("launch_failure", [False, True])
def test_office_tool_runs_through_agent_after_confirmation(
    trusted_actor, monkeypatch, tmp_path, launch_failure
):
    from sqlalchemy import text

    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.infrastructure.tenant_scope import tenant_scope

    actor = trusted_actor(role="admin")
    spec = get_tool_action_spec("excel_import", "office_stage")
    assert spec is not None and spec.risk == "medium" and not spec.idempotent
    monkeypatch.setattr("app.db.session.SessionLocal", actor.factory)
    monkeypatch.setattr("app.application.customer_app_service.get_customers_session", actor.factory)
    from app.application.agent_orchestrator.tool_process import _caller_business_db_url

    assert _caller_business_db_url() == str(actor.factory.kw["bind"].url)
    message = "@uploads/a.xlsx导入数据库"
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    _workbook(tmp_path / "uploads" / "a.xlsx")
    plan = PlanGraph(
        plan_id="office-stage",
        intent="office_import",
        nodes=[
            WorkflowNode(
                node_id="stage",
                tool_id="excel_import",
                action="office_stage",
                params={},
                risk="medium",
                idempotent=False,
            )
        ],
    )
    context = {**actor.context, "message": message}
    with tenant_scope(actor.tenant_id):
        orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
        waiting = orchestrator.start_run_from_plan(
            user_id=str(actor.user_id), message=message, plan=plan, runtime_context=context
        )
        assert waiting.status == "waiting_user" and not waiting.tool_calls
        completed = orchestrator.continue_run(
            waiting.run_id, approved_by=str(actor.user_id), approved_step_id="stage"
        )
    assert completed is not None and completed.status == "completed", (
        completed.error if completed else None,
        [(step.status, step.error, step.output) for step in completed.steps] if completed else None,
    )
    assert "已提交审批" in str(completed.steps[0].output)
    with actor.factory() as db:
        requests = db.execute(
            text("SELECT id, applicant_id, tenant_id, status FROM approval_requests")
        ).all()
        assert len(requests) == 1
        request_id, applicant_id, tenant_id, status = requests[0]
        assert (applicant_id, tenant_id, status) == (actor.user_id, actor.tenant_id, "pending")
    from app.application.approval_workspace_app_service import approve_request
    from app.application.elt.auto_ingest_service import AutoIngestService

    launched = []

    def launch(self, batch):
        launched.append(batch)
        if launch_failure:
            raise RuntimeError("synthetic lost launch receipt")

    monkeypatch.setattr(AutoIngestService, "_launch_worker", launch)
    with tenant_scope(actor.tenant_id):
        receipt = approve_request(request_id, actor.request, body={}, x_user_id=None)
    if hasattr(receipt, "body"):
        import json

        receipt = json.loads(receipt.body)
    assert receipt["success"] is False, receipt
    if launch_failure:
        assert receipt["data"]["workflow_execution"]["code"] == "outcome_unknown"
    else:
        assert receipt["accepted"] is True
    assert len(launched) == 1 and launched[0]["tenant_id"] == actor.tenant_id
    with actor.factory() as db:
        status, business = db.execute(
            text("SELECT status, business_data FROM approval_requests WHERE id = :id"),
            {"id": request_id},
        ).one()
        assert status == "approved"
        import json

        assert json.loads(business)["workflow_dispatch_claim"]["state"] == "unknown"
    with tenant_scope(actor.tenant_id):
        repeated = approve_request(request_id, actor.request, body={}, x_user_id=None)
    assert repeated.status_code == 400
    assert len(launched) == 1


def test_chat_save_picks_named_sheet_like_a_capsule(monkeypatch):
    parsed = {
        "file_path": "uploads/a.xlsx",
        "file_name": "a.xlsx",
        "templates": [
            {"id": "人员", "label": "人员", "sheet": "人员"},
            {"id": "部门", "label": "部门", "sheet": "部门"},
        ],
        "target_type": "products",
        "detection": {"target_type": "products"},
    }
    monkeypatch.setattr(
        "app.application.office_parse_app_service.parse_office_file_elt", lambda path: parsed
    )
    seen: dict = {}

    def _save(path, **kwargs):
        seen.update(kwargs)
        return {"file_name": "a.xlsx", "status": "awaiting_approval"}

    monkeypatch.setattr("app.application.office_parse_app_service.save_office_file_elt", _save)
    plain = office_chat_elt_reply("@uploads/a.xlsx导入数据库", {"tenant_id": 3, "user_id": 4})
    assert seen["template_index"] == -1
    assert plain["success"] is True
    assert "数据对接入库" in plain["response"]
    named = office_chat_elt_reply(
        "@uploads/a.xlsx 工作表：部门 导入数据库", {"tenant_id": 3, "user_id": 4}
    )
    assert seen["template_index"] == 1
    assert named["success"] is True
    listed = office_chat_elt_reply("解析办公 @uploads/a.xlsx", {"tenant_id": 3, "user_id": 4})
    assert "可选工作表模板" in listed["response"]
    assert seen["template_index"] == 1


def test_office_elt_tool_is_not_cut_at_8s():
    assert named_tool_timeout_seconds("parse_office_file") is None
    assert named_tool_timeout_seconds("office_parse_elt") is None
    assert named_tool_timeout_seconds("data_docking") is None
    assert named_tool_timeout_seconds("elt_preview") is None
    assert named_tool_timeout_seconds("other_tool") == 8


def test_save_fixture_restores_providers_and_consumer_alias_on_failure(tmp_path, monkeypatch):
    from app.application.elt import auto_ingest_service, docking_approval, service
    from app.db import session

    original = (
        auto_ingest_service.get_auto_ingest_service,
        service.get_elt_service,
        session.get_db,
        docking_approval.submit_docking_write,
        docking_approval.get_auto_ingest_service,
    )
    with pytest.raises(RuntimeError, match="fixture interrupted"), monkeypatch.context() as scoped:
        _patch_save(scoped, tmp_path)
        assert docking_approval.get_auto_ingest_service is original[4]
        raise RuntimeError("fixture interrupted")
    assert (
        auto_ingest_service.get_auto_ingest_service,
        service.get_elt_service,
        session.get_db,
        docking_approval.submit_docking_write,
        docking_approval.get_auto_ingest_service,
    ) == original
