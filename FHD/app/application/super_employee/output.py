"""Parse tool output without process, workspace, or dispatch dependencies."""

from __future__ import annotations

import json
import re


class CliOutput:
    def __init__(self, tool_name: str) -> None:
        self._tool_name = tool_name

    def parse_stream_json_line(self, line: str) -> str:
        """解析单行 stream-json 事件，返回文本 token（无文本则空串）。"""
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return ""
        if not isinstance(ev, dict):
            return ""
        ev_type = ev.get("type")
        if ev_type == "assistant":
            msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
            if not isinstance(msg, dict):
                msg = {}
            for blk in msg.get("content") or []:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    t = str(blk.get("text") or "")
                    if t:
                        return t
        elif ev_type == "result":
            r = ev.get("result")
            if isinstance(r, str) and r.strip():
                return r
        elif ev_type == "content_block_delta":
            delta = ev.get("delta") if isinstance(ev.get("delta"), dict) else {}
            if not isinstance(delta, dict):
                delta = {}
            t = str(delta.get("text") or "")
            if t:
                return t
        elif ev_type == "message_delta":
            t = str(ev.get("text") or "")
            if t:
                return t
        return ""

    def parse_claude_stream_json(self, out: str) -> str:
        """从 claude --output-format stream-json 的事件流里取最终回复。"""
        result = ""
        texts: list[str] = []
        for line in out.splitlines():
            s = line.strip()
            if not s.startswith("{"):
                continue
            try:
                ev = json.loads(s)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "result":
                r = ev.get("result")
                if isinstance(r, str) and r.strip():
                    result = r.strip()
            elif ev.get("type") == "assistant":
                msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
                if not isinstance(msg, dict):
                    msg = {}
                for blk in msg.get("content") or []:
                    if isinstance(blk, dict) and blk.get("type") == "text":
                        t = str(blk.get("text") or "").strip()
                        if t:
                            texts.append(t)
        return result or "\n".join(texts).strip()

    def parse_stream_json_full(self, out: str) -> tuple[str, str]:
        """从 stream-json 取 (最终回复, session_id)。session_id 取最后出现的(result 事件含)。"""
        text = self.parse_claude_stream_json(out)
        sid = ""
        for line in out.splitlines():
            s = line.strip()
            if not s.startswith("{"):
                continue
            try:
                ev = json.loads(s)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict) and ev.get("session_id"):
                sid = str(ev.get("session_id") or "")
        return (text, sid)

    def clean_cli_stdout(self, stdout: str) -> str:
        lines = []
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped in {self._tool_name, "codex", "tokens used"}:
                continue
            if re.fullmatch("[\\d,]+", stripped):
                continue
            lines.append(line)
        return "\n".join(lines).strip()
