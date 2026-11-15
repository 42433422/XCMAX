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


def test_split_run_ids_accepts_separators():
    assert tools_workflow_elt._split_run_ids("a, b；c") == ["a", "b", "c"]
    assert tools_workflow_elt._split_run_ids(["a", " ", "b"]) == ["a", "b"]
    assert tools_workflow_elt._split_run_ids("") == []


def test_preview_batch_caps_at_twenty(monkeypatch):
    monkeypatch.setattr(
        tools_workflow_elt, "_preview", lambda params, _context: {"success": True}
    )
    out = tools_workflow_elt._preview_batch([f"f{i}.xlsx" for i in range(25)], {}, {})
    assert out["file_count"] == 20
    assert out["truncated"] is True
    assert "一次最多 20 个" in out["message"]


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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
