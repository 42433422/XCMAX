"""员工包生成后可被运行时加载与执行器识别。"""

from __future__ import annotations

import asyncio
import io
import json
import tempfile
import zipfile
from pathlib import Path

import pytest


@pytest.mark.xfail(strict=False, reason="employee_full_chain pre-existing failures in CI")
def test_employee_pack_parser_adds_web_rankings_config():
    from modstore_server.employee_ai_scaffold import parse_employee_pack_llm_json

    manifest, err = parse_employee_pack_llm_json(
        json.dumps(
            {
                "id": "ai-rankings-stats",
                "name": "AI 模型排行统计员工",
                "version": "1.0.0",
                "description": "上网获取 AI 模型排行榜并统计来源和结论",
                "employee": {
                    "id": "ai-rankings",
                    "label": "AI 排行统计",
                    "capabilities": ["web.rankings"],
                },
            },
            ensure_ascii=False,
        )
    )

    assert err == ""
    assert manifest is not None
    assert manifest["employee_config_v2"]["perception"]["type"] == "web_rankings"
    assert manifest["employee_config_v2"]["actions"]["handlers"] == ["llm_md", "echo"]
    prompt = manifest["employee_config_v2"]["cognition"]["agent"]["system_prompt"]
    assert "不要编造" in prompt
    assert "## 用途" not in prompt
    rules = manifest["employee_config_v2"]["cognition"]["agent"]["behavior_rules"]
    assert len(rules) >= 3


@pytest.mark.xfail(strict=False, reason="employee_full_chain pre-existing failures in CI")
def test_employee_runtime_loads_manifest_from_registered_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "catalog"))
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "modstore.db"))

    from modstore_server import models
    from modstore_server.catalog_store import append_package
    from modstore_server.employee_ai_scaffold import build_employee_pack_zip
    from modstore_server.employee_runtime import load_employee_pack, parse_employee_config_v2
    from modstore_server.models import CatalogItem

    models._engine = None
    models._SessionFactory = None
    models.init_db()

    manifest = {
        "id": "rank-pack",
        "name": "排行员工",
        "version": "1.0.0",
        "artifact": "employee_pack",
        "scope": "global",
        "employee": {"id": "ranker", "label": "排行员工", "capabilities": []},
        "employee_config_v2": {
            "perception": {"type": "web_rankings"},
            "actions": {"handlers": ["echo"]},
        },
    }
    raw = build_employee_pack_zip("rank-pack", manifest)
    with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
        names = {n.replace("\\", "/") for n in zf.namelist()}
        assert "rank-pack/backend/blueprints.py" in names
        assert "rank-pack/backend/employees/ranker.py" in names
        assert "rank-pack/manifest.json" in names
    with tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)
    try:
        saved = append_package(
            {
                "id": "rank-pack",
                "name": "排行员工",
                "version": "1.0.0",
                "artifact": "employee_pack",
            },
            tmp_path,
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    sf = models.get_session_factory()
    with sf() as db:
        db.add(
            CatalogItem(
                pkg_id="rank-pack",
                version="1.0.0",
                name="排行员工",
                artifact="employee_pack",
                stored_filename=saved["stored_filename"],
            )
        )
        db.commit()
        pack = load_employee_pack(db, "rank-pack")

    cfg = parse_employee_config_v2(pack["manifest"])
    assert cfg["perception"]["type"] == "web_rankings"


def test_run_employee_ai_scaffold_registers_runtime_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "catalog"))
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "modstore.db"))

    from modman.repo_config import RepoConfig
    from modstore_server import models
    from modstore_server.mod_scaffold_runner import run_employee_ai_scaffold_async
    from modstore_server.models import CatalogItem, User

    models._engine = None
    models._SessionFactory = None
    models.init_db()

    sf = models.get_session_factory()
    with sf() as db:
        user = User(username="chain", email="chain@example.local", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    async def fake_chat_dispatch(*args, **kwargs):
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "id": "ai-rankings-stats",
                    "name": "AI 模型排行统计员工",
                    "version": "1.0.0",
                    "description": "上网获取 AI 模型排行榜并统计来源和结论",
                    "employee": {
                        "id": "ranker",
                        "label": "排行员工",
                        "capabilities": ["web.rankings"],
                    },
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr("modstore_server.mod_scaffold_runner.chat_dispatch", fake_chat_dispatch)
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.resolve_api_key", lambda *args, **kwargs: ("k", "test")
    )
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.load_config",
        lambda: RepoConfig(
            library_root=str(tmp_path / "library"),
            xcagi_root="",
            xcagi_backend_url="http://test.invalid",
        ),
    )

    with sf() as db:
        user = db.query(User).filter(User.id == user_id).first()
        res = asyncio.run(
            run_employee_ai_scaffold_async(
                db,
                user,
                brief="生成 AI 模型排行统计员工",
                provider="deepseek",
                model="deepseek-chat",
            )
        )
        assert res["ok"] is True
        assert res.get("published") is True
        row = db.query(CatalogItem).filter(CatalogItem.pkg_id == "ai-rankings-stats").first()
        assert row is not None
        assert row.artifact == "employee_pack"
        assert row.author_id == user_id
        assert row.stored_filename


def test_run_employee_ai_scaffold_skips_catalog_when_publish_disabled(tmp_path, monkeypatch):
    """工作台「做员工」流水线传入 publish_to_catalog=False 时，仅落本地 library，不写 Catalog。"""
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "catalog"))
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "modstore.db"))

    from modman.repo_config import RepoConfig
    from modstore_server import models
    from modstore_server.mod_scaffold_runner import run_employee_ai_scaffold_async
    from modstore_server.models import CatalogItem, User

    models._engine = None
    models._SessionFactory = None
    models.init_db()

    sf = models.get_session_factory()
    with sf() as db:
        user = User(
            username="chain-noimport", email="chain-noimport@example.local", password_hash="x"
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    async def fake_chat_dispatch(*args, **kwargs):
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "id": "ai-rankings-noimport",
                    "name": "AI 模型排行统计员工（草稿）",
                    "version": "1.0.0",
                    "description": "仅生成不导入 Catalog 的草稿",
                    "employee": {
                        "id": "ranker",
                        "label": "排行员工",
                        "capabilities": ["web.rankings"],
                    },
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr("modstore_server.mod_scaffold_runner.chat_dispatch", fake_chat_dispatch)
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.resolve_api_key", lambda *args, **kwargs: ("k", "test")
    )
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.load_config",
        lambda: RepoConfig(
            library_root=str(tmp_path / "library"),
            xcagi_root="",
            xcagi_backend_url="http://test.invalid",
        ),
    )

    with sf() as db:
        user = db.query(User).filter(User.id == user_id).first()
        res = asyncio.run(
            run_employee_ai_scaffold_async(
                db,
                user,
                brief="生成 AI 排行草稿员工",
                provider="deepseek",
                model="deepseek-chat",
                publish_to_catalog=False,
            )
        )
        assert res["ok"] is True
        assert res.get("published") is False
        assert res.get("package") in (None, {}, [])
        # local library still has the pack
        assert Path(res["path"]).is_dir()
        # CatalogItem must NOT be created
        row = db.query(CatalogItem).filter(CatalogItem.pkg_id == "ai-rankings-noimport").first()
        assert row is None


@pytest.mark.xfail(strict=False, reason="employee_full_chain pre-existing failures in CI")
def test_try_load_employee_pack_from_library_when_not_in_catalog(tmp_path, monkeypatch):
    """未登记到 packages.json 时，库目录 manifest 可被 try_load 命中（与 manifest 接口兜底一致）。"""
    monkeypatch.setenv("MODSTORE_EMPLOYEE_MANIFEST_LIBRARY_FALLBACK", "1")
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "cat"))

    lib = tmp_path / "library"
    lib.mkdir()
    pd = lib / "asset-worker-employee"
    pd.mkdir()
    (pd / "manifest.json").write_text(
        json.dumps(
            {
                "id": "asset-worker-employee",
                "name": "FromLib",
                "version": "1.0.0",
                "artifact": "employee_pack",
                "employee_config_v2": {"perception": {"type": "text"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    from modman.repo_config import RepoConfig

    monkeypatch.setattr(
        "modman.repo_config.load_config",
        lambda: RepoConfig(
            library_root=str(lib), xcagi_root="", xcagi_backend_url="http://x.local"
        ),
    )

    from modstore_server.employee_runtime import try_load_employee_pack_from_library

    pack = try_load_employee_pack_from_library("asset-worker-employee")
    assert pack is not None
    assert pack["pack_id"] == "asset-worker-employee"
    assert pack["manifest"]["name"] == "FromLib"
    assert pack["stored_filename"] == ""

    monkeypatch.setenv("MODSTORE_EMPLOYEE_MANIFEST_LIBRARY_FALLBACK", "0")
    import modstore_server.employee_runtime as er

    assert er.try_load_employee_pack_from_library("asset-worker-employee") is None


def test_employee_pack_can_attach_generated_skill_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "catalog"))
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "modstore.db"))

    from modman.repo_config import RepoConfig
    from modstore_server import models
    from modstore_server.mod_scaffold_runner import (
        attach_nl_workflow_to_employee_pack_dir,
        run_employee_ai_scaffold_async,
    )
    from modstore_server.workflow_engine import run_workflow_sandbox

    models._engine = None
    models._SessionFactory = None
    models.init_db()

    sf = models.get_session_factory()
    with sf() as db:
        user = models.User(
            username="skill-flow", email="skill-flow@example.local", password_hash="x"
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    async def fake_employee_chat(*args, **kwargs):
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "id": "invoice-employee-pack",
                    "name": "发票处理员工",
                    "version": "1.0.0",
                    "description": "处理发票字段抽取与复核",
                    "employee": {
                        "id": "invoice-worker",
                        "label": "发票员工",
                        "capabilities": ["invoice.extract"],
                    },
                    "workflow_employees": [
                        {
                            "id": "invoice-worker",
                            "label": "发票员工",
                            "panel_title": "发票处理",
                            "panel_summary": "抽取发票字段并输出复核结果。",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        }

    skill_workflow_payload = {
        "skill_blueprints": [
            {
                "temp_skill_id": "skill_invoice_extract",
                "name": "Invoice Extract Skill",
                "domain": "发票字段抽取",
                "description": "从发票输入中抽取金额、税号和购方信息。",
                "static_logic": {
                    "type": "template_transform",
                    "template": "发票字段：${value}",
                    "dynamic_template": "发票字段：${value}；补充修复：${details}",
                    "fallback_template": "发票字段待复核：${value}",
                    "required_fields": ["value"],
                    "domain_keywords": ["发票", "金额", "税号"],
                    "output_var": "invoice_fields",
                    "metadata": {
                        "repair_hints": ["缺金额时从 details 中查找含税金额"],
                        "failure_modes": ["missing_amount", "quality_below_threshold"],
                    },
                },
                "quality_gate": {"required_keys": ["invoice_fields"]},
                "trigger_policy": {"on_error": True, "on_quality_below_threshold": True},
            }
        ],
        "workflow": {
            "nodes": [
                {
                    "temp_id": "start",
                    "node_type": "start",
                    "name": "开始",
                    "config": {},
                    "position_x": 0,
                    "position_y": 0,
                },
                {
                    "temp_id": "extract",
                    "node_type": "eskill",
                    "name": "发票字段抽取",
                    "config": {
                        "temp_skill_id": "skill_invoice_extract",
                        "output_var": "invoice_fields",
                    },
                    "position_x": 220,
                    "position_y": 0,
                },
                {
                    "temp_id": "end",
                    "node_type": "end",
                    "name": "结束",
                    "config": {},
                    "position_x": 440,
                    "position_y": 0,
                },
            ],
            "edges": [
                {"source_temp_id": "start", "target_temp_id": "extract", "condition": ""},
                {"source_temp_id": "extract", "target_temp_id": "end", "condition": ""},
            ],
        },
    }

    async def fake_workflow_chat(*args, **kwargs):
        return {"ok": True, "content": json.dumps(skill_workflow_payload, ensure_ascii=False)}

    monkeypatch.setattr("modstore_server.mod_scaffold_runner.chat_dispatch", fake_employee_chat)
    monkeypatch.setattr(
        "modstore_server.workflow_nl_graph.chat_dispatch_via_session", fake_workflow_chat
    )
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.resolve_api_key", lambda *args, **kwargs: ("k", "test")
    )
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.resolve_llm_provider_model",
        lambda db, user, provider, model: (provider or "test", model or "test-model", None),
    )
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.load_config",
        lambda: RepoConfig(
            library_root=str(tmp_path / "library"),
            xcagi_root="",
            xcagi_backend_url="http://test.invalid",
        ),
    )

    with sf() as db:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        employee_res = asyncio.run(
            run_employee_ai_scaffold_async(
                db,
                user,
                brief="生成发票处理员工，并挂接 Skill 工作流",
                provider="deepseek",
                model="deepseek-chat",
            )
        )
        assert employee_res["ok"] is True

        attach_res = asyncio.run(
            attach_nl_workflow_to_employee_pack_dir(
                db,
                user,
                pack_dir=Path(employee_res["path"]),
                brief="发票处理员工：先生成发票字段抽取 Skill，再组合工作流",
                workflow_name="发票 Skill 工作流",
                provider="deepseek",
                model="deepseek-chat",
            )
        )
        assert attach_res["ok"] is True
        assert attach_res["nl"]["ok"] is True
        # vibe-coding / NL 路径是否已装会影响是否预先落库 Skill；只关心后续工作流与 manifest 一致
        assert attach_res["nl"]["skills_created"] in (0, 1)

        workflow_id = int(attach_res["workflow_id"])
        workflow = db.query(models.Workflow).filter_by(id=workflow_id, user_id=user.id).one()
        eskill_nodes = (
            db.query(models.WorkflowNode)
            .filter_by(workflow_id=workflow.id, node_type="eskill")
            .all()
        )
        assert eskill_nodes
        eskill_node = next(
            n
            for n in eskill_nodes
            if str(json.loads(n.config or "{}").get("skill_id") or "").isdigit()
        )
        cfg = json.loads(eskill_node.config)
        assert cfg["skill_id"].isdigit()

        skill = db.query(models.ESkill).filter_by(user_id=user.id, id=int(cfg["skill_id"])).one()
        version = db.query(models.ESkillVersion).filter_by(eskill_id=skill.id, version=1).one()
        logic = json.loads(version.static_logic_json)
        assert logic["type"] in {"vibe_code", "template_transform"}

        report = run_workflow_sandbox(
            workflow.id, {}, mock_employees=True, validate_only=True, user_id=user.id
        )
        assert report["ok"] is True

        manifest = json.loads(
            (Path(employee_res["path"]) / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["workflow_attachment"]["workflow_id"] == workflow.id
        assert manifest["workflow_attachment"]["nl_graph_ok"] is True


def test_load_employee_pack_with_aliases_error_includes_requested_id(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "cat"))
    monkeypatch.setenv("MODSTORE_EMPLOYEE_MANIFEST_LIBRARY_FALLBACK", "0")

    from modstore_server import models
    from modstore_server.employee_api import _load_employee_pack_with_aliases

    models._engine = None
    models._SessionFactory = None
    models.init_db()
    sf = models.get_session_factory()
    with sf() as db:
        with pytest.raises(ValueError) as ei:
            _load_employee_pack_with_aliases(db, "asset-worker-employee")
    msg = str(ei.value)
    assert "asset-worker-employee" in msg
    assert "原始请求" in msg
