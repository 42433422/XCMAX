"""Tests for :class:`LSPServer` and :func:`handle_lsp_request`.

The LSP layer doesn't need FastAPI — it's pure JSON-RPC framing — so it
is the natural surface to test even on hosts where ``fastapi`` is not
installed. The tests use a stub ``VibeCoder`` that records calls so the
JSON-RPC dispatch can be verified without reaching for a real LLM.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from vibe_coding.agent.web.lsp import LSPMessage, LSPServer, handle_lsp_request


# ----------------------------------------------------- stubs


@dataclass
class _StubSkill:
    skill_id: str = "demo"

    def to_dict(self) -> dict[str, Any]:
        return {"skill_id": self.skill_id}


@dataclass
class _StubPatch:
    patch_id: str = "p-1"

    def to_dict(self) -> dict[str, Any]:
        return {"patch_id": self.patch_id, "edits": []}


@dataclass
class _StubApplyResult:
    patch_id: str = "p-1"
    applied: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"patch_id": self.patch_id, "applied": self.applied}


@dataclass
class _StubIndex:
    summary_data: dict[str, Any] = field(default_factory=lambda: {"files": 5})

    def summary(self) -> dict[str, Any]:
        return dict(self.summary_data)


@dataclass
class _StubHealResult:
    success: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"success": self.success, "rounds": []}


@dataclass
class _StubPublishResult:
    published: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"published": self.published, "skill_id": "demo"}


@dataclass
class _StubCoder:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def code(self, brief: str, **kwargs: Any) -> _StubSkill:
        self.calls.append(("code", {"brief": brief, **kwargs}))
        return _StubSkill()

    def edit_project(self, brief: str, *, root: str, focus_paths=None, **_) -> _StubPatch:
        self.calls.append(("edit", {"brief": brief, "root": root, "focus_paths": focus_paths}))
        return _StubPatch()

    def apply_patch(self, patch, *, root: str, dry_run: bool = False) -> _StubApplyResult:
        self.calls.append(("apply", {"patch_id": patch.patch_id, "root": root, "dry_run": dry_run}))
        return _StubApplyResult(patch_id=patch.patch_id)

    def heal_project(self, brief: str, *, root: str, max_rounds: int = 3, **_) -> _StubHealResult:
        self.calls.append(("heal", {"brief": brief, "root": root, "max_rounds": max_rounds}))
        return _StubHealResult()

    def index_project(self, root: str | Path, *, refresh: bool = False) -> _StubIndex:
        self.calls.append(("index", {"root": str(root), "refresh": refresh}))
        return _StubIndex()

    def publish_skill(self, skill_id: str, **kwargs: Any) -> _StubPublishResult:
        self.calls.append(("publish", {"skill_id": skill_id, **kwargs}))
        return _StubPublishResult()


# ----------------------------------------------------- LSPMessage round-trip


def test_lsp_message_round_trip() -> None:
    msg = LSPMessage(id=42, method="vibe.code", params={"brief": "x"})
    raw = msg.to_dict()
    assert raw["jsonrpc"] == "2.0"
    assert raw["id"] == 42
    assert raw["method"] == "vibe.code"
    assert raw["params"] == {"brief": "x"}
    msg2 = LSPMessage.from_dict(raw)
    assert msg2.method == "vibe.code"
    assert msg2.params["brief"] == "x"


def test_response_message_keeps_result() -> None:
    msg = LSPMessage(id=7, result={"skill_id": "x"})
    raw = msg.to_dict()
    assert raw["result"] == {"skill_id": "x"}
    assert "error" not in raw


def test_error_message_keeps_error() -> None:
    msg = LSPMessage(id=8, error={"code": -32601, "message": "boom"})
    raw = msg.to_dict()
    assert raw["error"]["code"] == -32601


# ----------------------------------------------------- dispatch


def test_dispatch_code_routes_to_coder() -> None:
    coder = _StubCoder()
    req = LSPMessage(id=1, method="vibe.code", params={"brief": "say hi"})
    resp = handle_lsp_request(coder, req)
    assert resp.id == 1
    assert resp.result == {"skill_id": "demo"}
    assert coder.calls[0][0] == "code"


def test_dispatch_edit_routes_to_coder() -> None:
    coder = _StubCoder()
    req = LSPMessage(
        id=2, method="vibe.edit", params={"brief": "rename", "root": "/tmp/proj"}
    )
    resp = handle_lsp_request(coder, req)
    assert resp.result == {"patch_id": "p-1", "edits": []}
    assert coder.calls[0][1]["root"] == "/tmp/proj"


def test_dispatch_apply_round_trip() -> None:
    coder = _StubCoder()
    req = LSPMessage(
        id=3,
        method="vibe.apply",
        params={
            "patch": {
                "patch_id": "p-9",
                "summary": "demo",
                "rationale": "test",
                "edits": [],
            },
            "root": ".",
            "dry_run": True,
        },
    )
    resp = handle_lsp_request(coder, req)
    assert resp.result == {"patch_id": "p-9", "applied": True}


def test_dispatch_heal_uses_max_rounds() -> None:
    coder = _StubCoder()
    req = LSPMessage(
        id=4,
        method="vibe.heal",
        params={"brief": "fix tests", "root": ".", "max_rounds": 5},
    )
    resp = handle_lsp_request(coder, req)
    assert resp.result["success"] is True
    assert coder.calls[0][1]["max_rounds"] == 5


def test_dispatch_index_returns_summary() -> None:
    coder = _StubCoder()
    req = LSPMessage(id=5, method="vibe.index", params={"root": "."})
    resp = handle_lsp_request(coder, req)
    assert resp.result == {"files": 5}


def test_dispatch_publish() -> None:
    coder = _StubCoder()
    req = LSPMessage(
        id=6,
        method="vibe.publish",
        params={
            "skill_id": "demo",
            "base_url": "https://m.example.com",
            "admin_token": "tok",
            "dry_run": True,
        },
    )
    resp = handle_lsp_request(coder, req)
    assert resp.result["published"] is True
    assert coder.calls[0][1]["base_url"] == "https://m.example.com"


def test_unknown_method_returns_method_not_found() -> None:
    coder = _StubCoder()
    req = LSPMessage(id=99, method="vibe.unknown")
    resp = handle_lsp_request(coder, req)
    assert resp.error is not None
    assert resp.error["code"] == -32601


def test_handler_exception_becomes_internal_error() -> None:
    class _Boom:
        def code(self, *args, **kwargs):  # noqa: D401
            raise RuntimeError("kaboom")

    req = LSPMessage(id=1, method="vibe.code", params={"brief": "x"})
    resp = handle_lsp_request(_Boom(), req)
    assert resp.error is not None
    assert "kaboom" in resp.error["message"]


# ----------------------------------------------------- framing


def test_framing_round_trip() -> None:
    coder = _StubCoder()
    server = LSPServer(coder)

    request = LSPMessage(id=10, method="vibe.code", params={"brief": "ping"})
    body = json.dumps(request.to_dict()).encode("utf-8")
    raw = (
        f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
    )

    in_stream = io.BytesIO(raw)
    out_stream = io.BytesIO()
    server.serve_stdio(stdin=in_stream, stdout=out_stream)

    output = out_stream.getvalue().decode("utf-8")
    assert "Content-Length:" in output
    body_text = output.split("\r\n\r\n", 1)[1]
    payload = json.loads(body_text)
    assert payload["id"] == 10
    assert payload["result"] == {"skill_id": "demo"}


def test_handle_one_dict_in_dict_out() -> None:
    coder = _StubCoder()
    server = LSPServer(coder)
    out = server.handle_one(
        {"jsonrpc": "2.0", "id": 7, "method": "vibe.index", "params": {"root": "."}}
    )
    assert out["id"] == 7
    assert out["result"] == {"files": 5}
