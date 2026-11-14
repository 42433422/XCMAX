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
    # 阻断项属于预期交互：编排应停在这里询问用户，而不是继续执行后失败。
    assert result["requires_user_decision"] is True
    assert result["question"] == result["message"]


def test_preview_accepts_valid_rows_only_by_user_request():
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
            "preview",
            {"file_path": "宗南.xlsx", "valid_rows_only": True},
            _context(),
            "normal",
            "只导入正确的行",
        )
    assert result["data"]["executable"] is True
    assert result["requires_user_decision"] is False
    assert result["question"] == ""


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
    service.get_run.return_value = {"id": "run-1", "preview_revision": "a" * 64}
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
    assert service.execute.call_args.kwargs["preview_revision"] == "a" * 64


def test_execute_syncs_source_to_knowledge_base():
    service = MagicMock()
    service.get_run.return_value = {"id": "run-1", "preview_revision": "a" * 64}
    service.execute.return_value = {"id": "run-1"}
    run = _run(
        status="completed",
        summary={"new": 0, "update": 0, "skip": 0, "error": 0, "executed": 10},
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
            "app.domain.shared_services.tools_workflow_elt.get_db",
            return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()),
        ),
        patch("app.domain.shared_services.tools_workflow_elt._wait", return_value=run),
        patch(
            "app.domain.shared_services.tools_workflow_elt._knowledge_receipt",
            return_value={"action": "new", "run_id": "run-1"},
        ) as knowledge,
        patch("app.application.elt.service.get_elt_service", return_value=service),
    ):
        result = _registered_router_elt_import(
            "execute", {"run_id": "run-1"}, _context(), "normal", "导入"
        )
    knowledge.assert_called_once()
    assert result["data"]["knowledge"]["action"] == "new"
    assert "原件已同步到知识库" in result["message"]


def test_execute_registers_source_in_template_library():
    service = MagicMock()
    service.get_run.return_value = {"id": "run-1", "preview_revision": "a" * 64}
    service.execute.return_value = {"id": "run-1"}
    run = _run(
        status="completed",
        target_type="shipment_records",
        summary={"new": 0, "update": 0, "skip": 0, "error": 0, "executed": 10},
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
            "app.domain.shared_services.tools_workflow_elt.get_db",
            return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()),
        ),
        patch("app.domain.shared_services.tools_workflow_elt._wait", return_value=run),
        patch(
            "app.domain.shared_services.tools_workflow_elt._knowledge_receipt",
            return_value={"action": "new"},
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._template_receipt",
            return_value={"action": "new", "names": ["宗南家私-发货单版式"]},
        ),
        patch("app.application.elt.service.get_elt_service", return_value=service),
    ):
        result = _registered_router_elt_import(
            "execute", {"run_id": "run-1"}, _context(), "normal", "导入"
        )
    assert result["data"]["template"]["names"] == ["宗南家私-发货单版式"]
    assert "已从原件切出 1 个模板并登记到模板库（宗南家私-发货单版式）" in result["message"]


def test_template_receipt_registers_segmented_region(tmp_path):
    from app.domain.shared_services.tools_workflow_elt import _template_receipt

    upload = MagicMock(storage_path="/tmp/宗南.xlsx", file_name="宗南.xlsx")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = upload
    template_service = MagicMock()
    template_service.get_templates.return_value = {"templates": []}
    template_service.save_template.return_value = {"success": True, "id": 12}
    data = {
        "upload_id": "upload-1",
        "target_type": "shipment_records",
        "file_name": "宗南.xlsx",
        "file_sha256": "a" * 64,
        "source_features": {
            "regions": [
                {"id": "宗南!R3C1:10", "sheet": "宗南", "header_row": 3, "status": "selected"},
                {"id": "报价!R2C1:5", "sheet": "报价", "header_row": 2, "status": "excluded"},
            ]
        },
    }
    def _extract(_path, *, source_region_id, **_kwargs):
        if source_region_id == "宗南!R3C1:10":
            return {
                "file_path": str(tmp_path / "seg-1.xlsx"),
                "sheet": "宗南",
                "customer_name": "宗南家私",
                "headers": ["产品型号", "数量/件"],
            }
        return {
            "file_path": str(tmp_path / "seg-2.xlsx"),
            "sheet": "报价",
            "title": "2025年3月报价",
            "headers": ["型号", "单价"],
        }

    with (
        patch(
            "app.domain.shared_services.tools_workflow_elt.get_db",
            return_value=MagicMock(__enter__=MagicMock(return_value=db), __exit__=MagicMock()),
        ),
        patch("app.domain.shared_services.tools_workflow_elt.os.path.exists", return_value=True),
        patch(
            "app.utils.path_io.path_utils.get_app_data_dir", return_value=str(tmp_path)
        ),
        patch(
            "app.application.elt.shipment_template_extractor.extract_region_template",
            side_effect=_extract,
        ) as extract,
        patch(
            "app.application.template_app_service.get_template_app_service",
            return_value=template_service,
        ),
    ):
        receipt = _template_receipt(data, 7)
    assert receipt["action"] == "new"
    # 全部区段都登记：选中的送货单 + 未选入业务导入的报价表。
    assert receipt["names"] == ["宗南家私-发货单版式", "宗南-2025年3月报价"]
    assert extract.call_count == 2
    assert extract.call_args.kwargs["clear_example_rows"] is True
    payload = template_service.save_template.call_args_list[0].args[0]
    assert payload["template_name"] == "宗南家私-发货单版式"
    assert payload["original_file_path"].endswith("seg-1.xlsx")
    assert payload["analyzed_data"]["business_scope"] == "shipmentRecords"
    assert [field["label"] for field in payload["analyzed_data"]["fields"]] == ["产品型号", "数量/件"]


def test_template_receipt_skips_run_without_selected_region():
    from app.domain.shared_services.tools_workflow_elt import _template_receipt

    receipt = _template_receipt(
        {"upload_id": "upload-1", "source_features": {"regions": []}}, 7
    )
    assert receipt == {"action": "skip", "reason": "no_region"}


def test_template_receipt_skips_same_source_reimport(tmp_path):
    import hashlib

    from app.domain.shared_services.tools_workflow_elt import _template_receipt

    region_key = f"ELT_{hashlib.sha1('宗南!R3C1:10'.encode()).hexdigest()[:12]}"
    upload = MagicMock(storage_path="/tmp/宗南.xlsx", file_name="宗南.xlsx")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = upload
    template_service = MagicMock()
    template_service.get_templates.return_value = {
        "templates": [
            {"name": "宗南家私-发货单版式", "source": "db", "template_key": region_key}
        ]
    }
    data = {
        "upload_id": "upload-1",
        "target_type": "shipment_records",
        "file_name": "宗南.xlsx",
        "file_sha256": "a" * 64,
        "source_features": {
            "regions": [{"id": "宗南!R3C1:10", "sheet": "宗南", "status": "selected"}]
        },
    }
    with (
        patch(
            "app.domain.shared_services.tools_workflow_elt.get_db",
            return_value=MagicMock(__enter__=MagicMock(return_value=db), __exit__=MagicMock()),
        ),
        patch("app.domain.shared_services.tools_workflow_elt.os.path.exists", return_value=True),
        patch(
            "app.utils.path_io.path_utils.get_app_data_dir", return_value=str(tmp_path)
        ),
        patch(
            "app.application.elt.shipment_template_extractor.extract_region_template",
            return_value={
                "file_path": str(tmp_path / "seg.xlsx"),
                "sheet": "宗南",
                "customer_name": "宗南家私",
                "headers": [],
            },
        ),
        patch(
            "app.application.template_app_service.get_template_app_service",
            return_value=template_service,
        ),
    ):
        receipt = _template_receipt(data, 7)
    assert receipt["action"] == "skip"
    template_service.save_template.assert_not_called()


def test_template_receipt_suffixes_name_taken_by_other_file(tmp_path):
    from app.domain.shared_services.tools_workflow_elt import _template_receipt

    upload = MagicMock(storage_path="/tmp/宗南.xlsx", file_name="宗南.xlsx")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = upload
    template_service = MagicMock()
    template_service.get_templates.return_value = {
        "templates": [
            {"name": "宗南家私-发货单版式", "source": "db", "file_path": "/other/file.xlsx"}
        ]
    }
    template_service.save_template.return_value = {"success": True, "id": 13}
    data = {
        "upload_id": "upload-1",
        "target_type": "shipment_records",
        "file_name": "宗南.xlsx",
        "source_features": {
            "regions": [{"id": "宗南!R3C1:10", "sheet": "宗南", "status": "selected"}]
        },
    }
    with (
        patch(
            "app.domain.shared_services.tools_workflow_elt.get_db",
            return_value=MagicMock(__enter__=MagicMock(return_value=db), __exit__=MagicMock()),
        ),
        patch("app.domain.shared_services.tools_workflow_elt.os.path.exists", return_value=True),
        patch(
            "app.utils.path_io.path_utils.get_app_data_dir", return_value=str(tmp_path)
        ),
        patch(
            "app.application.elt.shipment_template_extractor.extract_region_template",
            return_value={
                "file_path": str(tmp_path / "seg.xlsx"),
                "sheet": "宗南",
                "customer_name": "宗南家私",
                "headers": [],
            },
        ),
        patch(
            "app.application.template_app_service.get_template_app_service",
            return_value=template_service,
        ),
    ):
        receipt = _template_receipt(data, 7)
    assert receipt["names"] == ["宗南家私-发货单版式-2"]


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
