"""HTTP-facing surface for vibe-coding: Web UI server + LSP-lite endpoints.

Two ways to consume vibe-coding from outside Python:

1. **Web UI** (:func:`vibe_coding.agent.web.create_app`) — a small
   FastAPI app that serves a single-page UI plus a JSON API. Drop it
   into any host, ``uvicorn vibe_coding.agent.web.server:app --reload``.
2. **LSP-lite** (:mod:`vibe_coding.agent.web.lsp`) — a JSON-RPC-style
   adapter that an editor (VSCode, Trae, …) can reuse via stdin/stdout
   or HTTP. The protocol is intentionally simpler than full LSP so the
   editor only needs to implement the requests it cares about.

Both are **optional** — installing vibe-coding without ``[web]`` extras
keeps the package importable but the calls below raise a useful error
explaining how to install ``fastapi``.
"""

from __future__ import annotations

from .server import create_app, run_server
from .lsp import LSPMessage, LSPServer, handle_lsp_request

__all__ = [
    "LSPMessage",
    "LSPServer",
    "create_app",
    "handle_lsp_request",
    "run_server",
]
