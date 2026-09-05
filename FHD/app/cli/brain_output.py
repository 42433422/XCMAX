"""Readable terminal output; JSON remains available for scripts."""

from __future__ import annotations

import json
from typing import Any


def terminal_text(value: Any) -> str:
    """Prevent server and file text from issuing terminal control sequences."""
    return "".join(
        f"\\x{ord(char):02x}"
        if (ord(char) < 32 and char not in "\n\t") or 127 <= ord(char) <= 159
        else char
        for char in str(value)
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _status(value: dict) -> str:
    lines = []
    for key, label in (
        ("health", "服务整体"),
        ("desktop", "桌面服务"),
        ("code_editor", "文件编辑"),
    ):
        part = value.get(key)
        if not isinstance(part, dict):
            continue
        if part.get("error"):
            lines.append(f"{label}: 不可用 — {part['error']}")
            continue
        state = part.get("status") or part.get("runtimeStatus") or part.get("phase") or "已连接"
        lines.append(f"{label}: {state}")
        reasons = part.get("degradedReasons") or part.get("degraded_reasons") or []
        if reasons:
            lines.append("  原因: " + ", ".join(map(str, reasons)))
    tier = value.get("tier")
    if isinstance(tier, dict) and tier.get("available") is False:
        lines.append(f"P2 权限: 未查询（{tier.get('reason', '服务未提供查询接口')}）")
    if value.get("draft_execution_verified") is False:
        lines.append("AI 文件草稿: 尚未验证实际生成能力")
    return "\n".join(lines) or _json(value)


def _models(value: dict) -> str:
    lines = []
    for key, label in (
        ("installed_local_models", "本地模型目录"),
        ("cloud_catalog", "云端模型目录"),
    ):
        part = value.get(key)
        if part is None:
            continue
        lines.append(label + "（目录存在不代表推理已就绪）")
        if isinstance(part, dict) and part.get("error"):
            lines.append(f"  不可用: {part['error']}")
            continue
        data = part.get("data", part) if isinstance(part, dict) else {}
        providers = data.get("providers") if isinstance(data, dict) else None
        if isinstance(providers, list):
            for provider in providers:
                if not isinstance(provider, dict):
                    lines.append(_json(provider))
                    continue
                name = provider.get("label") or provider.get("provider") or "未知提供商"
                source = provider.get("fetch_source") or "来源未标注"
                error = provider.get("error")
                lines.append(f"  {name} [{source}]" + (f" — {error}" if error else ""))
                models = provider.get("models")
                lines.append(
                    "    "
                    + (
                        ", ".join(map(str, models))
                        if isinstance(models, list) and models
                        else "暂无模型"
                    )
                )
            if not providers:
                lines.append("  暂无提供商")
            continue
        rows = part.get("models") if isinstance(part, dict) else None
        if isinstance(rows, list):
            if not rows:
                lines.append("  暂无模型")
            for row in rows:
                if isinstance(row, dict):
                    name = row.get("name") or row.get("id") or row.get("model")
                    if name:
                        version = row.get("version")
                        lines.append(f"  {name}" + (f" ({version})" if version else ""))
                    else:
                        lines.append(_json(row))
                else:
                    lines.append(f"  {row}")
        else:
            lines.append(_json(part))
    return "\n".join(lines) or _json(value)


def format_output(value: dict, command: str) -> str:
    """Render a response without hiding unknown payloads or partial failures."""
    output = _json(value)
    if command == "status":
        output = _status(value)
    elif command == "models":
        output = _models(value)
    elif value.get("success") is False:
        output = _json(value)
    elif command == "chat":
        raw = value.get("data")
        data = raw if isinstance(raw, dict) else {}
        response = value.get("response") or data.get("text")
        if isinstance(response, str):
            output = response
        elif value.get("session_id"):
            output = f"已创建会话: {value['session_id']}"
    elif command == "login" and value.get("username"):
        output = f"已登录: {value['username']}\n服务: {value.get('origin', '')}"
    elif command == "logout" and value.get("message"):
        output = str(value["message"])
    elif command == "openapi" and isinstance(value.get("routes"), list):
        lines = [
            f"{row['method']:<7} {row['path']}  {row.get('summary', '')}" for row in value["routes"]
        ]
        output = "\n".join(lines + [f"共 {len(lines)} 个接口"])
    elif command == "analyze" and isinstance(value.get("preview"), str):
        output = value["preview"]
    elif command == "draft" and isinstance(value.get("proposed_new_content"), str):
        output = "草稿（尚未写入文件）:\n" + value["proposed_new_content"]
    elif command == "edit" and value.get("edit_id"):
        output = f"修改提案: {value['edit_id']}（尚未写入文件）\n{value.get('unified_diff', '')}"
    elif command == "diff" and isinstance(value.get("unified_diff"), str):
        output = value["unified_diff"]
    elif command == "apply" and value.get("success") is True:
        output = "已创建文件" if value.get("created") else "已更新文件"
    return terminal_text(output)
