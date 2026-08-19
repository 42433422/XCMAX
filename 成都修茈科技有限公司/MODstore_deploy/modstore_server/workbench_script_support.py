# ruff: noqa
"""Script generation, repair, validation, and fallback helpers."""
from __future__ import annotations
import ast
import importlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional
from sqlalchemy.orm import Session

logger = logging.getLogger("modstore_server.workbench_script_runner")


def _facade():
    return importlib.import_module("modstore_server.workbench_script_runner")


def _fallback_script() -> str:
    """LLM 不可用时的兜底脚本：把 inputs 下的 xlsx 汇总到 outputs/处理结果.xlsx。

    依赖 ``openpyxl``（已在默认 allowlist），不调 ``modstore_runtime`` SDK，
    保证即使没有 LLM key 也能产出可下载结果。
    """
    return '\nfrom pathlib import Path\nfrom openpyxl import Workbook, load_workbook\n\ninput_dir = Path("inputs")\noutput_dir = Path("outputs")\noutput_dir.mkdir(exist_ok=True)\n\nout = Workbook()\nsummary = out.active\nsummary.title = "处理说明"\nsummary.append(["说明", "已读取上传文件，生成汇总预览。请在工作台中补充更具体规则后可再次执行。"])\nsummary.append(["输入文件数", len(list(input_dir.iterdir()))])\n\nfor file in input_dir.iterdir():\n    if file.suffix.lower() != ".xlsx":\n        continue\n    wb = load_workbook(file, data_only=False)\n    for ws in wb.worksheets:\n        title = (file.stem + "_" + ws.title)[:31]\n        sheet = out.create_sheet(title)\n        for r_idx, row in enumerate(ws.iter_rows(values_only=False), start=1):\n            if r_idx > 80:\n                break\n            for c_idx, cell in enumerate(row, start=1):\n                if c_idx > 40:\n                    break\n                sheet.cell(r_idx, c_idx).value = cell.value\n\nout.save(output_dir / "处理结果.xlsx")\nprint("已生成 outputs/处理结果.xlsx")\n'


def _extract_code(text: str) -> str:
    return _facade().extract_code_block(text or "", lang="python")


def _looks_like_non_python(code: str) -> bool:
    text = (code or "").strip()
    if not text:
        return True
    try:
        ast.parse(text)
        return False
    except SyntaxError:
        first = text.splitlines()[0] if text.splitlines() else text
        has_py_marker = any(
            (token in text for token in ("import ", "from ", "def ", "class ", "Path(", "open("))
        )
        has_cjk = bool(re.search("[\\u4e00-\\u9fff]", first))
        return has_cjk and (not has_py_marker)


def validate_script(code: str) -> List[str]:
    """兼容旧签名：仅返回错误列表。底层用 ``static_checker``。"""
    return _facade()._validate(code)


def _ensure_script_outputs_fallback(code: str, brief: str) -> str:
    """Ensure generated code is a runnable script that always writes outputs.

    Models sometimes return only helper functions/classes.  That can pass
    static checks and exit with code 0, but produces no files, causing the
    workbench handoff to loop forever.  Appending this guarded entrypoint keeps
    good business code intact while guaranteeing a minimal summary artifact.
    """
    src = (code or "").strip()
    if not src:
        return src
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    has_main_guard = any(
        (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and (node.test.left.id == "__name__")
            for node in tree.body
        )
    )
    mentions_outputs = "outputs" in src
    writes_file = any(
        (
            isinstance(node, ast.Call)
            and (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"write_text", "write_bytes", "open", "save", "dump"}
                or (isinstance(node.func, ast.Name) and node.func.id == "open")
            )
            for node in ast.walk(tree)
        )
    )
    if has_main_guard and mentions_outputs and writes_file:
        return src
    brief_text = json.dumps((brief or "").strip()[:1200], ensure_ascii=False)
    wrapper = f'\n\n# --- MODstore artifact guard: ensure at least one outputs/ file exists ---\ndef _modstore_artifact_guard():\n    from pathlib import Path\n    output_dir = Path("outputs")\n    output_dir.mkdir(exist_ok=True)\n    if any(p.is_file() for p in output_dir.iterdir()):\n        return\n    brief = {brief_text}\n    summary = [\n        "# 脚本运行摘要",\n        "",\n        "本次脚本未生成业务产物，系统已自动写入兜底说明，避免流程卡死。",\n        "",\n        "## 用户需求",\n        brief or "(未提供)",\n        "",\n        "## 下一步",\n        "- 请补充输入文件，或在工作台中完善具体规则。",\n        "- 脚本应在 outputs/ 下生成 summary.md、diff.md 或处理结果文件。",\n    ]\n    (output_dir / "summary.md").write_text("\\n".join(summary), encoding="utf-8")\n    print("已生成 outputs/summary.md")\n\n\nif __name__ == "__main__":\n    _modstore_artifact_guard()\n'
    return src.rstrip() + "\n" + wrapper


def _materialize_fallback_output(
    *, work_dir: str, brief: str, reason: str, script: str = ""
) -> List[Dict[str, Any]]:
    """Write a minimal ``outputs/summary.md`` into an existing sandbox dir.

    Used only when the agent exhausted repair rounds after a successful run
    produced no files.  It turns a non-actionable "no outputs" terminal state
    into a downloadable diagnostic artifact so the employee-pack flow can
    continue and the user can inspect what happened.
    """
    if not work_dir:
        return []
    try:
        output_dir = Path(work_dir) / "outputs"
        output_dir.mkdir(exist_ok=True)
        out = output_dir / "summary.md"
        if not out.exists():
            out.write_text(
                "\n".join(
                    [
                        "# 脚本运行摘要",
                        "",
                        "脚本代理未生成业务产物，系统已写入兜底说明文件。",
                        "",
                        "## 用户需求",
                        (brief or "").strip() or "(未提供)",
                        "",
                        "## 失败原因",
                        reason or "(未知)",
                        "",
                        "## 脚本摘录",
                        "```python",
                        (script or "")[:4000],
                        "```",
                    ]
                ),
                encoding="utf-8",
            )
        return [{"filename": out.name, "path": str(out), "size": out.stat().st_size}]
    except Exception:
        return []


class _ScriptGenResult(NamedTuple):
    code: str
    errors: List[str]


async def _generate_script(
    *,
    db: Optional[Session],
    user_id: int,
    brief: str,
    input_files: List[Path],
    provider: Optional[str],
    model: Optional[str],
    system_hint: str = "",
    upload_items: Optional[List[Dict[str, Any]]] = None,
) -> _ScriptGenResult:
    if db is None or not (provider or "").strip() or (not (model or "").strip()):
        if db is not None and (not (provider or "").strip() or not (model or "").strip()):
            _facade().logger.info(
                "_generate_script: provider/model missing, auto-resolving for user=%s", user_id
            )
            try:
                from modstore_server.llm_api import resolve_default_llm_route

                resolved = await resolve_default_llm_route(db, user_id)
                if not (provider or "").strip():
                    provider = str(resolved.get("provider") or "").strip() or provider
                if not (model or "").strip():
                    model = str(resolved.get("model") or "").strip() or model
                _facade().logger.info(
                    "_generate_script: auto-resolved provider=%r model=%r", provider, model
                )
            except Exception:
                _facade().logger.warning(
                    "_generate_script: auto-resolve failed for user=%s", user_id, exc_info=True
                )
    if db is None or not (provider or "").strip() or (not (model or "").strip()):
        _facade().logger.warning(
            "_generate_script: no provider/model available — db=%s provider=%r model=%r user=%s",
            type(db).__name__ if db is not None else None,
            provider,
            model,
            user_id,
        )
        return _facade()._ScriptGenResult(
            "",
            ["请配置 LLM 供应商与模型（工作台自选或用户默认 LLM 设置），否则无法使用 AI 生成脚本"],
        )
    (key, _src) = _facade().resolve_api_key(db, user_id, provider)
    if not key:
        return _facade()._ScriptGenResult(
            "", ["该供应商未配置可用 API Key（平台或 BYOK），无法调用 AI 生成脚本"]
        )
    base = _facade().resolve_base_url(db, user_id, provider)
    files_text = "\n".join((f"- {p.name}" for p in input_files))
    hint = (system_hint or "").strip()
    sys_prompt = "你是 Python 数据处理脚本生成器。请仅返回一个 ```python``` 代码块，不要任何解释。\n脚本运行目录包含 inputs/ 与 outputs/。只能读 inputs/，只能写 outputs/。\n可使用 Python 标准库与已审核的第三方库（openpyxl、docx/python-docx、zipfile、xml.etree）。禁止调用 subprocess、ctypes、网络 socket、删除目录、eval/exec。\n如需调 LLM/知识库/员工，使用 `from modstore_runtime import ai, kb_search, employee_run`。\n脚本必须无条件（unconditionally）在 outputs/ 下写至少一个结果文件，并 print 一行进度。\n即使 inputs/ 为空或没有任何文件，也要写一个 outputs/readme.md 说明脚本能力与期望输入；\n写输出是强制要求，不能只 print，不能放在 if 分支里跳过。"
    if hint:
        sys_prompt += "\n\n员工一站式规划约束：\n" + hint[:4000]
    user_prompt = f"任务:\n{brief}\n\n输入文件:\n{files_text or '（当前没有上传文件，请生成可空跑的模板脚本）'}\n\n请输出 script.py 完整内容。"
    csv_hint = _facade().tabular_upload_preview(upload_items or [])
    if csv_hint:
        user_prompt += "\n\n" + csv_hint
    res = await _facade().chat_dispatch(
        provider,
        api_key=key,
        base_url=base,
        model=model,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=6144,
        forbid_reasoning_fallback=True,
    )
    if not res.get("ok"):
        err = str(res.get("error") or "").strip() or "LLM 调用失败"
        return _facade()._ScriptGenResult("", [f"LLM 调用失败：{err[:800]}"])
    code = _facade()._extract_code(str(res.get("content") or ""))
    if not code.strip():
        return _facade()._ScriptGenResult("", ["模型未返回有效 Python 代码（解析后为空）"])
    if _facade()._looks_like_non_python(code):
        return _facade()._ScriptGenResult(
            code,
            ["模型未按要求返回 Python 代码，而是返回了说明文字；请重试或切换更适合代码生成的模型"],
        )
    return _facade()._ScriptGenResult(_facade()._ensure_script_outputs_fallback(code, brief), [])


async def _repair_script_once(
    *,
    provider: Optional[str],
    model: Optional[str],
    api_key: str,
    base_url: Optional[str],
    brief: str,
    code: str,
    errors: List[str],
    failure_context: str = "",
    system_hint: str = "",
    upload_items: Optional[List[Dict[str, Any]]] = None,
) -> _ScriptGenResult:
    """Ask the LLM for one deterministic repair pass after static check errors."""
    err_text = "\n".join((f"- {e}" for e in errors))[:3000]
    if failure_context.strip():
        err_text = (err_text + "\n\n" + failure_context.strip())[:5000]
    hint = (system_hint or "").strip()
    sys_prompt = "你是 Python 脚本修复器。请仅返回一个 ```python``` 代码块，不要任何解释或 Markdown 说明。\n保持原任务目标不变。脚本运行目录包含 inputs/ 与 outputs/；只能读 inputs/，只能写 outputs/。\n禁止 subprocess、ctypes、网络 socket、删除目录、eval/exec。"
    if hint:
        sys_prompt += "\n\n员工一站式规划约束：\n" + hint[:3000]
    user_prompt = f"任务:\n{brief}\n\n失败信息:\n{err_text}\n\n原始代码:\n```python\n{code[:12000]}\n```\n\n请输出修复后的 script.py 完整内容。"
    csv_hint = _facade().tabular_upload_preview(upload_items or [])
    if csv_hint:
        user_prompt += "\n\n" + csv_hint
    res = await _facade().chat_dispatch(
        provider or "",
        api_key=api_key,
        base_url=base_url,
        model=model or "",
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=6144,
        forbid_reasoning_fallback=True,
    )
    if not res.get("ok"):
        err = str(res.get("error") or "").strip() or "LLM 修复调用失败"
        return _facade()._ScriptGenResult("", [f"LLM 修复调用失败：{err[:800]}"])
    repaired = _facade()._extract_code(str(res.get("content") or ""))
    if not repaired.strip():
        return _facade()._ScriptGenResult("", ["模型修复后未返回有效 Python 代码（解析后为空）"])
    if _facade()._looks_like_non_python(repaired):
        return _facade()._ScriptGenResult(
            repaired,
            [
                "模型修复时仍未返回 Python 代码，而是返回了说明文字；请重试或切换更适合代码生成的模型"
            ],
        )
    return _facade()._ScriptGenResult(
        _facade()._ensure_script_outputs_fallback(repaired, brief), []
    )
