"""Native page reuse preserves snapshots, bounded output and request isolation."""

import hashlib
import json
import sys
from array import array
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, is_dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from openpyxl import Workbook
from openpyxl.styles import Font

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


def _lookup_workbook(tmp_path):
    path = tmp_path / "lookup.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Data"
    for address, value in {
        "A1": 0,
        "A2": False,
        "A3": "",
        "A5": "0",
        "A6": "=1-1",
        "A7": " \t ",
        "B1": 9007199254740993,
        "B2": 9007199254740992,
        "B3": 1,
        "B4": 1.0,
        "C1": "styled",
        "C2": "styled",
        "C3": "different",
        "D1": datetime(2026, 11, 27, 12, 30),
        "G1": "anchor",
        "XFD1048576": 0,
    }.items():
        sheet[address] = value
    sheet["A4"].font = Font(italic=True)
    for address in ("C1", "C2", "C3"):
        sheet[address].font = Font(bold=True)
    sheet.merge_cells("G1:H1")
    hidden = book.create_sheet("Hidden")
    hidden.sheet_state = "veryHidden"
    hidden["XFD1048576"] = 0
    book.save(path)
    book.close()
    # Preserve a literal large integer and a real formula cache in native XML.
    # H1 contains a raw value that openpyxl normalizes away in the merge, so its
    # canonical fact is explicitly unknown, never an ordinary blank.
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    original = path.read_bytes()
    with ZipFile(BytesIO(original)) as source, ZipFile(path, "w") as target:
        for member in source.infolist():
            body = source.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                root = ElementTree.fromstring(body)
                for cell in root.iter(ns + "c"):
                    if cell.attrib["r"] == "B1":
                        cell.find(ns + "v").text = "9007199254740993"
                    if cell.attrib["r"] == "A6":
                        cell.find(ns + "v").text = "0"
                row = root.find(ns + "sheetData").find(ns + "row")
                cell = ElementTree.SubElement(row, ns + "c", {"r": "H1", "t": "n"})
                ElementTree.SubElement(cell, ns + "v").text = "9"
                body = ElementTree.tostring(root)
            target.writestr(member, body)
    return path


def _match(value_type, value, value_state="present"):
    return {"value_type": value_type, "value_state": value_state, "value": value}


@pytest.mark.parametrize(
    "match,addresses",
    [
        (_match("number", 0), ["A1", "XFD1048576"]),
        (_match("number", 0.0), ["A1", "XFD1048576"]),
        (_match("boolean", False), ["A2"]),
        (_match("text", "", "empty_string"), ["A3"]),
        (_match("null", None, "blank"), ["A4"]),
        (_match("unknown", None, "unknown"), ["H1"]),
        (_match("text", "0"), ["A5"]),
        (_match("formula", "=1-1"), ["A6"]),
        (_match("text", " \t "), ["A7"]),
        (_match("number", 9007199254740993), ["B1"]),
        (_match("number", 9007199254740992.0), ["B2"]),
        (_match("number", 1.0), ["B3", "B4"]),
        (_match("datetime", "2026-11-27T12:30:00"), ["D1"]),
    ],
)
def test_typed_lookup_matches_complete_native_facts_with_and_without_index(
    tmp_path, match, addresses
):
    path = _lookup_workbook(tmp_path)
    document = reader.read_workbook_facts(path, authorization_scope="owned")
    before = json.dumps(document)
    cells = document["sheets"][0]["cells"]
    assert next(cell for cell in cells if cell["address"] == "A6")["cached_value"] == 0
    indexed = pages.WorkbookPageIndex.build(document, reader.WORKBOOK_PAGE_CACHE_ENTRY_BYTES)
    assert indexed is not None
    key, _ = pages.validate_lookup(match, None)
    arguments = {
        "view": "cells",
        "sheet_name": "Data",
        "bounds": None,
        "offset": 0,
        "limit": 100,
        "value_key": key,
    }
    cached = pages.project_workbook_page(indexed, **arguments)
    uncached = pages.project_workbook_page(document, **arguments)
    assert cached == uncached
    assert [cell["address"] for cell in cached["cells"]] == addresses
    assert cached["cells"] == [cell for cell in cells if cell["address"] in addresses]
    assert json.dumps(document) == before


def test_value_and_style_postings_intersect_ranges_without_decoding_unmatched_cells(
    tmp_path, monkeypatch
):
    path = _lookup_workbook(tmp_path)
    first = _page(path)
    style = next(cell["style_id"] for cell in first["cells"] if cell["address"] == "C1")
    inflate = Mock(wraps=pages.zlib.decompress)
    key = Mock(wraps=pages._value_key)
    monkeypatch.setattr(pages.zlib, "decompress", inflate)
    monkeypatch.setattr(pages, "_value_key", key)
    result = _page(
        path,
        style_id=style,
        value_match=_match("text", "styled"),
        cell_range="C2:C3",
        expected_sha256=first["source_sha256"],
    )
    assert result["total_items"] == 1
    assert [cell["address"] for cell in result["cells"]] == ["C2"]
    assert inflate.call_count == 1 and key.call_count == 1
    inflate.reset_mock()
    absent = _page(
        path, value_match=_match("text", "absent"), expected_sha256=first["source_sha256"]
    )
    assert absent["total_items"] == 0 and absent["cells"] == []
    assert absent["has_more"] is False and absent["next_cursor"] is None
    inflate.assert_not_called()


def test_lookup_paging_retains_every_coordinate_and_original_readback(tmp_path, monkeypatch):
    path = _workbook(tmp_path, rows=17)
    build = _spy(monkeypatch)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    args = {"value_match": _match("text", "中文"), "expected_sha256": digest, "limit": 4}
    found = []
    for _ in range(5):
        page = _page(path, **args)
        assert page["total_items"] == 17 and page["page_bytes"] <= pages.PAGE_BYTE_BUDGET
        found.extend(page["cells"])
        if not page["has_more"]:
            break
        args.update(offset=page["next_offset"], cursor=page["next_cursor"])
    assert not page["has_more"] and len(found) == 17
    assert [cell["address"] for cell in found] == [f"B{row}" for row in range(1, 18)]
    assert build.call_count == 1
    exact = _page(path, cell_range=found[-1]["address"], expected_sha256=digest)
    assert exact["cells"] == [found[-1]]
    with reader.workbook_snapshot_scope(path, "tenant-a:user-1:mod-a:session-1"):
        far = reader.read_workbook_page(
            path,
            view="cells",
            sheet_name="Hidden",
            expected_sha256=digest,
            value_match=_match("number", 0),
        )
    assert far["total_items"] == 1 and far["cells"][0]["address"] == "XFD1048576"


@pytest.mark.parametrize(
    "change", ["value", "state", "style", "range", "scope", "version", "offset", "missing_cursor"]
)
def test_lookup_cursor_binds_entire_selection_and_host_scope(tmp_path, monkeypatch, change):
    path = _lookup_workbook(tmp_path)
    args = {
        "value_match": _match("number", 0),
        "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "limit": 1,
    }
    first = _page(path, **args)
    args.update(offset=first["next_offset"], cursor=first["next_cursor"])
    if change == "value":
        args["value_match"] = _match("number", 1)
    elif change == "state":
        args["value_match"] = _match("null", None, "blank")
    elif change == "style":
        args["style_id"] = first["cells"][0]["style_id"]
    elif change == "range":
        args["cell_range"] = "A1:A6"
    elif change == "scope":
        args["scope"] = "another-real-host-scope"
    elif change == "version":
        monkeypatch.setattr(reader, "_PAGE_READER_VERSION", "next-parser-version")
    elif change == "offset":
        args["offset"] += 1
    else:
        args.pop("cursor")
    with pytest.raises(ValueError, match="native_lookup.*cursor"):
        _page(path, **args)


@pytest.mark.parametrize(
    "arguments,error",
    [
        ({"value_match": _match("number", False)}, "invalid_native_value_match"),
        ({"value_match": _match("boolean", 0)}, "invalid_native_value_match"),
        ({"value_match": _match("number", float("inf"))}, "invalid_native_value_match"),
        ({"value_match": _match("text", "")}, "invalid_native_value_match"),
        ({"value_match": _match("unknown", None, "blank")}, "invalid_native_value_match"),
        ({"value_match": _match("number", 1 << 4097)}, "native_lookup_query_budget_exceeded"),
        (
            {"value_match": _match("text", "x" * (pages.MAX_LOOKUP_QUERY_BYTES + 1))},
            "native_lookup_query_budget_exceeded",
        ),
        (
            {"value_match": _match("text", "文" * (pages.MAX_LOOKUP_QUERY_BYTES // 3))},
            "native_lookup_query_budget_exceeded",
        ),
        ({"style_id": "x" * 257}, "invalid_native_style_id"),
        ({"style_id": "0:0", "expected_sha256": None}, "native_lookup_requires_source_sha256"),
    ],
)
def test_invalid_or_oversized_lookup_is_rejected_before_snapshot_or_index(
    tmp_path, monkeypatch, arguments, error
):
    path = _workbook(tmp_path, rows=1)
    snapshot = Mock(side_effect=AssertionError("invalid selectors must fail before reading bytes"))
    monkeypatch.setattr(reader, "_snapshot", snapshot)
    with pytest.raises(ValueError, match=error):
        _page(path, **{"expected_sha256": "a" * 64, **arguments})
    snapshot.assert_not_called()


def _owned_memory_bytes(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    size = sys.getsizeof(value)
    children = []
    if is_dataclass(value):
        children = [getattr(value, field.name) for field in fields(value)]
    elif isinstance(value, dict):
        children = [item for pair in value.items() for item in pair]
    elif isinstance(value, (list, tuple)):
        children = list(value)
    # array.getsizeof already includes its owned numeric buffer.
    return size + sum(_owned_memory_bytes(child, seen) for child in children)


def test_index_budget_accounts_for_every_posting_key_dictionary_and_numeric_buffer(
    tmp_path, monkeypatch
):
    path = _workbook(tmp_path, rows=70)
    document = reader.read_workbook_facts(path)
    index = pages.WorkbookPageIndex.build(document, reader.WORKBOOK_PAGE_CACHE_ENTRY_BYTES)
    assert index is not None
    assert len(index.sheets["Data"].value_postings) > 70
    assert all(isinstance(value, array) for value in index.sheets["Data"].value_postings.values())
    assert index.size_bytes >= _owned_memory_bytes(index)
    degraded = pages.WorkbookPageIndex.build(document, index.size_bytes - 1)
    assert degraded is not None and degraded.size_bytes < index.size_bytes
    assert any(not sheet.postings_complete for sheet in degraded.sheets.values())
    assert pages.WorkbookPageIndex.build(document, index.size_bytes) is not None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    args = {"value_match": _match("text", "中文"), "expected_sha256": digest, "limit": 1000}
    cached = _page(path, **args)
    monkeypatch.setattr(reader, "WORKBOOK_PAGE_CACHE_ENTRY_BYTES", 100)
    reader._PAGE_CACHE.clear()
    build = _spy(monkeypatch)
    uncached = _page(path, **args)
    repeated = _page(path, **args)
    assert cached["cells"] == uncached["cells"] == repeated["cells"]
    assert cached["total_items"] == uncached["total_items"] == 70
    assert cached["source_ref"] == uncached["source_ref"]
    assert build.call_count == 2 and reader._PAGE_CACHE.size == 0


def test_optional_posting_overflow_preserves_coordinate_cache_and_full_lookup(
    tmp_path, monkeypatch
):
    path = _workbook(tmp_path, rows=150)
    document = reader.read_workbook_facts(
        path, authorization_scope="tenant-a:user-1:mod-a:session-1"
    )
    index = pages.WorkbookPageIndex.build(document, reader.WORKBOOK_PAGE_CACHE_ENTRY_BYTES)
    assert index is not None
    for sheet in index.sheets.values():
        sheet._discard_postings()
    budget = index.size_bytes + 1024
    degraded = pages.WorkbookPageIndex.build(document, budget)
    assert degraded is not None and not degraded.sheets["Data"].postings_complete
    assert degraded.size_bytes <= budget and degraded.size_bytes >= _owned_memory_bytes(degraded)
    assert not degraded.sheets["Data"].value_postings and not degraded.sheets["Data"].style_postings
    monkeypatch.setattr(reader, "WORKBOOK_PAGE_CACHE_ENTRY_BYTES", budget)
    build = _spy(monkeypatch)
    first = _page(path, limit=1)
    second = _page(path, offset=1, limit=1, expected_sha256=first["source_sha256"])
    assert second["cells"][0]["address"] == "B1"
    args = {
        "value_match": _match("text", "中文"),
        "expected_sha256": first["source_sha256"],
        "limit": 2,
    }
    filtered = _page(path, **args)
    continued = _page(path, **args, offset=filtered["next_offset"], cursor=filtered["next_cursor"])
    assert filtered["total_items"] == continued["total_items"] == 150
    assert [cell["address"] for cell in continued["cells"]] == ["B3", "B4"]
    assert build.call_count == 1 and reader._PAGE_CACHE.size == 1


def test_filtered_oversized_cell_is_explicitly_rejected_without_an_empty_continuation(tmp_path):
    path = _workbook(tmp_path, rows=1, value="文" * 32767)
    first = _page(path, limit=1)
    args = {
        "style_id": first["cells"][0]["style_id"],
        "expected_sha256": first["source_sha256"],
        "limit": 10,
    }
    partial = _page(path, **args)
    assert partial["cells"] == first["cells"] and partial["has_more"] is True
    with pytest.raises(ValueError, match="native_fact_exceeds_page_byte_budget"):
        _page(path, **args, offset=partial["next_offset"], cursor=partial["next_cursor"])
