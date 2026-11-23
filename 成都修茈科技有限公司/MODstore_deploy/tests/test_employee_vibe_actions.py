"""测试 :mod:`modstore_server.integrations.vibe_action_handlers`。

校验:
- 路径越界一律拒绝(``VibePathError``)。
- 无 provider/model 不发起调用。
- 正常路径会拿到 :class:`ProjectPatch` 的 to_dict。
- ``vibe_code`` 在 ``run_input`` 缺失时只生成不执行。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import zipfile
from typing import Any, Dict

import pytest

if importlib.util.find_spec("vibe_coding") is None:
    pytest.skip("vibe-coding 未安装,跳过 action handler 测试", allow_module_level=True)


@pytest.fixture(autouse=True)
def _reset_vibe_cache():
    from modstore_server.integrations import vibe_adapter

    vibe_adapter.reset_vibe_coder_cache()
    yield
    vibe_adapter.reset_vibe_coder_cache()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    ws = tmp_path / "ws" / "1"
    (ws / "app").mkdir(parents=True)
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(tmp_path / "ws" / "{user_id}"))
    return ws


@pytest.fixture
def authorized_employee(workspace, monkeypatch):
    """Load a real owner-scoped employee archive without another test initializing SQL."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from modstore_server import employee_runtime
    from modstore_server.integrations import vibe_action_handlers
    from modstore_server.models import CatalogItem, User

    archive = workspace / "emp.xcemp"
    manifest = {
        "id": "emp",
        "employee_config_v2": {
            "workspace_policy": {
                "scope_globs": ["ws/1/app", "ws/1/app/**"],
                "forbidden_globs": ["**/.env"],
            }
        },
    }
    with zipfile.ZipFile(archive, "w") as packed:
        packed.writestr("emp/manifest.json", json.dumps(manifest))
    engine = create_engine(f"sqlite:///{workspace / 'employee.sqlite'}")
    User.__table__.create(engine)
    CatalogItem.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(
            User(id=1, username="vibe-owner", password_hash="unused", account_state="active")
        )
        session.flush()
        session.add(
            CatalogItem(
                pkg_id="emp",
                version="1.0.0",
                name="Scoped employee",
                artifact="employee_pack",
                author_id=1,
                stored_filename=archive.name,
                sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            )
        )
        session.commit()
    monkeypatch.setenv("MODSTORE_REPO_ROOT", str(workspace.parent.parent))
    monkeypatch.setattr(employee_runtime, "files_dir", lambda: workspace)
    monkeypatch.setattr(vibe_action_handlers, "get_session_factory", lambda: factory)
    yield
    engine.dispose()


def _patch_provider_resolver(monkeypatch, *, provider="openai", model="gpt-4o-mini"):
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_action_handlers._safe_resolve_provider_model",
        lambda uid, p, m: {"provider": p or provider, "model": m or model},
    )


def test_vibe_edit_rejects_traversal(monkeypatch, workspace):
    _patch_provider_resolver(monkeypatch)
    from modstore_server.integrations.vibe_action_handlers import vibe_edit_handler

    out = vibe_edit_handler(
        action_cfg={"root": "/etc", "brief": "anything"},
        reasoning={"reasoning": "x"},
        task="t",
        employee_id="emp",
        user_id=1,
    )
    assert out["ok"] is False
    assert "工作区" in out["error"] or "不在" in out["error"]


def test_vibe_edit_async_mode_short_circuits(monkeypatch, workspace):
    _patch_provider_resolver(monkeypatch)
    from modstore_server.integrations.vibe_action_handlers import vibe_edit_handler

    out = vibe_edit_handler(
        action_cfg={"root": str(workspace / "app"), "brief": "x", "async_mode": True},
        reasoning={},
        task="",
        employee_id="emp",
        user_id=1,
    )
    assert out["ok"] is False
    assert "async_mode" in out["error"]


def test_vibe_edit_calls_apply_patch(monkeypatch, workspace, authorized_employee):
    _patch_provider_resolver(monkeypatch)

    class _StubApply:
        def __init__(self):
            self.applied = True
            self.errors = []

        def to_dict(self) -> Dict[str, Any]:
            return {"applied": True, "errors": []}

    class _StubPatch:
        def to_dict(self) -> Dict[str, Any]:
            return {"id": "patch-1", "files": []}

    class _StubCoder:
        def edit_project(self, brief, *, root, focus_paths=None):
            assert "task=改造" in brief or brief
            assert str(root) == str(workspace / "app")
            return _StubPatch()

        def apply_patch(self, patch, *, root, dry_run=False):
            return _StubApply()

    monkeypatch.setattr(
        "modstore_server.integrations.vibe_adapter.get_vibe_coder",
        lambda **kw: _StubCoder(),
    )
    from modstore_server.integrations.vibe_action_handlers import vibe_edit_handler

    out = vibe_edit_handler(
        action_cfg={"root": str(workspace / "app"), "brief": "task=改造"},
        reasoning={},
        task="",
        employee_id="emp",
        user_id=1,
    )
    assert out["ok"] is True
    assert out["patch"]["id"] == "patch-1"
    assert out["apply"]["applied"] is True


def test_vibe_heal_returns_ok(monkeypatch, workspace, authorized_employee):
    _patch_provider_resolver(monkeypatch)

    class _Result:
        ok = True
        rounds = 2

        def to_dict(self) -> Dict[str, Any]:
            return {"ok": True, "rounds": 2, "tool_log": []}

    class _StubCoder:
        def heal_project(self, brief, *, max_rounds=3):
            assert max_rounds == 3
            return _Result()

    monkeypatch.setattr(
        "modstore_server.integrations.vibe_adapter.get_project_vibe_coder",
        lambda root, **kw: _StubCoder(),
    )
    from modstore_server.integrations.vibe_action_handlers import vibe_heal_handler

    out = vibe_heal_handler(
        action_cfg={"root": str(workspace / "app"), "brief": "heal", "max_rounds": 3},
        reasoning={},
        task="",
        employee_id="emp",
        user_id=1,
    )
    assert out["ok"] is True
    assert out["rounds"] == 2


def test_vibe_code_runs_when_input_provided(monkeypatch):
    _patch_provider_resolver(monkeypatch)

    class _Skill:
        skill_id = "vc-test-1"
        code = "def fn(): return 1"

        def to_dict(self):
            return {"skill_id": self.skill_id, "code": self.code}

    class _Run:
        def to_dict(self):
            return {"output": 1, "ok": True}

    class _StubCoder:
        def code(self, brief, *, mode="brief_first", skill_id=None):
            return _Skill()

        def run(self, sid, input_data):
            assert input_data == {"x": 1}
            return _Run()

    monkeypatch.setattr(
        "modstore_server.integrations.vibe_adapter.get_vibe_coder",
        lambda **kw: _StubCoder(),
    )
    from modstore_server.integrations.vibe_action_handlers import vibe_code_handler

    out = vibe_code_handler(
        action_cfg={"brief": "x", "run_input": {"x": 1}},
        reasoning={},
        task="",
        employee_id="emp",
        user_id=1,
    )
    assert out["ok"] is True
    assert out["skill"]["skill_id"] == "vc-test-1"
    assert out["run"]["output"] == 1


def test_vibe_edit_rejects_focus_paths_traversal(monkeypatch, workspace):
    """focus_paths 含 .. 时必须在调用 vibe 前拒绝。"""
    _patch_provider_resolver(monkeypatch)
    from modstore_server.integrations.vibe_action_handlers import vibe_edit_handler

    out = vibe_edit_handler(
        action_cfg={
            "root": str(workspace / "app"),
            "brief": "x",
            "focus_paths": ["../escape"],
        },
        reasoning={},
        task="",
        employee_id="emp",
        user_id=1,
    )
    assert out["ok"] is False
    assert "穿越" in out["error"] or "越界" in out["error"]


def test_vibe_edit_rejects_focus_paths_workspace_scope(monkeypatch, tmp_path):
    """focus_paths 解析后的路径也必须落在 manifest workspace_policy 内。"""
    _patch_provider_resolver(monkeypatch)
    monkeypatch.setenv("MODSTORE_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(tmp_path / "ws" / "{user_id}"))
    ws = tmp_path / "ws" / "1" / "app"
    (ws / "deep").mkdir(parents=True)

    def fake_load(session, pid: str):
        return {
            "manifest": {
                "employee_config_v2": {
                    "workspace_policy": {
                        "scope_globs": ["ws/**/app/allowed/**"],
                        "forbidden_globs": [],
                    }
                }
            }
        }

    monkeypatch.setattr("modstore_server.employee_runtime.load_employee_pack", fake_load)

    from modstore_server.integrations.vibe_action_handlers import vibe_edit_handler

    out = vibe_edit_handler(
        action_cfg={
            "root": str(ws),
            "brief": "x",
            "focus_paths": ["deep"],
        },
        reasoning={},
        task="",
        employee_id="fp-scope",
        user_id=1,
    )
    assert out["ok"] is False
    assert "scope" in out["error"] or "允许" in out["error"]


def test_vibe_edit_rejects_workspace_scope_violation(monkeypatch, tmp_path):
    """manifest 中 workspace_policy 与 vibe root 不一致时拒绝（与 tool_write 对齐）。"""
    _patch_provider_resolver(monkeypatch)
    monkeypatch.setenv("MODSTORE_REPO_ROOT", str(tmp_path))
    ws = tmp_path / "ws" / "1" / "app"
    ws.mkdir(parents=True)
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(tmp_path / "ws" / "{user_id}"))

    def fake_load(session, pid: str):
        return {
            "manifest": {
                "employee_config_v2": {
                    "workspace_policy": {
                        "scope_globs": ["only-this-folder/**"],
                        "forbidden_globs": [],
                    }
                }
            }
        }

    monkeypatch.setattr("modstore_server.employee_runtime.load_employee_pack", fake_load)

    from modstore_server.integrations.vibe_action_handlers import vibe_edit_handler

    out = vibe_edit_handler(
        action_cfg={"root": str(ws), "brief": "x"},
        reasoning={},
        task="",
        employee_id="scoped-pack",
        user_id=1,
    )
    assert out["ok"] is False
    assert "scope" in out["error"] or "允许" in out["error"]


def test_vibe_heal_rejects_workspace_scope_violation(monkeypatch, tmp_path):
    _patch_provider_resolver(monkeypatch)
    monkeypatch.setenv("MODSTORE_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(tmp_path / "ws" / "{user_id}"))
    ws = tmp_path / "ws" / "1" / "proj" / "sub"
    ws.mkdir(parents=True)

    def fake_load(session, pid: str):
        return {
            "manifest": {
                "employee_config_v2": {
                    "workspace_policy": {
                        "scope_globs": ["nowhere/**"],
                        "forbidden_globs": [],
                    }
                }
            }
        }

    monkeypatch.setattr("modstore_server.employee_runtime.load_employee_pack", fake_load)

    from modstore_server.integrations.vibe_action_handlers import vibe_heal_handler

    out = vibe_heal_handler(
        action_cfg={"root": str(ws), "brief": "h"},
        reasoning={},
        task="",
        employee_id="scoped-heal",
        user_id=1,
    )
    assert out["ok"] is False
    assert "scope" in out["error"] or "允许" in out["error"]


def test_vibe_code_skips_run_without_input(monkeypatch):
    _patch_provider_resolver(monkeypatch)

    class _Skill:
        skill_id = "vc-only-gen"
        code = "def fn(): return 1"

        def to_dict(self):
            return {"skill_id": self.skill_id, "code": self.code}

    class _StubCoder:
        def code(self, brief, *, mode="brief_first", skill_id=None):
            return _Skill()

        def run(self, sid, input_data):
            raise AssertionError("不应被调用")

    monkeypatch.setattr(
        "modstore_server.integrations.vibe_adapter.get_vibe_coder",
        lambda **kw: _StubCoder(),
    )
    from modstore_server.integrations.vibe_action_handlers import vibe_code_handler

    out = vibe_code_handler(
        action_cfg={"brief": "只生成"},
        reasoning={},
        task="",
        employee_id="emp",
        user_id=1,
    )
    assert out["ok"] is True
    assert out["run"] is None
