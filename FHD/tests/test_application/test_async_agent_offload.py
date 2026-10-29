"""Blocking Agent calls must leave the ASGI loop and retain request context."""

import asyncio
import threading
from contextvars import ContextVar
from types import SimpleNamespace

import pytest
from starlette.requests import Request


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route_name", ["ocr_recognize", "ocr_recognize_and_extract", "ingest_excel_vector"]
)
async def test_blocking_agent_runs_off_loop_with_context(route_name, monkeypatch):
    from app.fastapi_routes import excel_vector, ocr

    request_context = ContextVar("offload_request_context", default="missing")
    token = request_context.set("tenant-request")
    entered, release = threading.Event(), threading.Event()
    observed = []
    loop_thread = threading.get_ident()

    def run_agent(**_kwargs):
        observed.append((threading.get_ident(), request_context.get()))
        entered.set()
        release.wait(timeout=3)
        return SimpleNamespace(status="completed", run_id="offload-test")

    async def receive():
        return {"type": "http.request", "body": b'{"file_path":"/synthetic.xlsx"}'}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )
    if route_name == "ingest_excel_vector":
        monkeypatch.setattr(excel_vector, "_run_excel_vector_agent", run_agent)
        call = excel_vector.ingest_excel_vector(request)
    else:
        monkeypatch.setattr(ocr, "_run_ocr_agent", run_agent)
        call = getattr(ocr, route_name)(request, file_path="/synthetic.png", image=None)
    task = asyncio.create_task(call)
    try:
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        # The loop can service another request while the actual worker is held.
        assert not task.done()
        assert observed == [(observed[0][0], "tenant-request")]
        assert observed[0][0] != loop_thread
    finally:
        release.set()
        response = await task
        request_context.reset(token)
    assert response.status_code == 200
