"""P0/P1 复杂编码单元：Cursor SDK / Webhook 真执行，产出回灌 CR 流程。"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


def _cursor_delegate_enabled() -> bool:
    return os.environ.get("MODSTORE_CURSOR_DELEGATE_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _cursor_api_key() -> str:
    return (
        os.environ.get("CURSOR_API_KEY") or os.environ.get("MODSTORE_CURSOR_API_KEY") or ""
    ).strip()


def _cursor_webhook_url() -> str:
    return (os.environ.get("MODSTORE_CURSOR_DELEGATE_WEBHOOK") or "").strip()


def _cursor_model() -> str:
    return (os.environ.get("MODSTORE_CURSOR_DELEGATE_MODEL") or "composer-2.5").strip()


def _resolve_project_root(input_data: Dict[str, Any]) -> str:
    return str(
        input_data.get("project_root")
        or input_data.get("workspace_root")
        or os.environ.get("MODSTORE_REPO_ROOT")
        or "."
    ).strip()


def _try_cursor_sdk_prompt(task: str, *, cwd: str) -> Dict[str, Any]:
    """调用 cursor_sdk.Agent.prompt（若已安装且配置了 API Key）。"""
    api_key = _cursor_api_key()
    if not api_key:
        return {"ok": False, "reason": "no CURSOR_API_KEY"}

    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
    except ImportError:
        return {"ok": False, "reason": "cursor_sdk not installed"}

    try:
        result = Agent.prompt(
            task,
            AgentOptions(
                api_key=api_key,
                model=_cursor_model(),
                local=LocalAgentOptions(cwd=cwd),
            ),
        )
        status = str(getattr(result, "status", "") or "")
        text = str(getattr(result, "result", "") or getattr(result, "output", "") or "")
        return {
            "ok": status.lower() in ("completed", "success", "done", "ok") or bool(text),
            "source": "cursor_sdk",
            "status": status,
            "output": text[:20_000],
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("cursor_sdk delegate failed")
        return {"ok": False, "source": "cursor_sdk", "error": str(exc)}


def _try_cursor_webhook(task: str, *, cwd: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    url = _cursor_webhook_url()
    if not url:
        return {"ok": False, "reason": "no MODSTORE_CURSOR_DELEGATE_WEBHOOK"}

    payload = {
        "task": task,
        "project_root": cwd,
        "input_data": input_data,
        "model": _cursor_model(),
    }
    try:
        resp = httpx.post(url, json=payload, timeout=600.0)
        body: Dict[str, Any] = {}
        try:
            body = resp.json() if resp.content else {}
        except Exception:
            body = {"raw": resp.text[:4000]}
        ok = resp.status_code < 400 and bool(body.get("ok", resp.status_code < 300))
        return {
            "ok": ok,
            "source": "cursor_webhook",
            "status_code": resp.status_code,
            "output": str(body.get("output") or body.get("result") or resp.text)[:20_000],
            "files_changed": (
                body.get("files_changed") if isinstance(body.get("files_changed"), list) else []
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "source": "cursor_webhook", "error": str(exc)}


def dispatch_cursor_delegate(
    *,
    task: str,
    input_data: Optional[Dict[str, Any]] = None,
    employee_id: str = "vibe-coding-maintainer",
) -> Dict[str, Any]:
    """Cursor 委派主入口：SDK → Webhook → 降级说明。"""
    if not _cursor_delegate_enabled():
        return {
            "handler": "cursor_delegate",
            "ok": False,
            "error": "MODSTORE_CURSOR_DELEGATE_ENABLED=0",
        }

    payload = dict(input_data or {})
    cwd = _resolve_project_root(payload)

    out = _try_cursor_sdk_prompt(task, cwd=cwd)
    if not out.get("ok") and out.get("reason") != "cursor_sdk not installed":
        if _cursor_webhook_url():
            out = _try_cursor_webhook(task, cwd=cwd, input_data=payload)
    elif not out.get("ok"):
        if _cursor_webhook_url():
            out = _try_cursor_webhook(task, cwd=cwd, input_data=payload)

    if not out.get("ok"):
        return {
            "handler": "cursor_delegate",
            "ok": False,
            "error": out.get("error") or out.get("reason") or "cursor delegate unavailable",
            "delegate_attempts": out,
        }

    files_changed: List[Dict[str, str]] = []
    raw_fc = out.get("files_changed")
    if isinstance(raw_fc, list):
        for item in raw_fc:
            if isinstance(item, dict) and item.get("path"):
                files_changed.append(
                    {
                        "path": str(item["path"]),
                        "content": str(item.get("content") or ""),
                    }
                )

    return {
        "handler": "cursor_delegate",
        "ok": True,
        "source": out.get("source"),
        "output": out.get("output", ""),
        "workspace_root": cwd,
        "files_changed": files_changed,
        "delegate_meta": {k: v for k, v in out.items() if k not in ("output", "files_changed")},
    }


__all__ = ["dispatch_cursor_delegate"]
