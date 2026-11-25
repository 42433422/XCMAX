"""Notion 页面导入：块纯文本化、嵌套、错误归一化与路由接线。"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.infrastructure.document_parsing import notion
from app.infrastructure.document_parsing.errors import DocumentSourceError
from app.infrastructure.document_parsing.notion import FetchedNotionPage, fetch_page

PAGE_ID = "0123456789abcdef0123456789abcdef"


class _Response:
    def __init__(
        self, payload: dict | None = None, *, status_code: int = 200, raw: bytes = b""
    ) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = raw or json.dumps(self._payload).encode("utf-8")

    def json(self):
        return self._payload


def _heading(text: str) -> dict:
    return {
        "type": "heading_1",
        "has_children": False,
        "heading_1": {"rich_text": [{"plain_text": text}]},
    }


def _paragraph(text: str, *, children: bool = False, block_id: str = "b2") -> dict:
    return {
        "id": block_id,
        "type": "paragraph",
        "has_children": children,
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _getter(*, empty: bool = False):
    calls: list[str] = []

    def _get(url, **kwargs):
        calls.append(url)
        if "/pages/" in url:
            return _Response(
                {
                    "object": "page",
                    "url": "https://www.notion.so/example",
                    "properties": {
                        "名称": {"type": "title", "title": [{"plain_text": "发布规范"}]}
                    },
                }
            )
        if url.endswith(f"/blocks/{PAGE_ID}/children?page_size=100"):
            return _Response(
                {
                    "results": []
                    if empty
                    else [_heading("发布规范"), _paragraph("第一段正文", children=True)],
                    "has_more": False,
                    "next_cursor": None,
                }
            )
        return _Response(
            {
                "results": [_paragraph("嵌套内容")],
                "has_more": False,
                "next_cursor": None,
            }
        )

    return _get, calls


def test_missing_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_NOTION_TOKEN", raising=False)
    with pytest.raises(ValueError, match="XCAGI_NOTION_TOKEN"):
        fetch_page(PAGE_ID)


@pytest.mark.parametrize("page_id", ["", "abc", "g" * 32, PAGE_ID + "x"])
def test_invalid_page_id_is_rejected(page_id: str) -> None:
    with pytest.raises(ValueError, match="页面 ID"):
        fetch_page(page_id)


def test_page_and_nested_blocks_are_flattened(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_NOTION_TOKEN", "secret")
    monkeypatch.delenv("XCAGI_NOTION_BASE_URL", raising=False)
    getter, calls = _getter()

    page = fetch_page(PAGE_ID, getter=getter)

    assert page.title == "发布规范"
    assert page.url == "https://www.notion.so/example"
    assert page.text.splitlines() == ["#发布规范", "第一段正文", "嵌套内容"]
    assert any("/blocks/b2/children" in url for url in calls)


def test_errors_and_empty_pages_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_NOTION_TOKEN", "secret")
    with pytest.raises(ValueError, match="Notion 返回 HTTP 404"):
        fetch_page(PAGE_ID, getter=lambda *_a, **_k: _Response(status_code=404))
    with pytest.raises(ValueError, match="Notion 读取失败"):
        fetch_page(
            PAGE_ID,
            getter=lambda *_a, **_k: _Response({"object": "error", "message": "unauthorized"}),
        )
    huge = b"x" * (notion.MAX_BYTES + 1)
    with pytest.raises(ValueError, match="大小限制"):
        fetch_page(PAGE_ID, getter=lambda *_a, **_k: _Response(raw=huge))
    empty_getter, _ = _getter(empty=True)
    with pytest.raises(ValueError, match="没有可导入的文本"):
        fetch_page(PAGE_ID, getter=empty_getter)


def test_route_ingests_notion_page(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return JSONResponse({"success": True})

    page = FetchedNotionPage(
        page_id=PAGE_ID,
        url="https://www.notion.so/example",
        title="发布规范",
        text="#发布规范\n第一段正文",
    )
    monkeypatch.setattr(notion, "fetch_page", lambda _pid: page)
    routes = DocumentRoutes(dispatch=lambda: _dispatch, uploads=lambda: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/datasets/kb/documents", json={"notion_page_id": PAGE_ID})

    assert response.status_code == 200
    params = calls[0]["params"]
    assert params["text"] == page.text
    assert params["source"] == "发布规范"
    assert params["document_id"] == page.url
    assert params["metadata"]["notion_page_id"] == PAGE_ID


def test_route_maps_notion_failure_and_exclusivity(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return JSONResponse({"success": True})

    def _boom(_pid):
        raise DocumentSourceError("未配置 XCAGI_NOTION_TOKEN")

    monkeypatch.setattr(notion, "fetch_page", _boom)
    routes = DocumentRoutes(dispatch=lambda: _dispatch, uploads=lambda: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    client = TestClient(app, raise_server_exceptions=False)

    failed = client.post("/datasets/kb/documents", json={"notion_page_id": PAGE_ID})
    mixed = client.post(
        "/datasets/kb/documents", json={"notion_page_id": PAGE_ID, "text": "inline"}
    )

    assert failed.status_code == 400
    assert "XCAGI_NOTION_TOKEN" in failed.json()["detail"]
    assert mixed.status_code == 422
    assert calls == []
