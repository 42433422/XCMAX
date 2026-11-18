"""OpenHands-compatible SKILL.md skills load and trigger deterministically."""

from __future__ import annotations

from pathlib import Path

from app.application.skills.skill_registry import load_skills, match_skills, skill_rules
from app.application.workflow.planner_prompt_profile import select_rules_for_prompt


def write_skill(root: Path, folder: str, front: str, body: str) -> None:
    target = root / folder
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(f"---\n{front}\n---\n{body}\n", encoding="utf-8")


def test_load_and_match_skills_by_trigger(tmp_path, monkeypatch):
    write_skill(
        tmp_path,
        "inventory",
        "name: inventory-check\ndescription: 库存核对\ntriggers:\n  - 库存\n  - 缺货",
        "先查安全库存，再核对在途数量。",
    )
    write_skill(
        tmp_path,
        "pricing",
        "name: pricing-review\ndescription: 价格复核\ntriggers: 报价折扣",
        "低于底价时必须走审批。",
    )
    monkeypatch.setenv("XCAGI_SKILLS_DIRS", str(tmp_path))

    skills = load_skills()
    assert {skill.name for skill in skills} == {"inventory-check", "pricing-review"}
    matched = match_skills("帮我看看华东仓库存", skills)
    assert [skill.name for skill in matched] == ["inventory-check"]
    assert match_skills("今天天气", skills) == []


def test_skill_rules_are_bounded_and_named(tmp_path, monkeypatch):
    write_skill(tmp_path, "long", "name: long-skill\ntriggers: 长技能", "字" * 5000)
    monkeypatch.setenv("XCAGI_SKILLS_DIRS", str(tmp_path))

    rules = skill_rules("执行长技能")
    assert len(rules) == 1
    assert rules[0].startswith("技能「long-skill」：")
    assert len(rules[0]) <= 1520


def test_planner_rules_include_active_skills():
    rules = select_rules_for_prompt(
        "任意请求", {"active_skills": ["技能「demo」：按步骤执行"]}
    )
    assert "技能「demo」：按步骤执行" in rules
