"""测试 :mod:`modstore_server.workflow_engine` 的 vibe_skill / vibe_workflow 节点。

包含:
- mock_employees 沙箱模式直接走桩,不调真实 vibe-coding。
- 真跑模式委派到 vibe_eskill_adapter(用 monkeypatch 截获)。
- WorkflowValidator 检测缺失 brief。
"""

from __future__ import annotations

import importlib.util
import json
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("vibe_coding") is None:
    pytest.skip("vibe-coding 未安装,跳过画布节点测试", allow_module_level=True)


def _node(node_type: str, **config) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        name="vibe-node",
        node_type=node_type,
        config=json.dumps(config, ensure_ascii=False),
    )


def test_vibe_skill_mock_returns_sandbox_payload():
    from modstore_server.workflow_engine import WorkflowEngine

    eng = WorkflowEngine()
    out = eng._execute_vibe_node_mock(
        _node("vibe_skill", brief="求和", output_var="r"),
        {"k": "v"},
        {"brief": "求和", "output_var": "r"},
    )
    assert out["r"]["sandbox"] is True
    assert out["r"]["brief"] == "求和"


def test_vibe_workflow_mock_uses_default_output_var():
    from modstore_server.workflow_engine import WorkflowEngine

    eng = WorkflowEngine()
    out = eng._execute_vibe_node_mock(
        _node("vibe_workflow", brief="拆"),
        {},
        {"brief": "拆"},
    )
    assert "vibe_workflow_result" in out
    assert out["vibe_workflow_result"]["sandbox"] is True


def test_vibe_skill_real_path_delegates_to_adapter(monkeypatch):
    captured = {}

    def fake_execute_vibe_code_kind(logic, input_data, *, user_id):
        captured["logic"] = logic
        captured["input_data"] = dict(input_data)
        captured["user_id"] = user_id
        return {"eskill_logic_type": "vibe_code", "ok": True, "vibe_skill": {"skill_id": "vc-1"}}

    monkeypatch.setattr(
        "modstore_server.integrations.vibe_eskill_adapter.execute_vibe_code_kind",
        fake_execute_vibe_code_kind,
    )

    from modstore_server.workflow_engine import WorkflowEngine

    eng = WorkflowEngine()
    out = eng._execute_vibe_skill_node(
        _node("vibe_skill", brief="brief"),
        {"k": "v", "extra": 1},
        {"brief": "brief", "output_var": "vibe_result"},
        user_id=11,
    )
    assert out["ok"] is True
    assert captured["user_id"] == 11
    assert captured["logic"]["type"] == "vibe_code"
    # 没填 run_input_mapping 时,直接把整个 data 喂下去
    assert captured["input_data"] == {"k": "v", "extra": 1}


def test_vibe_skill_node_requires_brief():
    from modstore_server.workflow_engine import WorkflowEngine

    eng = WorkflowEngine()
    with pytest.raises(ValueError):
        eng._execute_vibe_skill_node(_node("vibe_skill"), {}, {"brief": ""}, user_id=1)


def test_validator_flags_missing_brief(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "modstore.db"))
    import importlib

    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    importlib.reload(models)
    models.init_db()

    sf = models.get_session_factory()
    with sf() as session:
        user = models.User(username="vibe-validator", password_hash="x")
        session.add(user)
        session.commit()
        session.refresh(user)
        wf = models.Workflow(user_id=user.id, name="wf-vibe", description="", is_active=True)
        session.add(wf)
        session.commit()
        session.refresh(wf)
        session.add(
            models.WorkflowNode(
                workflow_id=wf.id,
                node_type="start",
                name="开始",
                config="{}",
                position_x=0.0,
                position_y=0.0,
            )
        )
        session.add(
            models.WorkflowNode(
                workflow_id=wf.id,
                node_type="vibe_skill",
                name="vibe-no-brief",
                config="{}",
                position_x=200.0,
                position_y=0.0,
            )
        )
        session.add(
            models.WorkflowNode(
                workflow_id=wf.id,
                node_type="end",
                name="结束",
                config="{}",
                position_x=400.0,
                position_y=0.0,
            )
        )
        session.commit()

        from modstore_server.workflow_engine import WorkflowValidator

        errors = WorkflowValidator.validate_workflow(wf, session)
        assert any("vibe-coding" in e and "brief" in e for e in errors), errors
