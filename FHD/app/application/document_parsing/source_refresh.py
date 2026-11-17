"""外部知识来源刷新：按入库时记录的坐标重新拉取正文。

入库时把 ``source_kind`` / ``source_ref`` 写入文档元数据，刷新动作据此重新抓取，
再交给既有入库链路生成新版本；本地文件与对象存储暂无稳定的来源坐标，明确拒绝。
"""

from __future__ import annotations

from typing import Any

SOURCE_KIND_KEY = "source_kind"
SOURCE_REF_KEY = "source_ref"

REFRESHABLE_KINDS = frozenset({"url", "confluence", "feishu", "notion"})


def source_coordinates(metadata: dict[str, Any] | None) -> tuple[str, str] | None:
    """返回 (source_kind, source_ref)；缺少坐标或暂不支持时返回 None。"""
    data = metadata or {}
    kind = str(data.get(SOURCE_KIND_KEY) or "").strip().lower()
    ref = str(data.get(SOURCE_REF_KEY) or "").strip()
    if kind not in REFRESHABLE_KINDS or not ref:
        return None
    return kind, ref


def fetch_source_text(kind: str, ref: str) -> tuple[str, str, dict[str, Any]]:
    """重新抓取来源，返回 (正文, 来源标签, 需要合并的元数据)。"""
    if kind == "url":
        from app.application.document_parsing.web_fetch import fetch_url_text

        page = fetch_url_text(ref)
        return page.text, page.title or page.url, {"source_url": page.url}
    if kind == "confluence":
        from app.application.document_parsing.confluence import fetch_page

        page = fetch_page(ref)
        return (
            page.text,
            page.title or f"confluence:{page.page_id}",
            {"confluence_page_id": page.page_id, "source_url": page.url},
        )
    if kind == "feishu":
        from app.application.document_parsing.feishu_doc import fetch_document

        doc = fetch_document(ref)
        return (
            doc.text,
            doc.title or f"feishu:{doc.document_id}",
            {"feishu_document_id": doc.document_id, "source_url": doc.url},
        )
    if kind == "notion":
        from app.application.document_parsing.notion import fetch_page

        notion = fetch_page(ref)
        return (
            notion.text,
            notion.title or f"notion:{notion.page_id}",
            {"notion_page_id": notion.page_id, "source_url": notion.url},
        )
    raise ValueError(f"unsupported refresh source: {kind}")
