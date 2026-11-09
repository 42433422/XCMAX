"""Office-file parse uses ELT, optional worksheet templates, and approval ingest."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

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
from app.application.workflow.chat_deterministic_fast_paths import try_deterministic_chat_reply


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

    monkeypatch.setattr("app.application.elt.docking_approval.submit_docking_write", _submit)
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
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    assert is_office_elt_chat_message("@uploads/宗南.xlsx导入数据库") is True
    missing = office_chat_elt_reply(
        "@uploads/宗南.xlsx导入数据库", {"tenant_id": 1, "local_user_id": 2}
    )
    assert missing["success"] is False
    assert missing["response"].startswith("处理失败：")
    routed = try_deterministic_chat_reply(
        "@uploads/宗南.xlsx导入数据库",
        runtime_context={"tenant_id": 1, "local_user_id": 2},
    )
    assert routed["success"] is False
    assert routed["response"].startswith("处理失败：")


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
