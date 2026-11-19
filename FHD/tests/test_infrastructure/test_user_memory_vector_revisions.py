"""Immutable authority revisions with compatible ungoverned archive updates."""

from __future__ import annotations

import json

import pytest

from app.infrastructure.persistence.user_memory_vector_store import SQLiteUserMemoryVectorStore


@pytest.mark.parametrize(
    ("old_revision", "new_revision", "new_content", "written"),
    [
        (None, None, "archive correction", 1),
        (2, 1, "stale correction", 0),
        (2, 2, "conflicting correction", 0),
        (2, 2, "confirmed fact", 1),
        (2, 3, "new confirmed fact", 1),
        (2, None, "legacy downgrade", 0),
    ],
)
def test_revision_content_guard(tmp_path, old_revision, new_revision, new_content, written):
    store = SQLiteUserMemoryVectorStore(str(tmp_path / "memory.sqlite"))
    store.create_or_update_index("owner", "owner")
    original = {
        "chunk_id": "source",
        "content": "confirmed fact",
        "embedding": [1.0, 0.0],
        "metadata": {} if old_revision is None else {"source_revision": old_revision},
    }
    assert store.upsert_chunks("owner", [original]) == 1
    replacement = {
        **original,
        "content": new_content,
        "embedding": [0.0, 1.0],
        "metadata": {} if new_revision is None else {"source_revision": new_revision},
    }
    assert store.upsert_chunks("owner", [replacement]) == written
    with store._get_conn() as connection:
        content, embedding, metadata = connection.execute(
            "SELECT content, embedding, metadata FROM user_memory_vector_chunks"
        ).fetchone()
    expected = replacement if written else original
    assert content == expected["content"]
    assert json.loads(embedding) == expected["embedding"]
    assert json.loads(metadata) == expected["metadata"]
