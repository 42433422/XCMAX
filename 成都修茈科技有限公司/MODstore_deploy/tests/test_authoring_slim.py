from __future__ import annotations

from modstore_server.authoring import slim_openapi_paths


def test_slim_openapi_paths_filters_api() -> None:
    spec = {
        "paths": {
            "/api/health": {"get": {}},
            "/static/x": {"get": {}},
            "/api/v1/a": {"get": {}, "post": {}},
        }
    }
    slim = slim_openapi_paths(spec)
    paths = [x["path"] for x in slim]
    assert "/api/health" in paths
    assert "/api/v1/a" in paths
    assert "/static/x" not in paths
    post = next(x for x in slim if x["path"] == "/api/v1/a")
    assert "GET" in post["methods"] and "POST" in post["methods"]
