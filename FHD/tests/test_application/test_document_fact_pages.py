"""Real native files exercise complete positions and bounded readback projections."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from docx import Document
from pptx import Presentation
from pptx.util import Inches
from reportlab.pdfgen.canvas import Canvas

from app.application import tabular_document as pages
from app.infrastructure.document_parsing import native, router


def write_document_fixture(path: Path) -> None:
    suffix = path.suffix
    if suffix in {".csv", ".tsv"}:
        delimiter = "," if suffix == ".csv" else "\t"
        path.write_text(
            delimiter.join(["A", "A"]) + "\n" + delimiter.join(['"line1\nline2"', "0"]) + "\n",
            newline="",
        )
    elif suffix == ".docx":
        document = Document()
        document.add_paragraph("before")
        table = document.add_table(rows=2, cols=2)
        for cell, value in zip(
            (table.cell(r, c) for r in range(2) for c in range(2)), ("A", "B", "0", "retained")
        ):
            cell.text = value
        document.add_paragraph("after")
        document.save(path)
    elif suffix == ".pptx":
        presentation = Presentation()
        first = presentation.slides.add_slide(presentation.slide_layouts[6])
        first.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(1)).text = "before"
        table = first.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(3), Inches(1)).table
        for cell, value in zip(
            (table.cell(r, c) for r in range(2) for c in range(2)), ("A", "B", "0", "retained")
        ):
            cell.text = value
        presentation.slides.add_slide(presentation.slide_layouts[6])
        presentation.save(path)
    elif suffix == ".pdf":
        canvas = Canvas(str(path), pagesize=(300, 300))
        for x in (20, 120, 220):
            canvas.line(x, 100, x, 200)
        for y in (100, 150, 200):
            canvas.line(20, y, 220, y)
        for x, y, value in (
            (30, 175, "A"),
            (130, 175, "B"),
            (30, 125, "0"),
            (130, 125, "retained"),
        ):
            canvas.drawString(x, y, value)
        canvas.showPage()
        canvas.showPage()
        canvas.save()
    elif suffix == ".json":
        path.write_text(
            json.dumps(
                {
                    "a/b": {"~flag": False, "zero": 0},
                    "null": None,
                    "empty": [],
                    "object": {},
                    "text": "",
                }
            )
        )
    elif suffix == ".xml":
        path.write_text('<r xmlns="urn:test">lead<x id="1">0</x>between<x id="2"/>tail</r>')
    elif suffix == ".html":
        path.write_text(
            '<table><tr><th>A</th><th>B</th></tr><tr><td>0</td><td>retained</td></tr></table><script>throw "not executed"</script>'
        )
    else:
        raise AssertionError(suffix)


def projected(document, view, **args):
    return pages._project(document, {"view": view, **args}, "owned-source")["data"]


@pytest.mark.parametrize("suffix", [".csv", ".tsv", ".docx", ".pptx", ".pdf", ".html"])
def test_real_tables_list_metadata_and_locate_every_cell(tmp_path, suffix):
    path = tmp_path / ("source" + suffix)
    write_document_fixture(path)
    facts = router.read_document_facts(path, authorization_scope="scope-a")
    before = json.dumps(facts)
    listing = projected(facts, "tables", max_rows=1)
    assert listing["source_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert listing["known_total"] == 1
    table = listing["items"][0]
    assert "cells" not in table and "records" not in table
    assert table["cell_count"] == 4 and table["projection"] == "table_metadata"
    args = {**table["readback"], "max_rows": 1}
    gathered = []
    while True:
        result = pages._project(facts, args, "owned-source")
        assert len(pages._encoded(result)) <= pages.MAX_PAGE_BYTES
        page = result["data"]
        gathered.extend(page["items"])
        if not page["has_more"]:
            break
        args.update(offset=page["next_offset"], cursor=page["next_cursor"])
    expected = (
        ["A", "A", "line1\nline2", "0"]
        if suffix in {".csv", ".tsv"}
        else ["A", "B", "0", "retained"]
    )
    assert [cell["value"] for cell in gathered] == expected
    assert len({cell["cell_id"] for cell in gathered}) == 4
    for cell in gathered:
        located = projected(
            facts, "cells", fact_id=cell["cell_id"], expected_sha256=listing["source_sha256"]
        )
        assert located["items"] == [cell]
        assert cell["source_ref"]["document_id"] == facts["document_id"]
    if suffix in {".csv", ".tsv"}:
        assert gathered[2]["source_ref"]["line_start"] == 2
        assert gathered[2]["source_ref"]["line_end"] == 3
    if suffix in {".pdf", ".html"}:
        assert page["partial"] is True and page["source_status"] == "partial"
    assert json.dumps(facts) == before


@pytest.mark.parametrize("suffix", [".pptx", ".pdf"])
def test_real_pages_regions_and_source_positions(tmp_path, suffix):
    source = tmp_path / ("pages" + suffix)
    write_document_fixture(source)
    facts = router.read_document_facts(source)
    page = projected(facts, "pages", max_rows=1)
    assert page["known_total"] == 2 and page["items"][0]["page"] == 1
    second = projected(
        facts, "pages", cursor=page["next_cursor"], expected_sha256=page["source_sha256"]
    )
    assert second["items"][0]["page"] == 2 and second["has_more"] is False
    assert second["items"][0]["source_ref"]["page"] == 2
    regions = projected(facts, "regions", page=1)
    assert regions["items"]
    first = regions["items"][0]
    assert first["source_ref"]["page"] == 1 and first["source_ref"]["bbox"]
    located = projected(
        facts, "regions", fact_id=first["region_id"], expected_sha256=page["source_sha256"]
    )
    assert located["items"] == [first]


def test_word_never_invents_rendered_pages(tmp_path):
    source = tmp_path / "source.docx"
    write_document_fixture(source)
    with pytest.raises(pages.DocumentPageError, match="document_view_unsupported") as failure:
        projected(router.read_document_facts(source), "pages")
    assert failure.value.status == "unsupported"


def test_json_tree_nodes_have_rfc6901_positions_and_exact_scalars(tmp_path):
    source = tmp_path / "source.json"
    write_document_fixture(source)
    facts = router.read_document_facts(source)
    data = projected(facts, "regions")
    nodes = {item["source_ref"]["json_pointer"]: item for item in data["items"]}
    assert nodes[""]["child_count"] == 5 and "value" not in nodes[""]
    assert nodes["/a~1b/~0flag"]["value"] is False
    assert type(nodes["/a~1b/zero"]["value"]) is int and nodes["/a~1b/zero"]["value"] == 0
    assert nodes["/null"]["value"] is None and nodes["/text"]["value"] == ""
    assert nodes["/empty"]["value"] == [] and nodes["/object"]["value"] == {}
    for node in nodes.values():
        assert projected(
            facts, "regions", fact_id=node["region_id"], expected_sha256=data["source_sha256"]
        )["items"] == [node]


def test_xml_node_positions_keep_namespace_attributes_and_tails(tmp_path):
    source = tmp_path / "source.xml"
    write_document_fixture(source)
    data = projected(router.read_document_facts(source), "regions")
    assert len(data["items"]) == 3
    first, left, right = data["items"]
    assert first["tag"] == "{urn:test}r" and first["text"] == "lead"
    assert first["child_count"] == 2 and "children" not in first
    assert left["attributes"] == {"id": "1"} and left["tail"] == "between"
    assert right["source_ref"]["xml_path"] == "/{urn:test}r[1]/{urn:test}x[2]"
    assert right["tail"] == "tail"


@pytest.mark.parametrize("mutation", ["parser_version", "authorization_scope"])
def test_same_sha_cursor_rejects_changed_parser_or_host_scope(tmp_path, mutation):
    source = tmp_path / "source.csv"
    write_document_fixture(source)
    facts = router.read_document_facts(source, authorization_scope="scope-a")
    first = projected(facts, "cells", max_rows=1)
    changed = copy.deepcopy(facts)
    changed["source_ref"][mutation] += "-changed"
    with pytest.raises(pages.DocumentPageError, match="document_cursor_source_or_scope_changed"):
        projected(
            changed, "cells", cursor=first["next_cursor"], expected_sha256=first["source_sha256"]
        )


@pytest.mark.parametrize(
    "options,code",
    [
        ({"offset": -1}, "invalid_document_offset"),
        ({"offset": True}, "invalid_document_offset"),
        ({"max_rows": 0}, "invalid_document_page_size"),
        ({"max_rows": 1001}, "invalid_document_page_size"),
        ({"page": False}, "invalid_document_page_number"),
        ({"fact_id": []}, "invalid_document_fact_id"),
        ({"offset": 1}, "document_readback_requires_source_sha256"),
        ({"offset": 1, "expected_sha256": "a" * 64}, "document_page_requires_cursor"),
        ({"cursor": "%%%", "expected_sha256": "a" * 64}, "invalid_document_cursor"),
        ({"authorization_scope": "forged"}, "document_argument_not_supported"),
    ],
)
def test_readback_parameters_fail_closed(tmp_path, options, code):
    source = tmp_path / "source.csv"
    write_document_fixture(source)
    with pytest.raises(pages.DocumentPageError, match=code):
        projected(router.read_document_facts(source), "cells", **options)


def test_oversized_native_item_is_blocked_without_empty_success_page(tmp_path):
    source = tmp_path / "large.csv"
    source.write_text("字" * 14_000)
    document = router.read_document_facts(source)
    with pytest.raises(pages.DocumentPageError, match="document_item_budget_exceeded") as failure:
        projected(document, "cells")
    assert failure.value.details["required_item_bytes"] > pages.MAX_PAGE_BYTES
    assert failure.value.details["fact_id"].startswith("cell:")


def test_native_budget_stop_cannot_be_reported_as_an_exhausted_cursor(tmp_path, monkeypatch):
    source = tmp_path / "limited.csv"
    write_document_fixture(source)
    monkeypatch.setattr(native, "MAX_NATIVE_ITEMS", 1)
    document = router.read_document_facts(source)
    assert document["status"] == "partial" and document["tables"][0]["cells"] == []
    for view in ("tables", "cells"):
        with pytest.raises(pages.DocumentPageError, match="document_structure_budget_exceeded"):
            projected(document, view)


def test_byte_budget_continuation_never_skips_an_oversized_later_item(tmp_path):
    source = tmp_path / "later.csv"
    source.write_text("first\n" + "字" * 14_000 + "\nlast\n")
    document = router.read_document_facts(source)
    first = projected(document, "cells")
    assert [item["value"] for item in first["items"]] == ["first"]
    assert first["has_more"] is True and first["next_offset"] == 1
    with pytest.raises(pages.DocumentPageError, match="document_item_budget_exceeded"):
        projected(
            document,
            "cells",
            cursor=first["next_cursor"],
            expected_sha256=first["source_sha256"],
        )


def test_native_source_and_node_budgets_fail_before_returning_partial_success(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.json"
    source.write_text('[0,false,null,""]')
    with pytest.raises(ValueError, match="source_sha256_mismatch"):
        router.read_document_facts(source, expected_sha256="a" * 64)
    monkeypatch.setattr(native, "MAX_NATIVE_ITEMS", 3)
    with pytest.raises(ValueError, match="node/depth budget"):
        router.read_document_facts(source)
