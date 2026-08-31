from __future__ import annotations

import json
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


def test_git_push_collector_uses_immutable_release_and_persistent_previous_sha(
    tmp_path, monkeypatch
):
    previous = "a" * 40
    current = "b" * 40
    release = tmp_path / "releases" / current
    release.mkdir(parents=True)
    manifest = release / ".xcmax-release.json"
    manifest.write_text(
        json.dumps({"git_sha": current, "release_id": current}),
        encoding="utf-8",
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "deployed-head-sha").write_text(previous + "\n", encoding="utf-8")
    monkeypatch.setenv("MODSTORE_RELEASE_MANIFEST", str(manifest))
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(collectors, "_LAST_GIT_HEAD_SHA", None)
    published = []
    monkeypatch.setattr(
        collectors,
        "publish",
        lambda event_type, payload, *, source: (
            published.append((event_type, payload, source)) or True
        ),
    )

    assert collectors.collect_git_push_event() is True
    assert published[0][0] == "git.push"
    assert published[0][1]["prev_sha"] == previous
    assert published[0][1]["head_sha"] == current
    context = published[0][1]["update_context"]
    assert context["commit_sha"] == current
    assert context["rollback"] == f"git:{previous}"
    assert context["git_clean"] is True
    assert (runtime / "deployed-head-sha").read_text(encoding="utf-8").strip() == current
    assert collectors.collect_git_push_event() is False


def test_git_push_collector_recovers_previous_immutable_release_on_first_run(tmp_path, monkeypatch):
    previous = "c" * 40
    current = "d" * 40
    releases = tmp_path / "releases"
    old_release = releases / previous
    new_release = releases / current
    old_release.mkdir(parents=True)
    new_release.mkdir(parents=True)
    (old_release / ".xcmax-release.json").write_text(
        json.dumps({"git_sha": previous}), encoding="utf-8"
    )
    manifest = new_release / ".xcmax-release.json"
    manifest.write_text(json.dumps({"git_sha": current}), encoding="utf-8")
    (old_release / ".xcmax-release.json").touch()
    manifest.touch()
    monkeypatch.setenv("MODSTORE_RELEASE_MANIFEST", str(manifest))
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(collectors, "_LAST_GIT_HEAD_SHA", None)
    published = []
    monkeypatch.setattr(
        collectors,
        "publish",
        lambda event_type, payload, *, source: published.append(payload) or True,
    )

    assert collectors.collect_git_push_event() is True
    assert published[0]["prev_sha"] == previous
