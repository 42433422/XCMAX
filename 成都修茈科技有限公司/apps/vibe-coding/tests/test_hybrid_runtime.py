from __future__ import annotations

from types import SimpleNamespace

from vibe_coding._internals.code_models import CodeSkillRun
from vibe_coding.runtime import HybridSkillRuntime


class _Store:
    def __init__(self, skill_type: str):
        self.skill_type = skill_type

    def get_skill(self, skill_id: str):
        return SimpleNamespace(skill_id=skill_id, skill_type=self.skill_type)


class _ConfigRuntime:
    def __init__(self, skill_type: str):
        self.store = _Store(skill_type)

    def run(self, skill_id, input_data, **kwargs):
        return SimpleNamespace(stage="dynamic", skill_id=skill_id, input_data=input_data)


class _CodeRuntime:
    def run(self, skill_id, input_data, **kwargs):
        return CodeSkillRun(
            run_id="run-1",
            skill_id=skill_id,
            stage="solidified",
            input_data=input_data,
            output_data={"ok": True},
        )


def test_code_runtime_returns_self_contained_code_skill_run():
    runtime = HybridSkillRuntime(_ConfigRuntime("code"), _CodeRuntime())

    result = runtime.run("skill-1", {"value": 1})

    assert isinstance(result, CodeSkillRun)
    assert result.stage == "solidified"


def test_hybrid_falls_back_to_code_runtime():
    runtime = HybridSkillRuntime(_ConfigRuntime("hybrid"), _CodeRuntime())

    result = runtime.run("skill-1", {"value": 1})

    assert isinstance(result, CodeSkillRun)
    assert result.output_data == {"ok": True}
