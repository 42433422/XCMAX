from __future__ import annotations

import tracemalloc

from modstore_server.self_maintenance_jsonl import read_jsonl_tail


def test_read_jsonl_tail_returns_newest_valid_objects_in_chronological_order(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_bytes(
        b'{"id": 1}\n' b"not-json\n" b'["not", "an", "object"]\n' b'{"id": 2}\n' b'{"id": 3}'
    )

    assert read_jsonl_tail(path, limit=2, chunk_size=7) == [{"id": 2}, {"id": 3}]


def test_read_jsonl_tail_discards_huge_newline_free_record_with_bounded_memory(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_bytes(b'{"id": "older"}\n' + (b"x" * (8 * 1024 * 1024)))

    tracemalloc.start()
    try:
        rows = read_jsonl_tail(
            path,
            limit=1,
            max_record_bytes=16 * 1024,
            max_scan_bytes=path.stat().st_size,
            chunk_size=4 * 1024,
        )
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert rows == [{"id": "older"}]
    assert peak_bytes < 2 * 1024 * 1024


def test_read_jsonl_tail_bounds_scan_for_sparse_valid_rows(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_bytes(
        b'{"id": "outside-budget"}\n' + (b"not-json\n" * 200_000) + b'{"id": "inside-budget"}\n'
    )

    rows = read_jsonl_tail(
        path,
        limit=2,
        max_scan_bytes=32 * 1024,
        chunk_size=4 * 1024,
    )

    assert rows == [{"id": "inside-budget"}]
