"""Installed runtime failures must precede desktop data changes and readiness."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from XCAGI import run_fastapi


@pytest.fixture
def startup(monkeypatch):
    import uvicorn

    from app.desktop_runtime import migrate

    calls = []
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    monkeypatch.setattr(run_fastapi, "_load_dotenv_if_present", lambda _path: None)
    monkeypatch.setattr(run_fastapi, "_apply_no_console_child_defaults", lambda: None)
    monkeypatch.setattr(run_fastapi, "_apply_desktop_local_market_env", lambda: None)
    monkeypatch.setattr(run_fastapi, "_is_frozen", lambda: True)
    bootstrap = Mock(side_effect=lambda _args: calls.append("bootstrap"))
    monkeypatch.setattr(run_fastapi, "_apply_desktop_bootstrap", bootstrap)
    monkeypatch.setattr(migrate, "ensure_startup_migration", lambda _path: calls.append("migrate"))
    monkeypatch.setattr(run_fastapi, "_persist_runtime_port", lambda _port: calls.append("port"))
    monkeypatch.setattr(uvicorn, "run", lambda *_args, **_kwargs: calls.append("serve"))
    return calls, bootstrap


@pytest.mark.parametrize("entry", [["--desktop"], []])
def test_missing_installed_cli_stops_before_bootstrap_and_migration(
    monkeypatch, tmp_path, capsys, startup, entry
):
    import codex_cli_bin

    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setattr(codex_cli_bin, "bundled_codex_path", lambda: tmp_path / "missing-cli")

    with pytest.raises(SystemExit) as error:
        run_fastapi.main([*entry, "--port", "17500"])

    assert error.value.code == 1
    assert startup[0] == []
    assert "xiaox_runtime_unavailable" in capsys.readouterr().err
    startup[1].assert_not_called()


@pytest.mark.parametrize("code", ["xiaox_runtime_version_mismatch", "xiaox_timeout"])
def test_installed_cli_failure_is_nonzero_and_never_becomes_healthy(
    monkeypatch, capsys, startup, code
):
    from app.infrastructure.xiaox import transport

    probe = Mock(side_effect=transport.XiaoxTransportError(code, "private diagnostic"))
    monkeypatch.setattr(transport, "verify_packaged_runtime", probe)
    with pytest.raises(SystemExit) as error:
        run_fastapi.main(["--desktop"])

    assert error.value.code == 1
    probe.assert_called_once_with()
    assert startup[0] == []
    output = capsys.readouterr().err
    assert code in output and "private diagnostic" not in output


def test_each_installed_start_runs_real_cli_before_migration(monkeypatch, capsys, startup):
    from app.infrastructure.xiaox import transport

    verify = transport.verify_packaged_runtime

    def probe():
        verify()  # Real pinned SDK/CLI initialization; no provider or model call.
        startup[0].append("runtime")

    monkeypatch.setattr(transport, "verify_packaged_runtime", probe)
    for _ in range(2):  # First install and subsequent restart/upgrade share the entry.
        run_fastapi.main(["--desktop", "--port", "17500"])

    assert startup[0] == ["runtime", "bootstrap", "migrate", "port", "serve"] * 2
    assert capsys.readouterr().out.count("initialize OK") == 2


@pytest.mark.parametrize("frozen,desktop", [(False, True), (False, False), (True, False)])
def test_source_and_web_entries_do_not_require_desktop_probe(monkeypatch, startup, frozen, desktop):
    from app.infrastructure.xiaox import transport
    from app.utils.device_system import listen_port

    monkeypatch.setattr(run_fastapi, "_is_frozen", lambda: frozen)
    monkeypatch.setattr(listen_port, "find_available_port", lambda _host, port, _range: port)
    probe = Mock(side_effect=AssertionError("desktop-only probe reached another entry"))
    monkeypatch.setattr(transport, "verify_packaged_runtime", probe)
    run_fastapi.main([*(["--desktop"] if desktop else []), "--port", "17500"])

    probe.assert_not_called()
    assert startup[0][-1] == "serve"
