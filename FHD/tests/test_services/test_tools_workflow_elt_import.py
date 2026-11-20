from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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


@pytest.fixture
def elt_tools(monkeypatch):
    from app.application.elt import service as elt_service
    from app.domain.shared_services import tools_workflow_elt as elt

    service = MagicMock()
    monkeypatch.setattr(elt_service, "get_elt_service", lambda: service)
    monkeypatch.setattr(elt, "_elt_enabled", lambda: True)
    monkeypatch.setattr(elt, "_bound_actor", lambda _context: SimpleNamespace(id=7))
    monkeypatch.setattr(elt, "get_db", lambda: nullcontext(MagicMock()))
    return elt, service


@pytest.fixture
def elt_preview(elt_tools, monkeypatch):
    elt, service = elt_tools
    service.create_preview.return_value = {"id": "run-1"}
    upload = {"id": "upload-1", "storage_path": "/tmp/x.xlsx", "suffix": ".xlsx"}
    monkeypatch.setattr(elt, "_owned_upload", lambda *_args: upload)
    monkeypatch.setattr(elt, "_resolve_template", lambda *_args: ("products", {}))
    return elt, service


def test_wait_delivers_real_changes_before_preview_finishes(monkeypatch):
    from app.domain.shared_services import tools_workflow_elt as elt
    from app.infrastructure.chat_stream_lifetime import StreamLifetime, current_lifetime

    snapshots = iter(
        [
            _run("previewing", stage="parsing", progress=5, processed_rows=0),
            _run("previewing", stage="parsing", progress=5, processed_rows=0),
            _run("previewing", stage="transforming", progress=20, processed_rows=2),
            _run("previewing", stage="transforming", progress=30, processed_rows=3),
            _run("preview_ready", progress=100, processed_rows=10),
        ]
    )
    notes, events = [], []
    lifetime = StreamLifetime()
    lifetime.observe_notes(notes.append)
    lifetime.observe_tools(lambda *, sequence, record: events.append(record))
    token = current_lifetime.set(lifetime)
    db = SimpleNamespace(expire_all=lambda: None)
    monkeypatch.setattr(elt, "get_db", lambda: nullcontext(db))

    def read_run(_db, *, run_id, owner_user_id):
        assert (run_id, owner_user_id) == ("run-1", 7)
        return {**next(snapshots), "file_name": "销售明细.xlsx"}

    def while_pending(_seconds):
        # Every wait observes progress already delivered, before a terminal result.
        assert events and events[-1]["progress"] < 100

    monkeypatch.setattr(elt.time, "sleep", while_pending)
    try:
        result = elt._wait(
            SimpleNamespace(get_run=read_run),
            "run-1",
            7,
            pending=elt.PREVIEW_PENDING,
            timeout=5,
            runtime_context={"node_id": "preview-node"},
        )
    finally:
        current_lifetime.reset(token)
    assert result["status"] == "preview_ready"
    assert [event["progress"] for event in events] == [5, 20, 30, 100]
    assert [event["processed_rows"] for event in events] == [0, 2, 3, 10]
    assert all(event["node_id"] == "preview-node" for event in events)
    assert all(event["phase"] == "progress" and "action" not in event for event in events)
    assert len(notes) == 3  # Duplicate polls and row updates do not flood the prose.
    assert "销售明细.xlsx" in notes[0]
    assert "预演结果已生成" in notes[-1]


def test_wait_timeout_does_not_invent_completion_or_orphan_nodes(monkeypatch):
    from app.domain.shared_services import tools_workflow_elt as elt
    from app.infrastructure.chat_stream_lifetime import StreamLifetime, current_lifetime

    pending = _run("executing", stage="persisting", progress=None, processed_rows=10)
    notes, events = [], []
    lifetime = StreamLifetime()
    lifetime.observe_notes(notes.append)
    lifetime.observe_tools(lambda *, sequence, record: events.append(record))
    token = current_lifetime.set(lifetime)
    monkeypatch.setattr(
        elt, "get_db", lambda: nullcontext(SimpleNamespace(expire_all=lambda: None))
    )
    try:
        result = elt._wait(
            SimpleNamespace(get_run=lambda *args, **kwargs: pending),
            "run-1",
            7,
            pending=elt.EXECUTION_PENDING,
            timeout=0,
        )
    finally:
        current_lifetime.reset(token)
    assert result is pending and result["status"] == "executing"
    assert events == []  # Calls without a graph binding cannot create new graph steps.
    assert notes == ["正在写入业务数据"]  # No percent or success without persisted evidence.


def test_preview_returns_run_id_for_execute(elt_preview):
    elt, service = elt_preview
    with patch.object(elt, "_wait", return_value=_run()):
        result = _registered_router_elt_import(
            "preview",
            {"file_path": "宗南.xlsx"},
            {**_context(), "chat_approval_mode": "auto"},
            "normal",
            "导入",
        )
    assert result["success"] is True
    assert result["data"]["run_id"] == "run-1"
    assert result["data"]["target_type"] == "products"
    service.execute.assert_not_called()


def test_preview_reports_pending_mappings(elt_preview):
    elt, _service = elt_preview
    run = _run(
        draft={
            "field_mappings": [
                {"source": "单价", "target": "unit_price", "confidence": 0.6},
                {"source": "产品名称", "target": "product_name", "confidence": 0.98},
            ]
        }
    )
    with patch.object(elt, "_wait", return_value=run):
        result = _registered_router_elt_import(
            "preview", {"file_path": "宗南.xlsx"}, _context(), "normal", "导入"
        )
    assert result["data"]["mapping_pending"] == ["unit_price"]
    assert result["data"]["executable"] is False
    assert result["data"]["executable_with_suggestions"] is True
    assert result["resume_params"] == {"accept_suggested": True}
    assert "AI 建议" in result["message"]


def test_preview_keeps_only_selected_paths_in_auto_chat():
    captured: list[list[str]] = []

    def fake_batch(paths, _payload, _context):
        captured.append(list(paths))
        return {"success": True, "file_count": len(paths)}

    with (
        patch("app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True),
        patch(
            "app.domain.shared_services.tools_workflow_elt._bound_actor",
            return_value=MagicMock(id=7),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._preview_batch",
            side_effect=fake_batch,
        ),
    ):
        result = _registered_router_elt_import(
            "preview",
            {"file_paths": ["温总.xlsx"]},
            {**_context(), "chat_approval_mode": "auto"},
            "normal",
            "导入",
        )
    assert result["file_count"] == 1
    assert captured == [["温总.xlsx"]]


def test_preview_requires_explicit_scope_even_in_auto_chat():
    with (
        patch("app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True),
        patch("app.domain.shared_services.tools_workflow_elt._preview_batch") as preview,
    ):
        result = _registered_router_elt_import(
            "preview",
            {},
            {**_context(), "chat_approval_mode": "auto"},
            "normal",
            "导入",
        )
    assert result["error_code"] == "elt_file_path_required"
    preview.assert_not_called()


def test_batch_preview_stops_before_budget_is_exhausted():
    import time as _time

    from app.domain.shared_services import tools_workflow_elt as elt

    notes: list[str] = []
    with (
        patch.object(elt, "_preview") as preview,
        patch(
            "app.domain.shared_services.tools_workflow_elt.publish_stream_note",
            side_effect=notes.append,
        ),
    ):
        result = elt._preview_batch(
            ["a.xlsx", "b.xlsx", "c.xlsx"], {}, {"deadline_monotonic": _time.monotonic() - 1}
        )
    preview.assert_not_called()
    assert result["deferred_count"] == 3
    assert result["success"] is False
    assert result["data"]["executable"] is False
    assert notes and "剩余 3 个文件" in notes[0]


def test_batch_progress_notes_include_file_name_and_counts():
    from app.domain.shared_services import tools_workflow_elt as elt

    notes: list[str] = []
    with patch(
        "app.domain.shared_services.tools_workflow_elt.publish_stream_note",
        side_effect=notes.append,
    ):
        elt._batch_progress_note("预演", 2, 5, "客户清单.xlsx")
        elt._batch_result_note(
            "预演",
            "客户清单.xlsx",
            {
                "success": True,
                "data": {
                    "total_rows": 10,
                    "new_rows": 8,
                    "update_rows": 1,
                    "skip_rows": 1,
                    "error_rows": 0,
                },
            },
        )
        elt._batch_result_note("预演", "坏文件.xlsx", {"success": False, "message": "无法解析"})
    assert notes[0] == "正在预演 2/5：客户清单.xlsx"
    assert "「客户清单.xlsx」预演完成" in notes[1]
    assert "新增 8" in notes[1]
    assert notes[2] == "「坏文件.xlsx」预演失败：无法解析"


def test_preview_batch_publishes_progress_and_result_per_file():
    from app.domain.shared_services import tools_workflow_elt as elt

    notes: list[str] = []

    def fake_preview(params, _context, **_kwargs):
        if params["file_path"] == "a.xlsx":
            return {
                "success": True,
                "data": {
                    "run_id": "run-a",
                    "total_rows": 2,
                    "new_rows": 2,
                    "update_rows": 0,
                    "skip_rows": 0,
                    "error_rows": 0,
                },
            }
        return {"success": False, "message": "无法解析"}

    with (
        patch.object(elt, "_preview", side_effect=fake_preview),
        patch.object(elt, "_owned_upload", return_value={}),
        patch(
            "app.domain.shared_services.tools_workflow_elt.publish_stream_note",
            side_effect=notes.append,
        ),
    ):
        result = elt._preview_batch(["a.xlsx", "b.xlsx"], {}, {})
    assert notes[0] == "正在预演 1/2：a.xlsx"
    assert notes[1].startswith("「a.xlsx」预演完成")
    assert notes[2] == "正在预演 2/2：b.xlsx"
    assert notes[3] == "「b.xlsx」预演失败：无法解析"
    assert result["run_ids"] == []
    assert result["results"][0]["data"]["run_id"] == "run-a"
    assert result["results"][0]["file_name"] == "a.xlsx"


def test_preview_accept_suggested_unblocks_low_confidence_mappings():
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
        patch("app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True),
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
            "preview",
            {"file_path": "宗南.xlsx", "accept_suggested": True},
            _context(),
            "normal",
            "导入",
        )
    assert result["data"]["executable"] is True
    assert result["requires_user_decision"] is False


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
        patch("app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True),
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
        patch("app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True),
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
            return_value=[{"sheet": "宗南", "row": 18, "message": "公斤数或桶数至少填写一项"}],
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
        patch("app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True),
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
            return_value=[{"sheet": "宗南", "row": 18, "message": "公斤数或桶数至少填写一项"}],
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
        patch("app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True),
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


def test_execute_completes_with_elt_run(elt_tools):
    elt, service = elt_tools
    service.get_run.return_value = _run(preview_revision="a" * 64)
    service.execute.return_value = {"id": "run-1"}
    run = _run(
        status="completed", summary={"new": 0, "update": 0, "skip": 0, "error": 0, "executed": 10}
    )
    with patch.object(elt, "_wait", return_value=run):
        result = _registered_router_elt_import(
            "execute", {"run_id": "run-1"}, _context(), "normal", "导入"
        )
    assert result["success"] is True
    assert result["data"]["executed_rows"] == 10
    service.execute.assert_called_once()
    assert service.execute.call_args.kwargs["confirmed"] is True
    assert service.execute.call_args.kwargs["preview_revision"] == "a" * 64


def test_execute_reports_original_uncertain_receipt_without_resubmitting(elt_tools):
    elt, service = elt_tools
    service.get_run.return_value = _run(status="outcome_unknown")
    out = elt._execute({"run_id": "run-1"}, _context())
    service.execute.assert_not_called()
    assert out["outcome"] == "unknown" and out["retryable"] is False
    assert out["data"]["run_id"] == "run-1"


def test_execute_syncs_source_to_knowledge_base():
    service = MagicMock()
    service.get_run.return_value = {"id": "run-1", "preview_revision": "a" * 64}
    service.execute.return_value = {"id": "run-1"}
    run = _run(
        status="completed",
        summary={"new": 0, "update": 0, "skip": 0, "error": 0, "executed": 10},
    )
    with (
        patch("app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True),
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
        patch("app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True),
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
    assert "已登记模板到模板库（宗南家私-发货单版式）" in result["message"]


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
        patch("app.utils.path_io.path_utils.get_app_data_dir", return_value=str(tmp_path)),
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
    assert [field["label"] for field in payload["analyzed_data"]["fields"]] == [
        "产品型号",
        "数量/件",
    ]


def test_template_receipt_skips_run_without_selected_region():
    from app.domain.shared_services.tools_workflow_elt import _template_receipt

    receipt = _template_receipt({"upload_id": "upload-1", "source_features": {"regions": []}}, 7)
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
        "templates": [{"name": "宗南家私-发货单版式", "source": "db", "template_key": region_key}]
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
        patch("app.utils.path_io.path_utils.get_app_data_dir", return_value=str(tmp_path)),
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
        patch("app.utils.path_io.path_utils.get_app_data_dir", return_value=str(tmp_path)),
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


def test_execute_reports_all_duplicate_rows():
    """全部判定重复时必须明说没有写入，不能只回「导入完成」。"""
    service = MagicMock()
    service.get_run.return_value = {"id": "run-1", "preview_revision": "a" * 64}
    run = _run(
        status="completed",
        details={},
        summary={"new": 0, "update": 0, "skip": 3, "error": 0, "executed": 0},
    )
    with (
        patch("app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True),
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
    assert "重复跳过 3 行" in result["message"]
    assert "没有新增数据" in result["message"]


@pytest.mark.parametrize(
    "selected,revision",
    [
        ("run-1", None),
        ("companion-1", None),
        ("companion-1", "stale"),
        ("companion-1", "a" * 64),
    ],
)
def test_companion_requires_separate_current_preview_confirmation(selected, revision):
    service = MagicMock()
    link = {"run_id": "companion-1", "status": "preview_ready", "preview_revision": "a" * 64}
    primary = _run(status="completed", details={"linked_customer_products_preview": link})
    companion = _run(
        status="preview_ready",
        id="companion-1",
        target_type="customer_products",
        preview_revision="a" * 64,
        draft={"linked_preview": {"read_only": True, "parent_run_id": "run-1"}},
    )
    service.get_run.side_effect = lambda _db, *, run_id, owner_user_id: (
        primary if run_id == "run-1" else companion
    )
    with (
        patch(
            "app.domain.shared_services.tools_workflow_elt._bound_actor",
            return_value=MagicMock(id=7),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt.get_db",
            return_value=nullcontext(MagicMock()),
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._wait",
            return_value={**(primary if selected == "run-1" else companion), "status": "completed"},
        ),
        patch(
            "app.domain.shared_services.tools_workflow_elt._finalize_import",
            return_value=({}, {}, ""),
        ),
        patch("app.application.elt.service.get_elt_service", return_value=service),
    ):
        from app.domain.shared_services.tools_workflow_elt import _execute

        result = _execute({"run_id": selected, "preview_revision": revision}, _context())
    if selected == "run-1":
        service.execute.assert_not_called()
        disclosed = result["data"]["customer_products"]
        assert disclosed["run_id"] == "companion-1"
        assert disclosed["preview_revision"] == "a" * 64
        assert disclosed["requires_user_confirmation"] is True
        assert "未随本次出货写入" in result["message"]
        assert not result.get("requires_user_decision")
        assert "resume_params" not in result
        assert "发送新消息" in result["message"]
        assert "run_id=companion-1" in result["message"]
        assert "preview_revision=" + "a" * 64 in result["message"]
    elif revision != "a" * 64:
        service.execute.assert_not_called()
        assert result["error_code"] == "ELT_PREVIEW_CHANGED"
    else:
        assert result["success"] is True
        assert service.execute.call_count == 1
        submitted = service.execute.call_args.kwargs
        assert submitted["run_id"] == "companion-1" and submitted["preview_revision"] == revision
        assert submitted["confirmed"] is True
        assert submitted["valid_rows_only"] is False and submitted["accept_suggested"] is False


def test_existing_preview_read_precedes_auto_import_and_refreshes_live_status(monkeypatch):
    from app.domain.shared_services import tools_workflow_elt as elt

    child = _run(
        id="child",
        status="queued",
        target_type="customer_products",
        draft={"linked_preview": {"parent_run_id": "parent"}},
    )
    service = MagicMock()
    service.get_run.side_effect = lambda *_args, **_kwargs: dict(child)
    monkeypatch.setattr(elt, "_elt_enabled", lambda: True)
    monkeypatch.setattr(elt, "_bound_actor", lambda _ctx: SimpleNamespace(id=7))
    monkeypatch.setattr(elt, "get_db", lambda: nullcontext(MagicMock()))
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: service)
    create = MagicMock()
    monkeypatch.setattr(elt, "_preview", create)
    monkeypatch.setattr(elt, "_execute", create)
    params = {"run_id": "child", "file_path": "do-not-import.xlsx"}
    context = {**_context(), "chat_approval_mode": "auto"}
    pending = elt._registered_router_elt_import(
        "preview", params, context, "normal", "查看导入预演"
    )
    assert pending["data"]["status"] == "queued"
    assert "查看导入预演，run_id=child" in pending["message"]
    child.update(status="preview_ready", preview_revision="b" * 64)
    ready = elt._registered_router_elt_import("preview", params, context, "normal", "查看导入预演")
    assert ready["data"]["preview_revision"] == "b" * 64
    assert "preview_revision=" + "b" * 64 in ready["message"]
    assert not ready.get("requires_user_decision")
    create.assert_not_called()
    service.create_preview.assert_not_called()
    service.execute.assert_not_called()


def test_execute_waits_for_linked_preview_before_submitting_main(elt_tools):
    elt, service = elt_tools
    service.get_run.return_value = _run(
        target_type="shipment_records",
        details={"linked_customer_products_preview": {"run_id": "companion-1"}},
    )
    with patch.object(elt, "_wait", return_value=_run(status="previewing")):
        result = elt._execute({"run_id": "run-1"}, _context())

    service.execute.assert_not_called()
    assert result["success"] is False and result["deferred"] is True
    assert result["data"]["customer_products"]["run_id"] == "companion-1"
    assert result["data"]["executed_rows"] == 0


def test_linked_preview_gets_bounded_read_budget_before_normal_write_budget(elt_tools):
    import time

    from app.application.agent_orchestrator.tool_timeouts import ELT_LINKED_PREVIEW_TIMEOUT_SECONDS

    elt, service = elt_tools
    primary = _run(
        target_type="shipment_records",
        details={"linked_customer_products_preview": {"run_id": "companion-1"}},
    )
    service.get_run.return_value = primary
    renew = MagicMock(
        side_effect=lambda _phase: time.monotonic() + ELT_LINKED_PREVIEW_TIMEOUT_SECONDS + 5
    )
    with (
        patch.object(elt, "_finalize_import", return_value=({}, {}, "")),
        patch.object(
            elt,
            "_wait",
            side_effect=[
                _run(status="previewing"),
                _run(),
                {**primary, "status": "completed"},
                _run(status="completed"),
            ],
        ) as wait,
    ):
        result = elt._execute(
            {"run_id": "run-1"}, {**_context(), "_renew_elt_file_deadline": renew}
        )

    assert result["success"] is True
    assert [call.args for call in renew.call_args_list] == [("linked_preview",), ("execute",)]
    assert wait.call_args_list[1].kwargs["timeout"] == ELT_LINKED_PREVIEW_TIMEOUT_SECONDS
    assert wait.call_args_list[2].kwargs["timeout"] == elt.EXECUTION_TIMEOUT_SECONDS
    service.execute.assert_called_once()


@pytest.mark.parametrize("initial_state", ["queued", "previewing", "interrupted"])
def test_exact_linked_child_resumes_only_unsubmitted_preview(initial_state, elt_tools):
    elt, service = elt_tools
    child = _run(
        id="child",
        status=initial_state,
        target_type="customer_products",
        details={"linked_from_shipment_preview": "parent"},
        confirmed_at=None,
        executed_at=None,
        error={"code": "ELT_EXECUTION_INTERRUPTED"} if initial_state == "interrupted" else None,
    )
    ready = {**child, "status": "preview_ready", "preview_revision": "a" * 64}
    service.get_run.return_value = child
    service.retry.return_value = {**child, "status": "previewing"}
    with (
        patch.object(
            elt,
            "_verified_companion_source",
            return_value=SimpleNamespace(id="child", tenant_id=1, status=initial_state),
        ),
        patch.object(elt, "_wait", side_effect=[ready, {**ready, "status": "completed"}]),
    ):
        result = elt._execute({"run_id": "child", "preview_revision": "a" * 64}, _context())

    assert result["success"] is True
    assert service.retry.call_count == int(initial_state == "interrupted")
    assert service._submit_preview.call_count == int(initial_state == "queued")
    service.execute.assert_called_once()
    assert service.execute.call_args.kwargs["run_id"] == "child"


def test_approved_ready_child_fails_closed_when_parent_business_rows_are_gone(elt_tools):
    elt, service = elt_tools
    source = {"tenant_id": 1, "upload_id": "upload", "file_sha256": "sha"}
    parent = SimpleNamespace(
        **source,
        status="completed",
        target_type="shipment_records",
        executed_at="date",
        rollback_status=None,
        summary_json='{"linked_customer_products_preview": {"run_id": "child"}}',
    )
    child = SimpleNamespace(
        **source, id="child", confirmed_at=None, executed_at=None, executed_rows=0
    )
    service.get_run.return_value = _run(
        id="child",
        target_type="customer_products",
        details={"linked_from_shipment_preview": "parent"},
        preview_revision="a" * 64,
    )
    service._owned_run.side_effect = [child, parent]
    with patch(
        "app.application.elt.batch_continuation.shipment_parent_writes_present", return_value=False
    ) as readback:
        result = elt._execute({"run_id": "child", "preview_revision": "a" * 64}, _context())

    readback.assert_called_once()
    service.execute.assert_not_called()
    assert result["success"] is False and result["error_code"] == "elt_companion_incomplete"


@pytest.mark.parametrize("unresolved_write", [False, True])
def test_durable_batch_resumes_original_slots_or_stops_on_unknown(
    elt_tools, monkeypatch, unresolved_write
):
    from uuid import UUID

    from app.application.agent_orchestrator import business_write_guard

    elt, service = elt_tools
    paths = [str(UUID(int=index)) for index in (1, 2, 3)]
    context = {**_context(), "run_id": "agent", "step_id": "step", "durable_elt_batch": True}
    monkeypatch.setattr(
        business_write_guard, "capture_worker_claim", lambda: ("agent", "worker", 2)
    )
    monkeypatch.setattr(elt, "tenant_id_for_write", lambda: 1)
    ids = elt.durable_elt_checkpoint_ids("agent", "step", paths)
    rows = {
        ids[path]: SimpleNamespace(
            tenant_id=1, owner_user_id=7, upload_id=path, rolled_back_at=None, rollback_status=None
        )
        for path in (paths[:1] + paths[2:] if unresolved_write else paths[:1])
    }
    completed = _run(
        id=ids[paths[0]],
        status="completed",
        file_name="done.xlsx",
        confirmed_at="earlier",
        executed_at="earlier",
        summary={"executed": 8},
        receipt={"run_id": ids[paths[0]], "target_type": "products", "executed_rows": 8},
    )
    interrupted = _run(
        id=ids[paths[2]], status="interrupted", file_name="pending.xlsx", confirmed_at="earlier"
    )
    db = MagicMock()
    db.get.side_effect = lambda _model, run_id: rows.get(run_id)
    service.get_run.side_effect = lambda db, *, run_id, owner_user_id: (
        completed if run_id == completed["id"] else interrupted
    )
    monkeypatch.setattr(elt, "get_db", lambda: nullcontext(db))
    monkeypatch.setattr(elt, "_owned_upload", lambda path, _ctx: {"id": path})
    preview = MagicMock(
        side_effect=lambda *args, checkpoint_id, **kw: {
            "success": True,
            "data": {"run_id": checkpoint_id, "executable": True},
        }
    )
    execute = MagicMock(return_value={"success": True, "data": {"executed_rows": 2}})
    monkeypatch.setattr(elt, "_preview", preview)
    monkeypatch.setattr(elt, "_execute", execute)

    result = elt._preview_batch(paths, {}, context, write=True)

    assert result["data"]["executed_rows"] == (8 if unresolved_write else 12)
    if unresolved_write:
        assert result["outcome"] == "unknown" and result["deferred_count"] == 1
        preview.assert_not_called()
        execute.assert_not_called()
    else:
        assert result["success"] is True and result["done_count"] == 3
        assert [call.kwargs["checkpoint_id"] for call in preview.call_args_list] == [
            ids[path] for path in paths[1:]
        ]
        assert [call.args[0]["run_id"] for call in execute.call_args_list] == [
            ids[path] for path in paths[1:]
        ]


def test_resuming_preview_keeps_existing_elt_run_id(elt_preview):
    elt, service = elt_preview
    existing = _run(id="saved-preview", status="queued")
    with (
        patch.object(elt, "tenant_id_for_write", return_value=1),
        patch.object(elt, "_wait", return_value={**existing, "status": "preview_ready"}),
    ):
        result = elt._preview({"file_path": "saved"}, _context(), checkpoint=existing)
    assert result["success"] is True and result["data"]["run_id"] == "saved-preview"
    service.create_preview.assert_not_called()
    service._submit_preview.assert_called_once_with("saved-preview", 1, 7)


def test_new_durable_preview_passes_checkpoint_to_native_creation(elt_preview):
    elt, service = elt_preview
    service.create_preview.return_value = {"id": "checkpoint"}
    with patch.object(elt, "_wait", return_value=_run(id="checkpoint")):
        result = elt._preview({"file_path": "new"}, _context(), checkpoint_id="checkpoint")
    assert result["data"]["run_id"] == "checkpoint"
    assert service.create_preview.call_args.kwargs["checkpoint_run_id"] == "checkpoint"


def test_execute_requires_run_id():
    with patch("app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True):
        result = _registered_router_elt_import("execute", {}, _context(), "normal", "导入")
    assert result["success"] is False
    assert result["error_code"] == "missing_run_id"


def test_disabled_outside_enterprise():
    with patch("app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=False):
        result = _registered_router_elt_import(
            "preview", {"file_path": "宗南.xlsx"}, _context(), "normal", "导入"
        )
    assert result["error_code"] == "elt_center_disabled"


def test_unknown_action():
    with patch("app.domain.shared_services.tools_workflow_elt._elt_enabled", return_value=True):
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
    # 批量执行接受 run_id 或 run_ids（required_any 由 clarification 覆盖），因此不再固定必填 run_id。
    assert execute.required_params == []
    assert preview.required_params == []


def test_existing_durable_plan_does_not_claim_success_for_missing_duplicate_slot(
    elt_tools, monkeypatch
):
    elt, _service = elt_tools
    monkeypatch.setattr(elt, "_batch_checkpoint_ids", lambda *_: {"a": "run-a", "b": "run-b"})
    monkeypatch.setattr(elt, "_load_checkpoint_batch", lambda *_: ({}, {}))
    monkeypatch.setattr(
        elt,
        "_owned_upload",
        lambda path, _ctx: {
            "id": path,
            "file_name": "same.xlsx",
            "sha256": "same",
            "suffix": ".xlsx",
        },
    )
    preview = MagicMock(
        return_value={"success": True, "data": {"run_id": "run-a", "executable": True}}
    )
    execute = MagicMock(return_value={"success": True, "data": {"executed_rows": 1}})
    monkeypatch.setattr(elt, "_preview", preview)
    monkeypatch.setattr(elt, "_execute", execute)

    result = elt._preview_batch(["a", "b"], {}, {}, write=True)

    assert not result["success"]
    assert result["done_count"] == 1 and result["data"]["executed_rows"] == 1
    assert result["results"][1]["error_code"] == "elt_duplicate_approved_upload"
    preview.assert_called_once()
    execute.assert_called_once()
