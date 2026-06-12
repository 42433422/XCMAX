# -*- coding: utf-8 -*-
"""AI 员工执行器（FHD 本地）：对齐 MODstore execute_employee_task 语义。"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.application.employee_runtime.agent_runner import run_agent_handler
from app.application.employee_runtime.loader import (
    DIRECT_PYTHON_RUNTIME_MISSING_MSG,
    build_employee_context,
    load_employee_pack_from_disk,
    pack_has_direct_python_runtime,
    parse_employee_config_v2,
    resolve_pack_dir,
)
from app.application.employee_runtime.risk_gate import gate_action_or_block
from app.utils.operational_errors import OPERATIONAL_ERRORS

logger = logging.getLogger(__name__)


def _get_section(config: dict[str, Any], key: str) -> dict[str, Any]:
    val = config.get(key) if isinstance(config, dict) else None
    return val if isinstance(val, dict) else {}


def _normalize_actions_cfg(config: dict[str, Any]) -> dict[str, Any]:
    actions_cfg = _get_section(config, "actions")
    inner = actions_cfg.get("actions") if isinstance(actions_cfg.get("actions"), dict) else actions_cfg
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
    except OPERATIONAL_ERRORS:
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
    mod = _import_module_from_path(convert_py, f"_xcagi_emp_convert_{employee_id.replace('-', '_')}")
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
            return {"handler": "direct_python", "ok": False, "error": "生成类员工需要 JSON 输入或 user_request"}
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
    except OPERATIONAL_ERRORS as exc:
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
    direct_cfg = actions_cfg.get("direct_python") if isinstance(actions_cfg.get("direct_python"), dict) else {}
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
    ctx = {
        "employee_id": employee_id,
        "workspace_root": payload["workspace_root"],
        "logger": logging.getLogger(f"employee.{employee_id}"),
    }
    out = _run_maybe_async(run_fn, payload, ctx)
    if isinstance(out, dict):
        return {
            "handler": "direct_python",
            "ok": bool(out.get("ok", out.get("success", True))),
            "output": out,
        }
    return {"handler": "direct_python", "ok": True, "output": out}


def _cognition_fhd(config: dict[str, Any], perceived: dict[str, Any], memory: dict[str, Any], task: str) -> dict[str, Any]:
    cog_cfg = _get_section(config, "cognition")
    agent = cog_cfg.get("agent") if isinstance(cog_cfg.get("agent"), dict) else {}
    system_prompt = str(agent.get("system_prompt") or cog_cfg.get("system_prompt") or "你是智能员工助手。")
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
    except OPERATIONAL_ERRORS as exc:
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
) -> dict[str, Any]:
    actions_cfg = _normalize_actions_cfg(config)
    handlers = _handler_list(actions_cfg)
    outputs: list[dict[str, Any]] = []
    for handler in handlers:
        if handler == "echo":
            outputs.append({"handler": "echo", "output": reasoning.get("reasoning", "")})
        elif handler == "direct_python":
            if not pack_has_direct_python_runtime(pack_root):
                outputs.append(
                    {"handler": "direct_python", "ok": False, "error": DIRECT_PYTHON_RUNTIME_MISSING_MSG}
                )
            else:
                outputs.append(
                    _action_direct_python_module(
                        pack_root, employee_id, actions_cfg, reasoning, task, workspace_root
                    )
                )
        elif handler == "agent":
            outputs.append(run_agent_handler(actions_cfg, reasoning, task, employee_id))
        elif handler == "llm_md":
            outputs.append({"handler": "llm_md", "output": reasoning.get("reasoning", "")})
        else:
            outputs.append({"handler": handler, "error": "unsupported handler in FHD local executor"})
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
) -> dict[str, Any]:
    """本地 employee_pack 执行入口（无 MODstore DB 依赖）。"""
    _ = user_id
    t0 = time.perf_counter()
    payload = dict(input_data or {})
    if workspace_root and "workspace_root" not in payload:
        payload["workspace_root"] = workspace_root
    logger.info("employee_execute_start_local employee_id=%s task_len=%s", employee_id, len(task or ""))
    try:
        pack = load_employee_pack_from_disk(employee_id)
        manifest = pack.get("manifest") or {}
        pack_root = Path(str(pack.get("pack_dir") or resolve_pack_dir(employee_id) or ""))
        config = parse_employee_config_v2(manifest)
        actions_cfg = _normalize_actions_cfg(config)
        handler_list = _handler_list(actions_cfg)
        gate = gate_action_or_block(employee_id, manifest, handler_list, payload)
        if not gate.get("ok"):
            duration_ms = round((time.perf_counter() - t0) * 1000, 3)
            return {
                "employee_id": employee_id,
                "pack": {"id": pack["pack_id"], "version": pack.get("version")},
                "duration_ms": duration_ms,
                "result": {
                    "task": task,
                    "handlers": handler_list,
                    "outputs": [],
                    "summary": "blocked by risk middleware",
                    "risk_gate": gate,
                },
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "blocked_by_risk_gate": True,
                "success": False,
            }
        ctx = build_employee_context(employee_id, payload)
        perceived = _perception_real(config, payload)
        file_path_fast = str(payload.get("file_path") or payload.get("path") or "").strip()
        direct_only = handler_list == ["direct_python"] and bool(file_path_fast)
        if direct_only:
            memory: dict[str, Any] = {}
            reasoning = {
                "input": dict(payload),
                "reasoning": "",
                "skipped_cognition": True,
                **{k: payload[k] for k in ("file_path", "path", "user_request") if k in payload},
            }
        else:
            memory = _memory_light(ctx)
            reasoning = _cognition_fhd(config, perceived, memory, task)
            if reasoning.get("error") and handler_list != ["direct_python"]:
                duration_ms = round((time.perf_counter() - t0) * 1000, 3)
                return {
                    "employee_id": employee_id,
                    "pack": {"id": pack["pack_id"], "version": pack.get("version")},
                    "duration_ms": duration_ms,
                    "success": False,
                    "result": {
                        "task": task,
                        "handlers": handler_list,
                        "outputs": [],
                        "summary": "cognition failed",
                        "cognition_error": reasoning.get("error"),
                    },
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                }
        result = _actions_fhd(
            config,
            reasoning,
            task,
            employee_id,
            pack_root,
            payload.get("workspace_root") or workspace_root,
        )
        duration_ms = round((time.perf_counter() - t0) * 1000, 3)
        ok = _handlers_execution_ok(result)
        return {
            "employee_id": employee_id,
            "pack": {"id": pack["pack_id"], "version": pack.get("version")},
            "duration_ms": duration_ms,
            "success": ok,
            "result": result,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "source": "employee_runtime.local",
        }
    except OPERATIONAL_ERRORS as exc:
        duration_ms = round((time.perf_counter() - t0) * 1000, 3)
        logger.exception("employee_execute_local failed employee_id=%s", employee_id)
        return {
            "employee_id": employee_id,
            "duration_ms": duration_ms,
            "success": False,
            "error": str(exc)[:800],
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }


__all__ = ["execute_employee_task_local"]
