"""Helpers for vibe_heal + SYSTEM_PROMPT alignment on employee .py files."""

from __future__ import annotations

from modstore_server.mod_employee_impl_scaffold import _employee_py_paths_missing_system_prompt


def test_missing_system_prompt_paths_detected(tmp_path):
    emp_dir = tmp_path / "backend" / "employees"
    emp_dir.mkdir(parents=True)
    (emp_dir / "no_prompt.py").write_text(
        "async def run(payload, ctx):\n    return {}\n",
        encoding="utf-8",
    )
    (emp_dir / "has_prompt.py").write_text(
        'SYSTEM_PROMPT = "你是助手"\n' "async def run(payload, ctx):\n    return {}\n",
        encoding="utf-8",
    )
    employees = [{"id": "no_prompt"}, {"id": "has_prompt"}]
    missing = _employee_py_paths_missing_system_prompt(tmp_path, employees)
    assert "backend/employees/no_prompt.py" in missing
    assert "backend/employees/has_prompt.py" not in missing


def test_extra_employee_file_missing_system_prompt_detected(tmp_path):
    emp_dir = tmp_path / "backend" / "employees"
    emp_dir.mkdir(parents=True)
    (emp_dir / "manifest_employee.py").write_text(
        'SYSTEM_PROMPT = "你是员工，请读取 payload 字段并生成结构化摘要。"\n'
        "async def run(payload, ctx):\n    return {}\n",
        encoding="utf-8",
    )
    (emp_dir / "brief_assistant.py").write_text(
        "async def run(payload, ctx):\n"
        "    result = await ctx['call_llm']([{'role': 'user', 'content': 'hi'}])\n"
        "    return result\n",
        encoding="utf-8",
    )
    employees = [{"id": "manifest_employee"}]
    missing = _employee_py_paths_missing_system_prompt(tmp_path, employees)
    assert "backend/employees/brief_assistant.py" in missing


def test_hollow_system_prompt_paths_detected_for_heal(tmp_path):
    emp_dir = tmp_path / "backend" / "employees"
    emp_dir.mkdir(parents=True)
    (emp_dir / "brief_assistant.py").write_text(
        'SYSTEM_PROMPT = "请根据用户输入完成任务"\n'
        "async def run(payload, ctx):\n    return {}\n",
        encoding="utf-8",
    )
    missing = _employee_py_paths_missing_system_prompt(tmp_path, [])
    assert "backend/employees/brief_assistant.py" in missing
