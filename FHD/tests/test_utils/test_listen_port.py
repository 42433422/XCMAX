"""listen_port 与 discover-hint 端口解析。"""

from __future__ import annotations

from app.utils.listen_port import resolve_listen_port


def test_resolve_listen_port_prefers_fastapi_port(monkeypatch):
    monkeypatch.delenv("XCAGI_API_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setenv("FASTAPI_PORT", "5100")
    assert resolve_listen_port() == 5100
