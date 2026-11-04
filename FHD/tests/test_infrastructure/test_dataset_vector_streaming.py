"""Exact SQLite retrieval keeps filter/version semantics without retaining N vectors."""

import gc
import tracemalloc

import pytest

from app.infrastructure.rag.dataset_vector_index import (
    DatasetVectorSQLiteIndex,
    _cosine,
    _filter_chunks,
    _lexical_score,
    _row_to_chunk,
    _tokenize_for_lexical,
)
from app.infrastructure.rag.hybrid_retriever import RetrievedChunk


def chunks(count, dimensions=64):
    return [
        RetrievedChunk(
            text=f"row {number}",
            score=0,
            source="document",
            chunk_index=number // 2,
            char_start=number,
            char_end=number + 1,
            metadata={
                "tenant_id": "a" if number % 3 else "b",
                "source": f"source-{number // 4}",
                "document_id": str(number),
                "document_version": number % 4 - 1,
                "version_label": "release" if number % 2 else "draft",
                "kind": number % 2,
                "_embedding": [((number + index) % 17) / 17 for index in range(dimensions)],
            },
        )
        for number in range(count)
    ]


@pytest.mark.parametrize("tenant", ["", "a", "b"])
@pytest.mark.parametrize("version", ["", "latest", "v1", "release", -1])
def test_ranking_matches_full_exact_reference(tmp_path, tenant, version):
    index = DatasetVectorSQLiteIndex(tmp_path / "vectors.sqlite")
    index.replace_dataset("set", chunks(48))
    vector, metadata_filter = [0.25] * 64, {"kind": 1}
    reference = _filter_chunks(
        [_row_to_chunk(row) for row in index._select_rows("set", tenant_id=tenant)],
        tenant_id=tenant,
        version=version,
        metadata_filter=metadata_filter,
    )
    terms = set(_tokenize_for_lexical(" ".join(str(value) for value in vector)))
    for item in reference:
        item.score = _cosine(vector, item.metadata["_embedding"]) + _lexical_score(item.text, terms)
        item.source = index.backend_name
    reference.sort(key=lambda item: item.score, reverse=True)
    actual = index.query(
        "set", vector, top_k=7, tenant_id=tenant, version=version, metadata_filter=metadata_filter
    )
    assert actual == reference[:7]


@pytest.mark.parametrize("version", ["", "latest"])
def test_fixed_top_k_has_bounded_python_memory(tmp_path, version):
    index = DatasetVectorSQLiteIndex(tmp_path / "vectors.sqlite")
    peaks = []
    for count in (200, 4000):
        records = chunks(count)
        # Include the worst-case latest-version cardinality: one source per row.
        for number, item in enumerate(records):
            item.metadata["source"] = str(number)
        index.replace_dataset("set", records)
        del records
        gc.collect()
        tracemalloc.start()
        try:
            result = index.query("set", [0.25] * 64, top_k=5, version=version)
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
        assert len(result) == 5
    assert peaks[1] < peaks[0] + 1024 * 1024, peaks


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_vectors_fail_without_replacing_existing_data(tmp_path, invalid):
    index = DatasetVectorSQLiteIndex(tmp_path / "vectors.sqlite")
    index.replace_dataset("set", chunks(3))
    broken = chunks(5)
    broken[-1].metadata["_embedding"][0] = invalid
    with pytest.raises(ValueError, match="finite"):
        index.replace_dataset("set", broken)
    assert index.status("set")["chunk_count"] == 3
    assert len(index.query("set", [0.25] * 64)) == 3
    with pytest.raises(ValueError, match="finite"):
        index.query("set", [invalid] * 64)
