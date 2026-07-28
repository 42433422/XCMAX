from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import TestingConfig
from app.fastapi_app import factory


def test_direct_factory_app_becomes_process_singleton(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_DESKTOP_FAST_START", "1")
    monkeypatch.setattr(factory, "_app_singleton", None)

    app = factory.create_fastapi_app(
        config_object=TestingConfig,
        enable_cors=False,
        enable_docs=False,
    )

    assert factory.get_fastapi_app() is app


def test_factory_uses_runtime_version_for_health(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_DESKTOP_FAST_START", "1")
    monkeypatch.setenv("XCAGI_VERSION", "1.0.2.4")
    monkeypatch.setattr(factory, "_app_singleton", None)

    app = factory.create_fastapi_app(
        config_object=TestingConfig,
        enable_cors=False,
        enable_docs=False,
    )

    assert app.version == "1.0.2.4"
    response = TestClient(app).get("/api/health", params={"lite": True})
    assert response.status_code == 200
    assert response.json()["version"] == "1.0.2.4"
