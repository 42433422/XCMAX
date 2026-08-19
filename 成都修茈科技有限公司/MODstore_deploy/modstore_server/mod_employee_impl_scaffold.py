"""为「做 Mod」生成的每名 workflow_employee 生成可执行 Python 实现。

产物写到 ``backend/employees/<safe_id>.py``，由 ``render_suite_blueprints_py``
通过 FHD 宿主 ``app.mod_sdk.mods_bus.import_mod_backend_py`` 加载并调度。

对每名员工单独调 LLM 一次；生成后立刻 ``py_compile``，不通过则一次修复重试。
不依赖外部凭证；允许模块内使用 ``ctx["call_llm"]`` / ``ctx["http_get"]`` 等由
host 注入的最小运行时（见 ``render_suite_blueprints_py`` 里的 build_run_context）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modstore_server.models import User

from modstore_server.mod_employee_impl_generation import (
    SYSTEM_PROMPT_EMPLOYEE_IMPL as SYSTEM_PROMPT_EMPLOYEE_IMPL,
    SYSTEM_PROMPT_EMPLOYEE_IMPL_REPAIR as SYSTEM_PROMPT_EMPLOYEE_IMPL_REPAIR,
    _behavior_check as _behavior_check,
    _compile_check as _compile_check,
    _employee_brief_lines as _employee_brief_lines,
    _fallback_employee_py as _fallback_employee_py,
    _generate_one_employee_py as _generate_one_employee_py,
    _security_check as _security_check,
    _strip_code_fence as _strip_code_fence,
    generate_mod_employee_impls_async as generate_mod_employee_impls_async,
    sanitize_employee_stem as sanitize_employee_stem,
)


_HOLLOW_SYSTEM_PROMPT_PATTERNS = (
    re.compile(r'SYSTEM_PROMPT\s*=\s*["\'].*请根据用户输入完成任务.*["\']'),
    # Exactly empty string: "" or '' - avoid matching triple quotes.
    re.compile(r'SYSTEM_PROMPT\s*=\s*["\']["\'](?!["\'])'),
)


def employee_py_system_prompt_gaps(emp_dir: Path) -> Dict[str, List[str]]:
    """Return employee files missing or hollow ``SYSTEM_PROMPT`` constants."""
    gaps: Dict[str, List[str]] = {"missing": [], "hollow": []}
    if not emp_dir.is_dir():
        return gaps

    for py_file in sorted(emp_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        try:
            src = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not re.search(r"(?m)^\s*SYSTEM_PROMPT\s*=", src):
            gaps["missing"].append(py_file.name)
        elif any(pat.search(src) for pat in _HOLLOW_SYSTEM_PROMPT_PATTERNS):
            gaps["hollow"].append(py_file.name)
    return gaps


def _employee_py_paths_needing_system_prompt(
    mod_dir: Path,
    employees: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """Relative paths under mod_dir for employee modules missing a useful prompt.

    Prefer scanning the whole generated employee directory because workflow/vibe
    generators can add helper employees that are not present in the manifest's
    ``employees`` list (for example ``brief_assistant.py``).
    """
    emp_dir = mod_dir / "backend" / "employees"
    if not emp_dir.is_dir():
        return []
    expected_stems = set()
    for e in employees or []:
        if not isinstance(e, dict):
            continue
        eid = str(e.get("id") or "").strip()
        if not eid:
            continue
        expected_stems.add(sanitize_employee_stem(eid))

    paths = [p for p in emp_dir.glob("*.py") if not p.name.startswith("__")]
    if expected_stems:
        by_name = {p.stem: p for p in paths}
        ordered = [by_name[stem] for stem in sorted(expected_stems) if stem in by_name]
        ordered.extend(sorted(p for p in paths if p.stem not in expected_stems))
        paths = ordered
    else:
        paths = sorted(paths)

    gaps = employee_py_system_prompt_gaps(emp_dir)
    needing = set(gaps["missing"]) | set(gaps["hollow"])
    return [f"backend/employees/{p.name}" for p in paths if p.name in needing]


def _employee_py_paths_missing_system_prompt(
    mod_dir: Path,
    employees: List[Dict[str, Any]],
) -> List[str]:
    """Backward-compatible alias for tests/imports; includes hollow prompts too."""
    return _employee_py_paths_needing_system_prompt(mod_dir, employees)


def _vibe_heal_mod_employees(
    db: Session,
    user: User,
    *,
    mod_dir: Path,
    mod_id: str,
    employees: List[Dict[str, Any]],
    provider: str,
    model: str,
) -> Dict[str, Any]:
    """同步辅助:把 vibe-coding 的 ``ProjectVibeCoder.heal_project`` 跑一轮。

    失败 / 缺依赖时静默降级,把 reason 记到返回值,不会让员工脚本生成整体失败。
    PatchLedger 自动记录补丁链,后续 ``ModAuthoringView`` 沙盒报告会通过
    ``ai_blueprint.sandbox_report`` 读到这一段。

    自愈 brief 强制要求模块级 ``SYSTEM_PROMPT``（与宿主 agent_runner / 工作台
    vibe 检查对齐）；若首轮后仍缺失则追加一轮针对缺失文件的 heal。
    """
    try:
        from modstore_server.integrations.vibe_adapter import (
            VibeIntegrationError,
            get_project_vibe_coder,
            heal_result_to_dict,
        )
    except ImportError as exc:  # pragma: no cover
        return {"enabled": False, "reason": f"integrations 未导入: {exc}"}

    try:
        coder = get_project_vibe_coder(
            mod_dir,
            session=db,
            user_id=user.id,
            provider=provider,
            model=model,
        )
    except VibeIntegrationError as exc:
        return {"enabled": False, "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"enabled": False, "reason": f"vibe coder 构造失败: {exc}"}

    employee_paths = [
        f"backend/employees/{sanitize_employee_stem(str(e.get('id') or ''))}.py"
        for e in employees
        if isinstance(e, dict) and str(e.get("id") or "").strip()
    ]
    paths_hint = ", ".join(employee_paths[:6]) if employee_paths else "backend/employees/*.py"
    brief = (
        f"对 mod={mod_id} 的员工实现（{paths_hint}）做最小自愈，遵守 FHD app.mod_sdk 边界。\n"
        "1) 修复语法错误、补缺失 import；保留 async def run(payload, ctx) 签名。\n"
        '2) 每个 backend/employees/*.py 必须在模块顶层定义 SYSTEM_PROMPT = "..." 或三引号字符串，'
        "写清：员工角色与边界、3–7 步执行流程、何时用 ctx 工具（read_workspace_file/call_llm 等）、"
        "输出格式、禁止编造数据。禁止空字符串、禁止仅写「请根据用户输入完成任务」。\n"
        "3) 不要新增/删除文件，不要改 manifest.json。"
    )
    passes_out: List[Dict[str, Any]] = []
    total_rounds = 0
    last_ok = True
    try:
        result = coder.heal_project(brief, max_rounds=3)
        total_rounds += int(getattr(result, "rounds", 0) or 0)
        last_ok = bool(getattr(result, "ok", True))
        passes_out.append(heal_result_to_dict(result))

        missing_sp = _employee_py_paths_needing_system_prompt(mod_dir, employees)
        if missing_sp:
            brief_sp = (
                "第二轮（仅补 SYSTEM_PROMPT）：以下文件缺少模块级 SYSTEM_PROMPT = 常量，"
                "或内容为空洞占位。请在每个文件中补充/改写为非空 str，满足 agent_runner 可用的角色与步骤指引。\n"
                + "\n".join(f"- {rel}" for rel in missing_sp[:12])
            )
            try:
                result2 = coder.heal_project(brief_sp, max_rounds=2)
                total_rounds += int(getattr(result2, "rounds", 0) or 0)
                last_ok = last_ok and bool(getattr(result2, "ok", True))
                passes_out.append(heal_result_to_dict(result2))
            except Exception as exc2:  # noqa: BLE001
                passes_out.append({"error": f"第二轮 SYSTEM_PROMPT heal 失败: {exc2}"})
                last_ok = False

        gap_after = _employee_py_paths_needing_system_prompt(mod_dir, employees)
        return {
            "enabled": True,
            "ok": last_ok,
            "rounds": total_rounds,
            "result": passes_out[-1] if passes_out else {},
            "passes": passes_out,
            "system_prompt_still_missing": gap_after,
        }
    except Exception as exc:  # noqa: BLE001
        return {"enabled": True, "ok": False, "reason": f"heal_project 失败: {exc}"}
