"""ELT 批量预览/执行与同名文件新鲜度约束。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.application.tools import workflow_spreadsheet_scope
from app.domain.shared_services import tools_workflow_elt


def test_preview_batch_reports_each_file(monkeypatch):
    calls: list[str] = []

    def fake_preview(params, _context):
        calls.append(params["file_path"])
        if params["file_path"].endswith("bad.xlsx"):
            return {"success": False, "error_code": "elt_preview_not_ready", "message": "坏文件"}
        return {"success": True, "data": {"total_rows": 3}, "requires_user_decision": False}

    monkeypatch.setattr(tools_workflow_elt, "_preview", fake_preview)
    out = tools_workflow_elt._preview_batch(["a.xlsx", "bad.xlsx"], {}, {})

    assert calls == ["a.xlsx", "bad.xlsx"]
    assert out["batch"] is True
    assert out["file_count"] == 2
    assert out["ready_count"] == 1
    assert out["results"][1]["success"] is False
    assert "需人工确认 0" in out["message"]
    assert out["run_ids"] == []


def test_preview_batch_collects_run_ids(monkeypatch):
    monkeypatch.setattr(
        tools_workflow_elt,
        "_preview",
        lambda params, _context: {"success": True, "data": {"run_id": f"r-{params['file_path']}"}},
    )
    out = tools_workflow_elt._preview_batch(["a.xlsx", "b.xlsx"], {}, {})
    assert out["run_ids"] == ["r-a.xlsx", "r-b.xlsx"]


def test_batch_preview_exposes_data_for_workflow_references(monkeypatch):
    from app.application.agent_orchestrator.param_references import resolve_references

    monkeypatch.setattr(
        tools_workflow_elt,
        "_preview",
        lambda params, _context: {"success": True, "data": {"run_id": f"r-{params['file_path']}"}},
    )
    out = tools_workflow_elt._preview_batch(["a.xlsx", "b.xlsx"], {}, {})
    assert out["data"]["run_ids"] == ["r-a.xlsx", "r-b.xlsx"]
    assert out["data"]["run_id"] == "r-a.xlsx,r-b.xlsx"

    problems: list[str] = []
    resolved = resolve_references(
        "{{preview_import.data.run_id}}", {"preview_import": out}, problems
    )
    assert problems == []
    assert resolved == "r-a.xlsx,r-b.xlsx"


def test_preview_batch_publishes_per_file_stage(monkeypatch):
    """执行链要能显示「正在处理哪个文件 / 哪个文件已完成」。"""
    from app.infrastructure import chat_stream_lifetime

    stages: list[dict] = []
    monkeypatch.setattr(chat_stream_lifetime, "publish_stream_tool_record", stages.append)
    monkeypatch.setattr(
        tools_workflow_elt,
        "_preview",
        lambda params, _context: {"success": True, "data": {"total_rows": 1}},
    )
    tools_workflow_elt._preview_batch(["a.xlsx", "b.xlsx"], {}, {})

    assert [item["phase"] for item in stages] == ["started", "finished", "started", "finished"]
    assert stages[0]["node_id"] == "elt-preview-1"
    assert stages[2]["node_id"] == "elt-preview-2"
    assert "1/2" in stages[0]["action"] and "2/2" in stages[2]["action"]
    assert stages[1]["success"] is True
    assert stages[1]["tool_id"] == "elt_import"


def test_split_run_ids_accepts_separators():
    assert tools_workflow_elt._split_run_ids("a, b；c") == ["a", "b", "c"]
    assert tools_workflow_elt._split_run_ids(["a", " ", "b"]) == ["a", "b"]
    assert tools_workflow_elt._split_run_ids("") == []


def test_split_run_ids_flattens_single_wrapped_joined_string():
    """规划把 {{preview.data.run_id}} 包进数组时，不能整串当成一个编号。"""
    assert tools_workflow_elt._split_run_ids(["a,b,c"]) == ["a", "b", "c"]
    assert tools_workflow_elt._split_run_ids(["a", "b,c"]) == ["a", "b", "c"]


def test_execute_route_flattens_wrapped_run_ids(monkeypatch):
    executed: list[str] = []
    monkeypatch.setattr(
        tools_workflow_elt,
        "_execute",
        lambda params, _context: executed.append(params["run_id"]) or {"success": True},
    )
    monkeypatch.setattr(tools_workflow_elt, "_elt_enabled", lambda: True)
    out = tools_workflow_elt._registered_router_elt_import(
        "execute", {"run_ids": ["a-1,b-2"]}, {}, "enterprise", "导入"
    )
    assert out["success"] is True
    assert executed == ["a-1", "b-2"]


def test_split_paths_flattens_single_wrapped_joined_string():
    assert tools_workflow_elt._split_paths(["a.xlsx,b.xlsx"]) == ["a.xlsx", "b.xlsx"]
    assert tools_workflow_elt._split_paths(["a.xlsx"]) == ["a.xlsx"]
    assert tools_workflow_elt._split_paths("a.xlsx") == []


def test_reference_resolution_feeds_array_validation(monkeypatch):
    """规划把 {{preview.data.run_id}} 写进 run_ids 时，解析后能通过类型校验。"""
    from app.application.agent_orchestrator.param_references import resolve_references
    from app.application.agent_orchestrator.tool_spec import validate_schema_object

    monkeypatch.setattr(
        tools_workflow_elt,
        "_preview",
        lambda params, _context: {"success": True, "data": {"run_id": f"r-{params['file_path']}"}},
    )
    out = tools_workflow_elt._preview_batch(["a.xlsx", "b.xlsx"], {}, {})
    problems: list[str] = []
    params = resolve_references({"run_ids": "{{preview.data.run_id}}"}, {"preview": out}, problems)
    assert problems == []
    schema = {
        "type": "object",
        "properties": {"run_ids": {"type": "array", "items": {"type": "string"}}},
    }
    ok, message = validate_schema_object(schema, params)
    assert ok, message
    assert params["run_ids"] == ["r-a.xlsx", "r-b.xlsx"]


def test_preview_batch_auto_executes_executable_items(monkeypatch):
    monkeypatch.setattr(
        tools_workflow_elt,
        "_preview",
        lambda params, _context: {
            "success": True,
            "data": {"run_id": f"r-{params['file_path']}", "executable": True},
        },
    )
    executed: list[list[str]] = []

    def fake_execute(run_ids, payload, _context):
        executed.append(list(run_ids))
        assert payload["accept_suggested"] is True
        return {"success": True, "done_count": len(run_ids)}

    monkeypatch.setattr(tools_workflow_elt, "_execute_batch", fake_execute)
    out = tools_workflow_elt._preview_batch(
        ["a.xlsx", "b.xlsx"], {}, {"chat_approval_mode": "auto"}
    )
    assert executed == [["r-a.xlsx", "r-b.xlsx"]]
    assert out["data"]["executed_count"] == 2
    assert "已自动入库 2 个" in out["message"]


def test_preview_batch_skips_auto_execute_without_auto_approval(monkeypatch):
    monkeypatch.setattr(
        tools_workflow_elt,
        "_preview",
        lambda params, _context: {
            "success": True,
            "data": {"run_id": f"r-{params['file_path']}", "executable": True},
        },
    )
    monkeypatch.setattr(
        tools_workflow_elt,
        "_execute_batch",
        lambda *args, **kwargs: pytest.fail("不应自动执行"),
    )
    out = tools_workflow_elt._preview_batch(["a.xlsx"], {}, {})
    assert out["data"]["executed_count"] == 0


def test_mentions_file_only_when_user_names_it():
    assert tools_workflow_elt._mentions_file("导入温总.xlsx", ["温总.xlsx"]) is True
    assert tools_workflow_elt._mentions_file("导入", ["温总.xlsx"]) is False


def test_preview_batch_caps_at_fifty(monkeypatch):
    monkeypatch.setattr(tools_workflow_elt, "_preview", lambda params, _context: {"success": True})
    out = tools_workflow_elt._preview_batch([f"f{i}.xlsx" for i in range(60)], {}, {})
    assert out["file_count"] == 50
    assert out["truncated"] is True
    assert "一次最多 50 个" in out["message"]


def test_execute_batch_reports_each_run(monkeypatch):
    monkeypatch.setattr(
        tools_workflow_elt,
        "_execute",
        lambda params, _context: (
            {"success": True}
            if params["run_id"].startswith("ok")
            else {"success": False, "message": "失败"}
        ),
    )
    out = tools_workflow_elt._execute_batch(["ok-1", "bad-2"], {}, {})
    assert out["run_count"] == 2
    assert out["done_count"] == 1
    assert out["results"][0]["run_id"] == "ok-1"


def test_fresh_upload_cutoff_honours_env(monkeypatch):
    monkeypatch.setenv("XCAGI_ELT_UPLOAD_FRESH_HOURS", "2")
    cutoff = workflow_spreadsheet_scope._fresh_upload_cutoff()
    assert workflow_spreadsheet_scope.utc_now_naive() - cutoff < timedelta(hours=2, minutes=1)


def test_fresh_upload_cutoff_falls_back_on_invalid_value(monkeypatch):
    monkeypatch.setenv("XCAGI_ELT_UPLOAD_FRESH_HOURS", "abc")
    cutoff = workflow_spreadsheet_scope._fresh_upload_cutoff()
    delta = workflow_spreadsheet_scope.utc_now_naive() - cutoff
    assert timedelta(hours=23) < delta < timedelta(hours=25)


def test_register_elt_upload_skips_without_identity(tmp_path):
    from app.application.attachment_artifacts.router import _register_elt_upload

    target = tmp_path / "a.xlsx"
    target.write_bytes(b"x")
    assert _register_elt_upload(target, "a.xlsx", None, None) == ""
    assert _register_elt_upload(target, "note.docx", None, (1, 2)) == ""


def test_preview_batch_expands_uploaded_directory(tmp_path, monkeypatch):
    """模型把本地目录当文件传时，按目录内已上传文件展开，不再报 upload_not_found。"""
    folder = tmp_path / "2026.10月综合系列"
    folder.mkdir()
    (folder / "26年材料总表.xlsx").write_bytes(b"x")
    (folder / "忽略.txt").write_text("x", encoding="utf-8")

    calls: list[str] = []
    monkeypatch.setattr(
        tools_workflow_elt,
        "_owned_upload",
        lambda path, _context: {"id": "u1"} if path == "26年材料总表.xlsx" else {},
    )
    monkeypatch.setattr(
        tools_workflow_elt,
        "_preview",
        lambda params, _context: calls.append(params["file_path"]) or {"success": True, "data": {}},
    )

    out = tools_workflow_elt._preview_batch([str(folder)], {}, {})

    assert calls == ["26年材料总表.xlsx"]
    assert out["ready_count"] == 1


def test_preview_batch_reports_directory_without_uploads(tmp_path, monkeypatch):
    """目录里没有已上传记录时，给出可执行提示而不是「找不到上传文件」。"""
    folder = tmp_path / "空目录"
    folder.mkdir()
    (folder / "26年材料总表.xlsx").write_bytes(b"x")

    monkeypatch.setattr(tools_workflow_elt, "_owned_upload", lambda *_args: {})
    monkeypatch.setattr(
        tools_workflow_elt,
        "_preview",
        lambda *_args: pytest.fail("不应把目录当文件预演"),
    )

    out = tools_workflow_elt._preview_batch([str(folder)], {}, {})

    assert out["ready_count"] == 0
    assert out["results"][0]["error_code"] == "directory_needs_upload"
    assert "上传" in out["results"][0]["message"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
