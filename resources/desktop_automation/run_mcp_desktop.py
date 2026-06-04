#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用桌面自动化 MCP stdio 服务。"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# 确保 FHD 在 path
_FHD = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _FHD not in sys.path:
    sys.path.insert(0, _FHD)

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool
except ImportError as exc:
    raise SystemExit("需要安装 mcp: pip install mcp") from exc

from app.desktop_automation.service import get_desktop_automation_service

server = Server("DesktopAutomation")
svc = get_desktop_automation_service()


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="desktop_list_profiles",
            description="列出已注册的 AppProfile",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="desktop_bootstrap_app",
            description="VLM/启发式切图建模板库",
            inputSchema={
                "type": "object",
                "properties": {"app_id": {"type": "string"}},
                "required": ["app_id"],
            },
        ),
        Tool(
            name="desktop_run_workflow",
            description="执行 AppProfile workflow",
            inputSchema={
                "type": "object",
                "properties": {
                    "app_id": {"type": "string"},
                    "workflow": {"type": "string"},
                    "params": {"type": "object"},
                },
                "required": ["app_id", "workflow"],
            },
        ),
        Tool(
            name="desktop_find_element",
            description="调试：定位 UI 元素屏幕坐标",
            inputSchema={
                "type": "object",
                "properties": {"app_id": {"type": "string"}, "element_id": {"type": "string"}},
                "required": ["app_id", "element_id"],
            },
        ),
        Tool(
            name="desktop_send_message",
            description="向 App 联系人/群发送消息（默认 wechat）",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_name": {"type": "string"},
                    "message": {"type": "string"},
                    "app_id": {"type": "string"},
                },
                "required": ["contact_name", "message"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    args = arguments or {}
    if name == "desktop_list_profiles":
        out = {"profiles": svc.list_profiles()}
    elif name == "desktop_bootstrap_app":
        out = await svc.bootstrap_app(str(args.get("app_id") or ""))
    elif name == "desktop_run_workflow":
        out = svc.run_workflow(
            str(args.get("app_id") or ""),
            str(args.get("workflow") or ""),
            dict(args.get("params") or {}),
        )
    elif name == "desktop_find_element":
        out = svc.find_element(str(args.get("app_id") or ""), str(args.get("element_id") or ""))
    elif name == "desktop_send_message":
        out = svc.send_wechat_message(
            str(args.get("contact_name") or ""),
            str(args.get("message") or ""),
            app_id=str(args.get("app_id") or "wechat"),
        )
    else:
        out = {"success": False, "error": f"unknown tool: {name}"}
    return [TextContent(type="text", text=json.dumps(out, ensure_ascii=False))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
