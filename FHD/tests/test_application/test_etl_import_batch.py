"""ELT 批量预览/执行与同名文件新鲜度约束。"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.application.tools import workflow_spreadsheet_scope
from app.domain.shared_services import tools_workflow_elt


@pytest.fixture(autouse=True)
def _stub_upload_lookup(monkeypatch):
    monkeypatch.setattr(tools_workflow_elt, "_owned_upload", lambda *_args: {})


def test_preview_batch_reports_each_file(monkeypatch):
    calls: list[str] = []

    def fake_preview(params, _context, **_kwargs):
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
        lambda params, _context, **_kwargs: {
            "success": True,
            "data": {"run_id": f"r-{params['file_path']}"},
        },
    )
    out = tools_workflow_elt._preview_batch(["a.xlsx", "b.xlsx"], {}, {})
    assert out["run_ids"] == ["r-a.xlsx", "r-b.xlsx"]


def test_batch_preview_exposes_data_for_workflow_references(monkeypatch):
    from app.application.agent_orchestrator.param_references import resolve_references

    monkeypatch.setattr(
        tools_workflow_elt,
        "_preview",
        lambda params, _context, **_kwargs: {
            "success": True,
            "data": {"run_id": f"r-{params['file_path']}"},
        },
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
    stages: list[dict] = []
    monkeypatch.setattr(tools_workflow_elt, "publish_stream_tool_record", stages.append)
    monkeypatch.setattr(
        tools_workflow_elt,
        "_preview",
        lambda params, _context, **_kwargs: {"success": True, "data": {"total_rows": 1}},
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


def test_split_paths_preserves_explicit_punctuation():
    assert tools_workflow_elt._split_paths(["a.xlsx,b.xlsx", "c.xlsx"]) == [
        "a.xlsx,b.xlsx",
        "c.xlsx",
    ]
    assert tools_workflow_elt._split_paths(["a.xlsx"]) == ["a.xlsx"]
    assert tools_workflow_elt._split_paths("a.xlsx") == []


def test_reference_resolution_feeds_array_validation(monkeypatch):
    """规划把 {{preview.data.run_id}} 写进 run_ids 时，解析后能通过类型校验。"""
    from app.application.agent_orchestrator.param_references import resolve_references
    from app.application.agent_orchestrator.tool_spec import validate_schema_object

    monkeypatch.setattr(
        tools_workflow_elt,
        "_preview",
        lambda params, _context, **_kwargs: {
            "success": True,
            "data": {"run_id": f"r-{params['file_path']}"},
        },
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


@pytest.mark.parametrize("mode", ["auto", "manual"])
def test_preview_batch_does_not_execute(monkeypatch, mode):
    monkeypatch.setattr(
        tools_workflow_elt,
        "_preview",
        lambda params, _context, **_kwargs: {
            "success": True,
            "data": {"run_id": f"r-{params['file_path']}", "executable": True},
        },
    )
    monkeypatch.setattr(
        tools_workflow_elt,
        "_execute",
        lambda *args, **kwargs: pytest.fail("不应自动执行"),
    )
    out = tools_workflow_elt._preview_batch(["a.xlsx"], {}, {"chat_approval_mode": mode})
    assert out["data"]["executable"] is True
    assert out["run_ids"] == ["r-a.xlsx"]


def test_preview_batch_caps_at_fifty(monkeypatch):
    monkeypatch.setattr(tools_workflow_elt, "_preview", lambda *_args, **_kwargs: {"success": True})
    out = tools_workflow_elt._preview_batch([f"f{i}.xlsx" for i in range(60)], {}, {})
    assert out["file_count"] == 50
    assert out["truncated"] is True
    assert out["success"] is False
    assert out["data"]["executable"] is False
    assert "一次最多 50 个" in out["message"]


def test_preview_deduplicates_owned_content_with_same_file_name(monkeypatch):
    calls: list[str] = []

    def upload(path, _context):
        name = "其他订单.xlsx" if path == "different-name" else "订单.xlsx"
        return {"id": path, "file_name": name, "suffix": ".xlsx", "sha256": "same-content"}

    def preview(_params, _context, *, upload):
        calls.append(upload["id"])
        return {"success": True, "data": {"run_id": upload["id"]}}

    monkeypatch.setattr(tools_workflow_elt, "_owned_upload", upload)
    monkeypatch.setattr(tools_workflow_elt, "_preview", preview)
    out = tools_workflow_elt._preview_batch(["first", "duplicate", "different-name"], {}, {})
    assert calls == out["run_ids"] == ["first", "different-name"]


def test_preview_budget_preserves_receipts_without_unlocking_execute(monkeypatch):
    budget = iter([20, 0])
    monkeypatch.setattr(tools_workflow_elt, "_remaining_budget", lambda _context: next(budget))
    monkeypatch.setattr(
        tools_workflow_elt,
        "_preview",
        lambda *_args, **_kwargs: {
            "success": True,
            "data": {"run_id": "run-a", "executable": True},
        },
    )
    out = tools_workflow_elt._preview_batch(["a.xlsx", "b.xlsx"], {}, {})
    assert out["success"] is False and out["data"]["executable"] is False
    assert out["deferred_count"] == 1 and out["data"]["run_ids"] == []
    assert out["results"][0]["data"]["run_id"] == "run-a"


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
    assert out["success"] is False
    assert out["results"][0]["run_id"] == "ok-1"


@pytest.mark.parametrize(
    "action,selection,stages",
    [
        ("preview", "file_paths", ["preview"]),
        ("execute", "file_paths", ["preview", "execute"]),
        ("execute", "run_ids", ["execute"]),
    ],
)
def test_elt_batch_renews_deadline_per_stage_beyond_300_seconds(
    monkeypatch, action, selection, stages
):
    clock = 0.0
    renewed = []
    budgets = {"preview": 120, "execute": 240}

    def renew(stage):
        renewed.append(stage)
        return clock + budgets[stage]

    def work(stage, context):
        nonlocal clock
        limit = budgets[stage]
        assert context["deadline_monotonic"] == clock + limit
        usable = tools_workflow_elt._wait_timeout({}, context, limit)
        assert usable == limit - tools_workflow_elt._RESERVED_SECONDS
        clock += usable - 1  # The old stage has only one usable second left.

    def preview(params, context, **_kwargs):
        work("preview", context)
        return {"success": True, "data": {"run_id": params["file_path"], "executable": True}}

    def execute(_params, context):
        work("execute", context)
        return {"success": True, "data": {"executed_rows": 1}}

    monkeypatch.setattr(tools_workflow_elt, "time", SimpleNamespace(monotonic=lambda: clock))
    monkeypatch.setattr(tools_workflow_elt, "_elt_enabled", lambda: True)
    monkeypatch.setattr(tools_workflow_elt, "_run_label", lambda run, _context: run)
    monkeypatch.setattr(tools_workflow_elt, "_preview", preview)
    monkeypatch.setattr(tools_workflow_elt, "_execute", execute)
    context = {"deadline_monotonic": 300, "_renew_elt_file_deadline": renew}
    params = {selection: [f"file-{index}.xlsx" for index in range(22)]}
    out = tools_workflow_elt._registered_router_elt_import(
        action, params, context, "normal", "导入"
    )

    assert clock > 300
    assert renewed == stages * 22
    assert out["success"] is True and out["deferred_count"] == 0
    assert len(out["results"]) == 22


@pytest.mark.parametrize("rolling_deadline", [False, True])
def test_execute_batch_stops_on_unknown_and_keeps_completed_receipts(monkeypatch, rolling_deadline):
    calls: list[str] = []

    def execute(params, _context):
        calls.append(params["run_id"])
        if params["run_id"] == "first":
            return {"success": True, "data": {"run_id": "first", "executed_rows": 3}}
        return {"success": False, "outcome": "unknown", "message": "核对 second"}

    monkeypatch.setattr(tools_workflow_elt, "_execute", execute)
    monkeypatch.setattr(tools_workflow_elt, "_run_label", lambda run, _context: run)
    context = (
        {"_renew_elt_file_deadline": lambda _stage: tools_workflow_elt.time.monotonic() + 240}
        if rolling_deadline
        else {}
    )
    out = tools_workflow_elt._execute_batch(["first", "second", "third"], {}, context)
    assert calls == ["first", "second"]
    assert out["success"] is False and out["retryable"] is False
    assert out["outcome"] == "unknown" and out["reconciliation_required"] is True
    assert out["deferred_run_ids"] == ["third"]
    assert out["data"]["executed_rows"] == 3 and out["results"][0]["run_id"] == "first"


@pytest.mark.parametrize(("stop", "written"), [(None, 9), ("unknown", 3), ("budget", 6)])
def test_import_by_file_writes_each_ready_file_before_previewing_the_next(monkeypatch, stop, written):
    from app.application.agent_orchestrator.tool_spec import validate_tool_call

    calls = []

    def preview(params, _context, **_kwargs):
        name = params["file_path"]
        calls.append(("preview", name))
        review = name == "review.xlsx"
        return {
            "success": True,
            "message": "预演完成",
            "requires_user_decision": review,
            "data": {"run_id": name, "executable": not review},
        }

    def execute(params, _context):
        name = params["run_id"]
        calls.append(("execute", name))
        if name == "last.xlsx" and stop == "unknown":
            return {"success": False, "outcome": "unknown", "message": "核对原回执"}
        return {"success": True, "data": {"executed_rows": 3}}

    monkeypatch.setattr(tools_workflow_elt, "_elt_enabled", lambda: True)
    monkeypatch.setattr(tools_workflow_elt, "_preview", preview)
    monkeypatch.setattr(tools_workflow_elt, "_execute", execute)
    if stop == "budget":
        monkeypatch.setattr(
            tools_workflow_elt, "_remaining_budget", lambda _context: 0 if len(calls) >= 5 else None
        )
    params = {"file_paths": ["first.xlsx", "review.xlsx", "last.xlsx", "next.xlsx"]}
    assert validate_tool_call("elt_import", "execute", params).ok
    out = tools_workflow_elt._registered_router_elt_import("execute", params, {}, "normal", "导入")
    assert calls[:5] == [
        ("preview", "first.xlsx"),
        ("execute", "first.xlsx"),
        ("preview", "review.xlsx"),
        ("preview", "last.xlsx"),
        ("execute", "last.xlsx"),
    ]
    assert out["success"] is False and "1 份待确认" in out["message"]
    assert out["data"]["executed_rows"] == written
    assert out["deferred_count"] == int(stop is not None)
    if stop == "unknown":
        assert len(calls) == 5 and out["reconciliation_required"] is True


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
        lambda params, _context, **_kwargs: (
            calls.append(params["file_path"]) or {"success": True, "data": {}}
        ),
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
