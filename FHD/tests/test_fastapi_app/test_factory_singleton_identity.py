from __future__ import annotations

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
