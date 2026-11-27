"""Native table operations use whole owned sources and declared coordinates."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from unittest.mock import Mock

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.application import tabular_document as pages
from app.application import tabular_document_table as operations
from app.infrastructure.document_parsing import native, router
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_document_fact_pages import write_document_fixture
from tests.test_application.test_owned_document_fact_pages import owned_document as owned_document


def selected(source, **kwargs):
    facts = router.read_document_facts(source, authorization_scope="native-table-test")
    args = {
        "view": "table",
        "table_id": facts["tables"][0]["table_id"],
        "expected_sha256": facts["source_ref"]["source_sha256"],
        **kwargs,
    }
    return facts, args


def test_registered_full_table_queries_and_statistics_exceed_preview_size(owned_document):
    raw = ("A,A,A_2\n" + "".join(f"g{i % 2},{i},{i * 2}\n" for i in range(2502))).encode()
    original, upload = owned_document.upload(".csv", raw)
    _, tables, _ = owned_document.execute({"file_path": upload["upload_id"], "view": "tables"})
    table_id = tables["data"]["items"][0]["table_id"]
    args = {
        "file_path": upload["upload_id"],
        "view": "table",
        "table_id": table_id,
        "expected_sha256": upload["sha256"],
        "row_range": [2, 2503],
        "native_columns": [2, 1],
        "column_types": {"c2": "number"},
        "max_rows": 2,
    }
    _, first, _ = owned_document.execute(args)
    assert first["success"] is True and first["data"]["known_total"] == 2502
    assert list(first["data"]["items"][0]["values"]) == ["c2", "c1"]
    assert first["data"]["items"][0]["values"] == {"c2": 0, "c1": "g0"}
    assert first["data"]["items"][0]["source_ref"]["row"] == 2
    assert first["data"]["header_interpretation"] == "none"
    _, cells, _ = owned_document.execute(
        {"file_path": upload["upload_id"], **first["data"]["readback"], "row_range": [2503, 2503]}
    )
    assert [cell["value"] for cell in cells["data"]["items"]] == ["g1", "2501"]
    query = {**args, "query_expression": "c2 >= 2500", "max_rows": 1}
    _, found, _ = owned_document.execute(query, action="query")
    assert found["success"] is True and found["data"]["known_total"] == 2
    _, last, _ = owned_document.execute(
        {**query, "cursor": found["data"]["next_cursor"]}, action="query"
    )
    assert last["data"]["items"][0]["values"]["c2"] == 2501
    assert last["data"]["items"][0]["source_ref"]["row"] == 2503
    _, aggregate, _ = owned_document.execute(
        {**args, "group_by": ["c1"], "metrics": [{"column": "c2", "op": "sum"}]},
        action="aggregate",
    )
    assert aggregate["success"] is True and aggregate["data"]["source_row_count"] == 2502
    assert {
        item["values"]["c1"]: item["values"]["c2_sum"] for item in aggregate["data"]["items"]
    } == {
        "g0": sum(range(0, 2502, 2)),
        "g1": sum(range(1, 2502, 2)),
    }
    _, statistics, _ = owned_document.execute(
        {**args, "expected_row_count": 2502, "expected_totals": {"c2": sum(range(2502))}},
        action="statistics",
    )
    assert statistics["success"] is True and statistics["verification"]["verified"] is True
    assert statistics["numeric_summary"]["c2"] == {
        "count": 2502,
        "sum": sum(range(2502)),
        "mean": 1250.5,
        "min": 0,
        "max": 2501,
    }
    assert statistics["data"]["items"][0]["source_ref"]["column"] == 2
    assert original.read_bytes() == raw


@pytest.mark.parametrize("suffix", [".tsv", ".docx", ".pptx", ".pdf", ".html"])
def test_real_formats_filter_convert_and_aggregate_only_selected_coordinates(tmp_path, suffix):
    source = tmp_path / ("table" + suffix)
    write_document_fixture(source)
    column = 2 if suffix == ".tsv" else 1
    facts, args = selected(
        source,
        row_range=[2, 2],
        native_columns=[column],
        column_types={f"c{column}": "number"},
        query_expression=f"c{column} == 0",
    )
    result = operations.analyze_native_table(facts, {**args, "action": "query"}, "owned")
    assert result["data"]["items"][0]["values"] == {f"c{column}": 0}
    assert result["data"]["source_row_count"] == 1
    total = operations.analyze_native_table(
        facts,
        {**args, "action": "aggregate", "metrics": [{"column": f"c{column}", "op": "sum"}]},
        "owned",
    )
    assert total["data"]["items"][0]["values"] == {f"c{column}_sum": 0}
    assert result["data"]["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result["data"]["partial"] is (suffix in {".pdf", ".html"})


def test_duplicate_headers_empty_strings_and_native_order_are_not_reinterpreted(tmp_path):
    source = tmp_path / "duplicate.csv"
    source.write_text("A,A,A_2\n0,,False\n")
    facts, args = selected(source)
    data = operations.analyze_native_table(facts, args, "owned")["data"]
    assert data["known_total"] == 2
    assert [item["values"] for item in data["items"]] == [
        {"c1": "A", "c2": "A", "c3": "A_2"},
        {"c1": "0", "c2": "", "c3": "False"},
    ]


@pytest.mark.parametrize("value", ["not-a-number", "", "inf", "NaN"])
def test_explicit_number_conversion_never_silently_discards_values(tmp_path, value):
    source = tmp_path / "numbers.csv"
    source.write_text(f'"{value}"\n')
    facts, args = selected(source, column_types={"c1": "number"})
    with pytest.raises(pages.DocumentPageError, match="document_numeric_conversion_failed"):
        operations.analyze_native_table(facts, args, "owned")


def test_large_integer_conversion_is_preserved_with_missing_native_position(tmp_path):
    source = tmp_path / "numbers.csv"
    source.write_text("x,9007199254740993\ny\n")
    facts, args = selected(source, native_columns=[2], column_types={"c2": "number"})
    result = operations.analyze_native_table(facts, args, "owned")
    assert result["data"]["items"][0]["values"]["c2"] == 9007199254740993
    assert type(result["data"]["items"][0]["values"]["c2"]) is int
    assert result["data"]["items"][1]["values"]["c2"] is None
    statistics = operations.analyze_native_table(facts, {**args, "action": "statistics"}, "owned")
    assert statistics["numeric_summary"]["c2"]["sum"] == 9007199254740993
    assert type(statistics["numeric_summary"]["c2"]["sum"]) is int
    assert statistics["data"]["items"][0]["values"]["sum"] == 9007199254740993


@pytest.mark.parametrize("expression", ["c1 * 1000000000 == 'x'", "[0] * 1000000000 == c1"])
def test_query_resource_guard_blocks_text_and_container_growth_before_evaluation(
    tmp_path, monkeypatch, expression
):
    source = tmp_path / "source.csv"
    source.write_text("x\ny\n")
    facts, args = selected(source, action="query", query_expression=expression)
    execute = Mock(side_effect=AssertionError("the unbounded arithmetic must not execute"))
    monkeypatch.setattr(operations, "safe_filter_dataframe", execute)
    with pytest.raises(
        pages.DocumentPageError, match="document_query_arithmetic_requires_numeric_operands"
    ):
        operations.analyze_native_table(facts, args, "owned")
    execute.assert_not_called()


def test_numeric_arithmetic_uses_the_existing_filter(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("0\n2\n")
    facts, args = selected(
        source, action="query", column_types={"c1": "number"}, query_expression="c1 * 2 + 1 > 4"
    )
    result = operations.analyze_native_table(facts, args, "owned")
    assert [item["values"] for item in result["data"]["items"]] == [{"c1": 2}]


def test_integer_query_and_aggregation_do_not_wrap_at_int64_limit(tmp_path):
    source = tmp_path / "large-integers.csv"
    source.write_text("9223372036854775807\n1\n")
    facts, args = selected(source, column_types={"c1": "number"})
    result = operations.analyze_native_table(
        facts,
        {**args, "action": "query", "query_expression": "c1 * 2 > 9223372036854775807"},
        "owned",
    )
    assert [item["values"] for item in result["data"]["items"]] == [{"c1": 9223372036854775807}]
    total = operations.analyze_native_table(
        facts,
        {**args, "action": "aggregate", "metrics": [{"column": "c1", "op": "sum"}]},
        "owned",
    )
    assert total["data"]["items"][0]["values"]["c1_sum"] == 9223372036854775808
    statistics = operations.analyze_native_table(facts, {**args, "action": "statistics"}, "owned")
    assert statistics["numeric_summary"]["c1"]["sum"] == 9223372036854775808


def test_real_sparse_word_table_is_rejected_before_rectangular_allocation(tmp_path, monkeypatch):
    source = tmp_path / "sparse.docx"
    document = Document()
    table = document.add_table(rows=3, cols=1)
    for row, native_row in enumerate(table.rows):
        before = OxmlElement("w:gridBefore")
        before.set(qn("w:val"), str(row))
        native_row._tr.get_or_add_trPr().append(before)
        native_row.cells[0].text = str(row)
    document.save(source)
    facts, args = selected(source)
    assert len(facts["tables"][0]["cells"]) == 3
    monkeypatch.setattr(operations, "MAX_SCAN_ITEMS", 4)
    allocation = Mock(side_effect=AssertionError("DataFrame must not be allocated"))
    monkeypatch.setattr(operations.pd, "DataFrame", allocation)
    with pytest.raises(pages.DocumentPageError, match="document_table_rectangle_budget_exceeded"):
        operations.analyze_native_table(facts, args, "owned")
    allocation.assert_not_called()


@pytest.mark.parametrize(
    "mutation", ["operation", "range", "columns", "conversion", "pandas_version"]
)
def test_same_source_cursor_is_bound_to_entire_native_operation(tmp_path, monkeypatch, mutation):
    source = tmp_path / "source.csv"
    source.write_text("0,1\n2,3\n")
    facts, args = selected(source, max_rows=1)
    first = operations.analyze_native_table(facts, args, "owned")["data"]
    resume = {**args, "cursor": first["next_cursor"]}
    if mutation == "pandas_version":
        monkeypatch.setattr(operations.pd, "__version__", "changed-parser-version")
    else:
        resume.update(
            {
                "operation": {"action": "query", "query_expression": "c1 == '0'"},
                "range": {"row_range": [1, 1]},
                "columns": {"native_columns": [2]},
                "conversion": {"column_types": {"c1": "number"}},
            }[mutation]
        )
    with pytest.raises(pages.DocumentPageError, match="document_cursor_source_or_scope_changed"):
        operations.analyze_native_table(facts, resume, "owned")


@pytest.mark.parametrize("action", ["read", "query", "aggregate", "statistics"])
@pytest.mark.parametrize("change", ["owner", "replacement"])
def test_registered_native_operations_recheck_source_before_parsing(
    owned_document, monkeypatch, action, change
):
    from app.db.models.elt import EltUpload

    _, upload = owned_document.upload(".csv")
    listing = owned_document.route({"file_path": upload["upload_id"], "view": "tables"})
    args = {
        "file_path": upload["upload_id"],
        "view": "table",
        "expected_sha256": upload["sha256"],
        "table_id": listing["data"]["items"][0]["table_id"],
        "native_columns": [2],
        "row_range": [2, 2],
        "column_types": {"c2": "number"},
        **({"query_expression": "c2 == 0"} if action == "query" else {}),
        **({"metrics": [{"column": "c2", "op": "sum"}]} if action == "aggregate" else {}),
    }
    parse = Mock(wraps=native._delimited)
    monkeypatch.setattr(native, "_delimited", parse)
    assert owned_document.route(args, action=action)["success"] is True
    assert parse.call_count == 1
    actor = owned_document.actor
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        row = db.get(EltUpload, upload["upload_id"])
        if change == "owner":
            row.owner_user_id = 99
        else:
            path = Path(row.storage_path)
            path.chmod(0o600)
            raw = b"A,A\nreplacement,1\n"
            path.write_bytes(raw)
            row.sha256, row.size_bytes = hashlib.sha256(raw).hexdigest(), len(raw)
    denied = owned_document.route(args, action=action)
    assert denied["success"] is False and parse.call_count == 1 and "data" not in denied
    if change == "replacement":
        assert denied["error_code"] == "document_source_changed"


def test_registered_native_query_rejects_code_and_missing_source_sha(owned_document, tmp_path):
    _, upload = owned_document.upload(".csv")
    listing = owned_document.route({"file_path": upload["upload_id"], "view": "tables"})
    marker = tmp_path / "should-not-exist"
    args = {
        "file_path": upload["upload_id"],
        "table_id": listing["data"]["items"][0]["table_id"],
        "query_expression": f"__import__('pathlib').Path('{marker}').touch()",
    }
    _, denied, _ = owned_document.execute(args, action="query")
    assert denied["success"] is False
    assert denied["error_code"] == "document_readback_requires_source_sha256"
    _, denied, _ = owned_document.execute(
        {**args, "expected_sha256": upload["sha256"]}, action="query"
    )
    assert denied["success"] is False and denied["error_code"] == "document_table_operation_failed"
    assert not marker.exists()


def test_final_registered_statistics_verification_obeys_the_response_budget(owned_document):
    _, upload = owned_document.upload(".csv")
    listing = owned_document.route({"file_path": upload["upload_id"], "view": "tables"})
    result = owned_document.route(
        {
            "file_path": upload["upload_id"],
            "table_id": listing["data"]["items"][0]["table_id"],
            "expected_sha256": upload["sha256"],
            "row_range": [2, 2],
            "native_columns": [2],
            "column_types": {"c2": "number"},
            "expected_totals": {str(index) + "x" * 1500: 0 for index in range(20)},
        },
        action="statistics",
    )
    assert result == {
        "success": False,
        "error_code": "document_response_budget_exceeded",
        "status": "blocked",
    }


@pytest.mark.parametrize(
    "raw,column,expected",
    [
        ("9007199254740993\n1.5\n", 1, [9007199254740993, 1.5]),
        ("x,18446744073709551615\ny\n", 2, [18446744073709551615, None]),
    ],
)
def test_numeric_conversion_keeps_exact_values_or_blocks_and_preserves_originals(
    tmp_path, raw, column, expected
):
    source = tmp_path / "precise.csv"
    source.write_text(raw)
    facts, args = selected(source, native_columns=[column], column_types={f"c{column}": "number"})
    before = [cell["value"] for cell in facts["tables"][0]["cells"]]
    try:
        result = operations.analyze_native_table(facts, args, "owned")
    except pages.DocumentPageError as exc:
        assert exc.code in {
            "document_numeric_conversion_failed",
            "document_numeric_conversion_precision_loss",
        }
    else:
        # Backend versions may represent nullable UInt64 exactly. A successful
        # conversion must preserve each actual value and its numeric type.
        assert result["success"] is True
        actual = [item["values"][f"c{column}"] for item in result["data"]["items"]]
        assert actual == expected
        assert [type(value) for value in actual] == [type(value) for value in expected]
    assert source.read_text() == raw
    assert [
        item["value"] for item in pages._project(facts, {"view": "cells"}, "owned")["data"]["items"]
    ] == before


def test_normal_decimal_integer_and_group_key_aggregations_keep_their_values(tmp_path):
    source = tmp_path / "normal.csv"
    source.write_text("0.5,0\n1.25,2\n")
    facts, args = selected(source, column_types={"c1": "number", "c2": "number"})
    data = operations.analyze_native_table(facts, args, "owned")["data"]
    assert [item["values"] for item in data["items"]] == [
        {"c1": 0.5, "c2": 0},
        {"c1": 1.25, "c2": 2},
    ]
    result = operations.analyze_native_table(
        facts,
        {
            **args,
            "action": "aggregate",
            "group_by": ["c2"],
            "metrics": [{"column": "c2", "op": "sum"}],
        },
        "owned",
    )
    assert [item["values"] for item in result["data"]["items"]] == [
        {"c2": 0, "c2_sum": 0},
        {"c2": 2, "c2_sum": 2},
    ]


def test_registered_statistics_verification_compares_native_integers_exactly(owned_document):
    _, upload = owned_document.upload(".csv", b"9007199254740993\n")
    listing = owned_document.route({"file_path": upload["upload_id"], "view": "tables"})
    args = {
        "file_path": upload["upload_id"],
        "table_id": listing["data"]["items"][0]["table_id"],
        "expected_sha256": upload["sha256"],
        "column_types": {"c1": "number"},
    }
    for expected in (9007199254740992, 9007199254740992.0):
        envelope, wrong, _ = owned_document.execute(
            {**args, "expected_totals": {"c1": expected}}, action="statistics"
        )
        assert envelope["success"] is False and wrong["verification"]["verified"] is False
        assert wrong["numeric_summary"]["c1"]["sum"] == 9007199254740993
    _, exact, _ = owned_document.execute(
        {**args, "expected_totals": {"c1": 9007199254740993}}, action="statistics"
    )
    assert exact["success"] is True and exact["verification"]["verified"] is True


@pytest.mark.parametrize("action", ["query", "aggregate", "statistics"])
def test_finite_float_overflow_never_becomes_successful_missing_data(tmp_path, action):
    source = tmp_path / "overflow.csv"
    source.write_text("g,1e308\ng,1e308\ng,-1e308\ng,-1e308\n")
    facts, args = selected(source, column_types={"c2": "number"}, action=action)
    if action == "query":
        args["query_expression"] = "c2 * 2 - c2 * 2 == 0"
    elif action == "aggregate":
        args.update(group_by=["c1"], metrics=[{"column": "c2", "op": "sum"}])
    with pytest.raises(pages.DocumentPageError, match="document_numeric_result_non_finite"):
        operations.analyze_native_table(facts, args, "owned")


@pytest.mark.parametrize("rows", [[2, 2], [3, 3]])
def test_empty_or_all_missing_statistics_keep_explicit_null_results(tmp_path, rows):
    source = tmp_path / "missing.csv"
    source.write_text("x,1\ny\n")
    facts, args = selected(
        source,
        row_range=rows,
        native_columns=[2],
        column_types={"c2": "number"},
        action="statistics",
    )
    result = operations.analyze_native_table(facts, args, "owned")
    assert result["success"] is True
    assert result["numeric_summary"]["c2"] == {
        "count": 0,
        "sum": 0,
        "mean": None,
        "min": None,
        "max": None,
    }
