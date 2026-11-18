"""外部知识来源刷新：按入库时记录的坐标重新拉取正文。

入库时把 ``source_kind`` / ``source_ref`` 写入文档元数据，刷新动作据此重新抓取，
再交给既有入库链路生成新版本；本地文件与对象存储暂无稳定的来源坐标，明确拒绝。
"""

from __future__ import annotations

from typing import Any

SOURCE_KIND_KEY = "source_kind"
SOURCE_REF_KEY = "source_ref"

REFRESHABLE_KINDS = frozenset({"url", "confluence", "feishu", "notion", "yuque"})


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
        from app.infrastructure.document_parsing.web_fetch import fetch_url_text

        page = fetch_url_text(ref)
        return page.text, page.title or page.url, {"source_url": page.url}
    if kind == "confluence":
        from app.infrastructure.document_parsing.confluence import fetch_page as fetch_confluence

        confluence = fetch_confluence(ref)
        return (
            confluence.text,
            confluence.title or f"confluence:{confluence.page_id}",
            {"confluence_page_id": confluence.page_id, "source_url": confluence.url},
        )
    if kind == "feishu":
        from app.infrastructure.document_parsing.feishu_doc import fetch_document as fetch_feishu

        feishu = fetch_feishu(ref)
        return (
            feishu.text,
            feishu.title or f"feishu:{feishu.document_id}",
            {"feishu_document_id": feishu.document_id, "source_url": feishu.url},
        )
    if kind == "notion":
        from app.infrastructure.document_parsing.notion import fetch_page as fetch_notion

        notion = fetch_notion(ref)
        return (
            notion.text,
            notion.title or f"notion:{notion.page_id}",
            {"notion_page_id": notion.page_id, "source_url": notion.url},
        )
    if kind == "yuque":
        from app.infrastructure.document_parsing.yuque import fetch_document as fetch_yuque

        yuque = fetch_yuque(ref)
        return (
            yuque.text,
            yuque.title or f"yuque:{ref}",
            {"yuque_document_ref": ref, "source_url": yuque.url},
        )
    raise ValueError(f"unsupported refresh source: {kind}")
