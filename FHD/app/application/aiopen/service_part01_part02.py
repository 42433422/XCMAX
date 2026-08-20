# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.aiopen.service")


def aiopen_manifest() -> dict[str, _facade().Any]:
    return {
        "name": _facade().AIOPEN_PRODUCT_NAME,
        "tagline": _facade().AIOPEN_PRODUCT_TAGLINE,
        "version": "1.0.0.1",
        "protocol": {
            "guide": "/api/aiopen/guide",
            "mcp": "/api/aiopen/mcp",
            "rest_invoke": "/api/aiopen/invoke",
            "ws_screen": "/api/aiopen/ws",
            "auth_header": "X-AIOPEN-Key",
        },
        "tools": [
            {k: v for k, v in tool.items() if k in ("name", "description", "inputSchema")}
            for tool in _facade().TOOL_DEFINITIONS
        ],
    }


def build_aiopen_guide(base_url: str) -> dict[str, _facade().Any]:
    """生成可供外部 AI 自行阅读的接入说明（``GET /api/aiopen/guide`` SSOT）。"""
    root = str(base_url or "").rstrip("/")
    mcp_url = f"{root}/api/aiopen/mcp"
    invoke_url = f"{root}/api/aiopen/invoke"
    manifest_url = f"{root}/api/aiopen/manifest"
    guide_url = f"{root}/api/aiopen/guide"
    keys_url = f"{root}/api/aiopen/keys"
    install_url = f"{root}/api/aiopen/install"
    install = _facade().build_mcp_install_bundle(root)
    mcp_template = install["mcp_config_template"]
    url_deeplink = install["methods"]["url"]["cursor_deeplink"]
    remote_cfg = install["methods"]["mcp_remote"]["config"]
    remote_template = _facade().json.dumps(
        {"mcpServers": {_facade().MCP_SERVER_NAME: remote_cfg}}, ensure_ascii=False, indent=2
    )
    tool_lines = "\n".join(
        f"- **{t['name']}**：{t['description']}" for t in _facade().TOOL_DEFINITIONS
    )
    markdown = f"""# XCAGI AIOPEN 接入说明（给 AI 阅读）\n\n你是即将接入 XCAGI 的 AI Agent。请阅读本文并完成 MCP 配置，然后告知用户配置结果。\n\n## 产品\n\n- 名称：**{_facade().AIOPEN_PRODUCT_NAME}** — {_facade().AIOPEN_PRODUCT_TAGLINE}\n- 版本：1.0.0.1（稳定版）\n\n## 前置条件（请提醒用户）\n\n1. 用户在 XCAGI 前端打开 **AI生态应用 → AIOPEN 开放智控**\n2. 用户点击 **「一键开启 AI 操控」**（或手动开启远程操控 + 本浏览器受控屏幕）\n3. 用户在本面板 **「获取连接口令」** 后将口令提供给你（开发模式无 Key 时可留空）\n\n当前服务端远程操控：{("已开启" if _facade().AIOPEN_STATE.get("remote_control_enabled") else "未开启")}\n在线虚拟光标会话数：{len(_facade().aiopen_cursor_hub.session_ids())}\n\n## 端点（基于请求来源 `{root}`）\n\n| 用途 | URL |\n|------|-----|\n| **本说明（你正在读的）** | `{guide_url}` |\n| 工具目录 JSON | `{manifest_url}` |\n| MCP 接入（推荐） | `{mcp_url}` |\n| REST 通用调用 | `{invoke_url}` |\n| 生成运行时 Key（POST） | `{keys_url}` |\n\n鉴权请求头：`X-AIOPEN-Key: <连接口令>`（未配置任何 Key 时开发模式可省略）\n\n## 你的配置任务（MCP）\n\n**方式 A（推荐 · Cursor 一键）**：让用户在 AIOPEN 面板点「在 Cursor 中安装」，或打开 deep link：\n\n`{url_deeplink}`\n\n**方式 B（手动 JSON）**：写入 `~/.cursor/mcp.json`：\n\n```json\n{_facade().json.dumps(mcp_template, ensure_ascii=False, indent=2)}\n```\n\n将连接口令填入 `X-AIOPEN-Key`（向用户索取或在面板生成）。\n\n**方式 C（npx mcp-remote · 与 Notion/Asana 同款）**：\n\n```json\n{remote_template}\n```\n\n完整安装选项：`GET {install_url}`\n\n### MCP 协议\n\n- 传输：Streamable HTTP — POST JSON-RPC 2.0 到 `{mcp_url}`\n- 支持方法：`initialize`、`tools/list`、`tools/call`、`ping`、`notifications/initialized`\n- 响应头：`MCP-Protocol-Version`、`Mcp-Session-Id`\n- 请求头：`Content-Type: application/json`，以及 `X-AIOPEN-Key`（若已配置）\n\n### 验证步骤\n\n1. `initialize` → 应返回 serverInfo.name = AIOPEN\n2. `tools/list` → 应返回 9 个工具（含 ui_snapshot、ui_click、chat 等）\n3. `tools/call` name=`ui_sessions` → 确认有在线 screen 会话（用户须保持浏览器打开）\n4. `tools/call` name=`ui_snapshot` → 读取当前页面可交互元素\n5. 按需 `ui_click` / `ui_type` / `ui_navigate` 操作页面\n\n## REST 备选\n\n```bash\ncurl -X POST '{invoke_url}' \\\n  -H 'Content-Type: application/json' \\\n  -H 'X-AIOPEN-Key: <连接口令>' \\\n  -d '{{"tool": "chat", "args": {{"message": "你好"}}}}'\n```\n\n## 可用工具\n\n{tool_lines}\n\n## 虚拟光标操作流程\n\n1. `ui_sessions` — 确认有在线会话\n2. `ui_snapshot` — 获取 selector / 可见文本\n3. `ui_click` — 点击（参数 selector 或 text）\n4. `ui_type` — 输入（selector + text）\n5. `ui_navigate` — 跳转路由 path\n6. `ui_scroll` — 滚动\n\n## 完成后请告诉用户\n\n- MCP 是否配置成功\n- tools/list 工具数量\n- 是否检测到在线 screen 会话\n- 若失败：是否缺少连接口令、用户是否已一键开启、后端是否已重启\n\n---\n文档 URL：{guide_url} · 重新获取最新说明请再次 GET 此链接\n"""
    prompt_for_user = (
        f"请打开并阅读以下 XCAGI AIOPEN 接入说明，然后帮我完成 MCP 配置并验证连接：\n{guide_url}"
    )
    return {
        "success": True,
        "guide_url": guide_url,
        "base_url": root,
        "endpoints": {
            "guide": guide_url,
            "manifest": manifest_url,
            "mcp": mcp_url,
            "invoke": invoke_url,
            "keys": keys_url,
        },
        "mcp_config_template": mcp_template,
        "install": install,
        "install_url": install_url,
        "cursor_deeplink": url_deeplink,
        "auth_header": "X-AIOPEN-Key",
        "remote_control_enabled": bool(_facade().AIOPEN_STATE.get("remote_control_enabled", False)),
        "screen_sessions_online": len(_facade().aiopen_cursor_hub.session_ids()),
        "prompt_for_user": prompt_for_user,
        "markdown": markdown,
        "instructions_for_ai": [
            "读取本文 markdown 字段或 format=markdown 纯文本",
            "向用户索取连接口令（或确认开发模式无 Key）",
            "将 mcp_config_template 写入用户 MCP 配置并替换 Key",
            "调用 initialize → tools/list 验证",
            "调用 ui_sessions 确认用户浏览器已开启受控屏幕",
            "告知用户配置结果",
        ],
    }


def normalize_api_path(path: str) -> str:
    """规范化 API 路径：去空白、补前导 /、去掉 query 与尾部 /。"""
    raw = str(path or "").strip()
    if not raw:
        return ""
    base = raw.split("?", 1)[0].strip()
    if not base.startswith("/"):
        base = "/" + base
    if len(base) > 1 and base.endswith("/"):
        base = base.rstrip("/")
    return base


def is_path_whitelisted(path: str, whitelist: dict[str, bool] | None = None) -> bool:
    """精确匹配，或命中已启用前缀的子路径（``/api/products`` → ``/api/products/list``）。"""
    wl = whitelist if whitelist is not None else _facade().AIOPEN_STATE.get("whitelist", {})
    if not isinstance(wl, dict):
        return False
    target = _facade().normalize_api_path(path)
    if not target:
        return False
    if bool(wl.get(target, False)):
        return True
    matched_len = -1
    for prefix, enabled in wl.items():
        if not enabled:
            continue
        p = _facade().normalize_api_path(str(prefix or ""))
        if not p:
            continue
        if target == p or target.startswith(p + "/"):
            matched_len = max(matched_len, len(p))
    return matched_len >= 0


def seed_capability_whitelist(
    *, enable: bool = True, merge: bool = True
) -> dict[str, _facade().Any]:
    """一键写入侧栏/业务全能力前缀白名单（全调用闭环默认入口）。"""
    wl = _facade().AIOPEN_STATE.setdefault("whitelist", {})
    if not isinstance(wl, dict):
        wl = {}
        _facade().AIOPEN_STATE["whitelist"] = wl
    if not merge:
        wl.clear()
    for path in _facade().CAPABILITY_ROUTE_PREFIXES:
        wl[path] = bool(enable)
    enabled = sum(1 for v in wl.values() if v)
    return {
        "success": True,
        "enabled": bool(enable),
        "merge": bool(merge),
        "enabled_count": enabled,
        "total_count": len(wl),
        "routes": [{"path": p, "enabled": bool(e)} for p, e in sorted(wl.items())],
    }


def _tool_api_catalog() -> dict[str, _facade().Any]:
    whitelist: dict[str, bool] = _facade().AIOPEN_STATE.get("whitelist", {})
    return {
        "success": True,
        "match_mode": "exact_or_prefix",
        "routes": [{"path": p, "enabled": bool(e)} for p, e in sorted(whitelist.items())],
    }


def _tool_api_call(app: _facade().Any, args: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    from starlette.testclient import TestClient

    raw_path = str(args.get("path") or "").strip()
    method = str(args.get("method") or "GET").upper()
    body = args.get("body") if isinstance(args.get("body"), dict) else {}
    if not raw_path:
        return {"success": False, "message": "path 不能为空"}
    if method not in _facade()._API_CALL_METHODS:
        return {
            "success": False,
            "message": f"不支持的 method：{method}",
            "code": "METHOD_NOT_ALLOWED",
        }
    if not _facade().is_path_whitelisted(raw_path):
        return {
            "success": False,
            "message": f"路由 {_facade().normalize_api_path(raw_path)} 未在 AIOPEN 白名单启用",
            "code": "ROUTE_NOT_WHITELISTED",
        }
    try:
        client = TestClient(app)
        headers: dict[str, str] = {"X-AIOPEN-Internal": "1"}
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            try:
                client.get("/api/aiopen/manifest")
            except _facade().RECOVERABLE_ERRORS:
                pass
            csrf = client.cookies.get("csrf_token")
            if csrf:
                headers["X-CSRF-Token"] = str(csrf)
        if method == "GET":
            resp = client.get(raw_path, headers=headers)
        elif method == "DELETE":
            resp = client.delete(raw_path, headers=headers)
        else:
            payload = dict(body or {})
            payload.setdefault("source", "aiopen")
            resp = client.request(method, raw_path, json=payload, headers=headers)
        try:
            data = resp.json()
        except (ValueError, TypeError):
            data = {"raw": resp.text[:2000]}
        try:
            status_code = int(resp.status_code)
        except (TypeError, ValueError):
            status_code = 599
        return {
            "success": status_code < 500,
            "path": raw_path,
            "method": method,
            "status_code": status_code,
            "data": data,
        }
    except _facade().RECOVERABLE_ERRORS as err:
        return {"success": False, "path": raw_path, "method": method, "message": str(err)}


def _tool_chat(app: _facade().Any, args: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    message = str(args.get("message") or "").strip()
    if not message:
        return {"success": False, "message": "message 不能为空"}
    return _facade()._tool_api_call(
        app,
        {
            "path": "/api/ai/unified_chat",
            "method": "POST",
            "body": {"message": message, "source": "aiopen"},
        },
    )


def _pick_probe_path(routes: list[dict[str, _facade().Any]], preferred: str = "") -> str | None:
    pref = _facade().normalize_api_path(preferred)
    if pref and _facade().is_path_whitelisted(pref):
        return pref
    enabled = [
        _facade().normalize_api_path(str(r.get("path") or ""))
        for r in routes
        if isinstance(r, dict) and r.get("enabled")
    ]
    enabled = [p for p in enabled if p]
    for candidate in (
        "/api/auth/me",
        "/api/products/list",
        "/api/customers/list",
        "/api/mods/",
        "/api/print/printers",
    ):
        n = _facade().normalize_api_path(candidate)
        if any(n == p or n.startswith(p + "/") or p.startswith(n) for p in enabled):
            if _facade().is_path_whitelisted(n):
                return n if n != "/api/mods" else "/api/mods/"
    return enabled[0] if enabled else None


def _tool_capability_loop(
    app: _facade().Any, args: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """catalog → api_call → chat → ui_sessions 闭环自检。"""

    def _step_http_ok(res: dict[str, _facade().Any]) -> bool:
        code = res.get("status_code")
        try:
            status = int(code) if code is not None else 599
        except (TypeError, ValueError):
            status = 599
        return bool(res.get("success")) and status < 400

    steps: list[dict[str, _facade().Any]] = []
    catalog = _facade()._tool_api_catalog()
    routes: list[dict[str, _facade().Any]] = [
        item for item in catalog.get("routes") or [] if isinstance(item, dict)
    ]
    enabled_count = sum(1 for r in routes or [] if isinstance(r, dict) and r.get("enabled"))
    steps.append(
        {
            "step": "api_catalog",
            "ok": bool(catalog.get("success")),
            "enabled_count": enabled_count,
            "total_count": len(routes or []),
        }
    )
    probe = _facade()._pick_probe_path(routes, str(args.get("probe_path") or ""))
    if probe:
        call_res = _facade()._tool_api_call(app, {"path": probe, "method": "GET"})
        steps.append(
            {
                "step": "api_call",
                "ok": _step_http_ok(call_res),
                "path": probe,
                "status_code": call_res.get("status_code"),
                "message": call_res.get("message"),
            }
        )
    else:
        steps.append(
            {
                "step": "api_call",
                "ok": False,
                "message": "无已启用白名单路径可探测；请先 seed 全能力白名单",
            }
        )
    msg = str(args.get("message") or "").strip() or "AIOPEN 全调用闭环探测"
    chat_res = _facade()._tool_chat(app, {"message": msg})
    steps.append(
        {
            "step": "chat",
            "ok": _step_http_ok(chat_res),
            "status_code": chat_res.get("status_code"),
            "message": chat_res.get("message"),
        }
    )
    sessions = _facade().aiopen_cursor_hub.sessions_info()
    remote_on = bool(_facade().AIOPEN_STATE.get("remote_control_enabled", False))
    steps.append(
        {
            "step": "ui_sessions",
            "ok": True,
            "remote_control_enabled": remote_on,
            "session_count": len(sessions),
            "ui_ready": remote_on and len(sessions) > 0,
        }
    )
    core_ok = all(
        bool(s.get("ok")) for s in steps if s.get("step") in {"api_catalog", "api_call", "chat"}
    )
    return {
        "success": core_ok,
        "closed_loop": core_ok,
        "ui_loop_ready": remote_on and len(sessions) > 0,
        "steps": steps,
        "hint": "API/对话闭环已通"
        + ("；虚拟光标已就绪" if remote_on and sessions else "；UI 闭环需面板开启「本页待命」")
        if core_ok
        else "闭环未通过：请检查白名单、鉴权与 unified_chat 是否可写",
    }
