from __future__ import annotations

import json

import pytest

from modstore_server.mod_ai_scaffold import parse_llm_mod_suite_json
from modstore_server.mod_scaffold_runner import (
    run_mod_suite_mod_sandbox,
    write_mod_suite_industry_card,
    write_mod_suite_ui_shell,
)
from modstore_server.workbench_api import (
    _default_steps,
    _embed_script_workflow_in_employee_pack,
    _fallback_employee_orchestration_plan,
)


def _suite_payload() -> dict:
    return {
        "manifest": {
            "id": "manufacture-flow",
            "name": "制造协同",
            "version": "1.0.0",
            "description": "生产协同与库存管理",
        },
        "industry": {
            "name": "制造业",
            "scenario": "生产任务、库存和报表协同",
            "product_fields": {"name": "物料名称", "category": "物料分类"},
            "order_types": {"shipment": "发货单"},
        },
        "ui_shell": {
            "sidebar_menu": [
                {"key": "products", "label": "物料管理", "path": "/materials", "order": 20},
                {"key": "shipments", "label": "发货单记录", "path": "/shipments", "order": 40},
            ],
            "settings": {"industry_options": ["制造业"]},
            "make_scene": {"title": "制作制造协同", "description": "按制造流程生成可运行工作流。"},
        },
        "employees": [
            {
                "id": "inventory_planner",
                "label": "库存计划员",
                "panel_title": "库存协同",
                "panel_summary": "跟踪库存并输出补货建议",
                "workflow": {
                    "name": "库存协同工作流",
                    "description": "读取库存，判断缺口，输出建议。",
                },
            }
        ],
        "configs": {"reports": ["库存日报"]},
    }


def test_parse_mod_suite_json_extracts_wrapped_json():
    payload = _suite_payload()
    raw = "模型说明如下：\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```\n请查收"
    parsed, err = parse_llm_mod_suite_json(raw)
    assert err == ""
    assert parsed
    assert parsed["manifest"]["id"] == "manufacture-flow"
    assert parsed["blueprint"]["industry"]["name"] == "制造业"
    assert parsed["manifest"]["industry"]["product_fields"]["name"] == "物料名称"
    assert parsed["manifest"]["frontend"]["menu_overrides"][0]["key"] in {"products", "shipments"}
    assert len(parsed["manifest"]["frontend"]["shell"]["sidebar_menu"]) >= 18
    assert parsed["blueprint"]["ui_shell"]["settings"]["industry_options"] == ["制造业"]
    assert parsed["employees"][0]["id"] == "inventory_planner"


def test_default_mod_steps_are_full_flow():
    ids = [s["id"] for s in _default_steps("mod")]
    assert ids == [
        "spec",
        "manifest",
        "repo",
        "industry",
        "employees",
        "employee_impls",
        "workflows",
        "register_packs",
        "api",
        "workflow_sandbox",
        "mod_sandbox",
        "complete",
    ]


def test_default_employee_steps_include_named_sandboxes():
    ids_pack = [s["id"] for s in _default_steps("employee", employee_target="pack_only")]
    assert ids_pack == [
        "spec",
        "employee_plan",
        "generate",
        "validate",
        "script_workflow",
        "embed_script",
        "workflow",
        "register_pack",
        "workflow_sandbox",
        "mod_sandbox",
        "standalone_smoke",
        "host_check",
        "six_dim_gate",
        "complete",
    ]
    ids_plus = [s["id"] for s in _default_steps("employee", employee_target="pack_plus_workflow")]
    assert ids_plus == ids_pack


def test_employee_orchestration_fallback_plan_splits_briefs():
    plan = _fallback_employee_orchestration_plan(
        "做一个文档归纳助手，读取文档并输出 Markdown 摘要",
        {"execution_checklist": ["支持多文件", "输出 md"]},
    )
    assert plan["employee_brief"]
    assert "inputs/" in plan["script_brief"]
    assert "outputs/" in plan["script_brief"]
    assert plan["workflow_brief"]
    assert plan["acceptance"]


@pytest.mark.asyncio
async def test_workbench_employee_multipart_session_keeps_uploaded_files(monkeypatch):
    """做员工带样本文件时，附件必须进入员工配套脚本生成链路。"""
    from types import SimpleNamespace

    from starlette.datastructures import FormData, Headers, UploadFile

    from modstore_server import workbench_api as wa

    captured = {}

    class _Req:
        headers = Headers({"content-type": "multipart/form-data; boundary=x"})

        async def form(self):
            meta = {
                "intent": "employee",
                "brief": "生成考勤转换员工",
                "employee_target": "pack_plus_workflow",
                "embed_script_workflow": True,
            }
            upload = UploadFile(
                filename="太阳鸟展示包装_考勤报表.xlsx",
                file=__import__("io").BytesIO(b"xlsx-bytes"),
            )
            return FormData([("metadata", json.dumps(meta, ensure_ascii=False)), ("files", upload)])

    async def _fake_run_pipeline(sid, user_id, payload):
        return None

    def _fake_run_pipeline_factory(sid, user_id, payload):
        captured["sid"] = sid
        captured["user_id"] = user_id
        captured["payload"] = payload
        return _fake_run_pipeline(sid, user_id, payload)

    class _NoopTask:
        def add_done_callback(self, _cb):
            return None

    monkeypatch.setattr(wa.asyncio, "create_task", lambda coro: (coro.close(), _NoopTask())[1])
    monkeypatch.setattr(wa, "_run_pipeline", _fake_run_pipeline_factory)

    res = await wa.create_workbench_session(_Req(), user=SimpleNamespace(id=7))

    sid = res["session_id"]
    assert captured["payload"]["intent"] == "employee"
    assert captured["payload"]["_files"][0]["filename"] == "太阳鸟展示包装_考勤报表.xlsx"
    assert captured["payload"]["_files"][0]["content"] == b"xlsx-bytes"
    wa.WORKBENCH_SESSIONS.pop(sid, None)


@pytest.mark.asyncio
async def test_workbench_json_session_body_parses_without_fastapi_body_injection(monkeypatch):
    """JSON 启动会话也必须由 request 手动解析，避免 Optional body 触发 Pydantic 英文错误。"""
    from types import SimpleNamespace

    from starlette.datastructures import Headers

    from modstore_server import workbench_api as wa

    captured = {}

    class _Req:
        headers = Headers({"content-type": "application/json"})

        async def json(self):
            return {
                "intent": "employee",
                "brief": "生成员工",
                "employee_target": "pack_plus_workflow",
            }

    async def _fake_run_pipeline(sid, user_id, payload):
        return None

    def _fake_run_pipeline_factory(sid, user_id, payload):
        captured["payload"] = payload
        return _fake_run_pipeline(sid, user_id, payload)

    class _NoopTask:
        def add_done_callback(self, _cb):
            return None

    monkeypatch.setattr(wa.asyncio, "create_task", lambda coro: (coro.close(), _NoopTask())[1])
    monkeypatch.setattr(wa, "_run_pipeline", _fake_run_pipeline_factory)

    res = await wa.create_workbench_session(_Req(), user=SimpleNamespace(id=7))

    sid = res["session_id"]
    assert captured["payload"]["intent"] == "employee"
    assert captured["payload"]["employee_target"] == "pack_plus_workflow"
    wa.WORKBENCH_SESSIONS.pop(sid, None)


def test_embed_script_workflow_in_employee_pack_manifest(tmp_path):
    pack_dir = tmp_path / "doc-helper"
    pack_dir.mkdir()
    manifest = {
        "id": "doc-helper",
        "name": "文档助手",
        "employee_config_v2": {
            "collaboration": {
                "workflow": {"workflow_id": 7},
            },
        },
    }
    (pack_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    attachment = _embed_script_workflow_in_employee_pack(
        pack_dir,
        script_workflow={"id": 42, "name": "文档助手 脚本工作流"},
        brief="批量生成 docstring",
    )

    updated = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    scripts = updated["employee_config_v2"]["collaboration"]["script_workflows"]
    assert attachment["script_workflow_id"] == 42
    assert scripts[0]["script_workflow_id"] == 42
    assert scripts[0]["workflow_id"] == 42
    assert scripts[0]["role"] == "primary_program"


def test_embed_script_workflow_missing_manifest_raises(tmp_path):
    """manifest.json 缺失时抛出 FileNotFoundError，不 crash 整 session。"""
    pack_dir = tmp_path / "no-manifest-pack"
    pack_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="manifest.json"):
        _embed_script_workflow_in_employee_pack(
            pack_dir,
            script_workflow={"id": 1, "name": "test"},
            brief="test",
        )


def test_embed_script_workflow_invalid_manifest_raises(tmp_path):
    """manifest.json 非法 JSON 时抛出 ValueError，含明确错误信息。"""
    pack_dir = tmp_path / "bad-manifest-pack"
    pack_dir.mkdir()
    (pack_dir / "manifest.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError, match="manifest.json"):
        _embed_script_workflow_in_employee_pack(
            pack_dir,
            script_workflow={"id": 1, "name": "test"},
            brief="test",
        )


def _make_in_memory_db():
    """Return a minimal SQLAlchemy in-memory SQLite Session for bundle tests."""
    pytest.importorskip("sqlalchemy")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from modstore_server.models import Base  # type: ignore

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_export_workflow_bundle_round_trip(tmp_path):
    """Bundle export serialises all nodes/edges; rehydration recreates them."""
    db = _make_in_memory_db()
    from modstore_server.employee_pack_workflow_bundle import (
        export_workflow_bundle,
        rehydrate_workflow_bundles,
    )
    from modstore_server.models import User, Workflow, WorkflowEdge, WorkflowNode

    user = User(id=1, username="tester", email="t@t.com", password_hash="x")
    db.add(user)
    db.flush()

    wf = Workflow(
        user_id=user.id,
        name="SEO 工作流",
        description="SEO 任务编排",
        kind="skill_group",
        is_active=True,
    )
    db.add(wf)
    db.flush()
    n1 = WorkflowNode(
        workflow_id=wf.id, node_type="start", name="开始", config="{}", position_x=0, position_y=0
    )
    n2 = WorkflowNode(
        workflow_id=wf.id,
        node_type="employee",
        name="SEO 员工",
        config='{"employee_id":"seo-file-maintainer"}',
        position_x=200,
        position_y=0,
    )
    n3 = WorkflowNode(
        workflow_id=wf.id, node_type="end", name="结束", config="{}", position_x=400, position_y=0
    )
    db.add_all([n1, n2, n3])
    db.flush()
    db.add(
        WorkflowEdge(workflow_id=wf.id, source_node_id=n1.id, target_node_id=n2.id, condition="")
    )
    db.add(
        WorkflowEdge(workflow_id=wf.id, source_node_id=n2.id, target_node_id=n3.id, condition="")
    )
    db.commit()

    bundle = export_workflow_bundle(db, wf.id)
    assert bundle is not None
    assert bundle["source_workflow_id"] == wf.id
    assert bundle["name"] == "SEO 工作流"
    assert len(bundle["nodes"]) == 3
    assert len(bundle["edges"]) == 2
    node_types = {n["node_type"] for n in bundle["nodes"]}
    assert node_types == {"start", "end", "employee"}
    # Node keys are portable (no DB IDs)
    node_keys = {n["node_key"] for n in bundle["nodes"]}
    assert node_keys == {"n0", "n1", "n2"}

    # Rehydrate into a fresh manifest — the new workflow should get a different ID
    manifest = {
        "workflow_employees": [{"id": "seo", "workflow_id": wf.id}],
        "employee_config_v2": {
            "collaboration": {"workflow": {"workflow_id": wf.id}},
        },
        "workflow_bundles": [bundle],
    }
    manifest = rehydrate_workflow_bundles(db, user, manifest, commit=True)

    new_wf_id = manifest["workflow_employees"][0]["workflow_id"]
    assert new_wf_id != wf.id  # a brand-new row was created
    assert manifest["employee_config_v2"]["collaboration"]["workflow"]["workflow_id"] == new_wf_id
    # The bundle carries the rehydrated ID for idempotency tracking
    assert manifest["workflow_bundles"][0]["rehydrated_workflow_id"] == new_wf_id


def test_export_script_workflow_bundle_round_trip():
    """Script workflow export includes script text; rehydration creates new row."""
    db = _make_in_memory_db()
    from modstore_server.employee_pack_workflow_bundle import (
        export_script_workflow_bundle,
        rehydrate_workflow_bundles,
    )
    from modstore_server.models import ScriptWorkflow, ScriptWorkflowVersion, User

    user = User(id=1, username="tester", email="t@t.com", password_hash="x")
    db.add(user)
    db.flush()

    swf = ScriptWorkflow(
        user_id=user.id,
        name="SEO 脚本工作流",
        brief_json='{"goal": "维护 sitemap"}',
        schema_in_json="{}",
        status="sandbox_testing",
    )
    db.add(swf)
    db.flush()
    ver = ScriptWorkflowVersion(
        workflow_id=swf.id,
        version_no=1,
        script_text="from pathlib import Path\nPath('outputs').mkdir()\n",
        plan_md="## 计划\n1. 写 sitemap",
        agent_log_json="{}",
        is_current=True,
    )
    db.add(ver)
    db.commit()

    bundle = export_script_workflow_bundle(db, swf.id)
    assert bundle is not None
    assert bundle["source_script_workflow_id"] == swf.id
    assert bundle["current_version"]["script_text"] != ""
    assert "计划" in bundle["current_version"]["plan_md"]
    assert bundle["status"] == "sandbox_testing"

    manifest = {
        "script_workflow_attachment": {"script_workflow_id": swf.id, "name": "SEO 脚本工作流"},
        "employee_config_v2": {
            "collaboration": {
                "script_workflows": [{"script_workflow_id": swf.id, "role": "primary_program"}],
            }
        },
        "script_workflow_bundles": [bundle],
    }
    manifest = rehydrate_workflow_bundles(db, user, manifest, commit=True)

    new_sid = manifest["script_workflow_attachment"]["script_workflow_id"]
    assert new_sid != swf.id
    assert (
        manifest["employee_config_v2"]["collaboration"]["script_workflows"][0]["script_workflow_id"]
        == new_sid
    )
    assert manifest["script_workflow_bundles"][0]["rehydrated_script_workflow_id"] == new_sid


def test_rehydrate_workflow_bundles_is_idempotent():
    """Calling rehydrate twice does not create duplicate DB rows."""
    db = _make_in_memory_db()
    from modstore_server.employee_pack_workflow_bundle import (
        export_script_workflow_bundle,
        rehydrate_workflow_bundles,
    )
    from modstore_server.models import ScriptWorkflow, User

    user = User(id=1, username="tester", email="t@t.com", password_hash="x")
    db.add(user)
    db.flush()

    swf = ScriptWorkflow(
        user_id=user.id,
        name="幂等测试工作流",
        brief_json="{}",
        schema_in_json="{}",
        status="draft",
    )
    db.add(swf)
    db.commit()

    bundle = export_script_workflow_bundle(db, swf.id)
    manifest = {
        "script_workflow_bundles": [bundle],
        "script_workflow_attachment": {"script_workflow_id": swf.id},
    }

    # First rehydration
    manifest = rehydrate_workflow_bundles(db, user, manifest, commit=True)
    first_new_id = manifest["script_workflow_attachment"]["script_workflow_id"]

    # Second call — must use the cached rehydrated_script_workflow_id, not create again
    manifest = rehydrate_workflow_bundles(db, user, manifest, commit=True)
    second_new_id = manifest["script_workflow_attachment"]["script_workflow_id"]

    assert first_new_id == second_new_id
    total = db.query(ScriptWorkflow).filter(ScriptWorkflow.name == "幂等测试工作流").count()
    # Original + exactly one new row (not two)
    assert total == 2


def test_embed_script_workflow_bundle_written_when_db_provided(tmp_path):
    """_embed_script_workflow_in_employee_pack embeds bundle when db is passed."""
    db = _make_in_memory_db()
    from modstore_server.models import ScriptWorkflow, ScriptWorkflowVersion, User
    from modstore_server.workbench_api import _embed_script_workflow_in_employee_pack

    user = User(id=1, username="tester", email="t@t.com", password_hash="x")
    db.add(user)
    db.flush()

    swf = ScriptWorkflow(
        user_id=user.id,
        name="文档助手配套脚本",
        brief_json='{"goal": "生成文档"}',
        schema_in_json="{}",
        status="sandbox_testing",
    )
    db.add(swf)
    db.flush()
    ver = ScriptWorkflowVersion(
        workflow_id=swf.id,
        version_no=1,
        script_text="print('ok')",
        plan_md="",
        agent_log_json="{}",
        is_current=True,
    )
    db.add(ver)
    db.commit()

    pack_dir = tmp_path / "doc-helper"
    pack_dir.mkdir()
    manifest = {
        "id": "doc-helper",
        "name": "文档助手",
        "employee_config_v2": {"collaboration": {"workflow": {"workflow_id": 0}}},
    }
    (pack_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    _embed_script_workflow_in_employee_pack(
        pack_dir,
        script_workflow={"id": swf.id, "name": "文档助手配套脚本"},
        brief="生成 docstring",
        db=db,
    )

    updated = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "script_workflow_bundles" in updated
    bundle = updated["script_workflow_bundles"][0]
    assert bundle["source_script_workflow_id"] == swf.id
    assert "print" in bundle["current_version"]["script_text"]


def test_mod_suite_mod_sandbox_checks_manifest_blueprint_and_links(tmp_path):
    mod_dir = tmp_path / "manufacture-flow"
    (mod_dir / "backend").mkdir(parents=True)
    (mod_dir / "frontend").mkdir()
    (mod_dir / "config").mkdir()
    manifest = {
        "id": "manufacture-flow",
        "name": "制造协同",
        "version": "1.0.0",
        "backend": {"entry": "blueprints", "init": "mod_init"},
        "frontend": {"routes": "frontend/routes.js"},
        "workflow_employees": [
            {"id": "inventory_planner", "label": "库存计划员", "workflow_id": 123}
        ],
    }
    (mod_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (mod_dir / "backend" / "__init__.py").write_text("", encoding="utf-8")
    (mod_dir / "backend" / "blueprints.py").write_text(
        "def mod_init():\n    return None\n", encoding="utf-8"
    )
    (mod_dir / "frontend" / "routes.js").write_text("export default []\n", encoding="utf-8")
    (mod_dir / "config" / "ai_blueprint.json").write_text("{}", encoding="utf-8")

    report = run_mod_suite_mod_sandbox(
        mod_dir,
        [{"workflow_id": 123, "employee_id": "inventory_planner"}],
    )
    assert report["ok"] is True
    assert {c["id"] for c in report["checks"]} >= {
        "manifest",
        "blueprint",
        "workflow_links",
        "python_compile",
    }


def test_mod_suite_writes_industry_card_and_ui_shell(tmp_path):
    parsed, err = parse_llm_mod_suite_json(json.dumps(_suite_payload(), ensure_ascii=False))
    assert err == ""
    mod_dir = tmp_path / "manufacture-flow"
    mod_dir.mkdir()

    industry_card = write_mod_suite_industry_card(mod_dir, parsed["blueprint"])
    ui_shell = write_mod_suite_ui_shell(mod_dir, parsed["blueprint"])

    assert industry_card["name"] == "制造业"
    assert industry_card["product_fields"]["name"] == "物料名称"
    assert ui_shell["target"] == "traditional-mode"
    assert any(item["label"] == "物料管理" for item in ui_shell["sidebar_menu"])
    assert (mod_dir / "config" / "industry_card.json").is_file()
    assert (mod_dir / "config" / "ui_shell.json").is_file()


def test_shell_ui_api_exposes_mod_sidebar_and_industries(client, library):
    mod_dir = library / "paint-mod"
    (mod_dir / "config").mkdir(parents=True)
    manifest = {
        "id": "paint-mod",
        "name": "涂料工坊",
        "version": "1.0.0",
        "primary": True,
        "backend": {"entry": "blueprints", "init": "mod_init"},
        "frontend": {
            "routes": "frontend/routes",
            "menu": [
                {"id": "paint-home", "label": "涂料工坊", "icon": "fa-cube", "path": "/paint-mod"}
            ],
            "menu_overrides": [{"key": "products", "label": "配方管理"}],
        },
        "industry": {"name": "涂料/油漆行业", "scenario": "配方、批次与出货"},
        "config": {
            "industry_card": "config/industry_card.json",
            "ui_shell": "config/ui_shell.json",
        },
    }
    ui_shell = {
        "schema_version": 1,
        "target": "traditional-mode",
        "sidebar_menu": [
            {
                "key": "products",
                "label": "配方管理",
                "path": "/recipes",
                "visible": True,
                "order": 20,
            }
        ],
        "menu_overrides": [{"key": "products", "label": "配方管理"}],
        "settings": {"default_industry": "涂料/油漆行业", "industry_options": ["涂料/油漆行业"]},
        "make_scene": {"title": "制作涂料工坊", "description": "生成配方和出货工作流。"},
    }
    (mod_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (mod_dir / "config" / "industry_card.json").write_text(
        json.dumps({"schema_version": 1, "name": "涂料/油漆行业"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (mod_dir / "config" / "ui_shell.json").write_text(
        json.dumps(ui_shell, ensure_ascii=False), encoding="utf-8"
    )

    res = client.get("/api/mods/shell-ui?mod_id=paint-mod")

    assert res.status_code == 200
    data = res.json()
    assert data["selected_mod_id"] == "paint-mod"
    assert data["sidebar_menu"][0]["label"] == "配方管理"
    assert "涂料/油漆行业" in data["industry_options"]
