import pytest


def test_resolve_cors_strips_wildcard(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*,http://example.com")
    from app.fastapi_app import resolve_cors_allow_origins

    origins = resolve_cors_allow_origins()
    assert "*" not in origins
    assert "http://example.com" in origins


def test_resolve_cors_only_star_uses_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    from app.fastapi_app import resolve_cors_allow_origins

    origins = resolve_cors_allow_origins()
    assert "*" not in origins
    assert "http://127.0.0.1:5000" in origins


def _build_cors_app():
    """Build a real CORSMiddleware app from the same config the factory uses."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from app.fastapi_app import resolve_cors_allow_origin_regex, resolve_cors_allow_origins

    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    kwargs = {
        "allow_origins": resolve_cors_allow_origins(),
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }
    regex = resolve_cors_allow_origin_regex()
    if regex:
        kwargs["allow_origin_regex"] = regex
    app.add_middleware(CORSMiddleware, **kwargs)
    return app


def test_cors_denies_non_allowlisted_origin(monkeypatch: pytest.MonkeyPatch):
    """An attacker Origin must never be granted access (and never via '*')."""
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    monkeypatch.delenv("CORS_ALLOW_ORIGIN_REGEX", raising=False)
    monkeypatch.setenv("XCAGI_DEV_ALLOW_LAN_CORS", "0")
    monkeypatch.setenv("XCAGI_DEBUG", "0")

    from fastapi.testclient import TestClient

    from app.fastapi_app import resolve_cors_allow_origins

    # The generated allow-list must never fall back to a wildcard.
    assert "*" not in resolve_cors_allow_origins()

    app = _build_cors_app()
    with TestClient(app) as client:
        # Positive control: an allowlisted origin is genuinely echoed, proving
        # the middleware is active (otherwise the denial below would be vacuous).
        allowed = "http://127.0.0.1:5173"
        allowed_response = client.get("/ping", headers={"Origin": allowed})
        assert allowed_response.headers.get("access-control-allow-origin") == allowed

        # Simple request from an arbitrary attacker origin: no grant.
        attacker = "https://evil.attacker.example"
        simple = client.get("/ping", headers={"Origin": attacker})
        assert simple.headers.get("access-control-allow-origin") is None

        # Preflight from the same attacker origin must not be granted either.
        preflight = client.options(
            "/ping",
            headers={"Origin": attacker, "Access-Control-Request-Method": "GET"},
        )
        allow_origin = preflight.headers.get("access-control-allow-origin")
        assert allow_origin != attacker
        assert allow_origin != "*"
