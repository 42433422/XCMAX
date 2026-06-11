"""LSP-lite adapter: JSON-RPC-style messages for editor integration.

Full LSP is overkill for vibe-coding's use case; we only need the editor
to push us a brief / context and receive a patch back. This module
defines a small subset that covers:

- ``vibe.code``      — single-skill generation.
- ``vibe.edit``      — project-level patch generation.
- ``vibe.apply``     — apply a patch the user already inspected.
- ``vibe.heal``      — iterative heal loop.
- ``vibe.index``     — build / refresh the project index.
- ``vibe.publish``   — push a skill to MODstore.

Wire format mirrors LSP's "Content-Length: …\\r\\n\\r\\n<json>" framing
when running over stdio, but the helpers here are framing-agnostic so
the same dispatch works over HTTP / WebSocket / TCP.

A trivial example:

    from vibe_coding.agent.web.lsp import LSPServer
    from vibe_coding import VibeCoder, OpenAILLM

    server = LSPServer(VibeCoder(llm=OpenAILLM(api_key="...")))
    server.serve_stdio()  # blocks; pipe stdin/stdout from the editor

The editor side can be implemented in any language that speaks
JSON-RPC. The Cursor / VSCode / Trae plugins ship as separate
deliverables — see ``docs/IDE_INTEGRATION.md``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, IO, Optional

from ...facade import VibeCoder


@dataclass(slots=True)
class LSPMessage:
    """One JSON-RPC-2.0-style envelope.

    ``id`` is set on requests / responses but stays ``None`` for
    notifications. ``method`` / ``params`` are mandatory on requests;
    ``result`` / ``error`` are mandatory on responses (mutually
    exclusive).
    """

    jsonrpc: str = "2.0"
    id: Optional[str | int] = None
    method: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"jsonrpc": self.jsonrpc}
        if self.id is not None:
            out["id"] = self.id
        if self.method:
            out["method"] = self.method
            out["params"] = self.params or {}
        if self.error is not None:
            out["error"] = dict(self.error)
        if self.result is not None:
            out["result"] = self.result
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> LSPMessage:
        return cls(
            jsonrpc=str(raw.get("jsonrpc") or "2.0"),
            id=raw.get("id"),
            method=str(raw.get("method") or ""),
            params=dict(raw.get("params") or {}),
            result=raw.get("result"),
            error=dict(raw["error"]) if isinstance(raw.get("error"), dict) else None,
        )


def handle_lsp_request(coder: VibeCoder, request: LSPMessage) -> LSPMessage:
    """Dispatch a single :class:`LSPMessage` against the given ``coder``."""
    method = request.method
    params = request.params or {}

    handlers: dict[str, Callable[[VibeCoder, dict[str, Any]], Any]] = {
        "vibe.code": _handle_code,
        "vibe.edit": _handle_edit,
        "vibe.apply": _handle_apply,
        "vibe.heal": _handle_heal,
        "vibe.index": _handle_index,
        "vibe.publish": _handle_publish,
    }
    handler = handlers.get(method)
    if handler is None:
        return LSPMessage(
            id=request.id,
            error={
                "code": -32601,
                "message": f"unknown method: {method!r}",
            },
        )
    try:
        result = handler(coder, params)
    except Exception as exc:  # noqa: BLE001
        return LSPMessage(
            id=request.id,
            error={
                "code": -32000,
                "message": f"{type(exc).__name__}: {exc}",
            },
        )
    return LSPMessage(id=request.id, result=result)


# ----------------------------------------------------------------- handlers


def _handle_code(coder: VibeCoder, params: dict[str, Any]) -> dict[str, Any]:
    skill = coder.code(
        params["brief"],
        mode=params.get("mode") or "brief_first",
        skill_id=params.get("skill_id"),
        dependencies=params.get("dependencies"),
    )
    return skill.to_dict()


def _handle_edit(coder: VibeCoder, params: dict[str, Any]) -> dict[str, Any]:
    patch = coder.edit_project(
        params["brief"],
        root=params.get("root") or ".",
        focus_paths=params.get("focus_paths") or None,
    )
    return patch.to_dict()


def _handle_apply(coder: VibeCoder, params: dict[str, Any]) -> dict[str, Any]:
    from ..patch import ProjectPatch

    patch = ProjectPatch.from_dict(params["patch"])
    result = coder.apply_patch(
        patch,
        root=params.get("root") or ".",
        dry_run=bool(params.get("dry_run", False)),
    )
    return result.to_dict()


def _handle_heal(coder: VibeCoder, params: dict[str, Any]) -> dict[str, Any]:
    result = coder.heal_project(
        params["brief"],
        root=params.get("root") or ".",
        max_rounds=int(params.get("max_rounds") or 3),
    )
    return result.to_dict()


def _handle_index(coder: VibeCoder, params: dict[str, Any]) -> dict[str, Any]:
    index = coder.index_project(
        params.get("root") or ".",
        refresh=bool(params.get("refresh", False)),
    )
    return index.summary()


def _handle_publish(coder: VibeCoder, params: dict[str, Any]) -> dict[str, Any]:
    result = coder.publish_skill(
        params["skill_id"],
        base_url=params["base_url"],
        admin_token=params["admin_token"],
        version=params.get("version") or "",
        name=params.get("name") or "",
        description=params.get("description") or "",
        price=float(params.get("price") or 0.0),
        artifact=params.get("artifact") or "mod",
        industry=params.get("industry") or "通用",
        verify_ssl=bool(params.get("verify_ssl", True)),
        dry_run=bool(params.get("dry_run", False)),
    )
    return result.to_dict()


# ---------------------------------------------------------------- framing


class LSPServer:
    """Stdio / file-descriptor server that loops on :func:`handle_lsp_request`."""

    def __init__(self, coder: VibeCoder) -> None:
        self.coder = coder

    def serve_stdio(
        self,
        *,
        stdin: IO[bytes] | None = None,
        stdout: IO[bytes] | None = None,
    ) -> None:
        """Read framed JSON-RPC messages from stdin and write replies to stdout.

        Blocks until stdin closes. Exits cleanly on EOF so editors can
        terminate the server by closing the pipe.
        """
        in_stream = stdin or sys.stdin.buffer
        out_stream = stdout or sys.stdout.buffer
        while True:
            request = self._read_message(in_stream)
            if request is None:
                return
            response = handle_lsp_request(self.coder, request)
            self._write_message(out_stream, response)

    def handle_one(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Convenience for HTTP-style transports: in dict → out dict."""
        request = LSPMessage.from_dict(payload)
        response = handle_lsp_request(self.coder, request)
        return response.to_dict()

    @staticmethod
    def _read_message(stream: IO[bytes]) -> LSPMessage | None:
        headers: Dict[str, str] = {}
        while True:
            line = stream.readline()
            if not line:
                return None
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if text == "":
                break
            if ":" in text:
                key, _, value = text.partition(":")
                headers[key.strip().lower()] = value.strip()
        try:
            length = int(headers.get("content-length") or 0)
        except ValueError:
            return None
        if length <= 0:
            return None
        body = stream.read(length)
        if not body:
            return None
        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return LSPMessage.from_dict(payload)

    @staticmethod
    def _write_message(stream: IO[bytes], message: LSPMessage) -> None:
        body = json.dumps(message.to_dict(), ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        stream.write(header)
        stream.write(body)
        stream.flush()


__all__ = ["LSPMessage", "LSPServer", "handle_lsp_request"]
