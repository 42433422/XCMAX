# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.aiopen.service')

def _default_capability_whitelist() -> dict[str, bool]:
    return dict.fromkeys(_facade().CAPABILITY_ROUTE_PREFIXES, True)

def _env_api_key() -> str:
    return (_facade().os.environ.get('AIOPEN_API_KEY') or '').strip()

def verify_api_key(provided: str | None) -> bool:
    """校验 ``X-AIOPEN-Key``。

    未配置任何 Key（env 与运行时均为空）时放行 —— 与
    :func:`app.fastapi_routes.business_api.require_fhd_business_key` 同策略，
    安全由 LAN 门禁兜底；生产务必配置 ``AIOPEN_API_KEY``。
    """
    env_key = _facade()._env_api_key()
    runtime_keys: dict[str, _facade().Any] = _facade().AIOPEN_STATE.get('runtime_keys', {})
    if not env_key and (not runtime_keys):
        return True
    got = (provided or '').strip()
    if not got:
        return False
    if env_key and _facade().secrets.compare_digest(got, env_key):
        return True
    return got in runtime_keys

def generate_api_key(label: str='') -> dict[str, _facade().Any]:
    key = 'aiopen_' + _facade().secrets.token_urlsafe(24)
    entry = {'label': (label or '').strip() or '未命名', 'created_at': _facade().time.time()}
    _facade().AIOPEN_STATE.setdefault('runtime_keys', {})[key] = entry
    return {'key': key, **entry}

def revoke_api_key(key: str) -> bool:
    return _facade().AIOPEN_STATE.setdefault('runtime_keys', {}).pop((key or '').strip(), None) is not None

def list_api_keys() -> list[dict[str, _facade().Any]]:
    """脱敏列出 Key（仅前 12 位 + label）。"""
    out: list[dict[str, _facade().Any]] = []
    if _facade()._env_api_key():
        out.append({'key_preview': 'env:AIOPEN_API_KEY', 'label': '环境变量', 'created_at': None})
    for (key, meta) in _facade().AIOPEN_STATE.get('runtime_keys', {}).items():
        out.append({'key_preview': key[:12] + '…', 'label': meta.get('label', ''), 'created_at': meta.get('created_at')})
    return out

def _repo_stdio_bridge_path() -> str:
    """stdio 桥脚本绝对路径（供 Cursor command/args 配置）。"""
    here = _facade().Path(__file__).resolve()
    bridge = here.parents[3] / 'scripts' / 'dev' / 'aiopen_mcp_stdio.py'
    return str(bridge)

def build_mcp_url_config(base_url: str, api_key: str='') -> dict[str, _facade().Any]:
    """Cursor 原生 HTTP MCP 配置（url + headers）。"""
    root = str(base_url or '').rstrip('/')
    cfg: dict[str, _facade().Any] = {'url': f'{root}/api/aiopen/mcp'}
    key = str(api_key or '').strip()
    if key:
        cfg['headers'] = {'X-AIOPEN-Key': key}
    return cfg

def build_mcp_stdio_config(base_url: str, api_key: str='') -> dict[str, _facade().Any]:
    """Python stdio 桥配置（无需 npx，适合 Claude Desktop）。"""
    env: dict[str, str] = {'AIOPEN_BASE_URL': str(base_url or '').rstrip('/')}
    key = str(api_key or '').strip()
    if key:
        env['AIOPEN_API_KEY'] = key
    return {'command': 'python3', 'args': [_facade()._repo_stdio_bridge_path()], 'env': env}

def build_mcp_remote_config(base_url: str, api_key: str='') -> dict[str, _facade().Any]:
    """npx mcp-remote 配置（业界常用，Cursor / Claude 均支持）。"""
    root = str(base_url or '').rstrip('/')
    args = ['-y', 'mcp-remote', f'{root}/api/aiopen/mcp']
    key = str(api_key or '').strip()
    if key:
        args.extend(['--header', f'X-AIOPEN-Key:{key}'])
    return {'command': 'npx', 'args': args}

def build_cursor_deeplink(server_name: str, server_config: dict[str, _facade().Any]) -> str:
    """生成 Cursor 一键安装 deep link（base64(JSON)）。"""
    config_b64 = _facade().base64.b64encode(_facade().json.dumps(server_config, ensure_ascii=False).encode('utf-8')).decode('ascii')
    return f"cursor://anysphere.cursor-deeplink/mcp/install?name={_facade().quote(server_name, safe='')}&config={_facade().quote(config_b64, safe='')}"

def build_mcp_install_bundle(base_url: str, api_key: str='') -> dict[str, _facade().Any]:
    """面板 / guide 共用的 MCP 安装包（多种 AI 客户端 + 传输方式）。"""
    root = str(base_url or '').rstrip('/')
    url_cfg = _facade().build_mcp_url_config(root, api_key)
    stdio_cfg = _facade().build_mcp_stdio_config(root, api_key)
    remote_cfg = _facade().build_mcp_remote_config(root, api_key)
    script_path = _facade()._repo_stdio_bridge_path()

    def _client_entry(cid: str, name: str, icon: str, config_path: str, hint: str, transport: str, server_cfg: dict[str, _facade().Any], *, install_mode: str='copy', cursor_deeplink: str | None=None, web_install_url: str | None=None) -> dict[str, _facade().Any]:
        entry: dict[str, _facade().Any] = {'id': cid, 'name': name, 'icon': icon, 'config_path': config_path, 'hint': hint, 'transport': transport, 'install_mode': install_mode, 'mcp_json': _facade().json.dumps({'mcpServers': {_facade().MCP_SERVER_NAME: server_cfg}}, ensure_ascii=False, indent=2), 'config': server_cfg}
        if cursor_deeplink:
            entry['cursor_deeplink'] = cursor_deeplink
        if web_install_url:
            entry['web_install_url'] = web_install_url
        return entry
    cursor_dl = _facade().build_cursor_deeplink(_facade().MCP_SERVER_NAME, url_cfg)
    cursor_web = f"https://cursor.com/en/install-mcp?name={_facade().quote(_facade().MCP_SERVER_NAME, safe='')}&config={_facade().quote(_facade().base64.b64encode(_facade().json.dumps(url_cfg, ensure_ascii=False).encode()).decode(), safe='')}"
    clients = [_client_entry('cursor', 'Cursor', '◆', '~/.cursor/mcp.json', '点一下自动写入 MCP 配置', 'url', url_cfg, install_mode='deeplink', cursor_deeplink=cursor_dl, web_install_url=cursor_web), _client_entry('claude', 'Claude', '✳', 'claude_desktop_config.json', '复制后粘贴到 Claude Desktop → 设置 → MCP', 'mcp_remote', remote_cfg), _client_entry('vscode', 'VS Code', '▣', 'MCP 扩展 · 用户 settings', '需安装 MCP 扩展；也可复制 JSON 手动添加', 'mcp_remote', remote_cfg, install_mode='vscode'), _client_entry('windsurf', 'Windsurf', '≋', '~/.codeium/windsurf/mcp_config.json', '与 Cursor 相同 url 格式，复制后写入配置文件', 'url', url_cfg), _client_entry('trae', 'Trae', '◎', 'Trae → MCP 服务器设置', '字节 Trae IDE，粘贴 mcpServers JSON', 'url', url_cfg), _client_entry('generic', '其他', '⋯', '任意支持 MCP 的 AI 客户端', 'Cherry Studio / Chatbox / Open WebUI 等通用 JSON', 'mcp_remote', remote_cfg)]
    return {'server_name': _facade().MCP_SERVER_NAME, 'mcp_url': f'{root}/api/aiopen/mcp', 'recommended': 'url', 'clients': clients, 'methods': {'url': {'label': 'Cursor 直连（推荐）', 'description': '写入 ~/.cursor/mcp.json 的 url 字段，Cursor 2025+ 原生支持', 'config': url_cfg, 'cursor_deeplink': cursor_dl, 'web_install_url': cursor_web}, 'mcp_remote': {'label': 'npx mcp-remote（通用）', 'description': '与 Notion、Asana 等远程 MCP 相同模式，适合 Claude Desktop', 'config': remote_cfg, 'cursor_deeplink': _facade().build_cursor_deeplink(_facade().MCP_SERVER_NAME, remote_cfg)}, 'stdio': {'label': 'Python stdio 桥', 'description': '无需 npx，本地 Python 转发到 HTTP', 'config': stdio_cfg, 'script_path': script_path, 'cursor_deeplink': _facade().build_cursor_deeplink(_facade().MCP_SERVER_NAME, stdio_cfg)}}, 'mcp_config_template': {'mcpServers': {_facade().MCP_SERVER_NAME: url_cfg}}}

def format_tool_result_text(tool_name: str, result: dict[str, _facade().Any]) -> str:
    """将工具执行结果格式化为 Agent 易读文本（MCP tools/call content）。"""
    name = str(tool_name or '').strip()
    ok = bool(result.get('success', False))
    if name == 'api_catalog':
        raw_routes = result.get('routes')
        routes: list[_facade().Any] = list(raw_routes) if isinstance(raw_routes, list) else []
        enabled = [r for r in routes or [] if isinstance(r, dict) and r.get('enabled')]
        lines = [f'AIOPEN 白名单 API（{len(enabled or [])}/{len(routes)} 已启用）：']
        for r in routes or []:
            if not isinstance(r, dict):
                continue
            mark = '✓' if r.get('enabled') else '·'
            lines.append(f"  {mark} {r.get('path', '')}")
        return '\n'.join(lines)
    if name == 'api_call':
        path = result.get('path', '')
        method = result.get('method', 'GET')
        status = result.get('status_code', '?')
        if not ok:
            return f"API 调用失败：{method} {path}\n{result.get('message', '')}"
        data = result.get('data')
        body = _facade().json.dumps(data, ensure_ascii=False, indent=2, default=str) if data is not None else '(empty)'
        if len(body) > 4000:
            body = body[:4000] + '\n…(truncated)'
        return f'API 调用成功：{method} {path} → HTTP {status}\n\n{body}'
    if name == 'capability_loop':
        raw_steps = result.get('steps')
        steps: list[_facade().Any] = list(raw_steps) if isinstance(raw_steps, list) else []
        lines = [f"全调用闭环：{('通过' if ok else '未通过')}", f"提示：{result.get('hint', '')}"]
        for s in steps or []:
            if not isinstance(s, dict):
                continue
            mark = '✓' if s.get('ok') else '✗'
            extra = ''
            if s.get('path'):
                extra += f" {s.get('path')}"
            if s.get('status_code') is not None:
                extra += f" HTTP {s.get('status_code')}"
            if s.get('session_count') is not None:
                extra += f" sessions={s.get('session_count')}"
            lines.append(f"  {mark} {s.get('step')}{extra}")
        return '\n'.join(lines)
    if name == 'chat':
        if not ok:
            return f"对话失败：{result.get('message', '')}"
        data = result.get('data') if isinstance(result.get('data'), dict) else result
        reply = ''
        if isinstance(data, dict):
            reply = str(data.get('reply') or data.get('message') or data.get('content') or '')
        if not reply:
            reply = _facade().json.dumps(data, ensure_ascii=False, default=str)[:2000]
        return f'XCAGI 助手回复：\n{reply}'
    if name == 'ui_sessions':
        raw_sessions = result.get('sessions')
        sessions: list[_facade().Any] = list(raw_sessions) if isinstance(raw_sessions, list) else []
        if not sessions:
            return '当前无在线虚拟光标会话。\n请让用户在 XCAGI 打开 AIOPEN 面板并开启「本页待命」。'
        lines = [f'在线 screen 会话 {len(sessions)} 个：']
        for s in sessions:
            if not isinstance(s, dict):
                continue
            lines.append(f"  · {s.get('session_id', '?')} — {s.get('label', 'XCAGI 前端')}")
        return '\n'.join(lines)
    if name == 'ui_snapshot':
        if not ok:
            return f"页面快照失败：{result.get('message', '')}"
        url = result.get('url') or result.get('page_url') or ''
        title = result.get('title') or result.get('page_title') or ''
        raw_elements = result.get('elements')
        elements: list[_facade().Any] = list(raw_elements) if isinstance(raw_elements, list) else []
        lines = [f"页面：{title or '(无标题)'}", f"URL：{url or '(未知)'}", f'可交互元素 {len(elements or [])} 个：']
        for el in elements[:40]:
            if not isinstance(el, dict):
                continue
            sel = el.get('selector') or el.get('ref') or '?'
            text = str(el.get('text') or el.get('label') or '')[:60]
            role = el.get('role') or el.get('tag') or ''
            lines.append(f'  · [{role}] {text!r} → {sel}')
        if len(elements or []) > 40:
            lines.append(f'  … 另有 {len(elements or []) - 40} 个元素')
        return '\n'.join(lines)
    if name in {'ui_click', 'ui_type', 'ui_navigate', 'ui_scroll'}:
        if not ok:
            return f"{name} 失败：{result.get('message', '')}"
        detail = result.get('message') or result.get('detail') or '操作已执行'
        extra_data = {key: value for (key, value) in result.items() if key not in {'success', 'message', 'detail'}}
        if extra_data:
            return f'{detail}\n{_facade().json.dumps(extra_data, ensure_ascii=False, default=str)}'
        return str(detail)
    if not ok:
        return f"工具 {name} 失败：{result.get('message', result.get('code', 'unknown error'))}"
    return _facade().json.dumps(result, ensure_ascii=False, indent=2, default=str)

def aiopen_manifest() -> dict[str, _facade().Any]:
    return {'name': _facade().AIOPEN_PRODUCT_NAME, 'tagline': _facade().AIOPEN_PRODUCT_TAGLINE, 'version': '1.0.0.1', 'protocol': {'guide': '/api/aiopen/guide', 'mcp': '/api/aiopen/mcp', 'rest_invoke': '/api/aiopen/invoke', 'ws_screen': '/api/aiopen/ws', 'auth_header': 'X-AIOPEN-Key'}, 'tools': [{k: v for (k, v) in tool.items() if k in ('name', 'description', 'inputSchema')} for tool in _facade().TOOL_DEFINITIONS]}

def build_aiopen_guide(base_url: str) -> dict[str, _facade().Any]:
    """生成可供外部 AI 自行阅读的接入说明（``GET /api/aiopen/guide`` SSOT）。"""
    root = str(base_url or '').rstrip('/')
    mcp_url = f'{root}/api/aiopen/mcp'
    invoke_url = f'{root}/api/aiopen/invoke'
    manifest_url = f'{root}/api/aiopen/manifest'
    guide_url = f'{root}/api/aiopen/guide'
    keys_url = f'{root}/api/aiopen/keys'
    install_url = f'{root}/api/aiopen/install'
    install = _facade().build_mcp_install_bundle(root)
    mcp_template = install['mcp_config_template']
    url_deeplink = install['methods']['url']['cursor_deeplink']
    remote_cfg = install['methods']['mcp_remote']['config']
    remote_template = _facade().json.dumps({'mcpServers': {_facade().MCP_SERVER_NAME: remote_cfg}}, ensure_ascii=False, indent=2)
    tool_lines = '\n'.join((f"- **{t['name']}**：{t['description']}" for t in _facade().TOOL_DEFINITIONS))
    markdown = f"""# XCAGI AIOPEN 接入说明（给 AI 阅读）\n\n你是即将接入 XCAGI 的 AI Agent。请阅读本文并完成 MCP 配置，然后告知用户配置结果。\n\n## 产品\n\n- 名称：**{_facade().AIOPEN_PRODUCT_NAME}** — {_facade().AIOPEN_PRODUCT_TAGLINE}\n- 版本：1.0.0.1（稳定版）\n\n## 前置条件（请提醒用户）\n\n1. 用户在 XCAGI 前端打开 **AI生态应用 → AIOPEN 开放智控**\n2. 用户点击 **「一键开启 AI 操控」**（或手动开启远程操控 + 本浏览器受控屏幕）\n3. 用户在本面板 **「获取连接口令」** 后将口令提供给你（开发模式无 Key 时可留空）\n\n当前服务端远程操控：{('已开启' if _facade().AIOPEN_STATE.get('remote_control_enabled') else '未开启')}\n在线虚拟光标会话数：{len(_facade().aiopen_cursor_hub.session_ids())}\n\n## 端点（基于请求来源 `{root}`）\n\n| 用途 | URL |\n|------|-----|\n| **本说明（你正在读的）** | `{guide_url}` |\n| 工具目录 JSON | `{manifest_url}` |\n| MCP 接入（推荐） | `{mcp_url}` |\n| REST 通用调用 | `{invoke_url}` |\n| 生成运行时 Key（POST） | `{keys_url}` |\n\n鉴权请求头：`X-AIOPEN-Key: <连接口令>`（未配置任何 Key 时开发模式可省略）\n\n## 你的配置任务（MCP）\n\n**方式 A（推荐 · Cursor 一键）**：让用户在 AIOPEN 面板点「在 Cursor 中安装」，或打开 deep link：\n\n`{url_deeplink}`\n\n**方式 B（手动 JSON）**：写入 `~/.cursor/mcp.json`：\n\n```json\n{_facade().json.dumps(mcp_template, ensure_ascii=False, indent=2)}\n```\n\n将连接口令填入 `X-AIOPEN-Key`（向用户索取或在面板生成）。\n\n**方式 C（npx mcp-remote · 与 Notion/Asana 同款）**：\n\n```json\n{remote_template}\n```\n\n完整安装选项：`GET {install_url}`\n\n### MCP 协议\n\n- 传输：Streamable HTTP — POST JSON-RPC 2.0 到 `{mcp_url}`\n- 支持方法：`initialize`、`tools/list`、`tools/call`、`ping`、`notifications/initialized`\n- 响应头：`MCP-Protocol-Version`、`Mcp-Session-Id`\n- 请求头：`Content-Type: application/json`，以及 `X-AIOPEN-Key`（若已配置）\n\n### 验证步骤\n\n1. `initialize` → 应返回 serverInfo.name = AIOPEN\n2. `tools/list` → 应返回 9 个工具（含 ui_snapshot、ui_click、chat 等）\n3. `tools/call` name=`ui_sessions` → 确认有在线 screen 会话（用户须保持浏览器打开）\n4. `tools/call` name=`ui_snapshot` → 读取当前页面可交互元素\n5. 按需 `ui_click` / `ui_type` / `ui_navigate` 操作页面\n\n## REST 备选\n\n```bash\ncurl -X POST '{invoke_url}' \\\n  -H 'Content-Type: application/json' \\\n  -H 'X-AIOPEN-Key: <连接口令>' \\\n  -d '{{"tool": "chat", "args": {{"message": "你好"}}}}'\n```\n\n## 可用工具\n\n{tool_lines}\n\n## 虚拟光标操作流程\n\n1. `ui_sessions` — 确认有在线会话\n2. `ui_snapshot` — 获取 selector / 可见文本\n3. `ui_click` — 点击（参数 selector 或 text）\n4. `ui_type` — 输入（selector + text）\n5. `ui_navigate` — 跳转路由 path\n6. `ui_scroll` — 滚动\n\n## 完成后请告诉用户\n\n- MCP 是否配置成功\n- tools/list 工具数量\n- 是否检测到在线 screen 会话\n- 若失败：是否缺少连接口令、用户是否已一键开启、后端是否已重启\n\n---\n文档 URL：{guide_url} · 重新获取最新说明请再次 GET 此链接\n"""
    prompt_for_user = f'请打开并阅读以下 XCAGI AIOPEN 接入说明，然后帮我完成 MCP 配置并验证连接：\n{guide_url}'
    return {'success': True, 'guide_url': guide_url, 'base_url': root, 'endpoints': {'guide': guide_url, 'manifest': manifest_url, 'mcp': mcp_url, 'invoke': invoke_url, 'keys': keys_url}, 'mcp_config_template': mcp_template, 'install': install, 'install_url': install_url, 'cursor_deeplink': url_deeplink, 'auth_header': 'X-AIOPEN-Key', 'remote_control_enabled': bool(_facade().AIOPEN_STATE.get('remote_control_enabled', False)), 'screen_sessions_online': len(_facade().aiopen_cursor_hub.session_ids()), 'prompt_for_user': prompt_for_user, 'markdown': markdown, 'instructions_for_ai': ['读取本文 markdown 字段或 format=markdown 纯文本', '向用户索取连接口令（或确认开发模式无 Key）', '将 mcp_config_template 写入用户 MCP 配置并替换 Key', '调用 initialize → tools/list 验证', '调用 ui_sessions 确认用户浏览器已开启受控屏幕', '告知用户配置结果']}

def normalize_api_path(path: str) -> str:
    """规范化 API 路径：去空白、补前导 /、去掉 query 与尾部 /。"""
    raw = str(path or '').strip()
    if not raw:
        return ''
    base = raw.split('?', 1)[0].strip()
    if not base.startswith('/'):
        base = '/' + base
    if len(base) > 1 and base.endswith('/'):
        base = base.rstrip('/')
    return base

def is_path_whitelisted(path: str, whitelist: dict[str, bool] | None=None) -> bool:
    """精确匹配，或命中已启用前缀的子路径（``/api/products`` → ``/api/products/list``）。"""
    wl = whitelist if whitelist is not None else _facade().AIOPEN_STATE.get('whitelist', {})
    if not isinstance(wl, dict):
        return False
    target = _facade().normalize_api_path(path)
    if not target:
        return False
    if bool(wl.get(target, False)):
        return True
    matched_len = -1
    for (prefix, enabled) in wl.items():
        if not enabled:
            continue
        p = _facade().normalize_api_path(str(prefix or ''))
        if not p:
            continue
        if target == p or target.startswith(p + '/'):
            matched_len = max(matched_len, len(p))
    return matched_len >= 0

def seed_capability_whitelist(*, enable: bool=True, merge: bool=True) -> dict[str, _facade().Any]:
    """一键写入侧栏/业务全能力前缀白名单（全调用闭环默认入口）。"""
    wl = _facade().AIOPEN_STATE.setdefault('whitelist', {})
    if not isinstance(wl, dict):
        wl = {}
        _facade().AIOPEN_STATE['whitelist'] = wl
    if not merge:
        wl.clear()
    for path in _facade().CAPABILITY_ROUTE_PREFIXES:
        wl[path] = bool(enable)
    enabled = sum((1 for v in wl.values() if v))
    return {'success': True, 'enabled': bool(enable), 'merge': bool(merge), 'enabled_count': enabled, 'total_count': len(wl), 'routes': [{'path': p, 'enabled': bool(e)} for (p, e) in sorted(wl.items())]}

def _tool_api_catalog() -> dict[str, _facade().Any]:
    whitelist: dict[str, bool] = _facade().AIOPEN_STATE.get('whitelist', {})
    return {'success': True, 'match_mode': 'exact_or_prefix', 'routes': [{'path': p, 'enabled': bool(e)} for (p, e) in sorted(whitelist.items())]}

def _tool_api_call(app: _facade().Any, args: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    from starlette.testclient import TestClient
    raw_path = str(args.get('path') or '').strip()
    method = str(args.get('method') or 'GET').upper()
    body = args.get('body') if isinstance(args.get('body'), dict) else {}
    if not raw_path:
        return {'success': False, 'message': 'path 不能为空'}
    if method not in _facade()._API_CALL_METHODS:
        return {'success': False, 'message': f'不支持的 method：{method}', 'code': 'METHOD_NOT_ALLOWED'}
    if not _facade().is_path_whitelisted(raw_path):
        return {'success': False, 'message': f'路由 {_facade().normalize_api_path(raw_path)} 未在 AIOPEN 白名单启用', 'code': 'ROUTE_NOT_WHITELISTED'}
    try:
        client = TestClient(app)
        headers: dict[str, str] = {'X-AIOPEN-Internal': '1'}
        if method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            try:
                client.get('/api/aiopen/manifest')
            except _facade().RECOVERABLE_ERRORS:
                pass
            csrf = client.cookies.get('csrf_token')
            if csrf:
                headers['X-CSRF-Token'] = str(csrf)
        if method == 'GET':
            resp = client.get(raw_path, headers=headers)
        elif method == 'DELETE':
            resp = client.delete(raw_path, headers=headers)
        else:
            payload = dict(body or {})
            payload.setdefault('source', 'aiopen')
            resp = client.request(method, raw_path, json=payload, headers=headers)
        try:
            data = resp.json()
        except (ValueError, TypeError):
            data = {'raw': resp.text[:2000]}
        try:
            status_code = int(resp.status_code)
        except (TypeError, ValueError):
            status_code = 599
        return {'success': status_code < 500, 'path': raw_path, 'method': method, 'status_code': status_code, 'data': data}
    except _facade().RECOVERABLE_ERRORS as err:
        return {'success': False, 'path': raw_path, 'method': method, 'message': str(err)}

def _tool_chat(app: _facade().Any, args: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    message = str(args.get('message') or '').strip()
    if not message:
        return {'success': False, 'message': 'message 不能为空'}
    return _facade()._tool_api_call(app, {'path': '/api/ai/unified_chat', 'method': 'POST', 'body': {'message': message, 'source': 'aiopen'}})

def _pick_probe_path(routes: list[dict[str, _facade().Any]], preferred: str='') -> str | None:
    pref = _facade().normalize_api_path(preferred)
    if pref and _facade().is_path_whitelisted(pref):
        return pref
    enabled = [_facade().normalize_api_path(str(r.get('path') or '')) for r in routes if isinstance(r, dict) and r.get('enabled')]
    enabled = [p for p in enabled if p]
    for candidate in ('/api/auth/me', '/api/products/list', '/api/customers/list', '/api/mods/', '/api/print/printers'):
        n = _facade().normalize_api_path(candidate)
        if any((n == p or n.startswith(p + '/') or p.startswith(n) for p in enabled)):
            if _facade().is_path_whitelisted(n):
                return n if n != '/api/mods' else '/api/mods/'
    return enabled[0] if enabled else None

def _tool_capability_loop(app: _facade().Any, args: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """catalog → api_call → chat → ui_sessions 闭环自检。"""

    def _step_http_ok(res: dict[str, _facade().Any]) -> bool:
        code = res.get('status_code')
        try:
            status = int(code) if code is not None else 599
        except (TypeError, ValueError):
            status = 599
        return bool(res.get('success')) and status < 400
    steps: list[dict[str, _facade().Any]] = []
    catalog = _facade()._tool_api_catalog()
    routes: list[dict[str, _facade().Any]] = [item for item in catalog.get('routes') or [] if isinstance(item, dict)]
    enabled_count = sum((1 for r in routes or [] if isinstance(r, dict) and r.get('enabled')))
    steps.append({'step': 'api_catalog', 'ok': bool(catalog.get('success')), 'enabled_count': enabled_count, 'total_count': len(routes or [])})
    probe = _facade()._pick_probe_path(routes, str(args.get('probe_path') or ''))
    if probe:
        call_res = _facade()._tool_api_call(app, {'path': probe, 'method': 'GET'})
        steps.append({'step': 'api_call', 'ok': _step_http_ok(call_res), 'path': probe, 'status_code': call_res.get('status_code'), 'message': call_res.get('message')})
    else:
        steps.append({'step': 'api_call', 'ok': False, 'message': '无已启用白名单路径可探测；请先 seed 全能力白名单'})
    msg = str(args.get('message') or '').strip() or 'AIOPEN 全调用闭环探测'
    chat_res = _facade()._tool_chat(app, {'message': msg})
    steps.append({'step': 'chat', 'ok': _step_http_ok(chat_res), 'status_code': chat_res.get('status_code'), 'message': chat_res.get('message')})
    sessions = _facade().aiopen_cursor_hub.sessions_info()
    remote_on = bool(_facade().AIOPEN_STATE.get('remote_control_enabled', False))
    steps.append({'step': 'ui_sessions', 'ok': True, 'remote_control_enabled': remote_on, 'session_count': len(sessions), 'ui_ready': remote_on and len(sessions) > 0})
    core_ok = all((bool(s.get('ok')) for s in steps if s.get('step') in {'api_catalog', 'api_call', 'chat'}))
    return {'success': core_ok, 'closed_loop': core_ok, 'ui_loop_ready': remote_on and len(sessions) > 0, 'steps': steps, 'hint': 'API/对话闭环已通' + ('；虚拟光标已就绪' if remote_on and sessions else '；UI 闭环需面板开启「本页待命」') if core_ok else '闭环未通过：请检查白名单、鉴权与 unified_chat 是否可写'}

async def invoke_tool(name: str, args: dict[str, _facade().Any] | None, app: _facade().Any) -> dict[str, _facade().Any]:
    """统一工具执行入口（MCP tools/call 与 REST invoke 共用）。"""
    args = args if isinstance(args, dict) else {}
    name = str(name or '').strip()
    if name == 'api_catalog':
        return _facade()._tool_api_catalog()
    if name == 'api_call':
        return _facade()._tool_api_call(app, args)
    if name == 'chat':
        return _facade()._tool_chat(app, args)
    if name == 'capability_loop':
        return _facade()._tool_capability_loop(app, args)
    if name == 'ui_sessions':
        return {'success': True, 'remote_control_enabled': bool(_facade().AIOPEN_STATE.get('remote_control_enabled', False)), 'sessions': _facade().aiopen_cursor_hub.sessions_info()}
    if name in _facade()._UI_ACTIONS:
        if not _facade().AIOPEN_STATE.get('remote_control_enabled', False):
            return {'success': False, 'message': '远程操控总开关已关闭（AIOPEN 面板可开启）', 'code': 'REMOTE_CONTROL_DISABLED'}
        session_id = str(args.get('session_id') or '') or None
        params = {k: v for (k, v) in args.items() if k != 'session_id'}
        return await _facade().aiopen_cursor_hub.dispatch(_facade()._UI_ACTIONS[name], params, session_id=session_id, timeout=_facade()._UI_TOOL_TIMEOUT_SECONDS)
    return {'success': False, 'message': f'未知工具：{name}', 'code': 'UNKNOWN_TOOL'}
