# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.aiopen.service")


def _default_capability_whitelist() -> dict[str, bool]:
    return dict.fromkeys(_facade().CAPABILITY_ROUTE_PREFIXES, True)


def _env_api_key() -> str:
    return (_facade().os.environ.get("AIOPEN_API_KEY") or "").strip()


def verify_api_key(provided: str | None) -> bool:
    """校验 ``X-AIOPEN-Key``。

    未配置任何 Key（env 与运行时均为空）时放行 —— 与
    :func:`app.fastapi_routes.business_api.require_fhd_business_key` 同策略，
    安全由 LAN 门禁兜底；生产务必配置 ``AIOPEN_API_KEY``。
    """
    env_key = _facade()._env_api_key()
    runtime_keys: dict[str, _facade().Any] = _facade().AIOPEN_STATE.get("runtime_keys", {})
    if not env_key and (not runtime_keys):
        return True
    got = (provided or "").strip()
    if not got:
        return False
    if env_key and _facade().secrets.compare_digest(got, env_key):
        return True
    return got in runtime_keys


def generate_api_key(label: str = "") -> dict[str, _facade().Any]:
    key = "aiopen_" + _facade().secrets.token_urlsafe(24)
    entry = {"label": (label or "").strip() or "未命名", "created_at": _facade().time.time()}
    _facade().AIOPEN_STATE.setdefault("runtime_keys", {})[key] = entry
    return {"key": key, **entry}


def revoke_api_key(key: str) -> bool:
    return (
        _facade().AIOPEN_STATE.setdefault("runtime_keys", {}).pop((key or "").strip(), None)
        is not None
    )


def list_api_keys() -> list[dict[str, _facade().Any]]:
    """脱敏列出 Key（仅前 12 位 + label）。"""
    out: list[dict[str, _facade().Any]] = []
    if _facade()._env_api_key():
        out.append({"key_preview": "env:AIOPEN_API_KEY", "label": "环境变量", "created_at": None})
    for key, meta in _facade().AIOPEN_STATE.get("runtime_keys", {}).items():
        out.append(
            {
                "key_preview": key[:12] + "…",
                "label": meta.get("label", ""),
                "created_at": meta.get("created_at"),
            }
        )
    return out


def _repo_stdio_bridge_path() -> str:
    """stdio 桥脚本绝对路径（供 Cursor command/args 配置）。"""
    here = _facade().Path(__file__).resolve()
    bridge = here.parents[3] / "scripts" / "dev" / "aiopen_mcp_stdio.py"
    return str(bridge)


def build_mcp_url_config(base_url: str, api_key: str = "") -> dict[str, _facade().Any]:
    """Cursor 原生 HTTP MCP 配置（url + headers）。"""
    root = str(base_url or "").rstrip("/")
    cfg: dict[str, _facade().Any] = {"url": f"{root}/api/aiopen/mcp"}
    key = str(api_key or "").strip()
    if key:
        cfg["headers"] = {"X-AIOPEN-Key": key}
    return cfg


def build_mcp_stdio_config(base_url: str, api_key: str = "") -> dict[str, _facade().Any]:
    """Python stdio 桥配置（无需 npx，适合 Claude Desktop）。"""
    env: dict[str, str] = {"AIOPEN_BASE_URL": str(base_url or "").rstrip("/")}
    key = str(api_key or "").strip()
    if key:
        env["AIOPEN_API_KEY"] = key
    return {"command": "python3", "args": [_facade()._repo_stdio_bridge_path()], "env": env}


def build_mcp_remote_config(base_url: str, api_key: str = "") -> dict[str, _facade().Any]:
    """npx mcp-remote 配置（业界常用，Cursor / Claude 均支持）。"""
    root = str(base_url or "").rstrip("/")
    args = ["-y", "mcp-remote", f"{root}/api/aiopen/mcp"]
    key = str(api_key or "").strip()
    if key:
        args.extend(["--header", f"X-AIOPEN-Key:{key}"])
    return {"command": "npx", "args": args}


def build_cursor_deeplink(server_name: str, server_config: dict[str, _facade().Any]) -> str:
    """生成 Cursor 一键安装 deep link（base64(JSON)）。"""
    config_b64 = (
        _facade()
        .base64.b64encode(_facade().json.dumps(server_config, ensure_ascii=False).encode("utf-8"))
        .decode("ascii")
    )
    return f"cursor://anysphere.cursor-deeplink/mcp/install?name={_facade().quote(server_name, safe='')}&config={_facade().quote(config_b64, safe='')}"


def build_mcp_install_bundle(base_url: str, api_key: str = "") -> dict[str, _facade().Any]:
    """面板 / guide 共用的 MCP 安装包（多种 AI 客户端 + 传输方式）。"""
    root = str(base_url or "").rstrip("/")
    url_cfg = _facade().build_mcp_url_config(root, api_key)
    stdio_cfg = _facade().build_mcp_stdio_config(root, api_key)
    remote_cfg = _facade().build_mcp_remote_config(root, api_key)
    script_path = _facade()._repo_stdio_bridge_path()

    def _client_entry(
        cid: str,
        name: str,
        icon: str,
        config_path: str,
        hint: str,
        transport: str,
        server_cfg: dict[str, _facade().Any],
        *,
        install_mode: str = "copy",
        cursor_deeplink: str | None = None,
        web_install_url: str | None = None,
    ) -> dict[str, _facade().Any]:
        entry: dict[str, _facade().Any] = {
            "id": cid,
            "name": name,
            "icon": icon,
            "config_path": config_path,
            "hint": hint,
            "transport": transport,
            "install_mode": install_mode,
            "mcp_json": _facade().json.dumps(
                {"mcpServers": {_facade().MCP_SERVER_NAME: server_cfg}},
                ensure_ascii=False,
                indent=2,
            ),
            "config": server_cfg,
        }
        if cursor_deeplink:
            entry["cursor_deeplink"] = cursor_deeplink
        if web_install_url:
            entry["web_install_url"] = web_install_url
        return entry

    cursor_dl = _facade().build_cursor_deeplink(_facade().MCP_SERVER_NAME, url_cfg)
    cursor_web = f"https://cursor.com/en/install-mcp?name={_facade().quote(_facade().MCP_SERVER_NAME, safe='')}&config={_facade().quote(_facade().base64.b64encode(_facade().json.dumps(url_cfg, ensure_ascii=False).encode()).decode(), safe='')}"
    clients = [
        _client_entry(
            "cursor",
            "Cursor",
            "◆",
            "~/.cursor/mcp.json",
            "点一下自动写入 MCP 配置",
            "url",
            url_cfg,
            install_mode="deeplink",
            cursor_deeplink=cursor_dl,
            web_install_url=cursor_web,
        ),
        _client_entry(
            "claude",
            "Claude",
            "✳",
            "claude_desktop_config.json",
            "复制后粘贴到 Claude Desktop → 设置 → MCP",
            "mcp_remote",
            remote_cfg,
        ),
        _client_entry(
            "vscode",
            "VS Code",
            "▣",
            "MCP 扩展 · 用户 settings",
            "需安装 MCP 扩展；也可复制 JSON 手动添加",
            "mcp_remote",
            remote_cfg,
            install_mode="vscode",
        ),
        _client_entry(
            "windsurf",
            "Windsurf",
            "≋",
            "~/.codeium/windsurf/mcp_config.json",
            "与 Cursor 相同 url 格式，复制后写入配置文件",
            "url",
            url_cfg,
        ),
        _client_entry(
            "trae",
            "Trae",
            "◎",
            "Trae → MCP 服务器设置",
            "字节 Trae IDE，粘贴 mcpServers JSON",
            "url",
            url_cfg,
        ),
        _client_entry(
            "generic",
            "其他",
            "⋯",
            "任意支持 MCP 的 AI 客户端",
            "Cherry Studio / Chatbox / Open WebUI 等通用 JSON",
            "mcp_remote",
            remote_cfg,
        ),
    ]
    return {
        "server_name": _facade().MCP_SERVER_NAME,
        "mcp_url": f"{root}/api/aiopen/mcp",
        "recommended": "url",
        "clients": clients,
        "methods": {
            "url": {
                "label": "Cursor 直连（推荐）",
                "description": "写入 ~/.cursor/mcp.json 的 url 字段，Cursor 2025+ 原生支持",
                "config": url_cfg,
                "cursor_deeplink": cursor_dl,
                "web_install_url": cursor_web,
            },
            "mcp_remote": {
                "label": "npx mcp-remote（通用）",
                "description": "与 Notion、Asana 等远程 MCP 相同模式，适合 Claude Desktop",
                "config": remote_cfg,
                "cursor_deeplink": _facade().build_cursor_deeplink(
                    _facade().MCP_SERVER_NAME, remote_cfg
                ),
            },
            "stdio": {
                "label": "Python stdio 桥",
                "description": "无需 npx，本地 Python 转发到 HTTP",
                "config": stdio_cfg,
                "script_path": script_path,
                "cursor_deeplink": _facade().build_cursor_deeplink(
                    _facade().MCP_SERVER_NAME, stdio_cfg
                ),
            },
        },
        "mcp_config_template": {"mcpServers": {_facade().MCP_SERVER_NAME: url_cfg}},
    }


def format_tool_result_text(tool_name: str, result: dict[str, _facade().Any]) -> str:
    """将工具执行结果格式化为 Agent 易读文本（MCP tools/call content）。"""
    name = str(tool_name or "").strip()
    ok = bool(result.get("success", False))
    if name == "api_catalog":
        raw_routes = result.get("routes")
        routes: list[_facade().Any] = list(raw_routes) if isinstance(raw_routes, list) else []
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
            _facade().json.dumps(data, ensure_ascii=False, indent=2, default=str)
            if data is not None
            else "(empty)"
        )
        if len(body) > 4000:
            body = body[:4000] + "\n…(truncated)"
        return f"API 调用成功：{method} {path} → HTTP {status}\n\n{body}"
    if name == "capability_loop":
        raw_steps = result.get("steps")
        steps: list[_facade().Any] = list(raw_steps) if isinstance(raw_steps, list) else []
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
            reply = _facade().json.dumps(data, ensure_ascii=False, default=str)[:2000]
        return f"XCAGI 助手回复：\n{reply}"
    if name == "ui_sessions":
        raw_sessions = result.get("sessions")
        sessions: list[_facade().Any] = list(raw_sessions) if isinstance(raw_sessions, list) else []
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
        elements: list[_facade().Any] = list(raw_elements) if isinstance(raw_elements, list) else []
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
            return f"{detail}\n{_facade().json.dumps(extra_data, ensure_ascii=False, default=str)}"
        return str(detail)
    if not ok:
        return f"工具 {name} 失败：{result.get('message', result.get('code', 'unknown error'))}"
    return _facade().json.dumps(result, ensure_ascii=False, indent=2, default=str)
