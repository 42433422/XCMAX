"""MCP connection formats and client installation bundles."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from .protocols import InstallationBuilders


def build_mcp_url_config(base_url: str, api_key: str = "") -> dict[str, Any]:
    """Cursor 原生 HTTP MCP 配置（url + headers）。"""
    root = str(base_url or "").rstrip("/")
    cfg: dict[str, Any] = {"url": f"{root}/api/aiopen/mcp"}
    key = str(api_key or "").strip()
    if key:
        cfg["headers"] = {"X-AIOPEN-Key": key}
    return cfg


def build_mcp_remote_config(base_url: str, api_key: str = "") -> dict[str, Any]:
    """npx mcp-remote 配置（业界常用，Cursor / Claude 均支持）。"""
    root = str(base_url or "").rstrip("/")
    args = ["-y", "mcp-remote", f"{root}/api/aiopen/mcp"]
    key = str(api_key or "").strip()
    if key:
        args.extend(["--header", f"X-AIOPEN-Key:{key}"])
    return {"command": "npx", "args": args}


def build_cursor_deeplink(server_name: str, server_config: dict[str, Any]) -> str:
    """生成 Cursor 一键安装 deep link（base64(JSON)）。"""
    config_b64 = base64.b64encode(
        json.dumps(server_config, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    return f"cursor://anysphere.cursor-deeplink/mcp/install?name={quote(server_name, safe='')}&config={quote(config_b64, safe='')}"


class InstallationComposer:
    def __init__(
        self, server_name: str, bridge_path: Callable[[], str], builders: InstallationBuilders
    ) -> None:
        self._server_name = server_name
        self._bridge_path = bridge_path
        self._builders = builders

    def stdio(self, base_url: str, api_key: str = "") -> dict[str, Any]:
        """Python stdio 桥配置（无需 npx，适合 Claude Desktop）。"""
        env: dict[str, str] = {"AIOPEN_BASE_URL": str(base_url or "").rstrip("/")}
        key = str(api_key or "").strip()
        if key:
            env["AIOPEN_API_KEY"] = key
        return {"command": "python3", "args": [self._bridge_path()], "env": env}

    def bundle(self, base_url: str, api_key: str = "") -> dict[str, Any]:
        """面板 / guide 共用的 MCP 安装包（多种 AI 客户端 + 传输方式）。"""
        root = str(base_url or "").rstrip("/")
        url_cfg = self._builders.url(root, api_key)
        stdio_cfg = self._builders.stdio(root, api_key)
        remote_cfg = self._builders.remote(root, api_key)
        script_path = self._bridge_path()

        def _client_entry(
            cid: str,
            name: str,
            icon: str,
            config_path: str,
            hint: str,
            transport: str,
            server_cfg: dict[str, Any],
            *,
            install_mode: str = "copy",
            cursor_deeplink: str | None = None,
            web_install_url: str | None = None,
        ) -> dict[str, Any]:
            entry: dict[str, Any] = {
                "id": cid,
                "name": name,
                "icon": icon,
                "config_path": config_path,
                "hint": hint,
                "transport": transport,
                "install_mode": install_mode,
                "mcp_json": json.dumps(
                    {"mcpServers": {self._server_name: server_cfg}},
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

        cursor_dl = self._builders.deeplink(self._server_name, url_cfg)
        cursor_web = f"https://cursor.com/en/install-mcp?name={quote(self._server_name, safe='')}&config={quote(base64.b64encode(json.dumps(url_cfg, ensure_ascii=False).encode()).decode(), safe='')}"
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
            "server_name": self._server_name,
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
                    "cursor_deeplink": self._builders.deeplink(self._server_name, remote_cfg),
                },
                "stdio": {
                    "label": "Python stdio 桥",
                    "description": "无需 npx，本地 Python 转发到 HTTP",
                    "config": stdio_cfg,
                    "script_path": script_path,
                    "cursor_deeplink": self._builders.deeplink(self._server_name, stdio_cfg),
                },
            },
            "mcp_config_template": {"mcpServers": {self._server_name: url_cfg}},
        }
