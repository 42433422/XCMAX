from __future__ import annotations

import json
from pathlib import Path

import pytest

import modstore_server.incident_collectors as collectors
from modstore_server.incident_bus import _incident_employee_input
from modstore_server.para_delegate_handler import _build_para_prompt, _build_request


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


@pytest.mark.parametrize("report_only", [False, True])
def test_nginx_evidence_reaches_para_prompt(tmp_path, monkeypatch, report_only):
    monkeypatch.chdir(tmp_path)
    log_path = Path("error.log")
    log_path.touch()
    _reset_nginx_cursor(monkeypatch, log_path)
    published = []
    monkeypatch.setattr(
        collectors, "publish", lambda event, payload, *, source: published.append(payload) or True
    )
    assert collectors.collect_nginx_error_tail() is False
    log_path.write_text(
        '2026/10/24 10:02:00 [error] upstream timed out, upstream: "http://127.0.0.1:8765/", '
        'request: "GET /api/health?token=private-log-token HTTP/1.1"\n',
        encoding="utf-8",
    )
    assert collectors.collect_nginx_error_tail() is True
    incident = {**published[0], "unrelated_private_field": "do-not-forward"}
    req = _build_request(
        task="[on_error] " + incident["summary"],
        employee_id="vibe-coding-maintainer",
        input_data={
            **_incident_employee_input(
                incident_payload=incident, event_type="on_error", source="nginx_error_log"
            ),
            "report_only": report_only,
        },
    )
    prompt = _build_para_prompt(req)
    assert "upstream timed out" in prompt
    assert "127.0.0.1:8765" in prompt
    assert str(log_path) in prompt
    assert "private-log-token" not in prompt and "do-not-forward" not in prompt
    assert prompt.index("upstream timed out") < prompt.rindex("MODstore loop context:")
    assert ("MODSTORE_REPORT_ONLY=1" in prompt) is report_only


def test_para_nginx_evidence_is_bounded_and_excludes_other_sources():
    raw = {"source": "nginx_error_log", "incident": {"path": "p" * 600, "snippet": "x" * 3000}}
    prompt = _build_para_prompt({"task": "diagnose", "raw_input": raw})
    assert "p" * 500 in prompt and "p" * 501 not in prompt
    assert "x" * 2000 in prompt and "x" * 2001 not in prompt
    for incident in (None, [], {}, {"path": [], "snippet": 123}):
        raw["incident"] = incident
        assert "Nginx 日志证据" not in _build_para_prompt({"raw_input": raw})
    raw.update(source="pytest", incident={"snippet": "unrelated"})
    assert "unrelated" not in _build_para_prompt({"raw_input": raw})


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
