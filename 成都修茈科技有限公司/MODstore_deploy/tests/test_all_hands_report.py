"""all_hands_report 的空上下文降级与信号提取测试。"""

from __future__ import annotations

from typing import Any, Dict

import pytest

import modstore_server.all_hands_report as ahr


class _DummySessionFactory:
    def __call__(self) -> "_DummySessionFactory":
        return self

    def __enter__(self) -> object:
        return object()

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_all_hands_template_mentions_empty_context_paths() -> None:
    tpl = ahr.ALL_HANDS_TASK_TEMPLATE
    assert "仓库节选缺失，待同步 yuangon 目录" in tpl
    assert "近期失败流水为空" in tpl
    assert "待联网检索验证" in tpl
    assert "不要输出「无法生成完整汇报」" in tpl
    assert "```mermaid" in tpl
    assert "flowchart" in tpl


def test_manifest_signals_extracts_behavior_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    pack = {
        "manifest": {
            "name": "mods-and-eskill-curator",
            "employee_config_v2": {
                "identity": {"name": "Mods/ESkill 策展员", "description": "负责策展与联动"},
                "cognition": {
                    "agent": {
                        "role": {
                            "persona": "严谨",
                            "expertise": ["curation", "workflow"],
                        },
                        "behavior_rules": [
                            "输出前先核验输入是否齐全",
                            {"name": "引用规范", "description": "只引用已给上下文"},
                            {"rule_id": "no-fabrication", "text": "禁止编造"},
                        ],
                    },
                    "skills": [
                        {"name": "manifest-review", "brief": "审查配置", "kind": "analysis"}
                    ],
                },
                "actions": {"handlers": ["llm_md", "echo"]},
                "collaboration": {
                    "depends_on": ["employee-pack-curator"],
                    "workflow": {"workflow_id": 17},
                },
            },
        }
    }

    monkeypatch.setattr(ahr, "get_session_factory", lambda: _DummySessionFactory())
    monkeypatch.setattr(ahr, "load_employee_pack", lambda _session, _pkg_id: pack)

    out = ahr._manifest_signals("mods-and-eskill-curator")
    assert out["name"] == "Mods/ESkill 策展员"
    assert out["description"] == "负责策展与联动"
    assert out["handlers"] == ["llm_md", "echo"]
    assert out["depends_on"] == ["employee-pack-curator"]
    assert out["workflow_id"] == 17
    assert out["behavior_rules"] == [
        "输出前先核验输入是否齐全",
        "引用规范: 只引用已给上下文",
        "no-fabrication: 禁止编造",
    ]


def test_manifest_signals_includes_ci_coverage_and_business_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = {
        "manifest": {
            "employee_config_v2": {
                "identity": {"name": "测试质量运行员"},
                "cognition": {"agent": {"role": {}}},
                "actions": {"handlers": ["llm_md"]},
                "manifest_signals": {
                    "ci_coverage_artifacts": ["coverage/**", "playwright-report/**"],
                },
            },
        }
    }

    monkeypatch.setattr(ahr, "get_session_factory", lambda: _DummySessionFactory())
    monkeypatch.setattr(ahr, "load_employee_pack", lambda _session, _pkg_id: pack)
    monkeypatch.setattr(
        ahr,
        "_load_yuangon_employee_meta",
        lambda _pkg_id: {
            "business_context": {"five_line": "P-S", "kpis": ["覆盖率"]},
            "ci_coverage_artifacts": ["coverage/**"],
        },
    )

    out = ahr._manifest_signals("test-qa-runner")
    assert out["ci_coverage_artifacts"] == ["coverage/**", "playwright-report/**"]
    assert out["business_context"]["five_line"] == "P-S"


@pytest.mark.asyncio
async def test_report_one_employee_sets_context_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: Dict[str, Any] = {}

    async def _fake_research_context(**_kwargs):
        return {"ok": True, "context_pack": "", "sources": [], "warnings": []}

    def _fake_execute_employee_task(
        pkg_id: str,
        task_text: str,
        inp: Dict[str, Any],
        user_id: int,
        bench_llm_override: tuple[str, str],
    ) -> Dict[str, Any]:
        captured["pkg_id"] = pkg_id
        captured["task_text"] = task_text
        captured["inp"] = inp
        captured["user_id"] = user_id
        captured["bench_llm_override"] = bench_llm_override
        return {
            "reasoning_excerpt": "ok",
            "cognition_error": "",
            "duration_ms": 12.0,
            "llm_tokens": 34,
        }

    async def _fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(ahr, "build_research_context", _fake_research_context)
    monkeypatch.setattr(ahr, "collect_yuangon_pack_excerpt", lambda _pkg_id: ("", []))
    monkeypatch.setattr(ahr, "_recent_failures", lambda _pkg_id: [])
    monkeypatch.setattr(
        ahr,
        "_manifest_signals",
        lambda _pkg_id: {
            "name": "Mods/ESkill 策展员",
            "description": "负责策展与联动",
            "persona": "严谨",
            "expertise": [],
            "handlers": ["llm_md"],
            "depends_on": ["employee-pack-curator"],
            "skills": [],
            "behavior_rules": ["禁止编造"],
            "workflow_id": 17,
        },
    )
    monkeypatch.setattr(ahr, "execute_employee_task", _fake_execute_employee_task)
    monkeypatch.setattr(ahr.asyncio, "to_thread", _fake_to_thread)

    row = await ahr._report_one_employee(
        pkg_id="mods-and-eskill-curator",
        display_name="Mods/ESkill 策展员",
        other_employees=["employee-pack-curator"],
        user_id=100,
        bench_provider="openai",
        bench_model="gpt-4o-mini",
        with_research=True,
    )

    assert row["status"] == "ok"
    assert captured["pkg_id"] == "mods-and-eskill-curator"
    assert captured["inp"]["context_availability"] == {
        "yuangon_excerpt": False,
        "research_pack": False,
        "execution_failures": False,
    }
    assert captured["inp"].get("allow_high_risk_real_run") is True
