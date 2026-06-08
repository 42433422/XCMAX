from __future__ import annotations

from typing import Any

import httpx

from modstore_server.workflow_fhd_bridge import run_steps_on_fhd


def test_run_steps_on_fhd_invokes_client(monkeypatch: Any) -> None:
    calls: list[tuple[str, str, Any]] = []

    class _Resp:
        status_code = 201
        text = '{"ok":true}'

        def json(self) -> dict[str, Any]:
            return {"ok": True}

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *a: Any) -> None:
            pass

        def request(self, method: str, url: str, **kw: Any) -> _Resp:
            calls.append((method, url, kw.get("json")))
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    out = run_steps_on_fhd(
        "http://localhost:5000",
        [
            {"path": "health", "method": "GET"},
            {"path": "shipment/create", "body": {"unit_name": "u"}},
        ],
        business_key="secret",
    )
    assert len(out) == 2
    assert out[0]["status_code"] == 201
    assert len(calls) == 2
    assert calls[0][0] == "GET"
    assert calls[0][1] == "/api/business/health"
