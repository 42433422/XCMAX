from __future__ import annotations

import http.client
import io
import json

import pytest

from app.cli import brain
from app.cli.brain_session import BrainError


def run(client, *args):
    return brain.execute(brain.parser().parse_args(args), client)


def login(client):
    client.login("alice", "fixture-password", "enterprise")


def test_real_editor_http_csrf_diff_apply_replay(brain_client, brain_server, monkeypatch, tmp_path):
    login(brain_client)
    assert run(brain_client, "analyze", "note.txt")["preview"] == "before\n"
    source = tmp_path / "replacement.txt"
    source.write_text("中文 after\n", encoding="utf-8")
    edit = run(brain_client, "edit", "note.txt", "--file", str(source))
    assert (brain_server.workspace / "note.txt").read_text() == "before\n"
    assert "+中文 after" in run(brain_client, "diff", edit["edit_id"])["unified_diff"]
    with pytest.raises(BrainError, match="未发送"):
        run(brain_client, "apply", edit["edit_id"])
    assert not any("/apply/" in path for _, path, _ in brain_server.calls)
    monkeypatch.setenv("XCAGI_BRAIN_P2_TOKEN", "wrong-token")
    with pytest.raises(BrainError, match="403"):
        run(brain_client, "apply", edit["edit_id"], "--confirm")
    assert (brain_server.workspace / "note.txt").read_text() == "before\n"
    monkeypatch.setenv("XCAGI_BRAIN_P2_TOKEN", "fixture-p2-secret")
    assert run(brain_client, "apply", edit["edit_id"], "--confirm")["success"] is True
    assert (brain_server.workspace / "note.txt").read_text() == "中文 after\n"
    with pytest.raises(BrainError, match="404"):
        run(brain_client, "apply", edit["edit_id"], "--confirm")
    edit_headers = next(
        headers for method, path, headers in brain_server.calls if path.endswith("/edit")
    )
    assert edit_headers["x-csrf-token"] in edit_headers["cookie"]
    assert "x-xcagi-elevated-token" not in edit_headers


def test_real_apply_conflict_preserves_external_change(brain_client, brain_server, monkeypatch):
    login(brain_client)
    monkeypatch.setattr("sys.stdin", io.StringIO("replacement\n"))
    edit = run(brain_client, "edit", "note.txt", "--stdin")
    (brain_server.workspace / "note.txt").write_text("external\n")
    monkeypatch.setenv("XCAGI_BRAIN_P2_TOKEN", "fixture-p2-secret")
    with pytest.raises(BrainError, match="409"):
        run(brain_client, "apply", edit["edit_id"], "--confirm")
    assert (brain_server.workspace / "note.txt").read_text() == "external\n"
    assert run(brain_client, "diff", edit["edit_id"])["success"] is True


def test_write_timeout_is_unknown_result_without_retry(brain_client, brain_server, monkeypatch):
    login(brain_client)
    monkeypatch.setattr("sys.stdin", io.StringIO("applied once\n"))
    edit = run(brain_client, "edit", "note.txt", "--stdin")
    monkeypatch.setenv("XCAGI_BRAIN_P2_TOKEN", "fixture-p2-secret")
    brain_server.delay_apply = True
    brain_client.timeout = 0.05
    with pytest.raises(BrainError, match="写入结果可能未知.*未自动重试") as exc:
        run(brain_client, "apply", edit["edit_id"], "--confirm")
    assert exc.value.kind == "transport"
    assert (brain_server.workspace / "note.txt").read_text() == "applied once\n"
    assert len([path for _, path, _ in brain_server.calls if "/apply/" in path]) == 1


def test_temporary_identity_failure_preserves_conversation(brain_client, brain_server):
    login(brain_client)
    session = brain_client.chat("hello")["session_id"]
    brain_server.me_failure = True
    with pytest.raises(BrainError, match="保留原会话") as exc:
        brain_client.chat("not sent")
    assert exc.value.status == 503
    assert brain_client.store.state["conversation_id"] == session
    brain_server.me_failure = False
    assert brain_client.chat("recovered")["session_id"] == session


def test_draft_current_backend_unavailable_never_stages_or_applies(
    brain_client, brain_server, monkeypatch
):
    login(brain_client)
    monkeypatch.setenv("XCAGI_BRAIN_P2_TOKEN", "fixture-p2-secret")
    with pytest.raises(BrainError, match="服务|500"):
        run(brain_client, "draft", "note.txt", "--instruction", "rewrite")
    assert (brain_server.workspace / "note.txt").read_text() == "before\n"
    assert not any(path.endswith("/edit") or "/apply/" in path for _, path, _ in brain_server.calls)


def test_nested_chat_failure_nonzero_preserves_message(brain_client, brain_server, capsys):
    login(brain_client)
    brain_server.chat_error = True
    assert (
        brain.main(
            [
                "--json",
                "--origin",
                brain_server.origin,
                "--session-dir",
                str(brain_client.store.directory),
                "chat",
                "hello",
            ]
        )
        == 1
    )
    assert "上游模型不可用" in capsys.readouterr().err


def test_status_models_and_openapi_use_real_available_contracts(brain_client, brain_server):
    status = run(brain_client, "status")
    assert status["code_editor"]["phase"] == "edit_diff_apply"
    assert status["draft_execution_verified"] is False
    assert status["tier"]["available"] is False
    routes = run(brain_client, "openapi", "--filter", "code-editor", "--method", "POST")
    assert routes["count"] > 0
    assert all(row["method"] == "POST" and "code-editor" in row["path"] for row in routes["routes"])
    login(brain_client)
    models = run(brain_client, "models")
    assert models["installed_local_models"]["models"][0]["name"] == "local-file"
    assert "cloud_catalog" in models
    assert not any("/api/fhd/" in path for _, path, _ in brain_server.calls)
    brain_server.cloud_degraded = True
    degraded = run(brain_client, "models")
    assert degraded["success"] is False
    assert "云目录不可用" in degraded["cloud_catalog"]["error"]


def test_invalid_json_is_explicit_partial_failure(brain_client, brain_server):
    brain_server.broken_json = True
    result = run(brain_client, "status")
    assert result["success"] is False
    assert "JSON" in result["desktop"]["error"]
    assert result["code_editor"]["success"] is True


def test_shell_reuses_chat_and_new_starts_another(brain_client, monkeypatch, capsys):
    login(brain_client)
    monkeypatch.setattr("sys.stdin", io.StringIO("hello\nagain\n/new\nthird\n/exit\n"))
    assert brain.shell(brain.parser().parse_args(["--json", "shell"]), brain_client) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0]["session_id"] == lines[1]["session_id"]
    assert lines[2]["session_id"] == lines[3]["session_id"]
    assert lines[0]["session_id"] != lines[2]["session_id"]


def test_edit_empty_stdin_create_is_explicit(brain_client, brain_server, monkeypatch):
    login(brain_client)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(BrainError, match="404"):
        run(brain_client, "edit", "new/file.txt", "--stdin")
    assert not (brain_server.workspace / "new").exists()
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    result = run(brain_client, "edit", "new/file.txt", "--stdin", "--create")
    assert result["is_new_file"] is True
    assert (brain_server.workspace / "new").is_dir()
    assert not (brain_server.workspace / "new/file.txt").exists()


def test_secret_input_refuses_getpass_echo_fallback(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def echo_fallback(prompt):
        raise brain.getpass.GetPassWarning("cannot disable echo")

    monkeypatch.setattr(brain.getpass, "getpass", echo_fallback)
    with pytest.raises(BrainError, match="拒绝回显"):
        brain._secret("Password: ")


def test_degraded_health_is_not_hidden_by_healthy_desktop(brain_client, brain_server, capsys):
    brain_server.health_degraded = True
    result = run(brain_client, "status")
    assert result["success"] is False
    assert result["desktop"]["mode"] == "desktop"
    assert brain._emit(result, False, "status") == 1
    text = capsys.readouterr().out
    assert "degraded" in text
    assert "LLM_RUNTIME_UNAVAILABLE" in text


@pytest.mark.parametrize("response", [b"not-json", b"[]", None])
def test_write_invalid_or_truncated_response_reports_unknown_without_retry(
    brain_client, monkeypatch, response
):
    login(brain_client)
    calls = []

    class BrokenResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            if response is None:
                raise http.client.IncompleteRead(b"partial", 20)
            return response

    def send_once(request, **kwargs):
        calls.append(request)
        return BrokenResponse()

    monkeypatch.setattr(brain_client.opener, "open", send_once)
    with pytest.raises(BrainError, match="结果可能未知.*未自动重试"):
        brain_client.request("POST", "/api/code-editor/apply/id", {})
    assert len(calls) == 1
