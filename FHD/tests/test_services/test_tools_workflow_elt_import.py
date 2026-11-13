from unittest.mock import MagicMock, patch

from app.domain.shared_services.tools_workflow_elt import (
    _registered_router_elt_import,
    _resolve_template,
)


def _run(status="preview_ready", **overrides):
    data = {
        "id": "run-1",
        "target_type": "products",
        "status": status,
        "stage": status,
        "total_rows": 10,
        "summary": {"new": 8, "update": 1, "skip": 1, "error": 0, "executed": 0},
        "draft": {"field_mappings": []},
        "error": None,
        "reversible": True,
    }
    data.update(overrides)
    return data


def _context():
    return {"user_id": 7, "tenant_id": 1}


def test_preview_returns_run_id_for_execute():
    service = MagicMock()
    service.create_preview.return_value = {"id": "run-1"}
    with (
        patch(
            "app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._bound_actor",
            return_value=MagicMock(id=7),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._owned_upload",
            return_value={"id": "upload-1", "storage_path": "/tmp/x.xlsx", "suffix": ".xlsx"},
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._resolve_template",
            return_value=("products", {}),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt.get_db",
            return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._wait", return_value=_run()
        ),
        patch("app.application.elt.service.get_elt_service", return_value=service),
    ):
        result = _registered_router_elt_import(
            "preview", {"file_path": "宗南.xlsx"}, _context(), "normal", "导入"
        )
    assert result["success"] is True
    assert result["data"]["run_id"] == "run-1"
    assert result["data"]["target_type"] == "products"


def test_preview_reports_pending_mappings():
    service = MagicMock()
    service.create_preview.return_value = {"id": "run-1"}
    run = _run(
        draft={
            "field_mappings": [
                {"source": "单价", "target": "unit_price", "confidence": 0.6},
                {"source": "产品名称", "target": "product_name", "confidence": 0.98},
            ]
        }
    )
    with (
        patch(
            "app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._bound_actor",
            return_value=MagicMock(id=7),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._owned_upload",
            return_value={"id": "upload-1", "storage_path": "/tmp/x.xlsx", "suffix": ".xlsx"},
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._resolve_template",
            return_value=("products", {}),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt.get_db",
            return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()),
        ),
        patch("app.domain.shared_services.tools_workflow_elt._wait", return_value=run),
        patch("app.application.elt.service.get_elt_service", return_value=service),
    ):
        result = _registered_router_elt_import(
            "preview", {"file_path": "宗南.xlsx"}, _context(), "normal", "导入"
        )
    assert result["data"]["mapping_pending"] == ["unit_price"]
    assert result["data"]["executable"] is False
    assert "字段映射待确认" in result["message"]


def test_preview_ignores_auto_confirmed_mappings():
    service = MagicMock()
    service.create_preview.return_value = {"id": "run-1"}
    run = _run(
        draft={
            "field_mappings": [
                {"source": "产品名称", "target": "product_name", "confidence": 0.98},
                {"source": "", "target": "source_fingerprint", "confidence": 0.0},
            ]
        }
    )
    with (
        patch(
            "app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._bound_actor",
            return_value=MagicMock(id=7),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._owned_upload",
            return_value={"id": "upload-1", "storage_path": "/tmp/x.xlsx", "suffix": ".xlsx"},
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._resolve_template",
            return_value=("products", {}),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt.get_db",
            return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()),
        ),
        patch("app.domain.shared_services.tools_workflow_elt._wait", return_value=run),
        patch("app.application.elt.service.get_elt_service", return_value=service),
    ):
        result = _registered_router_elt_import(
            "preview", {"file_path": "宗南.xlsx"}, _context(), "normal", "导入"
        )
    assert result["data"]["mapping_pending"] == []
    assert result["data"]["executable"] is True


def test_preview_reports_error_rows_as_not_executable():
    service = MagicMock()
    service.create_preview.return_value = {"id": "run-1"}
    run = _run(summary={"new": 10, "update": 0, "skip": 0, "error": 1, "executed": 0})
    with (
        patch(
            "app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._bound_actor",
            return_value=MagicMock(id=7),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._owned_upload",
            return_value={"id": "upload-1", "storage_path": "/tmp/x.xlsx", "suffix": ".xlsx"},
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._resolve_template",
            return_value=("shipment_records", {}),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt.get_db",
            return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()),
        ),
        patch("app.domain.shared_services.tools_workflow_elt._wait", return_value=run),
        patch(
            "app.domain.shared_services.tools_workflow_elt._error_row_details",
            return_value=[
                {"sheet": "宗南", "row": 18, "message": "公斤数或桶数至少填写一项"}
            ],
        ),
        patch("app.application.elt.service.get_elt_service", return_value=service),
    ):
        result = _registered_router_elt_import(
            "preview", {"file_path": "宗南.xlsx"}, _context(), "normal", "导入"
        )
    assert result["success"] is True
    assert result["data"]["executable"] is False
    assert result["data"]["error_row_details"][0]["row"] == 18
    assert "第18行" in result["message"]
    assert "公斤数或桶数至少填写一项" in result["message"]
    assert "valid_rows_only=true" in result["message"]


def test_resolve_template_uses_unique_match():
    service = MagicMock()
    service.list_templates.return_value = [
        {"id": "tpl-1", "name": "送货单模板", "target_type": "shipment_records"}
    ]
    with (
        patch(
            "app.application.elt.target_detection.detect_elt_target",
            return_value={"target_type": "shipment_records"},
        ) as detect,
        patch(
            "app.domain.shared_services.tools_workflow_elt.get_db",
            return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()),
        ),
        patch("app.application.elt.service.get_elt_service", return_value=service),
    ):
        target_type, template = _resolve_template(
            {"storage_path": "/tmp/a.xlsx", "suffix": ".xlsx"}, 7
        )
    assert detect.call_args.kwargs["owner_user_id"] == 7
    assert target_type == "shipment_records"
    assert template["id"] == "tpl-1"


def test_resolve_template_skips_ambiguous_candidates():
    service = MagicMock()
    service.list_templates.return_value = [
        {"id": "tpl-1", "name": "A", "target_type": "products"},
        {"id": "tpl-2", "name": "B", "target_type": "products"},
    ]
    with (
        patch(
            "app.application.elt.target_detection.detect_elt_target",
            return_value={"target_type": "products"},
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt.get_db",
            return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()),
        ),
        patch("app.application.elt.service.get_elt_service", return_value=service),
    ):
        target_type, template = _resolve_template(
            {"storage_path": "/tmp/a.xlsx", "suffix": ".xlsx"}, 7
        )
    assert target_type == "products"
    assert template == {}


def test_preview_passes_selected_template_to_create_preview():
    service = MagicMock()
    service.create_preview.return_value = {"id": "run-1"}
    with (
        patch(
            "app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._bound_actor",
            return_value=MagicMock(id=7),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._owned_upload",
            return_value={"id": "upload-1", "storage_path": "/tmp/x.xlsx", "suffix": ".xlsx"},
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._resolve_template",
            return_value=("shipment_records", {"id": "tpl-1", "name": "送货单模板"}),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt.get_db",
            return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._wait",
            return_value=_run(target_type="shipment_records"),
        ),
        patch("app.application.elt.service.get_elt_service", return_value=service),
    ):
        result = _registered_router_elt_import(
            "preview", {"file_path": "宗南.xlsx"}, _context(), "normal", "导入"
        )
    kwargs = service.create_preview.call_args.kwargs
    assert kwargs["template_id"] == "tpl-1"
    assert kwargs["target_type"] == "auto"
    assert result["data"]["template_name"] == "送货单模板"


def test_execute_completes_with_elt_run():
    service = MagicMock()
    service.execute.return_value = {"id": "run-1"}
    run = _run(status="completed", summary={"new": 0, "update": 0, "skip": 0, "error": 0, "executed": 10})
    with (
        patch(
            "app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._bound_actor",
            return_value=MagicMock(id=7),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt.get_db",
            return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()),
        ),
        patch("app.domain.shared_services.tools_workflow_elt._wait", return_value=run),
        patch("app.application.elt.service.get_elt_service", return_value=service),
    ):
        result = _registered_router_elt_import(
            "execute", {"run_id": "run-1"}, _context(), "normal", "导入"
        )
    assert result["success"] is True
    assert result["data"]["executed_rows"] == 10
    service.execute.assert_called_once()
    assert service.execute.call_args.kwargs["confirmed"] is True


def test_execute_requires_run_id():
    with patch(
        "app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True
    ):
        result = _registered_router_elt_import("execute", {}, _context(), "normal", "导入")
    assert result["success"] is False
    assert result["error_code"] == "missing_run_id"


def test_disabled_outside_enterprise():
    with patch(
        "app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=False
    ):
        result = _registered_router_elt_import(
            "preview", {"file_path": "宗南.xlsx"}, _context(), "normal", "导入"
        )
    assert result["error_code"] == "elt_center_disabled"


def test_unknown_action():
    with patch(
        "app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True
    ):
        result = _registered_router_elt_import("delete", {}, _context(), "normal", "")
    assert result["success"] is False


def test_tool_specs_register_elt_import():
    from app.application.agent_orchestrator.tool_spec import build_tool_specs_v2

    specs = build_tool_specs_v2()
    preview = specs[("elt_import", "preview")]
    execute = specs[("elt_import", "execute")]
    assert preview.permission == "elt.execute"
    assert preview.timeout_seconds == 180
    assert execute.risk == "high"
    assert execute.required_params == ["run_id"]
