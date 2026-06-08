"""``script_workflow_api`` 集成测试：commit / sandbox-run / activate 强校验等关键流转。

不涉及真实 LLM；commit 端点直接消费手工塞进会话内存的 outcome。
"""

from __future__ import annotations

import io
import json
import types
import uuid
from datetime import datetime
from typing import Any, Dict

import pytest

pytest.importorskip("fastapi")


def _make_user(is_admin: bool = False):
    from modstore_server.models import User, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        user = User(
            username=f"script_user_{uuid.uuid4().hex[:8]}",
            email=f"script_{uuid.uuid4().hex[:8]}@pytest.local",
            password_hash="x",
            is_admin=is_admin,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return types.SimpleNamespace(id=user.id, is_admin=is_admin)


@pytest.fixture
def user_client(client):
    from modstore_server import script_workflow_api
    from modstore_server.app import app

    user = _make_user()
    app.dependency_overrides[script_workflow_api._get_current_user] = lambda: user
    yield client, user
    app.dependency_overrides.pop(script_workflow_api._get_current_user, None)


# ----------------------------- helpers ----------------------------- #


def _seed_session(user_id: int, *, ok: bool, code: str = "") -> str:
    """直接写一条已完成会话到内存，模拟 SSE 跑完到 done。"""
    from modstore_server import script_workflow_api as api

    sid = uuid.uuid4().hex
    api.SCRIPT_AGENT_SESSIONS[sid] = api._Session(
        user_id=user_id,
        brief={
            "goal": "汇总 csv",
            "outputs": "result.json",
            "acceptance": "存在 result.json",
            "inputs": [],
            "fallback": "",
            "references": {},
            "trigger_type": "manual",
        },
        status="done" if ok else "error",
        events=[],
        outcome={
            "ok": ok,
            "iterations": 1,
            "final_code": code,
            "plan_md": "step 1\nstep 2",
            "trace": [{"phase": "code", "iteration": 0}],
            "error": "",
        },
        error="",
        started_at=datetime.utcnow().timestamp(),
        files_meta=[],
    )
    return sid


def _stub_llm_resolver(monkeypatch, *, provider="openai", api_key="fake"):
    """绕过真实 BYOK；让 commit 之前不会因为缺 key 失败（未涉及实际调用）。"""
    monkeypatch.setattr(
        "modstore_server.script_workflow_api.resolve_api_key",
        lambda db, uid, prov: (api_key, "test"),
    )
    monkeypatch.setattr(
        "modstore_server.script_workflow_api.resolve_base_url",
        lambda db, uid, prov: None,
    )

    # 给 user 一个默认 LLM preference，避免 _resolve_llm_for_user 报缺配置
    from modstore_server.models import User, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        for u in session.query(User).all():
            u.default_llm_json = json.dumps({"provider": provider, "model": "gpt-4o-mini"})
        session.commit()


# ----------------------------- 测试用例 ----------------------------- #


def test_commit_session_creates_workflow_in_sandbox_testing(user_client, monkeypatch):
    client, user = user_client
    _stub_llm_resolver(monkeypatch)

    code = "from pathlib import Path\nPath('outputs').mkdir(exist_ok=True)\nPath('outputs/x.txt').write_text('y')\nprint('ok')\n"
    sid = _seed_session(user.id, ok=True, code=code)
    r = client.post(
        f"/api/script-workflows/sessions/{sid}/commit",
        json={"name": "我的脚本", "schema_in": {}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "我的脚本"
    assert body["status"] == "sandbox_testing"
    assert body["script_text"].strip() == code.strip()

    # 列表 / 详情
    r2 = client.get("/api/script-workflows")
    assert r2.status_code == 200
    rows = r2.json()
    assert any(row["id"] == body["id"] for row in rows)

    r3 = client.get(f"/api/script-workflows/{body['id']}")
    assert r3.status_code == 200
    detail = r3.json()
    assert detail["status"] == "sandbox_testing"
    assert detail["current_version_id"] is not None


def test_commit_rejects_when_outcome_not_ok(user_client, monkeypatch):
    client, user = user_client
    _stub_llm_resolver(monkeypatch)
    sid = _seed_session(user.id, ok=False)
    r = client.post(
        f"/api/script-workflows/sessions/{sid}/commit",
        json={"name": "失败脚本", "schema_in": {}},
    )
    assert r.status_code == 400
    assert "未通过自动验收" in r.text


def test_activate_requires_successful_manual_sandbox_run(user_client, monkeypatch, tmp_path):
    """活体集成：commit → 直接 activate 应被拒；sandbox-run 成功后 activate 成功。"""
    from modstore_server.script_agent import sandbox_runner

    monkeypatch.setattr(sandbox_runner, "SCRIPT_ROOT", tmp_path)

    client, user = user_client
    _stub_llm_resolver(monkeypatch)

    # 先 commit 一份能跑通的脚本（不依赖 LLM）
    code = (
        "from pathlib import Path\n"
        "Path('outputs').mkdir(exist_ok=True)\n"
        "Path('outputs/r.txt').write_text('hi')\n"
        "print('done')\n"
    )
    sid = _seed_session(user.id, ok=True, code=code)
    r = client.post(
        f"/api/script-workflows/sessions/{sid}/commit",
        json={"name": "可启用脚本", "schema_in": {}},
    )
    assert r.status_code == 200
    wf_id = r.json()["id"]

    # activate 直接被拒（没 manual_sandbox run）
    r_bad = client.post(f"/api/script-workflows/{wf_id}/activate")
    assert r_bad.status_code == 400
    assert "manual_sandbox" in r_bad.text or "沙箱" in r_bad.text

    # 跑一次 manual_sandbox：用真实子进程
    r_sb = client.post(
        f"/api/script-workflows/{wf_id}/sandbox-run",
        files=[],
    )
    assert r_sb.status_code == 200, r_sb.text
    sb = r_sb.json()
    assert sb["mode"] == "manual_sandbox"
    assert sb["status"] == "success", sb

    # activate 现在应该通过
    r_ok = client.post(f"/api/script-workflows/{wf_id}/activate")
    assert r_ok.status_code == 200
    assert r_ok.json()["status"] == "active"


def test_deactivate_sets_deprecated(user_client, monkeypatch):
    client, user = user_client
    _stub_llm_resolver(monkeypatch)
    sid = _seed_session(user.id, ok=True, code="print('x')\n")
    wf_id = client.post(
        f"/api/script-workflows/sessions/{sid}/commit",
        json={"name": "x", "schema_in": {}},
    ).json()["id"]
    r = client.post(f"/api/script-workflows/{wf_id}/deactivate")
    assert r.status_code == 200
    assert r.json()["status"] == "deprecated"


def test_run_requires_active_status(user_client, monkeypatch):
    client, user = user_client
    _stub_llm_resolver(monkeypatch)
    sid = _seed_session(user.id, ok=True, code="print('x')\n")
    wf_id = client.post(
        f"/api/script-workflows/sessions/{sid}/commit",
        json={"name": "x", "schema_in": {}},
    ).json()["id"]
    r = client.post(f"/api/script-workflows/{wf_id}/run", files=[])
    assert r.status_code == 400
    assert "未启用" in r.text or "不能" in r.text or "active" in r.text


def test_delete_workflow_clears_versions_and_runs(user_client, monkeypatch):
    client, user = user_client
    _stub_llm_resolver(monkeypatch)
    sid = _seed_session(user.id, ok=True, code="print('x')\n")
    wf_id = client.post(
        f"/api/script-workflows/sessions/{sid}/commit",
        json={"name": "可删脚本", "schema_in": {}},
    ).json()["id"]

    r = client.delete(f"/api/script-workflows/{wf_id}")
    assert r.status_code == 200

    r2 = client.get(f"/api/script-workflows/{wf_id}")
    assert r2.status_code == 404


def test_session_lookup_returns_events(user_client, monkeypatch):
    client, user = user_client
    _stub_llm_resolver(monkeypatch)
    from modstore_server import script_workflow_api as api

    sid = _seed_session(user.id, ok=True)
    api.SCRIPT_AGENT_SESSIONS[sid]["events"] = [
        {"type": "context", "iteration": 0, "payload": {"x": 1}},
        {"type": "done", "iteration": 0, "payload": {"outcome": {"ok": True}}},
    ]

    r = client.get(f"/api/script-workflows/sessions/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert len(body["events"]) == 2
    assert body["events"][-1]["type"] == "done"
