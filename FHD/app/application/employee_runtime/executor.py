# -*- coding: utf-8 -*-
"""AI 员工执行器（FHD 本地）：对齐 MODstore execute_employee_task 语义。"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import logging
import os
from pathlib import Path
from typing import Any

from app.application.employee_runtime.agent_runner import run_agent_handler
from app.application.employee_runtime.loader import (
    DIRECT_PYTHON_RUNTIME_MISSING_MSG,
    pack_has_direct_python_runtime,
)
from app.mod_sdk.employee_specialized_tools import get_employee_tools, handle_specialized
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _build_enriched_ctx(employee_id: str, workspace_root: str) -> dict[str, Any]:
    """构建注入真实工具的 ctx（call_llm / http_get / http_post / specialized_tools）。

    补齐员工 run() 期望但原本缺失的 ctx 能力，让员工真正干活而非只靠 LLM 提示词。
    """
    ctx: dict[str, Any] = {
        "employee_id": employee_id,
        "workspace_root": workspace_root,
        "logger": logging.getLogger(f"employee.{employee_id}"),
        "specialized_tools": get_employee_tools(employee_id),
    }

    async def _call_llm(messages: list[dict[str, Any]], max_tokens: int = 4000, temperature: float = 0.7) -> dict[str, Any]:
        try:
            from app.mod_sdk.mod_employee_llm import mod_employee_complete

            result = await mod_employee_complete(
                messages=messages, max_tokens=max_tokens, temperature=temperature
            )
            if isinstance(result, dict) and result.get("success"):
                return {"ok": True, "content": result.get("content", "")}
            return {"ok": False, "error": result.get("error", "LLM 调用失败") if isinstance(result, dict) else "未知错误"}
        except Exception as exc:  # noqa: BLE001  LLM 调用边界：异常转结构化结果
            return {"ok": False, "error": repr(exc)}

    async def _http_request(method: str, url: str, **kw: Any) -> dict[str, Any]:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=kw.pop("timeout", 30)) as client:
                resp = await client.request(method, url, **kw)
                try:
                    body = resp.json()
                except Exception:  # noqa: BLE001  JSON 解析失败降级为文本
                    body = resp.text
                return {"ok": resp.is_success, "status": resp.status_code, "body": body}
        except Exception as exc:  # noqa: BLE001  HTTP 调用边界：异常转结构化结果
            return {"ok": False, "error": repr(exc)}

    async def _http_get(url: str, **kw: Any) -> dict[str, Any]:
        return await _http_request("GET", url, **kw)

    async def _http_post(url: str, json_body: Any = None, **kw: Any) -> dict[str, Any]:
        if json_body is not None:
            kw["json"] = json_body
        return await _http_request("POST", url, **kw)

    ctx["call_llm"] = _call_llm
    ctx["http_get"] = _http_get
    ctx["http_post"] = _http_post
    return ctx


def _get_section(config: dict[str, Any], key: str) -> dict[str, Any]:
    val = config.get(key) if isinstance(config, dict) else None
    return val if isinstance(val, dict) else {}


def _normalize_actions_cfg(config: dict[str, Any]) -> dict[str, Any]:
    actions_cfg = _get_section(config, "actions")
    inner = (
        actions_cfg.get("actions") if isinstance(actions_cfg.get("actions"), dict) else actions_cfg
    )
    return inner if isinstance(inner, dict) else actions_cfg


def _handler_list(actions_cfg: dict[str, Any]) -> list[str]:
    raw = actions_cfg.get("handlers") or ["echo"]
    return [str(x).strip() for x in raw if str(x).strip()]


def _perception_real(config: dict[str, Any], input_data: dict[str, Any]) -> dict[str, Any]:
    p_cfg = _get_section(config, "perception")
    p_type = str(p_cfg.get("type") or "text").strip().lower()
    payload = input_data or {}
    return {"normalized_input": payload, "type": p_type}


def _memory_light(ctx: dict[str, Any]) -> dict[str, Any]:
    return {"session": {"employee_id": ctx.get("employee_id")}, "long_term": None}


def _resolve_file_path(args: dict[str, Any], workspace_root: str | None) -> Path | None:
    raw = str(args.get("file_path") or args.get("path") or "").strip()
    if not raw:
        return None
    p = Path(raw)
    if p.is_file():
        return p.resolve()
    base = Path(workspace_root or os.getcwd()).resolve()
    candidate = (base / raw).resolve()
    return candidate if candidate.is_file() else None


def _import_module_from_path(module_path: Path, module_label: str):
    spec = importlib.util.spec_from_file_location(module_label, str(module_path))
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_maybe_async(fn, *args, **kwargs):
    out = fn(*args, **kwargs)
    if inspect.isawaitable(out):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(out)
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, out).result()
    return out


def _find_vendor_convert_module(pack_root: Path) -> Path | None:
    backend = pack_root / "backend"
    if not backend.is_dir():
        return None
    for py in backend.rglob("convert.py"):
        if "vendor" in py.as_posix().lower():
            return py
    return None


def _load_rule_spec(pack_root: Path) -> dict[str, Any]:
    spec_path = pack_root / "rule_spec.json"
    if not spec_path.is_file():
        return {}
    try:
        data = json.loads(spec_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except RECOVERABLE_ERRORS:
        return {}


def _action_vendor_convert(
    pack_root: Path,
    employee_id: str,
    payload: dict[str, Any],
    workspace_root: str | None,
) -> dict[str, Any]:
    convert_py = _find_vendor_convert_module(pack_root)
    if convert_py is None:
        return {"handler": "direct_python", "ok": False, "error": DIRECT_PYTHON_RUNTIME_MISSING_MSG}
    mod = _import_module_from_path(
        convert_py, f"_xcagi_emp_convert_{employee_id.replace('-', '_')}"
    )
    if mod is None or not callable(getattr(mod, "convert_file", None)):
        return {"handler": "direct_python", "ok": False, "error": "vendor convert 模块无效"}
    is_generate = "generate" in employee_id.lower()
    src = _resolve_file_path(payload, workspace_root)
    if not is_generate and src is None:
        return {"handler": "direct_python", "ok": False, "error": "缺少有效 file_path"}
    out_dir = pack_root / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    rule_spec = _load_rule_spec(pack_root)
    default_out = str(rule_spec.get("default_output_relpath") or "outputs/data.json")
    output_path = out_dir / Path(default_out).name
    if payload.get("output_path"):
        output_path = Path(str(payload["output_path"]))
    if is_generate:
        src = src or (pack_root / "inputs" / "payload.json")
        if not src.is_file() and payload.get("user_request"):
            payload_path = pack_root / "inputs" / "payload.json"
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            payload_path.write_text(
                json.dumps({"user_request": payload["user_request"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            src = payload_path
        if not src or not src.is_file():
            return {
                "handler": "direct_python",
                "ok": False,
                "error": "生成类员工需要 JSON 输入或 user_request",
            }
    ctx = {"employee_id": employee_id, "workspace_root": str(workspace_root or os.getcwd())}
    convert_fn = mod.convert_file
    try:
        result = _run_maybe_async(
            convert_fn,
            src,
            output_path,
            template_path=None,
            payload={k: v for k, v in payload.items() if k not in ("file_path", "path")},
            ctx=ctx,
            rule_spec=rule_spec,
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception("vendor convert failed employee_id=%s", employee_id)
        return {"handler": "direct_python", "ok": False, "error": str(exc)[:800]}
    return {
        "handler": "direct_python",
        "ok": True,
        "output": result if isinstance(result, dict) else {"result": result},
        "output_path": str(output_path),
    }


def _action_direct_python_module(
    pack_root: Path,
    employee_id: str,
    actions_cfg: dict[str, Any],
    reasoning: dict[str, Any],
    task: str,
    workspace_root: str | None,
) -> dict[str, Any]:
    direct_cfg = (
        actions_cfg.get("direct_python")
        if isinstance(actions_cfg.get("direct_python"), dict)
        else {}
    )
    module_name = str(direct_cfg.get("module") or "worker").strip() or "worker"
    module_path = pack_root / "backend" / "employees" / f"{module_name}.py"
    if not module_path.is_file():
        for py in (pack_root / "backend" / "employees").glob("*.py"):
            if not py.name.startswith("_"):
                module_path = py
                break
    if not module_path.is_file():
        if _find_vendor_convert_module(pack_root):
            payload = dict((reasoning or {}).get("input") or {})
            for key in ("file_path", "workspace_root", "user_request", "output_path"):
                if key in (reasoning or {}) and key not in payload:
                    payload[key] = reasoning[key]
            payload.setdefault("task", task)
            payload.setdefault("workspace_root", str(workspace_root or os.getcwd()))
            return _action_vendor_convert(pack_root, employee_id, payload, workspace_root)
        return {"handler": "direct_python", "ok": False, "error": DIRECT_PYTHON_RUNTIME_MISSING_MSG}
    mod = _import_module_from_path(
        module_path,
        f"_xcagi_emp_{employee_id.replace('-', '_')}_{module_path.stem}",
    )
    if mod is None:
        return {"handler": "direct_python", "ok": False, "error": f"无法加载 {module_path}"}
    run_fn = getattr(mod, "run", None)
    if not callable(run_fn):
        return {"handler": "direct_python", "ok": False, "error": "module has no run(payload, ctx)"}
    payload = dict((reasoning or {}).get("input") or {})
    for key in ("file_path", "workspace_root", "user_request", "output_path"):
        if key in (reasoning or {}) and key not in payload:
            payload[key] = reasoning[key]
    payload.setdefault("task", task)
    payload.setdefault("workspace_root", str(workspace_root or os.getcwd()))
    ctx = _build_enriched_ctx(employee_id, payload["workspace_root"])
    # 拦截 specialized handler：直接走专属工具调度，不调用员工 run()
    if str(payload.get("handler") or "").strip() == "specialized":
        spec_out = _run_maybe_async(handle_specialized, employee_id, payload, ctx)
        if isinstance(spec_out, dict):
            return {
                "handler": "specialized",
                "ok": bool(spec_out.get("ok", True)),
                "output": spec_out,
            }
    out = _run_maybe_async(run_fn, payload, ctx)
    if isinstance(out, dict):
        return {
            "handler": "direct_python",
            "ok": bool(out.get("ok", out.get("success", True))),
            "output": out,
        }
    return {"handler": "direct_python", "ok": True, "output": out}


def _cognition_fhd(
    config: dict[str, Any], perceived: dict[str, Any], memory: dict[str, Any], task: str
) -> dict[str, Any]:
    cog_cfg = _get_section(config, "cognition")
    agent = cog_cfg.get("agent") if isinstance(cog_cfg.get("agent"), dict) else {}
    system_prompt = str(
        agent.get("system_prompt") or cog_cfg.get("system_prompt") or "你是智能员工助手。"
    )
    model_cfg = agent.get("model") if isinstance(agent.get("model"), dict) else {}
    max_tokens = int(model_cfg.get("max_tokens") or 4000)
    normalized = perceived.get("normalized_input") if isinstance(perceived, dict) else {}
    user_payload = json.dumps({"task": task, "input": normalized}, ensure_ascii=False)[:12000]
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_payload},
    ]
    try:
        from app.application.employee_runtime.agent_runner import _chat_completion, _run_async

        raw = _run_async(_chat_completion(messages, max_tokens=max_tokens))
    except RECOVERABLE_ERRORS as exc:
        return {"reasoning": "", "error": str(exc)[:800], "input": normalized, "memory": memory}
    if raw.get("error"):
        return {"reasoning": "", "error": raw["error"], "input": normalized, "memory": memory}
    choices = raw.get("choices") or []
    text = ""
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message") or {}
        text = str(msg.get("content") or "")
    return {
        "reasoning": text,
        "input": normalized if isinstance(normalized, dict) else {},
        "memory": memory,
        "llm_raw": raw,
        "system_prompt": system_prompt,
    }


def _actions_fhd(
    config: dict[str, Any],
    reasoning: dict[str, Any],
    task: str,
    employee_id: str,
    pack_root: Path,
    workspace_root: str | None,
    *,
    agent_tools: list[dict[str, Any]] | None = None,
    agent_gate: Any = None,
    agent_max_iterations: int | None = None,
) -> dict[str, Any]:
    actions_cfg = _normalize_actions_cfg(config)
    handlers = _handler_list(actions_cfg)
    # 专属工具拦截：input_data.handler=specialized 时直接走专属工具调度，
    # 不受 manifest 声明的 handlers 限制（让 llm_md/echo 类员工也能用专属工具）
    raw_input = reasoning.get("input") if isinstance(reasoning, dict) else None
    if isinstance(raw_input, dict) and str(raw_input.get("handler") or "").strip() == "specialized":
        ws = str(workspace_root or os.getcwd())
        spec_ctx = _build_enriched_ctx(employee_id, ws)
        spec_out = _run_maybe_async(handle_specialized, employee_id, raw_input, spec_ctx)
        return {
            "task": task,
            "handlers": ["specialized"],
            "outputs": [
                {
                    "handler": "specialized",
                    "ok": bool(spec_out.get("ok", True)) if isinstance(spec_out, dict) else True,
                    "output": spec_out,
                }
            ],
            "summary": "executed specialized handler",
        }
    outputs: list[dict[str, Any]] = []
    for handler in handlers:
        if handler == "echo":
            outputs.append({"handler": "echo", "output": reasoning.get("reasoning", "")})
        elif handler == "direct_python":
            if not pack_has_direct_python_runtime(pack_root):
                outputs.append(
                    {
                        "handler": "direct_python",
                        "ok": False,
                        "error": DIRECT_PYTHON_RUNTIME_MISSING_MSG,
                    }
                )
            else:
                outputs.append(
                    _action_direct_python_module(
                        pack_root, employee_id, actions_cfg, reasoning, task, workspace_root
                    )
                )
        elif handler == "agent":
            outputs.append(
                run_agent_handler(
                    actions_cfg,
                    reasoning,
                    task,
                    employee_id,
                    workspace_root=workspace_root,
                    tools=agent_tools,
                    gate=agent_gate,
                    max_iterations=agent_max_iterations,
                )
            )
        elif handler == "llm_md":
            outputs.append({"handler": "llm_md", "output": reasoning.get("reasoning", "")})
        else:
            outputs.append(
                {"handler": handler, "error": "unsupported handler in FHD local executor"}
            )
    return {
        "task": task,
        "handlers": handlers,
        "outputs": outputs,
        "summary": f"executed {len(outputs)} handlers",
    }


def _handlers_execution_ok(result: dict[str, Any]) -> bool:
    outputs = result.get("outputs") if isinstance(result.get("outputs"), list) else []
    if not outputs:
        return True
    for out in outputs:
        if isinstance(out, dict) and out.get("ok") is False:
            return False
    return True


def execute_employee_task_local(
    employee_id: str,
    task: str,
    input_data: dict[str, Any] | None = None,
    user_id: int = 0,
    *,
    workspace_root: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """本地 employee_pack 执行入口（无 MODstore DB 依赖）。

    委托给 :class:`app.application.employee_runtime.agent.EmployeeAgent`：
    感知 → 记忆召回 → 认知 → 行动（多轮）→ 记忆回写。保留原返回结构与所有调用方兼容。
    """
    from app.application.employee_runtime.agent import EmployeeAgent

    return EmployeeAgent(employee_id).run(
        task,
        input_data,
        user_id=user_id,
        workspace_root=workspace_root,
        session_id=session_id,
    )


__all__ = ["execute_employee_task_local"]
