from __future__ import annotations

from pathlib import Path

import modstore_server.incident_collectors as collectors


def _reset_nginx_cursor(monkeypatch, log_path: Path) -> None:
    monkeypatch.setenv("OPS_NGINX_ERROR_LOG", str(log_path))
    monkeypatch.setattr(collectors, "_LAST_NGINX_FILE_ID", None)
    monkeypatch.setattr(collectors, "_LAST_NGINX_OFFSET", None)


def test_nginx_collector_ignores_existing_and_repeated_errors(tmp_path, monkeypatch):
    log_path = tmp_path / "error.log"
    log_path.write_text("2026/07/23 10:00:00 [error] historical failure\n", encoding="utf-8")
    _reset_nginx_cursor(monkeypatch, log_path)

    published = []
    monkeypatch.setattr(
        collectors,
        "publish",
        lambda event_type, payload, *, source: (
            published.append((event_type, payload, source)) or True
        ),
    )

    assert collectors.collect_nginx_error_tail() is False

    with log_path.open("a", encoding="utf-8") as fh:
        fh.write("2026/07/23 10:01:00 [notice] worker ready\n")
    assert collectors.collect_nginx_error_tail() is False

    with log_path.open("a", encoding="utf-8") as fh:
        fh.write("2026/07/23 10:02:00 [error] upstream timed out\n")
    assert collectors.collect_nginx_error_tail() is True
    assert len(published) == 1
    assert "upstream timed out" in published[0][1]["snippet"]
    assert "historical failure" not in published[0][1]["snippet"]

    assert collectors.collect_nginx_error_tail() is False
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write("2026/07/23 10:03:00 [info] request completed\n")
    assert collectors.collect_nginx_error_tail() is False
    assert len(published) == 1


def test_nginx_collector_rebaselines_after_rotation(tmp_path, monkeypatch):
    log_path = tmp_path / "error.log"
    log_path.write_text("", encoding="utf-8")
    _reset_nginx_cursor(monkeypatch, log_path)

    published = []
    monkeypatch.setattr(
        collectors,
        "publish",
        lambda event_type, payload, *, source: published.append(payload) or True,
    )

    assert collectors.collect_nginx_error_tail() is False
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write("2026/07/23 10:00:00 [error] first live failure\n")
    assert collectors.collect_nginx_error_tail() is True

    log_path.rename(tmp_path / "error.log.1")
    log_path.write_text("2026/07/23 10:01:00 [error] copied during rotation\n", encoding="utf-8")
    assert collectors.collect_nginx_error_tail() is False

    with log_path.open("a", encoding="utf-8") as fh:
        fh.write("2026/07/23 10:02:00 [crit] worker crash\n")
    assert collectors.collect_nginx_error_tail() is True
    assert len(published) == 2
    assert "worker crash" in published[-1]["snippet"]
