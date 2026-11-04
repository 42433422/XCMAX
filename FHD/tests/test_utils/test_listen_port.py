"""listen_port 与 discover-hint 端口解析。"""

from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path
from types import ModuleType

import pytest

from app.utils.device_system import listen_port
from app.utils.device_system.listen_port import resolve_listen_port


def test_resolve_listen_port_prefers_fastapi_port(monkeypatch):
    monkeypatch.delenv("XCAGI_API_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setenv("FASTAPI_PORT", "5100")
    assert resolve_listen_port() == 5100


@pytest.mark.parametrize("first", ["invalid", "0", "65536", ""])
def test_invalid_env_port_falls_back_to_next_valid_source(monkeypatch, first):
    monkeypatch.setenv("FASTAPI_PORT", first)
    monkeypatch.setenv("XCAGI_API_PORT", " 17500 ")
    monkeypatch.setenv("PORT", "8000")
    assert resolve_listen_port() == 17500


def test_profile_defaults_are_explicit_and_environment_order_is_shared(monkeypatch):
    for key in ("FASTAPI_PORT", "XCAGI_API_PORT", "PORT"):
        monkeypatch.delenv(key, raising=False)
    assert resolve_listen_port() == 5000
    assert resolve_listen_port(listen_port.DEVELOPMENT_API_PORT) == 42422
    monkeypatch.setenv("PORT", "8000")
    assert resolve_listen_port() == 8000
    listen_port.publish_listen_address("127.0.0.1", 17500)
    assert resolve_listen_port() == 17500
    assert listen_port.resolve_listen_host() == "127.0.0.1"


def test_probe_skips_real_occupied_port_and_reports_exhaustion():
    with socket.socket() as occupied, socket.socket() as spare:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        spare.bind(("127.0.0.1", 0))
        preferred, candidate = occupied.getsockname()[1], spare.getsockname()[1]
        spare.close()
        assert listen_port.find_available_port("127.0.0.1", preferred, [candidate]) == candidate
        with pytest.raises(RuntimeError, match="No available HTTP port"):
            listen_port.find_available_port("127.0.0.1", preferred, [])


def test_development_entry_publishes_its_selected_port(monkeypatch):
    factory = ModuleType("app.fastapi_app")
    factory.get_fastapi_app = lambda: object()
    monkeypatch.setitem(sys.modules, "app.fastapi_app", factory)
    for key in ("FASTAPI_PORT", "XCAGI_API_PORT", "PORT"):
        monkeypatch.delenv(key, raising=False)
    probes = []

    def select_available(host, preferred, candidates):
        probes.append((host, preferred, list(candidates)))
        return preferred + 1

    monkeypatch.setattr(listen_port, "find_available_port", select_available)
    spec = importlib.util.spec_from_file_location(
        "development_entry", Path(__file__).resolve().parents[2] / "run.py"
    )
    assert spec is not None and spec.loader is not None
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    assert entry._resolve_port("127.0.0.1") == 42423
    assert probes == [("127.0.0.1", 42422, list(range(42423, 42523)))]
    assert listen_port.resolve_listen_port() == 42423
