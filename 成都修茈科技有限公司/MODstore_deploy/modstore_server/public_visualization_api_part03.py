# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.public_visualization_api")


def get_public_visualization_data() -> dict[str, _facade().Any]:
    global _CACHE_VALUE, _CACHE_CREATED_MONOTONIC
    now = _facade().time.monotonic()
    ttl = _facade()._cache_ttl_seconds()
    with _facade()._CACHE_LOCK:
        if _facade()._CACHE_VALUE is not None and now - _facade()._CACHE_CREATED_MONOTONIC < ttl:
            return _facade().copy.deepcopy(_facade()._CACHE_VALUE)
        value = _facade()._build_public_visualization_data()
        _facade()._CACHE_VALUE = value
        _facade()._CACHE_CREATED_MONOTONIC = _facade().time.monotonic()
        return _facade().copy.deepcopy(value)


@_facade().router.get(
    "/api/public/visualization", summary="官网 AI 业务、软件下载与版本交付实时聚合"
)
def public_visualization(response: _facade().Response) -> dict[str, _facade().Any]:
    response.headers["Cache-Control"] = "public, max-age=15, stale-if-error=60"
    payload = _facade().get_public_visualization_data()
    response.headers["X-Data-Generated-At"] = payload["generated_at"]
    return payload
