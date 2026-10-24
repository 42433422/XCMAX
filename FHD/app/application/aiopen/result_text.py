"""Human-readable MCP tool results."""

from __future__ import annotations

import json
from typing import Any


def format_tool_result_text(tool_name: str, result: dict[str, Any]) -> str:
    """将工具执行结果格式化为 Agent 易读文本（MCP tools/call content）。"""
    name = str(tool_name or "").strip()
    ok = bool(result.get("success", False))
    if name == "api_catalog":
        raw_routes = result.get("routes")
        routes: list[Any] = list(raw_routes) if isinstance(raw_routes, list) else []
        enabled = [r for r in routes or [] if isinstance(r, dict) and r.get("enabled")]
        lines = [f"AIOPEN 白名单 API（{len(enabled or [])}/{len(routes)} 已启用）："]
        for r in routes or []:
            if not isinstance(r, dict):
                continue
            mark = "✓" if r.get("enabled") else "·"
            lines.append(f"  {mark} {r.get('path', '')}")
        return "\n".join(lines)
    if name == "api_call":
        path = result.get("path", "")
        method = result.get("method", "GET")
        status = result.get("status_code", "?")
        if not ok:
            return f"API 调用失败：{method} {path}\n{result.get('message', '')}"
        data = result.get("data")
        body = (
            json.dumps(data, ensure_ascii=False, indent=2, default=str)
            if data is not None
            else "(empty)"
        )
        if len(body) > 4000:
            body = body[:4000] + "\n…(truncated)"
        return f"API 调用成功：{method} {path} → HTTP {status}\n\n{body}"
    if name == "capability_loop":
        raw_steps = result.get("steps")
        steps: list[Any] = list(raw_steps) if isinstance(raw_steps, list) else []
        lines = [f"全调用闭环：{('通过' if ok else '未通过')}", f"提示：{result.get('hint', '')}"]
        for s in steps or []:
            if not isinstance(s, dict):
                continue
            mark = "✓" if s.get("ok") else "✗"
            extra = ""
            if s.get("path"):
                extra += f" {s.get('path')}"
            if s.get("status_code") is not None:
                extra += f" HTTP {s.get('status_code')}"
            if s.get("session_count") is not None:
                extra += f" sessions={s.get('session_count')}"
            lines.append(f"  {mark} {s.get('step')}{extra}")
        return "\n".join(lines)
    if name == "chat":
        if not ok:
            return f"对话失败：{result.get('message', '')}"
        data = result.get("data") if isinstance(result.get("data"), dict) else result
        reply = ""
        if isinstance(data, dict):
            reply = str(data.get("reply") or data.get("message") or data.get("content") or "")
        if not reply:
            reply = json.dumps(data, ensure_ascii=False, default=str)[:2000]
        return f"XCAGI 助手回复：\n{reply}"
    if name == "ui_sessions":
        raw_sessions = result.get("sessions")
        sessions: list[Any] = list(raw_sessions) if isinstance(raw_sessions, list) else []
        if not sessions:
            return "当前无在线虚拟光标会话。\n请让用户在 XCAGI 打开 AIOPEN 面板并开启「本页待命」。"
        lines = [f"在线 screen 会话 {len(sessions)} 个："]
        for s in sessions:
            if not isinstance(s, dict):
                continue
            lines.append(f"  · {s.get('session_id', '?')} — {s.get('label', 'XCAGI 前端')}")
        return "\n".join(lines)
    if name == "ui_snapshot":
        if not ok:
            return f"页面快照失败：{result.get('message', '')}"
        url = result.get("url") or result.get("page_url") or ""
        title = result.get("title") or result.get("page_title") or ""
        raw_elements = result.get("elements")
        elements: list[Any] = list(raw_elements) if isinstance(raw_elements, list) else []
        lines = [
            f"页面：{title or '(无标题)'}",
            f"URL：{url or '(未知)'}",
            f"可交互元素 {len(elements or [])} 个：",
        ]
        for el in elements[:40]:
            if not isinstance(el, dict):
                continue
            sel = el.get("selector") or el.get("ref") or "?"
            text = str(el.get("text") or el.get("label") or "")[:60]
            role = el.get("role") or el.get("tag") or ""
            lines.append(f"  · [{role}] {text!r} → {sel}")
        if len(elements or []) > 40:
            lines.append(f"  … 另有 {len(elements or []) - 40} 个元素")
        return "\n".join(lines)
    if name in {"ui_click", "ui_type", "ui_navigate", "ui_scroll"}:
        if not ok:
            return f"{name} 失败：{result.get('message', '')}"
        detail = result.get("message") or result.get("detail") or "操作已执行"
        extra_data = {
            key: value
            for key, value in result.items()
            if key not in {"success", "message", "detail"}
        }
        if extra_data:
            return f"{detail}\n{json.dumps(extra_data, ensure_ascii=False, default=str)}"
        return str(detail)
    if not ok:
        return f"工具 {name} 失败：{result.get('message', result.get('code', 'unknown error'))}"
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)
