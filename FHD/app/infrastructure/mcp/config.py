"""MCP 服务器配置：默认离线、无配置即停用。

配置文件（``XCAGI_MCP_SERVERS_FILE`` 可覆盖）：

```json
{
  "servers": {
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "env": {},
      "timeout_seconds": 20
    },
    "remote": {
      "transport": "http",
      "url": "https://example.com/mcp",
      "headers": {"Authorization": "Bearer ..."}
    }
  }
}
```
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_ENABLED = "XCAGI_MCP_ENABLED"
_ENV_CONFIG = "XCAGI_MCP_SERVERS_FILE"
_DEFAULT_TIMEOUT = 20.0


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    transport: str = "stdio"
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    auth: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = _DEFAULT_TIMEOUT


def mcp_enabled() -> bool:
    return str(os.environ.get(_ENV_ENABLED) or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def default_config_path() -> Path:
    override = str(os.environ.get(_ENV_CONFIG) or "").strip()
    if override:
        return Path(override).expanduser()
    from app.utils.path_io.path_utils import get_resource_path

    return Path(get_resource_path("config", "mcp_servers.json"))


def _server_config(name: str, raw: object) -> McpServerConfig | None:
    if not isinstance(raw, dict):
        return None
    transport = str(raw.get("transport") or "stdio").strip().lower()
    if transport not in {"stdio", "http"}:
        logger.warning("MCP 服务器 %s 的传输方式不支持：%s", name, transport)
        return None
    command = str(raw.get("command") or "").strip()
    url = str(raw.get("url") or "").strip()
    if transport == "stdio" and not command:
        logger.warning("MCP 服务器 %s 缺少 command", name)
        return None
    if transport == "http" and not url:
        logger.warning("MCP 服务器 %s 缺少 url", name)
        return None
    raw_args = raw.get("args") or []
    args = tuple(str(item) for item in raw_args) if isinstance(raw_args, list) else ()
    raw_env = raw.get("env") or {}
    env = {str(k): str(v) for k, v in raw_env.items()} if isinstance(raw_env, dict) else {}
    raw_headers = raw.get("headers") or {}
    headers = (
        {str(k): str(v) for k, v in raw_headers.items()} if isinstance(raw_headers, dict) else {}
    )
    raw_auth = raw.get("auth") or {}
    auth = {str(k): str(v) for k, v in raw_auth.items()} if isinstance(raw_auth, dict) else {}
    if auth and not (auth.get("token_url") and auth.get("client_id")):
        logger.warning("MCP 服务器 %s 的 auth 配置缺少 token_url/client_id", name)
        auth = {}
    try:
        timeout = float(raw.get("timeout_seconds") or _DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT
    return McpServerConfig(
        name=name,
        transport=transport,
        command=command,
        args=args,
        env=env,
        url=url,
        headers=headers,
        auth=auth,
        timeout_seconds=max(1.0, min(120.0, timeout)),
    )


def load_server_configs(path: Path | None = None) -> list[McpServerConfig]:
    """读取并校验服务器配置；文件缺失或损坏时返回空列表。"""
    if not mcp_enabled():
        return []
    target = path or default_config_path()
    if not target.is_file():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("MCP 配置读取失败（已停用外部工具）：%s", exc)
        return []
    raw_servers = payload.get("servers") if isinstance(payload, dict) else None
    if not isinstance(raw_servers, dict):
        return []
    configs: list[McpServerConfig] = []
    for name, raw in raw_servers.items():
        config = _server_config(str(name), raw)
        if config is not None:
            configs.append(config)
    return configs


__all__ = [
    "McpServerConfig",
    "default_config_path",
    "load_server_configs",
    "mcp_enabled",
]
