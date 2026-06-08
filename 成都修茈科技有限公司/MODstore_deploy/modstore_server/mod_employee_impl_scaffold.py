"""为「做 Mod」生成的每名 workflow_employee 生成可执行 Python 实现。

产物写到 ``backend/employees/<safe_id>.py``，由 ``render_suite_blueprints_py``
通过 FHD 宿主 ``app.mod_sdk.mods_bus.import_mod_backend_py`` 加载并调度。

对每名员工单独调 LLM 一次；生成后立刻 ``py_compile``，不通过则一次修复重试。
不依赖外部凭证；允许模块内使用 ``ctx["call_llm"]`` / ``ctx["http_get"]`` 等由
host 注入的最小运行时（见 ``render_suite_blueprints_py`` 里的 build_run_context）。
"""

from __future__ import annotations

import ast
import asyncio
import json
import py_compile
import re
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modstore_server.llm_chat_proxy import chat_dispatch
from modstore_server.llm_key_resolver import (
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    resolve_api_key,
    resolve_base_url,
)
from modstore_server.models import User
from modstore_server.script_agent.llm_output_sanitize import finalize_extracted_python
from modstore_server.script_agent.semantic_quality import oversized_string_literal_errors_for_source

_SAFE_ID_RE = re.compile(r"[^a-z0-9_]")

_MAX_CONCURRENT_LLM = 3
_MAX_REPAIR_ATTEMPTS = 2

_FORBIDDEN_IMPORTS = frozenset(
    {
        "os",
        "subprocess",
        "shutil",
        "sys",
        "pathlib",
        "socket",
        "ctypes",
        "multiprocessing",
        "threading",
        "signal",
        "resource",
        "fcntl",
        "mmap",
    }
)
_FORBIDDEN_ATTRS = frozenset(
    {
        "system",
        "popen",
        "exec",
        "eval",
        "compile",
        "__import__",
        "open",
    }
)
_ALLOWED_MOD_SDK_PREFIX = "app.mod_sdk."


def sanitize_employee_stem(emp_id: str) -> str:
    """与 ``workflow_employee_scaffold._sanitize_py_module`` 同规则，便于沙箱共存。"""
    s = _SAFE_ID_RE.sub("_", (emp_id or "").strip().lower())
    if s and s[0].isdigit():
        s = "e_" + s
    return s or "emp"


SYSTEM_PROMPT_EMPLOYEE_IMPL = """你是 XCAGI 工作台员工实现代码生成器。目标是生成一名**能真正执行工作**的 AI 员工（类似 Cursor/OpenClaw），而不是只会转发问题给 LLM 的对话机器人。

输出一个完整 Python 文件（UTF-8，不加 Markdown 围栏，不加解释），放到 backend/employees/<safe_id>.py，由宿主 FastAPI 动态加载。

═══════════════════════════════════════════════
一、可用 import
═══════════════════════════════════════════════
标准库：from __future__ import annotations / asyncio / json / os / glob / pathlib / logging / re / time / datetime / typing
可选：import httpx（仅当需要自行发起 HTTP 时；ctx 已内置 http_get/http_post 更推荐用 ctx）
FHD SDK：from app.mod_sdk.<子模块> import ...（仅限 mod_sdk 契约层；禁止 from app.routes/application/services）
禁止：相对 import、import *、硬编码密钥/手机号/身份证

═══════════════════════════════════════════════
二、ctx 能力字典（宿主注入，全部 async callable）
═══════════════════════════════════════════════
必有：
  ctx["call_llm"](messages, *, max_tokens, temperature) → {"ok":bool,"content":str,"error":str}
  ctx["http_get"](url, *, headers, timeout)              → {"ok":bool,"status":int,"text":str,"error":str}
  ctx["http_post"](url, *, json_body, headers, timeout)  → 同上
  ctx["mod_id"] / ctx["employee_id"] / ctx["logger"]
  ctx["workspace_root"]（str）                           → 员工专属工作区根目录

文件工具（在 workspace_root 内安全读写，越界自动拒绝）：
  ctx["read_workspace_file"](path)                       → {"ok":bool,"content":str,"truncated":bool,...}
  ctx["write_workspace_file"](path, content)             → {"ok":bool,"bytes_written":int,...}
  ctx["list_workspace_dir"](path=".")                    → {"ok":bool,"entries":[{name,type,size}],...}
  ctx["run_sandboxed_python"](code)                      → {"ok":bool,"stdout":str,"stderr":str,...}

Agent runner（内置 ReAct 循环，见第三条）：
  ctx["agent_runner"]                                    → EmployeeAgentRunner 实例，直接 await runner.run(task, system_prompt=...) 即可

可选：ctx.get("secrets") → None 或凭证 dict

═══════════════════════════════════════════════
三、ReAct Agent 模式（强烈推荐）
═══════════════════════════════════════════════
若员工需要多步执行（读文件 → 分析 → 写结果 / 搜索 → 提取 → 汇总 / 规划 → 执行 → 验证），
**直接使用 ctx["agent_runner"]**，无需自己实现循环：

    async def run(payload, ctx):
        runner = ctx.get("agent_runner")
        if runner is None:
            return {"ok": False, "error": "agent_runner 未注入，请升级宿主版本"}
        task = payload.get("task") or payload.get("message") or json.dumps(payload)[:1000]
        result = await runner.run(task, system_prompt=SYSTEM_PROMPT)
        return {
            "ok": result["ok"],
            "summary": result.get("summary") or result.get("error"),
            "rounds": result.get("rounds", 0),
            "tools_used": [t["tool"] for t in result.get("tool_calls", [])],
            "error": result.get("error") or "",
        }

agent runner 内置工具协议（LLM 需要输出此格式）：
  调用工具时：{"thought":"...","tool":"工具名","input":{参数}}
  给出答案时：{"thought":"...","answer":"最终结果"}

可用工具名：read_workspace_file / write_workspace_file / list_workspace_dir /
           run_sandboxed_python / http_get / http_post / call_llm

═══════════════════════════════════════════════
四、SYSTEM_PROMPT 常量（必须精心设计）
═══════════════════════════════════════════════
必须定义 SYSTEM_PROMPT 常量，用于 agent_runner 或直接 call_llm。
SYSTEM_PROMPT 必须写清楚：
  1. 员工角色与边界（是什么员工、能处理哪些任务、不能处理哪些）
  2. 工作步骤（给出 3-7 步具体执行流程，如：读配置 → 扫目录 → 分析 → 生成 → 写文件）
  3. 可使用的工具及调用时机（何时用 read_workspace_file，何时用 http_get 等）
  4. 输出格式要求（JSON / Markdown / 具体字段）
  5. 不确定时策略（如实告知缺少的信息，不编造）
  6. 禁止事项（禁止编造数据、禁止调用未声明的工具、禁止访问工作区外的文件）

禁止把 SYSTEM_PROMPT 写成"请根据用户输入完成任务"之类的空洞语句。

═══════════════════════════════════════════════
五、怎么做原则（不能跳过数据处理直奔 LLM）
═══════════════════════════════════════════════
  ✓ 读文件前先用 ctx["read_workspace_file"] 验证存在性，失败时返回有意义的错误
  ✓ 目录扫描后限制条目数（最多 50 项），提取关键字段再送给 LLM
  ✓ 从 package.json / pyproject.toml 抽取 name/version/dependencies/scripts 摘要，而非整文件
  ✓ HTTP 响应先解析 JSON / 提取关键段落，再送给 LLM 总结
  ✓ 多步任务用 agent_runner（或手写 for 循环）逐步推进，不要一次性把所有信息塞进一个超长 prompt
  ✗ 不要把整个 payload 直接 json.dumps 后扔给 LLM
  ✗ 不要在 run 里只写一个 call_llm 调用就返回

═══════════════════════════════════════════════
六、代码规范
═══════════════════════════════════════════════
  - 类型标注完整（Dict, List, Optional, Any 来自 typing）
  - 最多 ~250 行；复杂逻辑拆分辅助函数
  - 注释用简体中文，说明每段的实现思路
  - 异常 raise，由外层 blueprints 兜底（不要吞掉所有 Exception）
  - 输出必须能通过 py_compile 校验
  - 整个回复就是该 .py 的源代码本体（无围栏，无解释）

═══════════════════════════════════════════════
七、返回值 schema（async def run 的 return）
═══════════════════════════════════════════════
建议键（与 blueprints _ok/_err 对齐）：
  ok: bool
  summary: str     # 一句话人话结果
  items: list      # 数组明细（如生成的文件列表、搜索结果等）
  warnings: list   # 非致命问题
  error: str       # 失败时的错误描述

如果使用 agent_runner，可以直接把 runner.run() 的结果摊平返回（见第三条示例）。
"""


SYSTEM_PROMPT_EMPLOYEE_IMPL_REPAIR = """你是 Python 语法修复器。用户将给你一段被 ``py_compile`` 拒绝的源代码与错误信息。请只输出**修复后的完整 Python 文件**（UTF-8，不要 Markdown 围栏、不要解释）。保留原有 ``async def run(payload, ctx)`` 签名与业务逻辑，仅修正语法与引号/缩进问题。"""


def _employee_brief_lines(
    emp: Dict[str, Any],
    *,
    mod_id: str,
    mod_name: str,
    mod_brief: str,
    industry_card: Optional[Dict[str, Any]] = None,
) -> List[str]:
    eid = str(emp.get("id") or "").strip()
    label = str(emp.get("label") or emp.get("panel_title") or eid).strip()
    panel_title = str(emp.get("panel_title") or "").strip()
    panel_summary = str(emp.get("panel_summary") or "").strip()
    capabilities = emp.get("capabilities") if isinstance(emp.get("capabilities"), list) else []
    data_sources = emp.get("data_sources") if isinstance(emp.get("data_sources"), list) else []
    outputs = emp.get("outputs") if isinstance(emp.get("outputs"), list) else []
    wf = emp.get("workflow") if isinstance(emp.get("workflow"), dict) else {}
    wf_desc = str(wf.get("description") or "").strip()
    lines = [
        f"Mod id: {mod_id}",
        f"Mod 名称: {mod_name}",
        f"Mod 一句话: {mod_brief[:400]}",
    ]
    if industry_card:
        ind = str(industry_card.get("name") or industry_card.get("id") or "").strip()
        scen = str(industry_card.get("scenario") or "").strip()
        if ind:
            lines.append(f"行业/场景: {ind}; 说明: {scen[:240]}")
    lines.extend(
        [
            "",
            f"员工 id: {eid}",
            f"员工显示名: {label}",
            f"面板标题: {panel_title}",
            f"职责摘要: {panel_summary[:800]}",
        ]
    )
    if capabilities:
        lines.append(f"能力标识: {', '.join(str(x) for x in capabilities[:12])}")
    if data_sources:
        lines.append(f"数据源: {', '.join(str(x) for x in data_sources[:12])}")
    if outputs:
        lines.append(f"预期输出: {', '.join(str(x) for x in outputs[:12])}")
    if wf_desc:
        lines.append(f"所属工作流说明: {wf_desc[:800]}")
    lines.append("")
    lines.append(
        "请你基于以上画像实现 async def run(payload, ctx)。若画像信息不足以写出真实业务逻辑，"
        "请让 run 走「调用 ctx['call_llm'] 生成一段针对 payload 的结构化建议，并把模型输出作为 data」的兜底实现，"
        "但仍要按画像里的 panel_summary 调整 SYSTEM_PROMPT。"
    )
    return lines


def _security_check(src: str) -> Optional[str]:
    """AST 级安全审查。返回 None 表示通过；否则返回违规描述。"""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return f"语法错误: {e}"

    violations: List[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_mod = alias.name.split(".")[0]
                if root_mod in _FORBIDDEN_IMPORTS:
                    violations.append(f"禁止 import {alias.name}")

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_mod = node.module.split(".")[0]
                if root_mod in _FORBIDDEN_IMPORTS:
                    violations.append(f"禁止 from {node.module} import ...")
                if root_mod == "app" and not node.module.startswith(_ALLOWED_MOD_SDK_PREFIX):
                    violations.append(
                        f"仅允许 from app.mod_sdk.<子模块> import ...，禁止 from {node.module}"
                    )

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                attr_name = node.func.attr
                if attr_name in _FORBIDDEN_ATTRS:
                    violations.append(f"禁止调用 .{attr_name}()")

            if isinstance(node.func, ast.Name):
                if node.func.id in ("eval", "exec", "compile", "__import__"):
                    violations.append(f"禁止调用 {node.func.id}()")

    if violations:
        return "安全审查未通过: " + "; ".join(violations[:8])
    return None


def _behavior_check(src: str) -> Optional[str]:
    """行为校验：检查 run 函数是否存在且签名基本正确。"""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return f"语法错误: {e}"

    has_run = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run":
            has_run = True
            arg_names = [a.arg for a in node.args.args]
            if "payload" not in arg_names or "ctx" not in arg_names:
                return "run() 签名必须为 async def run(payload, ctx)"
            break

    if not has_run:
        return "缺少 async def run(payload, ctx) 函数定义"

    if not re.search(r"(?m)^\s*SYSTEM_PROMPT\s*=", src):
        return "缺少 SYSTEM_PROMPT 常量定义（宿主 agent_runner / call_llm 依赖模块级指引）"

    return None


def _compile_check(src: str) -> Optional[str]:
    """返回 None 表示通过；否则返回编译错误字符串。"""
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".py", delete=False, mode="w", encoding="utf-8"
        ) as fp:
            fp.write(src)
            tmp = Path(fp.name)
        try:
            py_compile.compile(str(tmp), doraise=True)
        finally:
            tmp.unlink(missing_ok=True)
        return None
    except py_compile.PyCompileError as e:
        return str(e.msg or e)
    except OSError as e:
        return str(e)


def _strip_code_fence(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:python|py)?\s*\n?", "", s, flags=re.I)
        s = re.sub(r"\n?```\s*$", "", s)
    return s.strip() + "\n"


async def _generate_one_employee_py(
    *,
    prov: str,
    api_key: str,
    base_url: Optional[str],
    model: str,
    emp: Dict[str, Any],
    mod_id: str,
    mod_name: str,
    mod_brief: str,
    industry_card: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    user_msg = "\n".join(
        _employee_brief_lines(
            emp,
            mod_id=mod_id,
            mod_name=mod_name,
            mod_brief=mod_brief,
            industry_card=industry_card,
        )
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_EMPLOYEE_IMPL},
        {"role": "user", "content": user_msg},
    ]
    res = await chat_dispatch(
        prov,
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        max_tokens=6000,
        forbid_reasoning_fallback=True,
    )
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error") or "upstream error"}
    raw_orig = finalize_extracted_python(_strip_code_fence(str(res.get("content") or "")))[0]
    current_source = raw_orig

    last_err: Optional[str] = None
    for attempt in range(_MAX_REPAIR_ATTEMPTS):
        noise_errs = oversized_string_literal_errors_for_source(current_source)
        err = noise_errs[0] if noise_errs else _compile_check(current_source)
        if not err:
            sec_err = _security_check(current_source)
            if sec_err:
                return {"ok": False, "error": sec_err, "raw": raw_orig}
            beh_err = _behavior_check(current_source)
            if beh_err:
                return {"ok": False, "error": beh_err, "raw": raw_orig}
            return {
                "ok": True,
                "source": current_source,
                "repair_used": attempt > 0,
            }

        last_err = err
        repair_messages = [
            {"role": "system", "content": SYSTEM_PROMPT_EMPLOYEE_IMPL_REPAIR},
            {
                "role": "user",
                "content": (
                    f"py_compile 报错：\n{err}\n\n原始代码（保持业务逻辑，仅修语法）：\n{current_source[:8000]}"
                ),
            },
        ]
        res2 = await chat_dispatch(
            prov,
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=repair_messages,
            max_tokens=6000,
            forbid_reasoning_fallback=True,
        )
        if not res2.get("ok"):
            return {
                "ok": False,
                "error": f"repair upstream: {res2.get('error') or 'error'}",
                "raw": raw_orig,
                "compile_error": err,
            }
        current_source = finalize_extracted_python(
            _strip_code_fence(str(res2.get("content") or ""))
        )[0]

    return {
        "ok": False,
        "error": f"经过 {_MAX_REPAIR_ATTEMPTS} 次修复仍无法通过编译",
        "raw": raw_orig,
        "compile_error": last_err,
    }


def _fallback_employee_py(emp_id: str, label: str, panel_summary: str) -> str:
    """模型失败或信息极少时的最小可编译实现：调用 ctx.call_llm 做兜底应答。"""
    safe_label = json.dumps(label or emp_id, ensure_ascii=False)
    safe_summary = json.dumps(
        (panel_summary or "根据 payload 完成员工任务并返回结构化结果。")[:600],
        ensure_ascii=False,
    )
    body = f'''"""自动生成的员工实现（兜底版）：{emp_id}。

画像信息不足或 LLM 生成失败时使用，行为为「把 payload 与员工画像拼给 ctx.call_llm，
把模型文本作为 summary 返回」。部署后请在「Mod 制作页」里替换为真实业务逻辑。
"""

from __future__ import annotations

import json
from typing import Any, Dict


EMPLOYEE_LABEL = {safe_label}
SYSTEM_PROMPT = {safe_summary}


async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger = ctx.get("logger")
    if logger:
        logger.info("[employee:{emp_id}] invoked payload=%s", str(payload)[:200])
    call_llm = ctx.get("call_llm")
    if not callable(call_llm):
        return {{
            "summary": "ctx.call_llm 未注入；请在宿主 build_run_context 中挂载 LLM 调度。",
            "items": [],
            "warnings": ["call_llm_missing"],
            "echo": payload,
        }}
    user_msg = json.dumps(payload or {{}}, ensure_ascii=False)[:4000]
    res = await call_llm(
        [
            {{"role": "system", "content": SYSTEM_PROMPT}},
            {{"role": "user", "content": user_msg}},
        ],
        max_tokens=1024,
        temperature=0.2,
    )
    if not res.get("ok"):
        return {{
            "summary": f"员工 {{EMPLOYEE_LABEL}} 调用 LLM 失败：" + str(res.get("error") or "")[:300],
            "items": [],
            "warnings": ["call_llm_failed"],
        }}
    return {{
        "summary": str(res.get("content") or "").strip()[:2000],
        "items": [],
        "warnings": [],
    }}
'''
    return body


async def generate_mod_employee_impls_async(
    db: Session,
    user: User,
    *,
    mod_dir: Path,
    employees: List[Dict[str, Any]],
    mod_id: str,
    mod_name: str,
    mod_brief: str,
    industry_card: Optional[Dict[str, Any]] = None,
    provider: Optional[str],
    model: Optional[str],
    status_hook: Optional[Callable[[str], Awaitable[None]]] = None,
    enable_vibe_heal: bool = True,
) -> Dict[str, Any]:
    """
    为 employees 中每名员工生成 ``backend/employees/<stem>.py``。
    生成失败（LLM 不可用或重试仍编译失败）时写入「兜底版」源码，以保证编排能继续跑，
    并把失败项写入返回值 ``errors`` 供前端展示。
    """
    out_dir = mod_dir / "backend" / "employees"
    out_dir.mkdir(parents=True, exist_ok=True)
    init_py = out_dir / "__init__.py"
    if not init_py.is_file():
        init_py.write_text(
            '"""Generated employee implementations (loaded via import_mod_backend_py)."""\n',
            encoding="utf-8",
        )

    prov = (provider or "").strip()
    mdl = (model or "").strip()
    api_key = ""
    base = None
    if prov:
        api_key, _ = resolve_api_key(db, user.id, prov)
        if prov in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
            base = resolve_base_url(db, user.id, prov)

    valid_employees = [
        e for e in employees if isinstance(e, dict) and str(e.get("id") or "").strip()
    ]
    total = len(valid_employees)
    sem = asyncio.Semaphore(_MAX_CONCURRENT_LLM)
    progress_lock = asyncio.Lock()
    done_cnt = 0

    async def _gen_one(idx: int, emp: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal done_cnt
        eid = str(emp.get("id") or "").strip()
        stem = sanitize_employee_stem(eid)
        target = out_dir / f"{stem}.py"
        label = str(emp.get("label") or emp.get("panel_title") or eid).strip()
        panel_summary = str(emp.get("panel_summary") or "").strip()

        used_fallback = False
        gen_err = ""
        source = ""

        if prov and mdl and api_key:
            async with sem:
                gen = await _generate_one_employee_py(
                    prov=prov,
                    api_key=api_key,
                    base_url=base,
                    model=mdl,
                    emp=emp,
                    mod_id=mod_id,
                    mod_name=mod_name,
                    mod_brief=mod_brief,
                    industry_card=industry_card,
                )
            if gen.get("ok"):
                source = str(gen.get("source") or "").strip() + "\n"
            else:
                gen_err = str(gen.get("error") or "")
        else:
            gen_err = "LLM provider/model/api_key 不可用，写入兜底实现"

        if not source:
            source = _fallback_employee_py(eid, label, panel_summary)
            used_fallback = True

        target.write_text(source, encoding="utf-8")
        entry = {
            "employee_id": eid,
            "stem": stem,
            "path": f"backend/employees/{stem}.py",
            "fallback": used_fallback,
        }
        if used_fallback and gen_err:
            entry["note"] = gen_err[:400]

        async with progress_lock:
            done_cnt += 1
            if status_hook:
                await status_hook(
                    f"已完成 {done_cnt}/{max(total, 1)} 名员工实现生成（并发上限 {_MAX_CONCURRENT_LLM}）…"
                )

        return entry

    results = await asyncio.gather(*[_gen_one(i, e) for i, e in enumerate(valid_employees)])

    generated = list(results)
    errors = [e for e in generated if e.get("fallback") and e.get("note")]

    heal_report: Dict[str, Any] = {"enabled": False}
    if enable_vibe_heal and prov and mdl:
        if status_hook:
            await status_hook("vibe-coding 自愈中：对生成的员工脚本做静态校验与补丁修复…")
        heal_report = await asyncio.to_thread(
            _vibe_heal_mod_employees,
            db,
            user,
            mod_dir=mod_dir,
            mod_id=mod_id,
            employees=valid_employees,
            provider=prov,
            model=mdl,
        )

    return {
        "ok": not errors,
        "generated": generated,
        "errors": errors,
        "vibe_heal": heal_report,
    }


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
