"""Real HTTP transport and production CSRF/code-editor; deterministic account fixture."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from types import SimpleNamespace

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.cli.brain_client import BrainClient
from app.cli.brain_session import SessionStore
from app.fastapi_routes import code_editor
from app.middleware.csrf import CSRFMiddleware


@pytest.fixture
def brain_server(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("before\n", encoding="utf-8")
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("FHD_AI_ELEVATED_TOKEN", "fixture-p2-secret")
    code_editor._EDIT_STORE.clear()
    state = SimpleNamespace(
        calls=[],
        sessions={},
        counter=0,
        expired=False,
        redirect="",
        broken_json=False,
        chat_error=False,
        cloud_degraded=False,
        workspace=workspace,
        me_failure=False,
        delay_apply=False,
        health_degraded=False,
    )
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.middleware("http")
    async def record(request, call_next):
        state.calls.append((request.method, request.url.path, dict(request.headers)))
        response = await call_next(request)
        if state.delay_apply and request.url.path.startswith("/api/code-editor/apply/"):
            await asyncio.sleep(0.2)
        return response

    app.include_router(code_editor.router)

    @app.get("/api/health")
    def health():
        return {
            "success": True,
            "status": "degraded" if state.health_degraded else "healthy",
            "degradedReasons": ["LLM_RUNTIME_UNAVAILABLE"] if state.health_degraded else [],
        }

    @app.post("/api/auth/login")
    async def login(request: Request):
        if state.redirect:
            return RedirectResponse(state.redirect, status_code=307)
        body = await request.json()
        if body.get("password") != "fixture-password":
            return {"success": False, "error": {"message": "账号或密码错误"}}
        username = body["username"]
        sid = f"private-session-{username}"
        state.sessions[sid] = username
        response = JSONResponse(
            {"success": True, "session_id": sid, "web_tokens": {"access": "private-jwt"}}
        )
        response.set_cookie("session_id", sid, httponly=True)
        return response

    @app.get("/api/auth/me")
    def me(request: Request):
        if state.me_failure:
            return JSONResponse({"detail": "identity service unavailable"}, status_code=503)
        username = state.sessions.get(request.cookies.get("session_id"))
        if not username or state.expired:
            return {
                "success": False,
                "valid": False,
                "error": {"code": "UNAUTHORIZED", "message": "请先登录"},
            }
        return {
            "success": True,
            "data": {
                "user": {"id": 1, "username": username},
                "local_user_id": 1,
                "tenant_id": username,
            },
        }

    @app.post("/api/auth/logout")
    def logout(request: Request):
        state.sessions.pop(request.cookies.get("session_id"), None)
        response = JSONResponse(True)
        response.delete_cookie("session_id")
        return response

    @app.post("/api/ai/conversation/new")
    def new_conversation():
        state.counter += 1
        return {"success": True, "data": {"session_id": f"chat-{state.counter}"}}

    @app.post("/api/ai/unified_chat")
    async def chat(request: Request):
        if state.chat_error:
            return {
                "success": True,
                "data": {"success": False, "error": {"message": "上游模型不可用"}},
            }
        payload = await request.json()
        return {
            "success": True,
            "response": payload["message"],
            "session_id": payload["session_id"],
        }

    @app.get("/api/desktop/status")
    def desktop_status():
        if state.broken_json:
            from fastapi.responses import PlainTextResponse

            return PlainTextResponse("not JSON")
        return {"mode": "desktop"}

    @app.get("/api/desktop/models")
    def local_models():
        return {"models": [{"name": "local-file", "version": "1"}]}

    @app.get("/api/market/llm-catalog")
    def cloud_models():
        return {
            "success": True,
            "degraded": state.cloud_degraded,
            "message": "云目录不可用" if state.cloud_degraded else "ok",
            "models": [],
        }

    @app.get("/api/system/openapi")
    def openapi():
        return app.openapi()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    state.origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    try:
        yield state
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()
        code_editor._EDIT_STORE.clear()
        assert not thread.is_alive()


@pytest.fixture
def brain_client(brain_server, tmp_path):
    return BrainClient(SessionStore(brain_server.origin, tmp_path / "session"))
