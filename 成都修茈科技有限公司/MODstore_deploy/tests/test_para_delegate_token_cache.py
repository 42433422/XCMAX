from modstore_server import para_delegate_handler as handler


class _FakeResponse:
    status_code = 200
    content = b'{"token":"guest-token"}'
    text = '{"token":"guest-token"}'

    def json(self):
        return {"token": "guest-token"}


class _FakeClient:
    def __init__(self):
        self.calls = 0

    def post(self, url):
        self.calls += 1
        return _FakeResponse()


def test_para_delegate_token_uses_env(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_AUTH_TOKEN", "env-token")
    handler._PARA_GUEST_AUTH_CACHE.clear()

    token = handler._get_para_token(_FakeClient(), "http://127.0.0.1:3001")

    assert token == {"token": "env-token", "source": "env"}


def test_para_delegate_guest_token_is_cached(monkeypatch):
    monkeypatch.delenv("MODSTORE_PARA_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("DEVFLEET_AUTH_TOKEN", raising=False)
    handler._PARA_GUEST_AUTH_CACHE.clear()
    client = _FakeClient()

    first = handler._get_para_token(client, "http://127.0.0.1:3001")
    second = handler._get_para_token(client, "http://127.0.0.1:3001")

    assert first == {"token": "guest-token", "source": "guest"}
    assert second == {"token": "guest-token", "source": "guest_cache"}
    assert client.calls == 1
