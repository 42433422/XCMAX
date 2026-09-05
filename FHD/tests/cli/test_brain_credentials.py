from __future__ import annotations

import io
import json

import pytest

from app.cli import brain
from app.cli.brain_client import BrainClient
from app.cli.brain_session import BrainError, SessionStore


def test_login_cookie_persistence_permissions_and_no_secret_output(
    brain_client, brain_server, monkeypatch, capsys
):
    monkeypatch.setattr("sys.stdin", io.StringIO("fixture-password\n"))
    args = [
        "--json",
        "--origin",
        brain_server.origin,
        "--session-dir",
        str(brain_client.store.directory),
        "login",
        "--username",
        "alice",
        "--password-stdin",
    ]
    assert brain.main(args) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["username"] == "alice"
    assert not any(
        secret in output.out + output.err
        for secret in ("fixture-password", "private-session", "private-jwt")
    )
    store = SessionStore(brain_server.origin, brain_client.store.directory)
    assert store.cookie_path.stat().st_mode & 0o777 == 0o600
    assert store.state_path.stat().st_mode & 0o777 == 0o600
    assert store.directory.stat().st_mode & 0o777 == 0o700
    assert BrainClient(store).require_login()["data"]["user"]["username"] == "alice"
    assert "private-session" in store.cookie_path.read_text()


def test_cookie_and_conversation_never_cross_origin(brain_client, brain_server):
    brain_client.login("alice", "fixture-password", "enterprise")
    first = brain_client.chat("hello")
    other = SessionStore("http://127.0.0.1:1", brain_client.store.directory)
    assert list(other.cookies) == []
    assert "conversation_id" not in other.state
    same = BrainClient(SessionStore(brain_server.origin, brain_client.store.directory))
    assert same.chat("again")["session_id"] == first["session_id"]


def test_login_account_switch_and_logout_clear_conversation(brain_client):
    brain_client.login("alice", "fixture-password", "enterprise")
    first = brain_client.chat("hello")["session_id"]
    brain_client.login("bob", "fixture-password", "enterprise")
    assert "conversation_id" not in brain_client.store.state
    assert brain_client.chat("hello")["session_id"] != first
    brain_client.logout()
    assert "conversation_id" not in brain_client.store.state
    assert list(brain_client.store.cookies) == []
    with pytest.raises(BrainError, match="请先 login"):
        brain_client.chat("after logout")


def test_failed_login_has_nonzero_exit_and_preserves_server_message(
    brain_server, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr("sys.stdin", io.StringIO("wrong-password\n"))
    assert (
        brain.main(
            [
                "--origin",
                brain_server.origin,
                "--session-dir",
                str(tmp_path / "private"),
                "login",
                "--username",
                "alice",
                "--password-stdin",
            ]
        )
        == 1
    )
    assert "账号或密码错误" in capsys.readouterr().err


@pytest.mark.parametrize(
    "command",
    [
        ["models"],
        ["chat", "hello"],
        ["analyze", "note.txt"],
        ["edit", "note.txt", "--stdin"],
        ["diff", "old-edit"],
        ["apply", "old-edit", "--confirm"],
        ["draft", "note.txt", "--instruction", "change"],
    ],
)
def test_anonymous_cannot_reach_business_api_even_with_p2(
    command, brain_client, brain_server, monkeypatch
):
    monkeypatch.setenv("XCAGI_BRAIN_P2_TOKEN", "fixture-p2-secret")
    with pytest.raises(BrainError, match="请先 login"):
        brain.execute(brain.parser().parse_args(command), brain_client)
    assert [path for _, path, _ in brain_server.calls] == ["/api/auth/me"]


def test_live_expiry_checked_before_every_action(brain_client, brain_server):
    brain_client.login("alice", "fixture-password", "enterprise")
    brain_client.chat("before")
    brain_server.expired = True
    brain_server.calls.clear()
    with pytest.raises(BrainError, match="请先登录"):
        brain_client.chat("must not send")
    assert "conversation_id" not in brain_client.store.state
    assert [path for _, path, _ in brain_server.calls] == ["/api/auth/me"]


def test_origin_redirect_does_not_forward_credentials(brain_client, brain_server):
    brain_server.redirect = brain_server.origin + "/api/ai/unified_chat"
    with pytest.raises(BrainError, match="重定向"):
        brain_client.login("alice", "fixture-password", "enterprise")
    assert not any(path == "/api/ai/unified_chat" for _, path, _ in brain_server.calls)


def test_existing_open_directory_is_rejected_without_chmod(tmp_path):
    directory = tmp_path / "shared"
    directory.mkdir(mode=0o755)
    before = directory.stat().st_mode
    with pytest.raises(BrainError, match="0700"):
        SessionStore("http://localhost:17500", directory)
    assert directory.stat().st_mode == before


def test_session_symlink_and_open_cookie_file_rejected(tmp_path):
    store = SessionStore("http://localhost:17500", tmp_path / "private")
    store.save()
    store.cookie_path.chmod(0o644)
    with pytest.raises(BrainError, match="0600"):
        SessionStore(store.origin, store.directory)
    store.cookie_path.unlink()
    target = tmp_path / "untouched"
    target.write_text("keep")
    store.cookie_path.symlink_to(target)
    with pytest.raises(BrainError, match="符号链接"):
        SessionStore(store.origin, store.directory)
    assert target.read_text() == "keep"


def test_secret_options_and_defaults(monkeypatch):
    monkeypatch.delenv("XCAGI_BRAIN_ORIGIN", raising=False)
    monkeypatch.delenv("XCAGI_DESKTOP_PORT", raising=False)
    assert brain.parser().parse_args(["status"]).origin == "http://127.0.0.1:17500"
    monkeypatch.setenv("XCAGI_DESKTOP_PORT", "18234")
    assert brain.parser().parse_args(["status"]).origin.endswith(":18234")
    monkeypatch.setenv("XCAGI_DESKTOP_PORT", "70000")
    assert brain.parser().parse_args(["status"]).origin.endswith(":17500")
    with pytest.raises(SystemExit):
        brain.parser().parse_args(["login", "--username", "alice", "--password", "secret"])


@pytest.mark.parametrize(
    "origin", ["http://example.org", "https://name:pass@example.org", "https://example.org/api"]
)
def test_unsafe_origin_is_rejected(origin, tmp_path):
    with pytest.raises(BrainError):
        SessionStore(origin, tmp_path / "private")


@pytest.mark.parametrize("deleted", [True, False])
def test_real_logout_route_boolean_contract(deleted, monkeypatch):
    from types import SimpleNamespace

    from starlette.requests import Request

    from app.application import auth_app_service
    from app.fastapi_routes import market_account
    from app.fastapi_routes.domains.auth.routes import auth_logout

    seen = []

    def logout(sid):
        seen.append(sid)
        return deleted

    monkeypatch.setattr(
        auth_app_service, "get_auth_app_service", lambda: SimpleNamespace(logout=logout)
    )
    monkeypatch.setattr(market_account, "clear_session_market_token", lambda sid: None)
    request = Request({"type": "http", "headers": [(b"cookie", b"session_id=contract-session")]})
    response = auth_logout(request)
    assert json.loads(response.body) is deleted
    assert seen == ["contract-session"]
    assert 'session_id=""' in response.headers["set-cookie"]


def test_logout_false_reports_failure_but_clears_local_state(brain_client, monkeypatch):
    brain_client.login("alice", "fixture-password", "enterprise")
    brain_client.chat("hello")

    class FalseResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return b"false"

    monkeypatch.setattr(brain_client.opener, "open", lambda *a, **kw: FalseResponse())
    with pytest.raises(BrainError, match="未完成请求"):
        brain_client.logout()
    assert list(brain_client.store.cookies) == []
    assert "conversation_id" not in brain_client.store.state


def test_password_stdin_refuses_echoing_terminal(brain_client, brain_server, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    with pytest.raises(BrainError, match="隐藏输入"):
        brain.execute(
            brain.parser().parse_args(["login", "--username", "alice", "--password-stdin"]),
            brain_client,
        )
    assert brain_server.calls == []


def test_invalid_p2_header_is_rejected_without_secret_in_error(monkeypatch):
    monkeypatch.setenv("XCAGI_BRAIN_P2_TOKEN", "private-secret\nforged-header")
    with pytest.raises(BrainError) as exc:
        brain._p2_token()
    assert "private-secret" not in str(exc.value)
