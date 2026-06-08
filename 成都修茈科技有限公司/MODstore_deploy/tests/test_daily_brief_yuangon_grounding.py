"""daily_employee_briefs：yuangon 目录节选注入简报 input。"""

from __future__ import annotations

from pathlib import Path

import modstore_server.daily_employee_briefs as deb
from modstore_server.daily_employee_briefs import collect_yuangon_pack_excerpt
from modstore_server.duty_roster import yuangon_area_for_pkg


def test_yuangon_area_for_pkg_known() -> None:
    assert yuangon_area_for_pkg("employee-interview-assistant") == "quality-and-docs"
    assert yuangon_area_for_pkg("employee-pack-quality-interviewer") == "quality-and-docs"
    assert yuangon_area_for_pkg("unknown-nope") is None


def test_collect_disabled_returns_empty(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MODSTORE_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("MODSTORE_DAILY_BRIEF_GROUND_YUANGON", "0")
    body, warns = collect_yuangon_pack_excerpt("employee-interview-assistant")
    assert body == ""
    assert warns == []


def test_collect_reads_pack_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MODSTORE_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("MODSTORE_DAILY_BRIEF_GROUND_YUANGON", "1")
    monkeypatch.setenv("MODSTORE_DAILY_BRIEF_GROUND_MAX_CHARS", "8000")
    pack = tmp_path / "yuangon" / "quality-and-docs" / "employee-interview-assistant"
    pack.mkdir(parents=True)
    (pack / "README.md").write_text("# Interview assistant\nscope: meta\n", encoding="utf-8")
    (pack / "employee.yaml").write_text("id: employee-interview-assistant\n", encoding="utf-8")

    body, warns = collect_yuangon_pack_excerpt("employee-interview-assistant")
    assert "Interview assistant" in body
    assert "employee-interview-assistant" in body
    assert not warns


def test_collect_warns_when_pack_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MODSTORE_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("MODSTORE_DAILY_BRIEF_GROUND_YUANGON", "1")
    body, warns = collect_yuangon_pack_excerpt("employee-interview-assistant")
    assert body == ""
    assert warns and "未找到本岗仓库目录" in warns[0]


def test_daily_brief_task_text_strict_toggle(monkeypatch) -> None:
    monkeypatch.delenv("MODSTORE_DAILY_BRIEF_STRICT_GROUNDING", raising=False)
    assert deb.daily_brief_task_text() == deb.DAILY_BRIEF_TASK
    monkeypatch.setenv("MODSTORE_DAILY_BRIEF_STRICT_GROUNDING", "1")
    assert deb.daily_brief_task_text() == deb.DAILY_BRIEF_TASK_STRICT
    assert "**依据**" in deb.DAILY_BRIEF_TASK_STRICT


def test_daily_brief_prompts_include_todo_heading() -> None:
    assert "## 待办任务" in deb.DAILY_BRIEF_TASK
    assert "## 待办任务" in deb.DAILY_BRIEF_TASK_STRICT


def test_split_brief_markdown_extracts_todos() -> None:
    src = """## 工作内容摘要\nHello.\n## 待办任务\n1. First task\n2. Second\n## 风险或依赖（可选）\nNone.\n"""
    main, todos = deb.split_brief_markdown(src)
    assert "First task" in todos
    assert "## 风险或依赖" in main
    assert "待办任务" not in main


def test_collect_includes_prompts_tasks_and_extra_glob(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MODSTORE_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("MODSTORE_DAILY_BRIEF_GROUND_YUANGON", "1")
    monkeypatch.setenv("MODSTORE_DAILY_BRIEF_GROUND_MAX_CHARS", "16000")
    monkeypatch.setenv(
        "MODSTORE_DAILY_BRIEF_EXTRA_GLOBS_JSON",
        '{"employee-interview-assistant":["docs/*.md"]}',
    )
    pack = tmp_path / "yuangon" / "quality-and-docs" / "employee-interview-assistant"
    (pack / "prompts").mkdir(parents=True)
    (pack / "tasks").mkdir(parents=True)
    (pack / "docs").mkdir(parents=True)
    (pack / "README.md").write_text("# root readme\n", encoding="utf-8")
    (pack / "prompts" / "extra.md").write_text("extra prompt line\n", encoding="utf-8")
    (pack / "tasks" / "example-input.json").write_text('{"task":"seed"}\n', encoding="utf-8")
    (pack / "docs" / "more.md").write_text("from extra glob\n", encoding="utf-8")

    body, warns = collect_yuangon_pack_excerpt("employee-interview-assistant")
    assert "extra prompt line" in body
    assert "task" in body
    assert "from extra glob" in body
    assert not warns


def test_collect_resolves_when_repo_root_points_to_modstore_deploy(
    monkeypatch, tmp_path: Path
) -> None:
    monorepo = tmp_path / "repo-root"
    (monorepo / "MODstore_deploy").mkdir(parents=True)
    pack = monorepo / "yuangon" / "quality-and-docs" / "employee-interview-assistant"
    pack.mkdir(parents=True)
    (pack / "README.md").write_text("grounded by sibling yuangon\n", encoding="utf-8")

    monkeypatch.setenv("MODSTORE_REPO_ROOT", str(monorepo / "MODstore_deploy"))
    monkeypatch.setenv("MODSTORE_DAILY_BRIEF_GROUND_YUANGON", "1")

    body, warns = collect_yuangon_pack_excerpt("employee-interview-assistant")
    assert "grounded by sibling yuangon" in body
    assert str(monorepo) in body
    assert not warns
