from __future__ import annotations

import importlib
import json
from pathlib import Path


def _bootstrap(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "modstore.db"))
    import modstore_server.db.base as db_base
    import modstore_server.models as models

    db_base._engine = None
    db_base._SessionFactory = None
    models._engine = None
    models._SessionFactory = None
    importlib.reload(models)
    models.init_db()
    return models


def _seed_eskill(session, models, *, min_length: int = 0):
    user = models.User(username="eskill-user", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)

    skill = models.ESkill(
        user_id=user.id,
        name="Brief Writer",
        domain="brief writing",
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
                    "template": "Brief: ${topic}",
                    "dynamic_template": "Brief: ${topic}. Details: ${details}",
                    "required_fields": ["topic"],
                    "output_var": "brief",
                    "domain_keywords": ["ESkill", "brief"],
                }
            ),
            trigger_policy_json=json.dumps({"on_error": True, "on_quality_below_threshold": True}),
            quality_gate_json=json.dumps({"min_length": min_length}),
        )
    )
    session.commit()
    session.refresh(skill)
    return user, skill


def test_eskill_runtime_static_success(tmp_path, monkeypatch):
    models = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.eskill_runtime import ESkillRuntime

    sf = models.get_session_factory()
    with sf() as session:
        user, skill = _seed_eskill(session, models, min_length=1)
        result = ESkillRuntime().run(
            session,
            eskill_id=skill.id,
            user_id=user.id,
            input_data={"topic": "ESkill"},
        )

        assert result["stage"] == "static"
        assert result["output"]["brief"] == "Brief: ESkill"
        assert session.query(models.ESkillVersion).filter_by(eskill_id=skill.id).count() == 1


def test_eskill_runtime_dynamic_solidifies_new_version(tmp_path, monkeypatch):
    models = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.eskill_runtime import ESkillRuntime

    sf = models.get_session_factory()
    with sf() as session:
        user, skill = _seed_eskill(session, models, min_length=30)
        result = ESkillRuntime().run(
            session,
            eskill_id=skill.id,
            user_id=user.id,
            input_data={"topic": "ESkill", "details": "dynamic solidification"},
        )

        assert result["stage"] == "solidified"
        assert result["output"]["solidified_version"] == 2
        session.refresh(skill)
        assert skill.active_version == 2
        active = session.query(models.ESkillVersion).filter_by(eskill_id=skill.id, version=2).one()
        assert "Details" in json.loads(active.static_logic_json)["template"]


def test_eskill_runtime_rejects_out_of_domain_dynamic(tmp_path, monkeypatch):
    models = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.eskill_runtime import ESkillRuntime

    sf = models.get_session_factory()
    with sf() as session:
        user, skill = _seed_eskill(session, models, min_length=50)
        result = ESkillRuntime().run(
            session,
            eskill_id=skill.id,
            user_id=user.id,
            input_data={"topic": "tax", "details": "invoice"},
        )

        assert result["stage"] == "domain_rejected"
        session.refresh(skill)
        assert skill.active_version == 1


def test_eskill_runtime_patch_can_add_pipeline_steps(tmp_path, monkeypatch):
    models = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.eskill_runtime import ESkillRuntime

    sf = models.get_session_factory()
    with sf() as session:
        user = models.User(username="pipeline-user", password_hash="x")
        session.add(user)
        session.commit()
        session.refresh(user)
        skill = models.ESkill(
            user_id=user.id,
            name="Pipeline Skill",
            domain="ESkill",
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
                        "template": "Brief: ${topic}",
                        "dynamic_template": "Brief: ${topic}. ${details}",
                        "required_fields": ["topic"],
                        "output_var": "brief",
                        "allow_steps": True,
                        "domain_keywords": ["ESkill"],
                    }
                ),
                trigger_policy_json=json.dumps({"on_quality_below_threshold": True}),
                quality_gate_json=json.dumps({"required_keys": ["adaptation_reason"]}),
            )
        )
        session.commit()
        session.refresh(skill)

        result = ESkillRuntime().run(
            session,
            eskill_id=skill.id,
            user_id=user.id,
            input_data={"topic": "ESkill", "details": "pipeline"},
        )

        assert result["stage"] == "solidified"
        active = session.query(models.ESkillVersion).filter_by(eskill_id=skill.id, version=2).one()
        assert json.loads(active.static_logic_json)["type"] == "pipeline"


def test_workflow_eskill_node_sandbox_mock(tmp_path, monkeypatch):
    models = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.workflow_engine import WorkflowEngine

    sf = models.get_session_factory()
    with sf() as session:
        user = models.User(username="wf-eskill-user", password_hash="x")
        session.add(user)
        session.commit()
        session.refresh(user)
        wf = models.Workflow(user_id=user.id, name="wf-eskill")
        session.add(wf)
        session.flush()
        start = models.WorkflowNode(workflow_id=wf.id, node_type="start", name="start", config="{}")
        eskill = models.WorkflowNode(
            workflow_id=wf.id,
            node_type="eskill",
            name="eskill",
            config=json.dumps({"skill_id": "1", "task": "write", "output_var": "eskill_out"}),
        )
        end = models.WorkflowNode(workflow_id=wf.id, node_type="end", name="end", config="{}")
        session.add_all([start, eskill, end])
        session.flush()
        session.add_all(
            [
                models.WorkflowEdge(
                    workflow_id=wf.id,
                    source_node_id=start.id,
                    target_node_id=eskill.id,
                ),
                models.WorkflowEdge(
                    workflow_id=wf.id,
                    source_node_id=eskill.id,
                    target_node_id=end.id,
                ),
            ]
        )
        session.commit()

        report = WorkflowEngine().run_sandbox(
            session,
            wf,
            {"topic": "ESkill"},
            mock_employees=True,
            user_id=user.id,
        )

        assert report["ok"] is True
        assert report["output"]["eskill_out"]["sandbox"] is True
