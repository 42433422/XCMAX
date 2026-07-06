from __future__ import annotations

from app.utils.openapi_path import (
    filter_proxy_request_headers,
    normalize_path_template,
    url_rule_to_openapi_path,
)


def test_url_rule_to_openapi_path_converts_supported_converters() -> None:
    assert url_rule_to_openapi_path(
        "/api/<int:user_id>/<float:score>/<path:item_path>/<uuid:request_id>/<string:name>/<plain>"
    ) == ("/api/{user_id:int}/{score:float}/{item_path:path}/{request_id}/{name}/{plain}")


def test_url_rule_to_openapi_path_leaves_unknown_converter_literal() -> None:
    assert url_rule_to_openapi_path("/api/<slug:item>") == "/api/<slug:item>"


def test_normalize_path_template_handles_empty_root_trailing_and_typed_params() -> None:
    assert normalize_path_template("") == "/"
    assert normalize_path_template("/") == "/"
    assert normalize_path_template("/api/items/") == "/api/items"
    assert normalize_path_template("/api/<literal>/{user_id:int}/{path:path}/") == (
        "/api/<literal>/{user_id}/{path}"
    )


def test_filter_proxy_request_headers_skips_hop_by_hop_headers() -> None:
    assert filter_proxy_request_headers(
        [
            (b"Host", b"example.test"),
            (b"Content-Length", b"10"),
            (b"Connection", b"keep-alive"),
            (b"Transfer-Encoding", b"chunked"),
            (b"X-Trace", b"abc"),
            ("X-Cafe".encode("latin-1"), "caf\xe9".encode("latin-1")),
        ]
    ) == {"X-Trace": "abc", "X-Cafe": "caf\xe9"}
