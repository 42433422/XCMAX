"""Native page reuse preserves snapshots, bounded output and request isolation."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest
from openpyxl import Workbook

from app.application import tabular_workbook as reader
from app.infrastructure.excel import workbook_page_index as pages


@pytest.fixture(autouse=True)
def isolated_cache():
    reader._PAGE_CACHE.clear()
    yield
    reader._PAGE_CACHE.clear()


def _workbook(tmp_path, *, rows=12, value="中文", name="book.xlsx"):
    path = tmp_path / name
    book = Workbook()
    sheet = book.active
    sheet.title = "Data"
    for row in range(1, rows + 1):
        sheet.append([row, value, row % 2 == 0])
    hidden = book.create_sheet("Hidden")
    hidden.sheet_state = "veryHidden"
    hidden["XFD1048576"] = 0
    book.save(path)
    book.close()
    return path


def _page(path, *, scope="tenant-a:user-1:mod-a:session-1", **kwargs):
    with reader.workbook_snapshot_scope(path, scope):
        return reader.read_workbook_page(path, view="cells", sheet_name="Data", **kwargs)


def _spy(monkeypatch):
    build = Mock(wraps=reader.build_workbook_facts)
    monkeypatch.setattr(reader, "build_workbook_facts", build)
    return build


def test_all_pages_reuse_one_parse_and_match_complete_original_facts(tmp_path, monkeypatch):
    path = _workbook(tmp_path, rows=120, value="😀中文" * 30)
    scope = "tenant-a:user-1:mod-a:session-1"
    expected = reader.read_workbook_facts(path, authorization_scope=scope)["sheets"][0]["cells"]
    build = _spy(monkeypatch)
    all_cells, offset, digest = [], 0, None
    while True:
        page = _page(path, offset=offset, limit=1000, expected_sha256=digest)
        assert page["total_items"] == len(expected)
        assert page["page_bytes"] == len(
            json.dumps(page["cells"], ensure_ascii=False, separators=(",", ":")).encode()
        )
        assert page["page_bytes"] <= 40_000
        all_cells.extend(page["cells"])
        if not page["has_more"]:
            break
        offset, digest = page["next_offset"], page["source_sha256"]
    assert all_cells == expected
    assert build.call_count == 1


def test_same_snapshot_in_another_temporary_path_can_reuse_verified_scope(tmp_path, monkeypatch):
    path = _workbook(tmp_path)
    copy = tmp_path / "another.xlsx"
    copy.write_bytes(path.read_bytes())
    build = _spy(monkeypatch)
    first = _page(path, limit=1)
    second = _page(copy, offset=1, limit=1, expected_sha256=first["source_sha256"])
    assert first["document_id"] == second["document_id"]
    assert second["cells"][0]["value"] == "中文"
    assert build.call_count == 1


def test_range_uses_coordinate_index_and_inflates_only_selected_block(tmp_path, monkeypatch):
    path = _workbook(tmp_path, rows=1000)
    first = _page(path, limit=1)
    inflate = Mock(wraps=pages.zlib.decompress)
    monkeypatch.setattr(pages.zlib, "decompress", inflate)
    selected = _page(
        path, cell_range="B901:B905", offset=2, limit=1, expected_sha256=first["source_sha256"]
    )
    assert selected["total_items"] == 5
    assert selected["cells"][0]["address"] == "B903"
    assert selected["next_offset"] == 3
    assert inflate.call_count == 1
    assert len(pages.zlib.decompress(inflate.call_args.args[0])) <= pages._BLOCK_BYTES
    empty = _page(path, cell_range="D901:D905")
    assert empty["cells"] == [] and empty["total_items"] == 0


def test_returned_cells_and_metadata_cannot_poison_next_page(tmp_path):
    path = _workbook(tmp_path)
    first = _page(path, limit=2)
    first["cells"][0]["value"] = "poison"
    first["cells"][0]["source_ref"]["address"] = "Z99"
    first["source_ref"]["authorization_scope"] = "foreign"
    first["warnings"].append({"code": "poison"})
    second = _page(path, limit=2)
    assert second["cells"][0]["value"] == 1
    assert second["cells"][0]["source_ref"]["address"] == "A1"
    assert second["source_ref"]["authorization_scope"] == "tenant-a:user-1:mod-a:session-1"
    assert second["warnings"] == []
    with reader.workbook_snapshot_scope(path, "tenant-a:user-1:mod-a:session-1"):
        directory = reader.read_workbook_page(path, view="sheets")
        directory["sheets"][0]["sheet"] = "changed"
        again = reader.read_workbook_page(path, view="sheets")
    assert [sheet["sheet"] for sheet in again["sheets"]] == ["Data", "Hidden"]
    assert again["sheets"][1]["sheet_state"] == "veryHidden"


@pytest.mark.parametrize(
    "scope",
    [
        "tenant-b:user-1:mod-a:session-1",
        "tenant-a:user-2:mod-a:session-1",
        "tenant-a:user-1:mod-b:session-1",
        "tenant-a:user-1:mod-a:session-2",
    ],
)
def test_account_tenant_mod_and_session_have_separate_indexes(tmp_path, monkeypatch, scope):
    path = _workbook(tmp_path)
    build = _spy(monkeypatch)
    first = _page(path, limit=1)
    second = _page(path, scope=scope, limit=1)
    assert first["document_id"] != second["document_id"]
    assert second["source_ref"]["authorization_scope"] == scope
    assert build.call_count == 2


def test_unbound_local_read_cannot_consume_or_publish_scoped_cache(tmp_path, monkeypatch):
    path = _workbook(tmp_path)
    build = _spy(monkeypatch)
    _page(path, limit=1)
    for _ in range(2):
        page = reader.read_workbook_page(path, view="cells", sheet_name="Data", limit=1)
        assert page["source_ref"]["authorization_scope"] == ""
    # A host context bound to another file must not leak into this source.
    with reader.workbook_snapshot_scope(tmp_path / "different.xlsx", "tenant-a:user-1"):
        assert (
            reader.read_workbook_page(path, view="sheets")["source_ref"]["authorization_scope"]
            == ""
        )
    assert build.call_count == 4
    assert reader._PAGE_CACHE.size == 1


def test_changed_bytes_are_revalidated_before_reuse_and_old_digest_is_rejected(
    tmp_path, monkeypatch
):
    path = _workbook(tmp_path)
    build = _spy(monkeypatch)
    first = _page(path, limit=1)
    _workbook(tmp_path, value="changed")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        _page(path, offset=1, limit=1, expected_sha256=first["source_sha256"])
    assert build.call_count == 1
    current = _page(path, limit=2)
    assert current["source_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert current["source_sha256"] != first["source_sha256"]
    assert current["cells"][1]["value"] == "changed"
    assert build.call_count == 2


def test_cache_size_limit_bypasses_reuse_without_truncating_facts(tmp_path, monkeypatch):
    path = _workbook(tmp_path)
    monkeypatch.setattr(reader, "WORKBOOK_PAGE_CACHE_ENTRY_BYTES", 100)
    build = _spy(monkeypatch)
    first = _page(path)
    second = _page(path)
    assert first == second and first["total_items"] == 36
    assert reader._PAGE_CACHE.size == 0
    assert build.call_count == 2


def test_long_record_skips_cache_and_retains_explicit_page_budget_error(tmp_path):
    path = _workbook(tmp_path, rows=1, value="文" * 50_000)
    # openpyxl limits ordinary strings; extend the native XML text to exercise
    # an actually oversized cell accepted by the source parser.
    from io import BytesIO
    from zipfile import ZipFile

    original = path.read_bytes()
    with ZipFile(BytesIO(original)) as source, ZipFile(path, "w") as target:
        for item in source.infolist():
            body = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                body = body.replace(b"&#25991;" * 32767, "文".encode() * 50_000)
            target.writestr(item, body)
    first = _page(path, limit=1)
    with pytest.raises(ValueError, match="native_fact_exceeds_page_byte_budget"):
        _page(path, offset=1, expected_sha256=first["source_sha256"])
    assert reader._PAGE_CACHE.size == 0


def test_expired_and_evicted_entries_are_rebuilt(tmp_path, monkeypatch):
    from app.utils.performance import cache_manager

    paths = [_workbook(tmp_path, name=f"book-{index}.xlsx", value=str(index)) for index in range(3)]
    clock = [1000.0]
    monkeypatch.setattr(cache_manager.time, "time", lambda: clock[0])
    build = _spy(monkeypatch)
    _page(paths[0], limit=1)
    _page(paths[1], limit=1)
    _page(paths[0], limit=1)
    _page(paths[2], limit=1)
    assert build.call_count == 3 and reader._PAGE_CACHE.size == 2
    _page(paths[1], limit=1)
    assert build.call_count == 4
    clock[0] += 121
    _page(paths[1], limit=1)
    assert build.call_count == 5


def test_budget_version_is_part_of_cache_identity(tmp_path, monkeypatch):
    from app.infrastructure.document_parsing.archive_safety import OfficeArchiveError

    path = _workbook(tmp_path)
    _page(path)
    monkeypatch.setattr(reader, "WORKBOOK_MATERIALIZED_CELL_LIMIT", 1)
    with pytest.raises(OfficeArchiveError, match="materialization_budget"):
        _page(path)


def test_concurrent_same_scope_requests_publish_one_complete_index(tmp_path, monkeypatch):
    path = _workbook(tmp_path)
    build = _spy(monkeypatch)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: _page(path, limit=1), range(3)))
    assert results[0] == results[1] == results[2]
    assert build.call_count == 1


def test_invalid_ranges_and_unbound_offsets_do_not_parse(tmp_path, monkeypatch):
    path = _workbook(tmp_path)
    build = _spy(monkeypatch)
    for bounds in ("A:A", "A0:B2", "B2:A1", "A1:XFE2"):
        with pytest.raises(ValueError):
            _page(path, cell_range=bounds)
    with pytest.raises(ValueError, match="requires_source_sha256"):
        _page(path, offset=1)
    assert build.call_count == 0


@pytest.mark.parametrize("offset,limit", [(-1, 1), (0, 0), (0, -1), (True, 1), (0, 1.5)])
@pytest.mark.parametrize("scope", ["", "tenant-a:user-1"])
def test_application_page_boundary_rejects_nonprogressing_or_invalid_cursors(
    tmp_path, monkeypatch, offset, limit, scope
):
    path = _workbook(tmp_path)
    build = _spy(monkeypatch)
    with pytest.raises(ValueError, match="invalid_native_page_bounds"):
        _page(
            path,
            scope=scope,
            offset=offset,
            limit=limit,
            expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    assert build.call_count == 0
