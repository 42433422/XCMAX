"""``scripts.migrate_workflows_to_script`` 单测：

- agent loop 成功 → 新 ``ScriptWorkflow`` 状态 = ``sandbox_testing``，旧 workflow 标 migrated
- agent loop 失败 → 旧 workflow 标 failed
- 用户缺 LLM 配置 → 旧 workflow 标 failed
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

import pytest

pytest.importorskip("fastapi")


def _make_user(default_llm: Optional[Dict[str, str]] = None):
    import json

    from modstore_server.models import User, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        u = User(
            username=f"mig_user_{uuid.uuid4().hex[:8]}",
            email=f"mig_{uuid.uuid4().hex[:8]}@pytest.local",
            password_hash="x",
            is_admin=False,
            default_llm_json=(
                json.dumps(default_llm or {}, ensure_ascii=False) if default_llm else ""
            ),
        )
        session.add(u)
        session.commit()
        session.refresh(u)
        return u.id


def _seed_legacy_workflow(user_id: int, with_nodes: bool = True) -> int:
    """造一份还没迁移的旧节点图工作流。"""
    import json

    from modstore_server.models import (
        Workflow,
        WorkflowEdge,
        WorkflowNode,
        get_session_factory,
    )

    sf = get_session_factory()
    with sf() as session:
        wf = Workflow(
            user_id=user_id,
            name="老工作流",
            description="对接 AI 员工进行内容审核",
            is_active=True,
        )
        session.add(wf)
        session.commit()
        session.refresh(wf)
        if with_nodes:
            n1 = WorkflowNode(
                workflow_id=wf.id,
                node_type="start",
                name="开始",
                config=json.dumps({}),
            )
            n2 = WorkflowNode(
                workflow_id=wf.id,
                node_type="employee",
                name="审核员工",
                config=json.dumps({"employee_id": "reviewer", "task": "审核"}),
            )
            session.add_all([n1, n2])
            session.commit()
            session.refresh(n1)
            session.refresh(n2)
            session.add(WorkflowEdge(workflow_id=wf.id, source_node_id=n1.id, target_node_id=n2.id))
            session.commit()
        return wf.id


def _good_code() -> str:
    return (
        "from pathlib import Path\n"
        "import json\n"
        "Path('outputs').mkdir(exist_ok=True)\n"
        "Path('outputs/result.json').write_text(json.dumps({'migrated': True}), encoding='utf-8')\n"
        "print('migrate done')\n"
    )


# ----------------------------- 用例 ----------------------------- #


def test_migration_success_creates_script_workflow(client, monkeypatch, tmp_path):
    """端到端：mock LLM + 真子进程沙箱 → 新表行齐全。"""
    from modstore_server.script_agent import sandbox_runner
    from modstore_server.script_agent.llm_client import StubLlmClient
    from modstore_server.scripts import migrate_workflows_to_script as m

    monkeypatch.setattr(sandbox_runner, "SCRIPT_ROOT", tmp_path)

    user_id = _make_user(default_llm={"provider": "openai", "model": "gpt-4o-mini"})
    wf_id = _seed_legacy_workflow(user_id)

    stub = StubLlmClient(
        [
            "## 计划\n1. 写 result.json\n验收: outputs/result.json 存在",
            f"```python\n{_good_code()}```",
            '{"ok": true, "reason": "ok"}',
        ]
    )

    def fake_factory(db, user):
        return stub

    results = asyncio.run(m.migrate_user_workflows(user_id=user_id, llm_factory=fake_factory))
    assert len(results) == 1
    r = results[0]
    assert r.ok, r.error
    assert r.new_workflow_id

    # 数据库状态
    from modstore_server.models import (
        ScriptWorkflow,
        ScriptWorkflowVersion,
        Workflow,
        get_session_factory,
    )

    sf = get_session_factory()
    with sf() as session:
        old = session.query(Workflow).filter(Workflow.id == wf_id).first()
        assert old.migration_status == "migrated"
        assert old.migrated_to_id == r.new_workflow_id

        new = session.query(ScriptWorkflow).filter(ScriptWorkflow.id == r.new_workflow_id).first()
        assert new is not None
        assert new.status == "sandbox_testing"
        assert new.migrated_from_workflow_id == wf_id
        assert "result.json" in new.script_text

        ver = (
            session.query(ScriptWorkflowVersion)
            .filter(ScriptWorkflowVersion.workflow_id == new.id)
            .first()
        )
        assert ver is not None
        assert ver.is_current
        assert ver.version_no == 1


def test_migration_marks_failed_when_agent_loop_fails(client, monkeypatch, tmp_path):
    """LLM 一直让脚本失败（错误代码） → 4 轮后达上限，旧 workflow 标 failed。"""
    from modstore_server.script_agent import sandbox_runner
    from modstore_server.script_agent.llm_client import StubLlmClient
    from modstore_server.scripts import migrate_workflows_to_script as m

    monkeypatch.setattr(sandbox_runner, "SCRIPT_ROOT", tmp_path)

    user_id = _make_user(default_llm={"provider": "openai", "model": "gpt-4o-mini"})
    wf_id = _seed_legacy_workflow(user_id)

    bad_code = "raise RuntimeError('boom')\n"
    stub = StubLlmClient(
        [
            "plan",
            f"```python\n{bad_code}```",
            f"```python\n{bad_code}```",
            f"```python\n{bad_code}```",
            f"```python\n{bad_code}```",
        ]
    )

    def fake_factory(db, user):
        return stub

    results = asyncio.run(m.migrate_user_workflows(user_id=user_id, llm_factory=fake_factory))
    assert len(results) == 1
    r = results[0]
    assert not r.ok

    from modstore_server.models import Workflow, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        old = session.query(Workflow).filter(Workflow.id == wf_id).first()
        assert old.migration_status == "failed"
        assert old.migrated_to_id is None


def test_migration_marks_failed_when_user_has_no_llm_config(client, monkeypatch):
    """用户没配 default_llm_json → 直接 failed，不浪费 sandbox。"""
    from modstore_server.scripts import migrate_workflows_to_script as m

    user_id = _make_user(default_llm=None)
    wf_id = _seed_legacy_workflow(user_id)

    # 默认 llm_factory 走 _resolve_user_llm_for_migration → None
    results = asyncio.run(m.migrate_user_workflows(user_id=user_id))
    assert len(results) == 1
    assert not results[0].ok
    assert "LLM" in results[0].error or "default_llm" in results[0].error

    from modstore_server.models import Workflow, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        old = session.query(Workflow).filter(Workflow.id == wf_id).first()
        assert old.migration_status == "failed"


def test_build_brief_from_workflow_includes_nodes_and_triggers(client):
    """``build_brief_from_workflow`` 把 nodes/edges/triggers 都灌到 goal 里。"""
    import json

    from modstore_server.models import (
        Workflow,
        WorkflowTrigger,
        get_session_factory,
    )
    from modstore_server.scripts import migrate_workflows_to_script as m

    user_id = _make_user()
    wf_id = _seed_legacy_workflow(user_id)
    sf = get_session_factory()
    with sf() as session:
        session.add(
            WorkflowTrigger(
                workflow_id=wf_id,
                user_id=user_id,
                trigger_type="cron",
                trigger_key="0 * * * *",
                config_json=json.dumps({"timezone": "Asia/Shanghai"}),
                is_active=True,
            )
        )
        session.commit()
        wf = session.query(Workflow).filter(Workflow.id == wf_id).first()
        brief = m.build_brief_from_workflow(session, wf)
    assert "审核员工" in brief.goal
    assert "cron" in brief.goal
    assert brief.references["migrated_from_workflow_id"] == wf_id
    assert brief.trigger_type in ("cron", "manual")
