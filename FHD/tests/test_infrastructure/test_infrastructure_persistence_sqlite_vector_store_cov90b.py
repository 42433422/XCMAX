"""真实行为测试: SQLiteVectorStore (cov90b 第二波)。

覆盖 create_or_update_index / upsert_chunks / query (含 except 降级分支) /
list_indexes / delete_index 的成功路径与边界/错误分支。

依赖仅 numpy + 标准库 sqlite3，使用 tmp_path 落真实临时库,离线确定性。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.infrastructure.persistence.sqlite_vector_store import SQLiteVectorStore


@pytest.fixture
def store(tmp_path):
    """每个测试一个独立的临时 SQLite 向量库。"""
    return SQLiteVectorStore(str(tmp_path / "vec.db"))


# ---------------------------------------------------------------------------
# _ensure_tables (构造时已调用) — 验证表结构真实落地
# ---------------------------------------------------------------------------


def test_ensure_tables_creates_schema(store):
    with store._get_conn() as conn:
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert "excel_vector_indexes" in names
    assert "excel_vector_chunks" in names


# ---------------------------------------------------------------------------
# create_or_update_index — INSERT + ON CONFLICT UPDATE 分支
# ---------------------------------------------------------------------------


def test_create_index_inserts_row(store):
    store.create_or_update_index("idx-1", "名字A", "a.xlsx")
    indexes = store.list_indexes()
    assert len(indexes) == 1
    row = indexes[0]
    assert row["index_id"] == "idx-1"
    assert row["name"] == "名字A"
    assert row["source_file"] == "a.xlsx"
    assert row["chunk_count"] == 0
    # created_at/updated_at 初始相等
    assert row["created_at"] == row["updated_at"]


def test_create_index_upsert_updates_name_and_source(store):
    store.create_or_update_index("idx-1", "旧名", "old.xlsx")
    before = store.list_indexes()[0]
    # 同 index_id 再次写入触发 ON CONFLICT DO UPDATE
    store.create_or_update_index("idx-1", "新名", "new.xlsx")
    after = store.list_indexes()
    assert len(after) == 1  # 没有插入第二行
    row = after[0]
    assert row["name"] == "新名"
    assert row["source_file"] == "new.xlsx"
    # created_at 保持不变, updated_at 被刷新 (>= 原值)
    assert row["created_at"] == before["created_at"]
    assert row["updated_at"] >= before["updated_at"]


# ---------------------------------------------------------------------------
# upsert_chunks — 空入参短路 / 真实写入 / 计数刷新 / 替换语义
# ---------------------------------------------------------------------------


def test_upsert_chunks_empty_returns_zero(store):
    store.create_or_update_index("idx-1", "n", "f.xlsx")
    assert store.upsert_chunks("idx-1", []) == 0
    # chunk_count 未被改动 (短路, 不执行 DELETE/UPDATE)
    assert store.list_indexes()[0]["chunk_count"] == 0


def test_upsert_chunks_writes_and_updates_count(store):
    store.create_or_update_index("idx-1", "n", "f.xlsx")
    chunks = [
        {
            "chunk_id": "c1",
            "content": "内容一",
            "embedding": [1.0, 0.0],
            "metadata": {"sheet": "S1"},
        },
        {
            "chunk_id": "c2",
            "content": "内容二",
            "embedding": [0.0, 1.0],
            # 故意不带 metadata, 走 chunk.get("metadata", {})
        },
    ]
    written = store.upsert_chunks("idx-1", chunks)
    assert written == 2
    # 索引 chunk_count 被刷新
    assert store.list_indexes()[0]["chunk_count"] == 2
    # 数据真实落库
    with store._get_conn() as conn:
        rows = conn.execute(
            "SELECT chunk_id, content, embedding, metadata FROM excel_vector_chunks "
            "WHERE index_id = ? ORDER BY chunk_id",
            ("idx-1",),
        ).fetchall()
    assert [r["chunk_id"] for r in rows] == ["c1", "c2"]
    assert rows[0]["content"] == "内容一"
    # 缺省 metadata 序列化成 "{}"
    assert rows[1]["metadata"] == "{}"


def test_upsert_chunks_replaces_previous(store):
    store.create_or_update_index("idx-1", "n", "f.xlsx")
    store.upsert_chunks(
        "idx-1",
        [{"chunk_id": "old", "content": "x", "embedding": [1.0], "metadata": {}}],
    )
    # 再次 upsert 会先 DELETE 同 index_id 旧 chunk
    store.upsert_chunks(
        "idx-1",
        [{"chunk_id": "new", "content": "y", "embedding": [1.0], "metadata": {}}],
    )
    with store._get_conn() as conn:
        ids = [
            r[0]
            for r in conn.execute(
                "SELECT chunk_id FROM excel_vector_chunks WHERE index_id = ?",
                ("idx-1",),
            ).fetchall()
        ]
    assert ids == ["new"]
    assert store.list_indexes()[0]["chunk_count"] == 1


# ---------------------------------------------------------------------------
# query — 相似度排序 / top_k 截断 / 损坏 embedding 走 except 降级
# ---------------------------------------------------------------------------


def test_query_returns_scored_sorted(store):
    store.create_or_update_index("idx-1", "n", "f.xlsx")
    store.upsert_chunks(
        "idx-1",
        [
            {
                "chunk_id": "match",
                "content": "对齐向量",
                "embedding": [1.0, 0.0],
                "metadata": {"k": "v"},
            },
            {
                "chunk_id": "ortho",
                "content": "正交向量",
                "embedding": [0.0, 1.0],
                "metadata": {},
            },
        ],
    )
    results = store.query("idx-1", [1.0, 0.0], top_k=5)
    assert len(results) == 2
    # 与查询向量对齐者得分更高, 排在最前
    assert results[0]["chunk_id"] == "match"
    assert results[0]["score"] > results[1]["score"]
    # metadata 被反序列化为 dict
    assert results[0]["metadata"] == {"k": "v"}
    assert results[0]["content"] == "对齐向量"


def test_query_top_k_truncates(store):
    store.create_or_update_index("idx-1", "n", "f.xlsx")
    store.upsert_chunks(
        "idx-1",
        [
            {"chunk_id": f"c{i}", "content": str(i), "embedding": [float(i), 1.0], "metadata": {}}
            for i in range(5)
        ],
    )
    results = store.query("idx-1", [1.0, 0.0], top_k=2)
    assert len(results) == 2


def test_query_top_k_zero_clamped_to_one(store):
    store.create_or_update_index("idx-1", "n", "f.xlsx")
    store.upsert_chunks(
        "idx-1",
        [
            {"chunk_id": "c1", "content": "a", "embedding": [1.0], "metadata": {}},
            {"chunk_id": "c2", "content": "b", "embedding": [1.0], "metadata": {}},
        ],
    )
    # top_k=0 -> max(top_k, 1) == 1
    results = store.query("idx-1", [1.0], top_k=0)
    assert len(results) == 1


def test_query_empty_index_returns_empty(store):
    store.create_or_update_index("idx-1", "n", "f.xlsx")
    assert store.query("idx-1", [1.0, 0.0]) == []


def test_query_skips_corrupt_embedding(store):
    """损坏的 embedding JSON 触发 except RECOVERABLE_ERRORS -> continue。"""
    store.create_or_update_index("idx-1", "n", "f.xlsx")
    store.upsert_chunks(
        "idx-1",
        [{"chunk_id": "good", "content": "ok", "embedding": [1.0, 0.0], "metadata": {}}],
    )
    # 直接写一行非法 embedding JSON, 绕开 upsert 的 json.dumps
    with store._get_conn() as conn:
        conn.execute(
            "INSERT INTO excel_vector_chunks"
            "(chunk_id, index_id, content, embedding, metadata, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            ("bad", "idx-1", "corrupt", "not-json{", "{}", 0.0),
        )
        conn.commit()
    results = store.query("idx-1", [1.0, 0.0], top_k=10)
    # 损坏行被跳过, 仅保留合法行
    ids = [r["chunk_id"] for r in results]
    assert ids == ["good"]


def test_query_filters_arg_ignored(store):
    """filters 当前实现被 del 掉, 传入不影响结果且不报错。"""
    store.create_or_update_index("idx-1", "n", "f.xlsx")
    store.upsert_chunks(
        "idx-1",
        [{"chunk_id": "c1", "content": "x", "embedding": [1.0, 0.0], "metadata": {}}],
    )
    results = store.query("idx-1", [1.0, 0.0], top_k=5, filters={"any": "thing"})
    assert [r["chunk_id"] for r in results] == ["c1"]


# ---------------------------------------------------------------------------
# list_indexes — 排序 (updated_at DESC) 与空库
# ---------------------------------------------------------------------------


def test_list_indexes_empty(store):
    assert store.list_indexes() == []


def test_list_indexes_orders_by_updated_at_desc(store):
    store.create_or_update_index("idx-old", "old", "o.xlsx")
    store.create_or_update_index("idx-new", "new", "n.xlsx")
    # 触碰 idx-old 使其 updated_at 最新 -> 应排到最前
    store.create_or_update_index("idx-old", "old-touched", "o2.xlsx")
    listed = store.list_indexes()
    assert [r["index_id"] for r in listed][0] == "idx-old"
    # 行被转成 dict, 含全部列
    assert set(listed[0].keys()) == {
        "index_id",
        "name",
        "source_file",
        "created_at",
        "updated_at",
        "chunk_count",
    }


# ---------------------------------------------------------------------------
# delete_index — 命中 (rowcount>0) 与未命中 (False) 两分支
# ---------------------------------------------------------------------------


def test_delete_index_existing_returns_true(store):
    store.create_or_update_index("idx-1", "n", "f.xlsx")
    store.upsert_chunks(
        "idx-1",
        [{"chunk_id": "c1", "content": "x", "embedding": [1.0], "metadata": {}}],
    )
    assert store.delete_index("idx-1") is True
    # 索引与 chunk 均被删
    assert store.list_indexes() == []
    with store._get_conn() as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM excel_vector_chunks WHERE index_id = ?",
            ("idx-1",),
        ).fetchone()[0]
    assert remaining == 0


def test_delete_index_missing_returns_false(store):
    # 不存在的 index_id -> rowcount == 0 -> False
    assert store.delete_index("nope") is False


def test_get_conn_uses_row_factory(store):
    """_get_conn 设置 row_factory = sqlite3.Row。"""
    with store._get_conn() as conn:
        assert conn.row_factory is sqlite3.Row
