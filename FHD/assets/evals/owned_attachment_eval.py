"""Owned-file planner contracts: real parsing/session, deterministic model boundary."""

from __future__ import annotations

import io
import json
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


def run_owned_attachment_task(task):
    from starlette.requests import Request

    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
    from app.application.elt.service_uploads import UploadServiceMixin
    from app.db.session import get_db
    from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context
    from app.infrastructure.auth.agent_principal import require_agent_principal
    from app.infrastructure.tenant_scope import tenant_scope

    try:
        from evals.run_agent_eval import (
            _authenticated_route_fixture,
            _check_equal,
            _check_event_types,
            _check_tool_calls,
            _result,
        )
    except ModuleNotFoundError:
        # 脚本直跑时评测入口模块名为 __main__，避免重复执行
        from __main__ import (
            _authenticated_route_fixture,
            _check_equal,
            _check_event_types,
            _check_tool_calls,
            _result,
        )

    expected = task["expected"]
    kind = task["attachment_kind"]
    raw = io.BytesIO()
    evidence = "XCauto server platform model; human review and tenant scoped citations."
    if kind == "image":
        from PIL import Image

        Image.new("RGB", (100, 30), "white").save(raw, format="PNG")
        filename, mime = "policy.png", "image/png"
    elif kind == "excel":
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.append(["客户", "产品名称", "型号", "单价"])
        sheet.append(["甲公司", "清漆", "5003", 120])
        book.save(raw)
        book.close()
        filename, mime = (
            "products.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        evidence = "清漆"
    else:
        from reportlab.pdfgen.canvas import Canvas

        canvas = Canvas(raw)
        canvas.drawString(30, 700, evidence)
        canvas.save()
        filename, mime = "policy.pdf", "application/pdf"
    raw.seek(0)
    captured = []

    def completion(**kwargs):
        captured.append(kwargs["context"]["file_context"]["verified_uploads"][0]["text"])
        return {
            "choices": [
                {"message": {"content": json.dumps(task["model_response"], ensure_ascii=False)}}
            ]
        }

    repo = InMemoryAgentRunRepository()
    checks = []
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as root, ExitStack() as stack:
        client = SimpleNamespace(headers={})
        stack.enter_context(_authenticated_route_fixture(client, role_name="admin"))
        stack.enter_context(
            patch("app.utils.path_io.path_utils.get_app_data_dir", return_value=root)
        )
        stack.enter_context(
            patch("app.application.elt.service_uploads.get_app_data_dir", return_value=root)
        )
        stack.enter_context(
            patch(
                "app.application.workflow.planner.request_planner_completion",
                side_effect=completion,
            )
        )
        if kind == "image":
            stack.enter_context(
                patch(
                    "app.domain.shared_services.ocr_service.get_ocr_service",
                    return_value=SimpleNamespace(
                        recognize_text_blocks=lambda _: [{"text": evidence}]
                    ),
                )
            )
        request = Request(
            {
                "type": "http",
                "headers": [(b"x-session-id", client.headers["X-Session-ID"].encode())],
            }
        )
        principal = require_agent_principal(request, x_user_id=None)
        with tenant_scope(int(principal.tenant_id)), get_db() as db:
            upload = UploadServiceMixin().save_upload(
                db,
                owner_user_id=int(principal.user_id),
                file_name=filename,
                content_type=mime,
                stream=raw,
            )
        context = authenticated_runtime_context(
            {"attachment_upload_ids": [upload["upload_id"]]}, principal
        )
        products = Mock()
        products.get_products.return_value = {"success": True, "data": []}
        products.create_product.return_value = {"success": True}
        customers = Mock()
        customers.match_purchase_unit.return_value = None
        customers.create.return_value = {"success": True}
        stack.enter_context(patch("app.bootstrap.get_products_service", return_value=products))
        stack.enter_context(patch("app.bootstrap.get_customer_app_service", return_value=customers))
        if task.get("mock_office_document"):
            office = task["mock_office_document"]
            stack.enter_context(
                patch(
                    "app.services.kitten_ai_document.generate.generate_office_file",
                    return_value=(b"fixture generated document", office["file_name"]),
                )
            )
            stack.enter_context(
                patch(
                    "app.services.kitten_ai_document.pickup.store_document_pickup",
                    return_value=office["pickup_token"],
                )
            )
        from app.application.dataset_rag_app_service import get_dataset_rag_app_service

        dataset = get_dataset_rag_app_service()
        ingest = stack.enter_context(
            patch.object(dataset, "ingest_document", wraps=dataset.ingest_document)
        )
        orchestrator = AgentOrchestrator(repository=repo)
        run = orchestrator.start_run(
            user_id=principal.user_id, message=task["message"], runtime_context=context
        )
        initial = run.status
        _check_equal(checks, "no_knowledge_write_before_approval", ingest.call_count, 0)
        _check_equal(
            checks, "no_business_write_before_approval", products.create_product.call_count, 0
        )
        if expected.get("continue_after_approval"):
            run = orchestrator.continue_run(run.run_id, approved_by=principal.user_id) or run
        if kind == "excel":
            _check_equal(checks, "approved_business_write", products.create_product.call_count, 1)
        if task.get("explicit_knowledge_import"):
            _check_equal(checks, "explicit_approved_knowledge_write", ingest.call_count, 1)
            _check_equal(
                checks,
                "no_model_file_path",
                bool(ingest.call_args and not ingest.call_args.kwargs.get("file_path")),
                True,
            )
        _check_equal(
            checks,
            "parsed_evidence_reaches_model",
            bool(captured and evidence in captured[0]),
            True,
        )
        _check_equal(
            checks,
            "source_artifact_is_owned",
            bool(
                run.artifacts
                and run.artifacts[0].source == "plan.metadata"
                and run.artifacts[0].metadata.get("upload_id") == upload["upload_id"]
                and run.artifacts[0].metadata.get("parser_used") == "owned_upload"
            ),
            True,
        )
        _check_equal(
            checks, "source_has_no_path", run.artifacts[0].uri if run.artifacts else None, ""
        )
        _check_equal(
            checks,
            "source_does_not_implicitly_ingest",
            run.artifacts[0].metadata.get("skip_dataset_ingest") if run.artifacts else None,
            True,
        )
        _check_equal(checks, "initial_status", initial, expected["initial_status"])
        _check_equal(checks, "final_status", run.status, expected["final_status"])
        _check_equal(
            checks,
            "planner",
            run.metadata.get("plan", {}).get("metadata", {}).get("planner"),
            "llm",
        )
        _check_tool_calls(checks, run.tool_calls, expected.get("tool_calls", []))
        _check_event_types(checks, run.events, expected["event_types"])
        _check_equal(
            checks,
            "source_implicit_ingest_count",
            sum(
                a.metadata.get("dataset_ingest") is not None
                for a in run.artifacts
                if a.metadata.get("upload_id") == upload["upload_id"]
            ),
            0,
        )
    return _result(task, checks, {"run": run.to_dict()})
