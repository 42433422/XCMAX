"""Desktop assigned ports and the discovery address share one bind policy."""

from __future__ import annotations

import pytest
import uvicorn

from app.utils.device_system import listen_port
from XCAGI import run_fastapi


@pytest.fixture
def isolated_startup(monkeypatch):
    from app.desktop_runtime import migrate

    monkeypatch.setattr(run_fastapi, "_load_dotenv_if_present", lambda _path: None)
    monkeypatch.setattr(run_fastapi, "_apply_desktop_bootstrap", lambda _args: None)
    monkeypatch.setattr(run_fastapi, "_apply_desktop_local_market_env", lambda: None)
    monkeypatch.setattr(run_fastapi, "_apply_no_console_child_defaults", lambda: None)
    monkeypatch.setattr(migrate, "ensure_startup_migration", lambda _path: None)
    monkeypatch.setattr(run_fastapi, "_is_frozen", lambda: False)
    persisted = []
    monkeypatch.setattr(run_fastapi, "_persist_runtime_port", persisted.append)
    launched = []
    monkeypatch.setattr(uvicorn, "run", lambda target, **kwargs: launched.append((target, kwargs)))
    return persisted, launched


@pytest.mark.parametrize("desktop_args", [["--desktop"], []])
def test_desktop_cli_and_environment_never_probe_assigned_port(
    monkeypatch, isolated_startup, desktop_args
):
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setenv("FASTAPI_PORT", "5100")
    monkeypatch.setenv("XCAGI_API_PORT", "5200")

    def unexpected_probe(*_args):
        raise AssertionError("desktop must use Electron's assigned port")

    monkeypatch.setattr(listen_port, "find_available_port", unexpected_probe)
    run_fastapi.main([*desktop_args, "--port", "17500", "--host", "127.0.0.1"])

    persisted, launched = isolated_startup
    assert persisted == [17500]
    assert launched[0][0] == "app.fastapi_app:create_fastapi_app"
    assert launched[0][1]["port"] == 17500
    assert launched[0][1]["reload"] is False
    assert listen_port.resolve_listen_port() == 17500


def test_server_entry_uses_shared_environment_precedence_and_discovery(
    monkeypatch, isolated_startup
):
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    monkeypatch.setenv("FASTAPI_PORT", "17500")
    monkeypatch.setenv("XCAGI_API_PORT", "5200")
    monkeypatch.setenv("FASTAPI_HOST", "127.0.0.1")
    probes = []

    def select_available(host, preferred, candidates):
        probes.append((host, preferred, list(candidates)))
        return 5001

    monkeypatch.setattr(listen_port, "find_available_port", select_available)
    run_fastapi.main([])
    persisted, launched = isolated_startup
    assert probes == [("127.0.0.1", 17500, list(range(5000, 5021)))]
    assert persisted == [5001]
    assert launched[0][1]["port"] == 5001
    assert listen_port.resolve_listen_port() == 5001
