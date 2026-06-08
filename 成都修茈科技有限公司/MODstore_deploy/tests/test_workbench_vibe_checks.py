"""Tests for the _check_vibe_coding_capability helper in workbench_api.

These tests verify that the employee mod_sandbox checks surface genuine
'怎么做' gaps (hollow system prompts, missing business logic) and correctly
report vibe_code ESkill counts from the workflow attachment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def _emp_dir(pack_dir: Path) -> Path:
    d = pack_dir / "backend" / "employees"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_py(emp_dir: Path, name: str, content: str) -> None:
    (emp_dir / name).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Import helper (lazy, so missing modstore doesn't break collection)
# ---------------------------------------------------------------------------


def _get_checker():
    from modstore_server.workbench_api import _check_vibe_coding_capability

    return _check_vibe_coding_capability


# ---------------------------------------------------------------------------
# 1. vibe_logic_present check
# ---------------------------------------------------------------------------


def test_vibe_logic_present_no_workflow(tmp_path):
    check = _get_checker()
    results = check(tmp_path, {})
    ids = {r["id"]: r for r in results}
    assert "vibe_logic_present" in ids
    assert "跳过" in ids["vibe_logic_present"]["message"]


def test_vibe_logic_present_with_eskill(tmp_path):
    check = _get_checker()
    wf_attach = {"workflow_id": 5, "eskill_count": 3, "nl": {"ok": True}}
    results = check(tmp_path, wf_attach)
    ids = {r["id"]: r for r in results}
    assert "3" in ids["vibe_logic_present"]["message"]


# ---------------------------------------------------------------------------
# 2. system_prompt_quality check
# ---------------------------------------------------------------------------


def test_system_prompt_hollow_flagged(tmp_path):
    emp_dir = _emp_dir(tmp_path)
    _write_py(
        emp_dir,
        "hollow_agent.py",
        "import json\n"
        "from typing import Any, Dict\n\n"
        'SYSTEM_PROMPT = "请根据用户输入完成任务"\n\n'
        "async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:\n"
        '    return {"ok": True}\n',
    )
    check = _get_checker()
    results = check(tmp_path, {"workflow_id": 1, "eskill_count": 1})
    ids = {r["id"]: r for r in results}
    assert ids["vibe_system_prompt_quality"]["ok"] is False
    assert "hollow_agent.py" in ids["vibe_system_prompt_quality"]["message"]


def test_system_prompt_missing_flagged(tmp_path):
    emp_dir = _emp_dir(tmp_path)
    _write_py(
        emp_dir,
        "no_prompt.py",
        "import json\nfrom typing import Any, Dict\n\n"
        "async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:\n"
        "    result = await ctx['call_llm']([{'role': 'user', 'content': 'hi'}])\n"
        "    return {'ok': True}\n",
    )
    check = _get_checker()
    results = check(tmp_path, {"workflow_id": 1, "eskill_count": 1})
    ids = {r["id"]: r for r in results}
    assert ids["vibe_system_prompt_quality"]["ok"] is False
    assert "no_prompt.py" in ids["vibe_system_prompt_quality"]["message"]


def test_system_prompt_meaningful_passes(tmp_path):
    emp_dir = _emp_dir(tmp_path)
    _write_py(
        emp_dir,
        "good_agent.py",
        "import json\n"
        "from typing import Any, Dict\n\n"
        'SYSTEM_PROMPT = """\n'
        "你是项目文档助手。根据传入的 project_analysis 字典生成 README。\n"
        "必须包含技术栈、安装步骤、开发命令。禁止编造内容。\n"
        '"""\n\n'
        "async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:\n"
        "    pa = payload.get('project_analysis') or {}\n"
        "    tech = pa.get('tech_stack', [])\n"
        "    manifests = pa.get('manifests', {})\n"
        "    pkg = manifests.get('package.json') or {}\n"
        "    scripts = pkg.get('scripts', {})\n"
        "    prompt = f'Tech: {tech}  Scripts: {scripts}'\n"
        "    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': prompt}]\n"
        "    result = await ctx['call_llm'](messages)\n"
        "    return {'readme': result.get('content', ''), 'ok': result.get('ok', False)}\n",
    )
    check = _get_checker()
    results = check(tmp_path, {"workflow_id": 1, "eskill_count": 1})
    ids = {r["id"]: r for r in results}
    assert ids["vibe_system_prompt_quality"]["ok"] is True


# ---------------------------------------------------------------------------
# 3. how_to_do_logic check
# ---------------------------------------------------------------------------


def test_how_to_do_thin_impl_flagged(tmp_path):
    """A file that only calls call_llm without any extraction steps should be flagged."""
    emp_dir = _emp_dir(tmp_path)
    thin_src = (
        "import json\n"
        "from typing import Any, Dict\n\n"
        'SYSTEM_PROMPT = "你是助手，请完成用户任务。分析项目结构并生成文档。"\n\n'
        "async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:\n"
        "    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}, "
        "{'role': 'user', 'content': json.dumps(payload)}]\n"
        "    result = await ctx['call_llm'](messages)\n"
        "    return {'output': result.get('content', ''), 'ok': result.get('ok', False)}\n"
    )
    _write_py(emp_dir, "thin_agent.py", thin_src)
    check = _get_checker()
    results = check(tmp_path, {"workflow_id": 1, "eskill_count": 1})
    ids = {r["id"]: r for r in results}
    assert ids["vibe_how_to_do_logic"]["ok"] is False
    assert "thin_agent.py" in ids["vibe_how_to_do_logic"]["message"]


def test_how_to_do_rich_impl_passes(tmp_path):
    """An employee file with dict/list extraction before call_llm should pass."""
    emp_dir = _emp_dir(tmp_path)
    rich_src = (
        "import json, os, glob\n"
        "from typing import Any, Dict\n\n"
        'SYSTEM_PROMPT = "你是项目文档生成助手。根据传入的项目摘要生成 README。"\n\n'
        "async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:\n"
        "    pa = payload.get('project_analysis') or {}\n"
        "    tech = pa.get('tech_stack', [])\n"
        "    manifests = pa.get('manifests', {})\n"
        "    pkg = manifests.get('package.json') or {}\n"
        "    scripts = {k: v for k, v in pkg.get('scripts', {}).items()}\n"
        "    summary = f'Tech: {tech}; Scripts: {list(scripts.items())[:5]}'\n"
        "    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': summary}]\n"
        "    result = await ctx['call_llm'](messages)\n"
        "    return {'readme': result.get('content', ''), 'ok': result.get('ok', False)}\n"
    )
    _write_py(emp_dir, "rich_agent.py", rich_src)
    check = _get_checker()
    results = check(tmp_path, {"workflow_id": 1, "eskill_count": 1})
    ids = {r["id"]: r for r in results}
    assert ids["vibe_how_to_do_logic"]["ok"] is True


def test_no_employees_dir_all_checks_pass(tmp_path):
    """No backend/employees directory means checks are skipped (pass)."""
    check = _get_checker()
    results = check(tmp_path, {"workflow_id": 1, "eskill_count": 1})
    ids = {r["id"]: r for r in results}
    assert ids.get("vibe_system_prompt_quality", {}).get("ok") is True
    assert ids.get("vibe_how_to_do_logic", {}).get("ok") is True
