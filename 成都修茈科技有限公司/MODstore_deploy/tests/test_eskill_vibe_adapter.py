"""测试 :mod:`modstore_server.integrations.vibe_eskill_adapter` 与
:func:`eskill_runtime._execute_logic` 的派发分支。
"""

from __future__ import annotations

import importlib.util

import pytest

if importlib.util.find_spec("vibe_coding") is None:
    pytest.skip("vibe-coding 未安装,跳过 ESkill adapter 测试", allow_module_level=True)


def test_render_brief_substitutes_placeholders():
    from modstore_server.integrations.vibe_eskill_adapter import _render_brief

    out = _render_brief({"brief": "求 {{x}} 的平方"}, {"x": 5})
    assert out == "求 5 的平方"


def test_render_brief_falls_back_to_input_json():
    from modstore_server.integrations.vibe_eskill_adapter import _render_brief

    out = _render_brief({}, {"text": "hello"})
    assert "hello" in out


def test_execute_vibe_code_kind_uses_run_input_mapping(monkeypatch):
    class _Skill:
        skill_id = "vc-eskill-1"

        def to_dict(self):
            return {"skill_id": self.skill_id, "code": "..."}

    class _Run:
        def to_dict(self):
            return {"output": 42}

    class _StubCoder:
        def code(self, brief, *, mode="brief_first", skill_id=None, project_root=None):
            return _Skill()

        def run(self, sid, input_data):
            assert input_data.get("a") == 1
            return _Run()

    monkeypatch.setattr(
        "modstore_server.integrations.vibe_adapter.get_vibe_coder",
        lambda **kw: _StubCoder(),
    )
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_eskill_adapter._resolve_provider_model",
        lambda logic, uid: {"provider": "openai", "model": "gpt-4o-mini"},
    )
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_eskill_adapter._resolve_project_root",
        lambda logic, uid: None,
    )

    from modstore_server.integrations.vibe_eskill_adapter import execute_vibe_code_kind

    result = execute_vibe_code_kind(
        {
            "type": "vibe_code",
            "brief": "压平 {{a}}",
            "run_input_mapping": {"a": "src"},
            "output_var": "vibe_out",
        },
        {"src": 1, "extra": 9},
        user_id=1,
    )
    assert result["ok"] is True
    assert result["vibe_run"]["output"] == 42
    assert result["vibe_out"]["output"] == 42


def test_execute_vibe_code_kind_repairs_failed_existing_skill(monkeypatch):
    class _Skill:
        skill_id = "vc-existing"

        def to_dict(self):
            return {"skill_id": self.skill_id, "code": "..."}

    class _Store:
        def has_code_skill(self, sid):
            return sid == "vc-existing"

        def get_code_skill(self, sid):
            return _Skill()

    class _Run:
        def __init__(self, payload):
            self.payload = payload

        def to_dict(self):
            return self.payload

    class _StubCoder:
        code_store = _Store()

        def __init__(self):
            self.runs = 0
            self.repaired = False

        def code(self, brief, *, mode="brief_first", skill_id=None, project_root=None):
            raise AssertionError("existing skill should be reused before repair")

        def repair(self, sid, failure):
            assert sid == "vc-existing"
            assert "boom" in failure
            self.repaired = True
            return _Skill()

        def run(self, sid, input_data):
            self.runs += 1
            if self.runs == 1:
                return _Run({"output": {"error": "boom"}, "stage": "failed"})
            return _Run({"output": {"ok": True, "value": 7}, "stage": "static"})

    stub = _StubCoder()
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_adapter.get_vibe_coder",
        lambda **kw: stub,
    )
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_eskill_adapter._resolve_provider_model",
        lambda logic, uid: {"provider": "openai", "model": "gpt-4o-mini"},
    )
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_eskill_adapter._resolve_project_root",
        lambda logic, uid: None,
    )

    from modstore_server.integrations.vibe_eskill_adapter import execute_vibe_code_kind

    result = execute_vibe_code_kind(
        {"type": "vibe_code", "skill_id": "vc-existing", "brief": "do work"},
        {"x": 1},
        user_id=1,
    )
    assert result["ok"] is True
    assert result["auto_repaired"] is True
    assert stub.repaired is True
    assert result["vibe_run"]["output"]["value"] == 7


def test_execute_vibe_workflow_kind_runs_graph(monkeypatch):
    class _Graph:
        def to_dict(self):
            return {"nodes": [{"id": "n1"}], "edges": []}

    class _RunResult:
        def to_dict(self):
            return {"status": "completed", "output": {"x": 1}}

    class _StubCoder:
        def workflow(self, brief, *, project_root=None):
            assert brief
            return _Graph()

        def execute(self, graph, input_data):
            assert isinstance(graph, _Graph)
            return _RunResult()

    monkeypatch.setattr(
        "modstore_server.integrations.vibe_adapter.get_vibe_coder",
        lambda **kw: _StubCoder(),
    )
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_eskill_adapter._resolve_provider_model",
        lambda logic, uid: {"provider": "openai", "model": "gpt-4o-mini"},
    )
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_eskill_adapter._resolve_project_root",
        lambda logic, uid: None,
    )

    from modstore_server.integrations.vibe_eskill_adapter import execute_vibe_workflow_kind

    out = execute_vibe_workflow_kind(
        {"type": "vibe_workflow", "brief": "拆 {{topic}}"},
        {"topic": "演示"},
        user_id=1,
    )
    assert out["ok"] is True
    assert out["vibe_graph"]["nodes"][0]["id"] == "n1"
    assert out["vibe_workflow_run"]["output"] == {"x": 1}


def test_eskill_runtime_dispatches_vibe_code(monkeypatch):
    """``eskill_runtime._execute_logic`` 在 type=vibe_code 时委派到本适配器。"""
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_eskill_adapter.execute_vibe_kind",
        lambda logic, input_data, *, user_id: {
            "eskill_logic_type": str(logic.get("type") or ""),
            "ok": True,
            "vibe_skill": {"skill_id": "x"},
            "stub_payload": dict(input_data),
            "user_id_seen": user_id,
        },
    )
    from modstore_server.eskill_runtime import ESkillRuntime

    runtime = ESkillRuntime()
    out = runtime._execute_logic(
        {"type": "vibe_code", "brief": "x"},
        {"k": "v"},
        user_id=7,
    )
    assert out["ok"] is True
    assert out["stub_payload"] == {"k": "v"}
    assert out["user_id_seen"] == 7


# ---------------------------------------------------------------------------
# project_root tests
# ---------------------------------------------------------------------------


def test_execute_vibe_code_kind_project_root_invalid_path_returns_error(monkeypatch, tmp_path):
    """project_root 不在工作区内时应立即返回错误，不调 vibe coder。"""
    from modstore_server.integrations.vibe_adapter import VibePathError

    def _bad_ensure(root, *, user_id):
        raise VibePathError(f"root={root} 不在工作区内")

    monkeypatch.setattr(
        "modstore_server.integrations.vibe_eskill_adapter._resolve_project_root",
        lambda logic, uid: (_ for _ in ()).throw(
            VibePathError(f"root={logic.get('project_root')} 不在工作区内")
        ),
    )

    monkeypatch.setattr(
        "modstore_server.integrations.vibe_eskill_adapter._resolve_provider_model",
        lambda logic, uid: {"provider": "openai", "model": "gpt-4o-mini"},
    )

    from modstore_server.integrations.vibe_eskill_adapter import execute_vibe_code_kind

    out = execute_vibe_code_kind(
        {"type": "vibe_code", "brief": "do stuff", "project_root": "/evil/path"},
        {},
        user_id=1,
    )
    assert out["ok"] is False
    assert "project_root" in out["error"].lower() or "路径" in out["error"]


def test_execute_vibe_code_kind_valid_project_root_injects_analysis(monkeypatch, tmp_path):
    """合法 project_root 应触发 analyze_project 并把结果注入 run_input['project_analysis']。"""
    # Create a minimal project directory.
    project = tmp_path / "myproj"
    project.mkdir()
    (project / "package.json").write_text(
        '{"name": "myproj", "dependencies": {"vue": "^3.0.0"}}',
        encoding="utf-8",
    )

    captured_project_root = []
    captured_run_input = []

    class _Skill:
        skill_id = "vc-proj"

        def to_dict(self):
            return {"skill_id": self.skill_id}

    class _Run:
        def to_dict(self):
            return {"output": {"ok": True}}

    class _StubCoder:
        code_store = None

        def code(self, brief, *, mode="brief_first", skill_id=None, project_root=None):
            captured_project_root.append(project_root)
            return _Skill()

        def run(self, sid, input_data):
            captured_run_input.append(dict(input_data))
            return _Run()

    monkeypatch.setattr(
        "modstore_server.integrations.vibe_adapter.get_vibe_coder",
        lambda **kw: _StubCoder(),
    )
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_eskill_adapter._resolve_provider_model",
        lambda logic, uid: {"provider": "openai", "model": "gpt-4o-mini"},
    )
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_eskill_adapter._resolve_project_root",
        lambda logic, uid: str(project),
    )

    from modstore_server.integrations.vibe_eskill_adapter import execute_vibe_code_kind

    out = execute_vibe_code_kind(
        {"type": "vibe_code", "brief": "生成项目文档", "project_root": str(project)},
        {},
        user_id=1,
    )
    assert out["ok"] is True
    # project_root was forwarded to coder.code()
    assert captured_project_root and captured_project_root[0] == str(project)
    # project_analysis was injected into run_input
    assert captured_run_input
    pa = captured_run_input[0].get("project_analysis")
    assert isinstance(pa, dict), "project_analysis should have been injected into run_input"
    assert "tech_stack" in pa
    assert "Vue" in pa.get("tech_stack", [])


def test_execute_vibe_code_kind_no_project_root_does_not_inject_analysis(monkeypatch):
    """Without project_root, run_input must NOT gain a project_analysis key."""
    captured_run_input = []

    class _Skill:
        skill_id = "vc-noproj"

        def to_dict(self):
            return {"skill_id": self.skill_id}

    class _Run:
        def to_dict(self):
            return {"output": {"ok": True}}

    class _StubCoder:
        code_store = None

        def code(self, brief, *, mode="brief_first", skill_id=None, project_root=None):
            return _Skill()

        def run(self, sid, input_data):
            captured_run_input.append(dict(input_data))
            return _Run()

    monkeypatch.setattr(
        "modstore_server.integrations.vibe_adapter.get_vibe_coder",
        lambda **kw: _StubCoder(),
    )
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_eskill_adapter._resolve_provider_model",
        lambda logic, uid: {"provider": "openai", "model": "gpt-4o-mini"},
    )
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_eskill_adapter._resolve_project_root",
        lambda logic, uid: None,
    )

    from modstore_server.integrations.vibe_eskill_adapter import execute_vibe_code_kind

    out = execute_vibe_code_kind(
        {"type": "vibe_code", "brief": "sum two numbers"},
        {"a": 1, "b": 2},
        user_id=1,
    )
    assert out["ok"] is True
    assert captured_run_input
    assert "project_analysis" not in captured_run_input[0]
