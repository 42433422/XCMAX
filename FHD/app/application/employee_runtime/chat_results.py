"""Interactive chat result helpers for employee runtime."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from app.application.employee_runtime.memory import MemoryContext


def is_interactive_chat_payload(payload: dict[str, Any]) -> bool:
    mode = str(payload.get("invoke_mode") or payload.get("mode") or "").strip().lower()
    source = str(payload.get("source") or payload.get("client_surface") or "").strip().lower()
    return mode in {"interactive_chat", "chat", "dialog"} and source in {
        "admin_im",
        "mobile_im",
        "employee_im",
        "admin_console",
        "mobile_app",
    }


def is_collaboration_context_payload(payload: dict[str, Any]) -> bool:
    mode = str(payload.get("invoke_mode") or payload.get("mode") or "").strip().lower()
    source = str(payload.get("source") or payload.get("client_surface") or "").strip().lower()
    return mode in {"collaboration_context", "upstream_context"} or source in {
        "employee_collaboration",
        "collaboration",
    }


def employee_label(
    employee_id: str,
    pack: dict[str, Any],
    manifest: dict[str, Any],
) -> str:
    raw_employee_meta = manifest.get("employee")
    employee_meta: dict[str, Any] = (
        dict(raw_employee_meta) if isinstance(raw_employee_meta, dict) else {}
    )
    return str(
        (manifest or {}).get("name")
        or employee_meta.get("label")
        or pack.get("pack_id")
        or employee_id
    ).strip()


def build_collaboration_context_result(
    employee_id: str,
    pack: dict[str, Any],
    manifest: dict[str, Any],
    task: str,
    handler_list: list[str],
    reasoning: dict[str, Any],
    t0: float,
    mem_ctx: MemoryContext,
    *,
    degraded: bool = False,
) -> dict[str, Any]:
    label = employee_label(employee_id, pack, manifest)
    text = str((reasoning or {}).get("reasoning") or "").strip()
    if not text:
        error = str((reasoning or {}).get("error") or "").strip()
        text = f"{label} 协作上下文暂不可用" + (f"：{error}" if error else "。")
    return {
        "employee_id": employee_id,
        "pack": {"id": pack["pack_id"], "version": pack.get("version")},
        "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
        "success": True,
        "result": {
            "task": task,
            "handlers": handler_list,
            "outputs": [
                {
                    "handler": "collaboration_context",
                    "ok": True,
                    "output": text,
                }
            ],
            "summary": "collaboration context",
            **({"cognition_error": reasoning.get("error")} if degraded else {}),
        },
        "executed_at": datetime.now(UTC).isoformat(),
        "source": "employee_runtime.local",
        "memory_used": mem_ctx.has_content,
        "degraded": degraded,
    }


def build_interactive_chat_fallback_result(
    employee_id: str,
    pack: dict[str, Any],
    manifest: dict[str, Any],
    task: str,
    handler_list: list[str],
    reasoning: dict[str, Any],
    t0: float,
) -> dict[str, Any]:
    label = employee_label(employee_id, pack, manifest)
    text = (
        f"我在，{label} 已接到消息。当前员工认知模型暂不可用，"
        "所以先进入降级对话；你可以继续补充明确任务，涉及写库、改文件或高风险动作仍会走风险门和审批。"
    )
    return {
        "employee_id": employee_id,
        "pack": {"id": pack["pack_id"], "version": pack.get("version")},
        "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
        "success": True,
        "result": {
            "task": task,
            "handlers": handler_list,
            "outputs": [
                {
                    "handler": "interactive_chat_fallback",
                    "ok": True,
                    "output": text,
                }
            ],
            "summary": "interactive chat fallback",
            "cognition_error": reasoning.get("error"),
        },
        "executed_at": datetime.now(UTC).isoformat(),
        "source": "employee_runtime.local",
        "degraded": True,
    }


def build_interactive_chat_reply_result(
    employee_id: str,
    pack: dict[str, Any],
    manifest: dict[str, Any],
    task: str,
    handler_list: list[str],
    reasoning: dict[str, Any],
    t0: float,
    upstream: dict[str, Any] | None,
    mem_ctx: MemoryContext,
) -> dict[str, Any]:
    label = employee_label(employee_id, pack, manifest)
    text = str((reasoning or {}).get("reasoning") or "").strip()
    if not text:
        text = (
            f"我在，{label} 已接到消息。你可以继续补充要咨询的问题；"
            "如果需要我执行改文件、写库或发布类动作，请明确任务目标、范围和验收标准。"
        )
    return {
        "employee_id": employee_id,
        "pack": {"id": pack["pack_id"], "version": pack.get("version")},
        "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
        "success": True,
        "result": {
            "task": task,
            "handlers": handler_list,
            "outputs": [
                {
                    "handler": "interactive_chat",
                    "ok": True,
                    "output": text,
                }
            ],
            "summary": "interactive chat reply",
        },
        "executed_at": datetime.now(UTC).isoformat(),
        "source": "employee_runtime.local",
        "memory_used": mem_ctx.has_content,
        "collaboration_upstream": upstream if upstream and not upstream.get("skipped") else None,
    }
