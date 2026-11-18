"""PDF 表格上下文：命中表格块时附带完整 Markdown 表格，且不跨文档。"""

from __future__ import annotations

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag.retrieval import _table_context
from app.application.dataset_rag_app_service import DatasetRagApplicationService

_TABLE = "[table 1]\n| 型号 | 价格 |\n|---|---|\n| A1 | 100 元 |\n| B2 | 200 元 |"


def _ctx() -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id="alice",
        tenant_id="t1",
        permissions=frozenset({"dataset.read", "dataset.write"}),
        is_admin=False,
    )


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def test_table_context_stops_at_next_marker_and_budget() -> None:
    text = f"[page 1]\n说明文字\n{_TABLE}\n[table 2]\n| 其它 | 表 |"

    block = _table_context([text])

    assert block.startswith("[table 1]")
    assert "A1 | 100" in block
    assert "table 2" not in block

    assert _table_context([text], max_chars=20).startswith("[table 1]")
    assert len(_table_context([text], max_chars=20)) <= 20


def test_table_context_joins_across_chunks() -> None:
    first = "[table 1]\n| 型号 | 价格 |"
    second = "|---|---|\n| A1 | 100 元 |"

    assert _table_context([first, second]) == f"{first}\n{second}"


def test_query_attaches_table_context(tmp_path) -> None:
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="报价单.pdf",
        text=f"[page 1]\n产品报价如下。\n{_TABLE}\n",
        tenant_id="t1",
        chunk_strategy="fixed",
        chunk_size=500,
        chunk_overlap=0,
        access_context=_ctx(),
    )
    service.ingest_document(
        dataset_id="kb",
        source="说明.md",
        text="安装说明：双击安装包后按提示完成。",
        tenant_id="t1",
        access_context=_ctx(),
    )

    result = service.query(
        dataset_id="kb", query="A1 价格", top_k=5, tenant_id="t1", access_context=_ctx()
    )

    tables = [
        (row.get("metadata") or {}).get("table_context")
        for row in result["chunks"]
        if (row.get("metadata") or {}).get("table_context")
    ]
    assert tables
    assert "| A1 | 100 元 |" in tables[0]
    assert all("安装说明" not in str(text) for text in tables)
