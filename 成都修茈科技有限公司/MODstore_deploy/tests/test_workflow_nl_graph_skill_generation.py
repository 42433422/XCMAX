from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


def _bootstrap(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "modstore.db"))
    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    importlib.reload(models)
    models.init_db()
    return models


def _seed_user_workflow(session, models):
    user = models.User(username="skill-gen-user", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)

    workflow = models.Workflow(
        user_id=user.id, name="Skill workflow", description="generate skills"
    )
    session.add(workflow)
    session.commit()
    session.refresh(workflow)
    return user, workflow


def _patch_llm(monkeypatch, payload: dict):
    import modstore_server.workflow_nl_graph as wng

    async def fake_chat_dispatch(*args, **kwargs):
        return {"ok": True, "content": json.dumps(payload, ensure_ascii=False)}

    monkeypatch.setattr(wng, "chat_dispatch_via_session", fake_chat_dispatch)
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.resolve_llm_provider_model",
        lambda db, user, provider, model: (provider or "test", model or "test-model", None),
    )


@pytest.mark.asyncio
async def test_apply_nl_workflow_graph_creates_skill_blueprints(tmp_path, monkeypatch):
    models = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.eskill_runtime import ESkillRuntime
    from modstore_server.workflow_nl_graph import apply_nl_workflow_graph

    payload = {
        "skill_blueprints": [
            {
                "temp_skill_id": "skill_parse_order",
                "name": "Parse Order",
                "domain": "订单输入解析",
                "description": "把原始订单文本解析成结构化摘要",
                "static_logic": {
                    "type": "template_transform",
                    "template": "Parsed order: ${value}",
                    "output_var": "parsed_order",
                },
                "quality_gate": {"required_keys": ["parsed_order"]},
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
                    "temp_id": "parse",
                    "node_type": "eskill",
                    "name": "解析订单",
                    "config": {
                        "temp_skill_id": "skill_parse_order",
                        "task": "解析订单",
                        "output_var": "parsed_order",
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
                {"source_temp_id": "start", "target_temp_id": "parse", "condition": ""},
                {"source_temp_id": "parse", "target_temp_id": "end", "condition": ""},
            ],
        },
    }
    _patch_llm(monkeypatch, payload)

    sf = models.get_session_factory()
    with sf() as session:
        user, workflow = _seed_user_workflow(session, models)
        result = await apply_nl_workflow_graph(
            session,
            user,
            workflow_id=workflow.id,
            brief="解析订单并输出摘要",
            provider="test",
            model="test-model",
        )

        assert result["ok"] is True
        assert result["sandbox_ok"] is True
        assert result["nodes_created"] == 3
        assert result["edges_created"] == 2

        skill = session.query(models.ESkill).filter_by(user_id=user.id, name="Parse Order").one()
        version = session.query(models.ESkillVersion).filter_by(eskill_id=skill.id, version=1).one()
        assert json.loads(version.static_logic_json)["output_var"] == "parsed_order"

        eskill_node = (
            session.query(models.WorkflowNode)
            .filter_by(workflow_id=workflow.id, node_type="eskill")
            .one()
        )
        cfg = json.loads(eskill_node.config)
        assert cfg["skill_id"] == str(skill.id)
        assert "temp_skill_id" not in cfg

        run = ESkillRuntime().run(
            session,
            eskill_id=skill.id,
            user_id=user.id,
            input_data={"value": "订单A，金额100"},
            solidify=False,
        )
        assert run["stage"] == "static"
        assert run["output"]["parsed_order"] == "Parsed order: 订单A，金额100"


@pytest.mark.asyncio
async def test_apply_nl_workflow_graph_reuses_existing_skill_id(tmp_path, monkeypatch):
    models = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.workflow_nl_graph import apply_nl_workflow_graph

    sf = models.get_session_factory()
    with sf() as session:
        user, workflow = _seed_user_workflow(session, models)
        skill = models.ESkill(
            user_id=user.id,
            name="Existing Skill",
            domain="复用能力",
            active_version=1,
        )
        session.add(skill)
        session.flush()
        session.add(
            models.ESkillVersion(
                eskill_id=skill.id,
                version=1,
                static_logic_json=json.dumps(
                    {
                        "type": "template_transform",
                        "template": "Existing ${value}",
                        "output_var": "existing_result",
                    },
                    ensure_ascii=False,
                ),
                trigger_policy_json="{}",
                quality_gate_json="{}",
            )
        )
        session.commit()
        session.refresh(skill)

        payload = {
            "skill_blueprints": [],
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
                        "temp_id": "reuse",
                        "node_type": "eskill",
                        "name": "复用已有 Skill",
                        "config": {"skill_id": skill.id, "output_var": "existing_result"},
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
                    {"source_temp_id": "start", "target_temp_id": "reuse", "condition": ""},
                    {"source_temp_id": "reuse", "target_temp_id": "end", "condition": ""},
                ],
            },
        }
        _patch_llm(monkeypatch, payload)

        result = await apply_nl_workflow_graph(
            session,
            user,
            workflow_id=workflow.id,
            brief="复用已有能力",
            provider="test",
            model="test-model",
        )

        assert result["ok"] is True
        assert session.query(models.ESkill).filter_by(user_id=user.id).count() == 1
        eskill_node = (
            session.query(models.WorkflowNode)
            .filter_by(workflow_id=workflow.id, node_type="eskill")
            .one()
        )
        assert json.loads(eskill_node.config)["skill_id"] == str(skill.id)


@pytest.mark.asyncio
async def test_apply_nl_workflow_graph_reuses_same_name_blueprint(tmp_path, monkeypatch):
    models = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.workflow_nl_graph import apply_nl_workflow_graph

    sf = models.get_session_factory()
    with sf() as session:
        user, workflow = _seed_user_workflow(session, models)
        skill = models.ESkill(
            user_id=user.id,
            name="Reusable Generated Skill",
            domain="已有生成能力",
            active_version=1,
        )
        session.add(skill)
        session.flush()
        session.add(
            models.ESkillVersion(
                eskill_id=skill.id,
                version=1,
                static_logic_json=json.dumps(
                    {
                        "type": "template_transform",
                        "template": "Reuse ${value}",
                        "output_var": "reuse_result",
                    },
                    ensure_ascii=False,
                ),
                trigger_policy_json="{}",
                quality_gate_json="{}",
            )
        )
        session.commit()
        session.refresh(skill)

        payload = {
            "skill_blueprints": [
                {
                    "temp_skill_id": "skill_reuse",
                    "name": "Reusable Generated Skill",
                    "domain": "重复名称应复用",
                    "static_logic": {
                        "type": "template_transform",
                        "template": "New ${value}",
                        "output_var": "new_result",
                    },
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
                        "temp_id": "reuse",
                        "node_type": "eskill",
                        "name": "复用同名 Skill",
                        "config": {"temp_skill_id": "skill_reuse", "output_var": "reuse_result"},
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
                    {"source_temp_id": "start", "target_temp_id": "reuse", "condition": ""},
                    {"source_temp_id": "reuse", "target_temp_id": "end", "condition": ""},
                ],
            },
        }
        _patch_llm(monkeypatch, payload)

        result = await apply_nl_workflow_graph(
            session,
            user,
            workflow_id=workflow.id,
            brief="复用同名生成能力",
            provider="test",
            model="test-model",
        )

        assert result["ok"] is True
        assert session.query(models.ESkill).filter_by(user_id=user.id).count() == 1
        assert result["skill_ids"]["skill_reuse"] == skill.id


@pytest.mark.asyncio
async def test_apply_nl_workflow_graph_preserves_repair_ready_skill_metadata(tmp_path, monkeypatch):
    models = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.workflow_nl_graph import apply_nl_workflow_graph

    payload = {
        "skill_blueprints": [
            {
                "temp_skill_id": "skill_invoice_repair_ready",
                "name": "Invoice Repair Ready Skill",
                "domain": "发票字段抽取与校验",
                "description": "抽取发票金额、税号和购方名称，并在质量不足时进入动态修复。",
                "static_logic": {
                    "type": "template_transform",
                    "template": "发票摘要：${value}",
                    "dynamic_template": "发票摘要：${value}；请根据补充信息修复：${details}",
                    "fallback_template": "发票摘要待人工复核：${value}",
                    "required_fields": ["value"],
                    "domain_keywords": ["发票", "税号", "金额"],
                    "allow_steps": True,
                    "output_var": "invoice_summary",
                    "metadata": {
                        "repair_hints": [
                            "缺少税号时从 details 中查找纳税人识别号",
                            "金额为空时保留待复核标记并触发动态阶段",
                        ],
                        "failure_modes": [
                            "missing_tax_id",
                            "missing_amount",
                            "quality_below_threshold",
                        ],
                    },
                },
                "quality_gate": {"required_keys": ["invoice_summary"], "min_length": 10},
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
                    "temp_id": "invoice",
                    "node_type": "eskill",
                    "name": "发票修复 Skill",
                    "config": {
                        "temp_skill_id": "skill_invoice_repair_ready",
                        "output_var": "invoice_summary",
                        "quality_gate": {"required_keys": ["invoice_summary"]},
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
                {"source_temp_id": "start", "target_temp_id": "invoice", "condition": ""},
                {"source_temp_id": "invoice", "target_temp_id": "end", "condition": ""},
            ],
        },
    }
    _patch_llm(monkeypatch, payload)

    sf = models.get_session_factory()
    with sf() as session:
        user, workflow = _seed_user_workflow(session, models)
        result = await apply_nl_workflow_graph(
            session,
            user,
            workflow_id=workflow.id,
            brief="生成一个能后续自修复的发票处理 Skill",
            provider="test",
            model="test-model",
        )

        assert result["ok"] is True
        skill = (
            session.query(models.ESkill)
            .filter_by(user_id=user.id, name="Invoice Repair Ready Skill")
            .one()
        )
        version = session.query(models.ESkillVersion).filter_by(eskill_id=skill.id, version=1).one()
        logic = json.loads(version.static_logic_json)

        assert logic["dynamic_template"].endswith("请根据补充信息修复：${details}")
        assert logic["fallback_template"] == "发票摘要待人工复核：${value}"
        assert logic["required_fields"] == ["value"]
        assert logic["domain_keywords"] == ["发票", "税号", "金额"]
        assert logic["allow_steps"] is True
        assert "缺少税号时从 details 中查找纳税人识别号" in logic["metadata"]["repair_hints"]
        assert "quality_below_threshold" in logic["metadata"]["failure_modes"]
