"""Source failures remain diagnosable without leaking through the ingestion API."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.knowledge.document_routes import DocumentRoutes
from app.infrastructure.document_parsing import feishu_doc, object_store
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

_PRIVATE_DETAIL = "internal-path=/srv/customer/private.json upstream-token=synthetic-only"
_INPUTS = {
    "url": {"url": "https://example.invalid/page"},
    "confluence": {"confluence_page_id": "123"},
    "feishu": {"feishu_document_id": "docx12345678"},
    "notion": {"notion_page_id": "0123456789abcdef0123456789abcdef"},
    "yuque": {"yuque_document_ref": "team/repo/doc"},
    "s3": {"s3_uri": "s3://kb/document.pdf"},
}


def _fail(*_args, **_kwargs):
    raise OSError(_PRIVATE_DETAIL)


def _route_client(headers):
    def dispatch(**_kwargs):
        pytest.fail("Failed sources must never be dispatched for ingestion")

    routes = DocumentRoutes(dispatch=lambda: dispatch, uploads=lambda: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    return TestClient(app, headers=headers)


@pytest.mark.parametrize(
    ("source", "failure", "public_message"),
    [
        ("confluence", "transport", "Confluence 请求失败"),
        ("confluence", "decode", "Confluence 响应无法解析"),
        ("feishu", "auth_transport", "飞书鉴权请求失败"),
        ("feishu", "auth_decode", "飞书鉴权响应无法解析"),
        ("feishu", "auth_error", "飞书鉴权失败"),
        ("feishu", "transport", "飞书文档请求失败"),
        ("feishu", "decode", "飞书文档响应无法解析"),
        ("feishu", "remote_error", "飞书文档读取失败"),
        ("notion", "transport", "Notion 请求失败"),
        ("notion", "decode", "Notion 响应无法解析"),
        ("notion", "remote_error", "Notion 读取失败"),
        ("yuque", "transport", "语雀请求失败"),
        ("yuque", "decode", "语雀响应无法解析"),
        ("s3", "transport", "对象存储读取失败"),
        ("s3", "body", "对象读取失败"),
    ],
)
def test_ingestion_failure_keeps_details_in_server_logs_only(
    monkeypatch, caplog, source, failure, public_message, trusted_actor
):
    for key, value in {
        "XCAGI_CONFLUENCE_BASE_URL": "https://example.invalid/wiki",
        "XCAGI_CONFLUENCE_API_TOKEN": "synthetic-token",
        "XCAGI_FEISHU_APP_ID": "synthetic-app",
        "XCAGI_FEISHU_APP_SECRET": "synthetic-secret",
        "XCAGI_NOTION_TOKEN": "synthetic-token",
        "XCAGI_YUQUE_TOKEN": "synthetic-token",
        "XCAGI_S3_ALLOWED_BUCKETS": "kb",
    }.items():
        monkeypatch.setenv(key, value)
    feishu_doc.reset_token_cache_for_tests()
    remote_error = {
        "object": "error",
        "code": 10003,
        "message": _PRIVATE_DETAIL,
        "msg": _PRIVATE_DETAIL,
    }
    failed_response = SimpleNamespace(
        status_code=200,
        content=b"{}",
        json=_fail if failure.endswith("decode") else lambda: remote_error,
    )
    token_response = SimpleNamespace(
        status_code=200,
        json=lambda: {"code": 0, "tenant_access_token": "synthetic-token", "expire": 3600},
    )
    monkeypatch.setattr(
        "requests.get",
        _fail if failure == "transport" else lambda *_a, **_k: failed_response,
    )
    monkeypatch.setattr(
        "requests.post",
        (
            _fail
            if failure == "auth_transport"
            else lambda *_a, **_k: (
                failed_response if failure.startswith("auth_") else token_response
            )
        ),
    )
    body = SimpleNamespace(read=_fail, close=lambda: None)
    s3_client = SimpleNamespace(
        get_object=_fail if failure == "transport" else lambda **_kwargs: {"Body": body}
    )
    monkeypatch.setattr(object_store, "_client", lambda: s3_client)

    actor = trusted_actor(permissions=["dataset.write"])
    with _route_client(actor.headers) as client:
        response = client.post("/datasets/kb/documents", json=_INPUTS[source])

    assert response.status_code == 400
    assert response.json() == {"detail": public_message}
    assert _PRIVATE_DETAIL in caplog.text
    if not failure.endswith("error"):
        assert any(record.exc_info for record in caplog.records)


@pytest.mark.parametrize(
    ("source", "target", "public_message"),
    [
        ("url", "web_fetch.fetch_url_text", "网页导入失败"),
        ("confluence", "confluence.fetch_page", "Confluence 导入失败"),
        ("feishu", "feishu_doc.fetch_document", "飞书文档导入失败"),
        ("notion", "notion.fetch_page", "Notion 导入失败"),
        ("yuque", "yuque.fetch_document", "语雀文档导入失败"),
        ("s3", "object_store.fetch_object", "对象暂存失败"),
    ],
)
def test_unclassified_value_errors_do_not_become_public_messages(
    monkeypatch, caplog, source, target, public_message, trusted_actor
):
    def fail(*_args, **_kwargs):
        raise ValueError(_PRIVATE_DETAIL)

    monkeypatch.setattr(f"app.infrastructure.document_parsing.{target}", fail)
    actor = trusted_actor(permissions=["dataset.write"])
    with _route_client(actor.headers) as client:
        response = client.post("/datasets/kb/documents", json=_INPUTS[source])

    assert response.status_code == 400
    assert response.json() == {"detail": public_message}
    assert _PRIVATE_DETAIL in caplog.text
    assert any(record.exc_info for record in caplog.records)
