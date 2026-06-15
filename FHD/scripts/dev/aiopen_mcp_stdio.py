#!/usr/bin/env python3
"""AIOPEN MCP stdio 桥：将 Cursor / Claude Desktop 的 stdio MCP 转发到 HTTP。

环境变量：
  AIOPEN_BASE_URL  — XCAGI 后端根地址，默认 http://127.0.0.1:5100
  AIOPEN_API_KEY   — 可选，对应 X-AIOPEN-Key

Cursor mcp.json 示例::

  "xcagi-aiopen": {
    "command": "python3",
    "args": ["/path/to/FHD/scripts/dev/aiopen_mcp_stdio.py"],
    "env": {
      "AIOPEN_BASE_URL": "http://127.0.0.1:5100",
      "AIOPEN_API_KEY": "aiopen_..."
    }
  }
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("AIOPEN_BASE_URL", "http://127.0.0.1:5100").rstrip("/")
KEY = (os.environ.get("AIOPEN_API_KEY") or "").strip()
MCP_URL = f"{BASE}/api/aiopen/mcp"
TIMEOUT = float(os.environ.get("AIOPEN_MCP_TIMEOUT", "120"))


def _post_message(msg: dict) -> dict | None:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if KEY:
        headers["X-AIOPEN-Key"] = KEY
    data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(MCP_URL, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status == 202:
                return None
            raw = resp.read().decode("utf-8", errors="replace").strip()
            if not raw:
                return None
            return json.loads(raw)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            parsed = {"error": {"code": err.code, "message": body or str(err)}}
        if "jsonrpc" in parsed:
            return parsed
        req_id = msg.get("id")
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32603, "message": body or f"HTTP {err.code}"},
        }


def _write_response(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        try:
            resp = _post_message(msg)
            if resp is not None:
                _write_response(resp)
        except Exception as err:  # noqa: BLE001 — stdio 桥需兜底并回 JSON-RPC 错误
            _write_response(
                {
                    "jsonrpc": "2.0",
                    "id": msg.get("id"),
                    "error": {"code": -32603, "message": str(err)},
                }
            )


if __name__ == "__main__":
    main()
