"""Coordinate-selected native facts adapted to the existing pandas operations."""

from __future__ import annotations

import ast
import math
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from numbers import Integral, Real
from typing import Any

import numpy as np
import pandas as pd

from app.application.tabular_document import (
    MAX_PAGE_BYTES,
    MAX_PAGE_ITEMS,
    MAX_SCAN_ITEMS,
    DocumentPageError,
    _coordinates,
    _encoded,
    _items,
    _paginate,
    _parameters,
    _validate_document,
)
from app.application.tools.safe_dataframe_query import (
    _MAX_AST_NODES,
    _evaluate,
    safe_filter_dataframe,
)
from app.application.tools.workflow_tools.excel_analysis import aggregate_frame
from app.domain.tabular_facts import location_id
from app.utils.json_safe import json_safe

_BASE_KEYS = {
    "file_path",
    "table_id",
    "expected_sha256",
    "offset",
    "max_rows",
    "cursor",
    "row_range",
    "native_columns",
}
_OPERATION_KEYS = {"column_types", "query_expression", "group_by", "metrics"}


def analysis_parameters(arguments: dict) -> tuple[int, int, dict, str]:
    allowed = (
        _BASE_KEYS
        | _OPERATION_KEYS
        | {
            "action",
            "view",
            "expected_row_count",
            "expected_totals",
        }
    )
    if any(key not in allowed and value is not None for key, value in arguments.items()):
        raise DocumentPageError("document_argument_not_supported")
    action = arguments.get("action", "read")
    if not isinstance(action, str) or action not in {"read", "query", "aggregate", "statistics"}:
        raise DocumentPageError("document_table_action_unsupported", status="unsupported")
    if arguments.get("view", "table") != "table":
        raise DocumentPageError("document_table_operation_requires_table_view")
    if not arguments.get("table_id"):
        raise DocumentPageError("document_table_operation_requires_table_id")
    _, offset, limit, selection, digest = _parameters(
        {"view": "cells", **{key: arguments[key] for key in _BASE_KEYS if key in arguments}}
    )
    if digest is None:
        raise DocumentPageError("document_readback_requires_source_sha256")
    expression = arguments.get("query_expression")
    if expression is not None and (
        not isinstance(expression, str) or not expression.strip() or len(expression) > 2048
    ):
        raise DocumentPageError("invalid_query_expression")
    if action == "query" and expression is None:
        raise DocumentPageError("document_table_query_requires_expression")
    conversions = arguments.get("column_types", {})
    if (
        not isinstance(conversions, dict)
        or len(conversions) > MAX_PAGE_ITEMS
        or any(not isinstance(key, str) or value != "number" for key, value in conversions.items())
    ):
        raise DocumentPageError("invalid_document_column_types")
    groups, metrics = arguments.get("group_by", []), arguments.get("metrics", [])
    if (
        not isinstance(groups, list)
        or len(groups) > MAX_PAGE_ITEMS
        or any(not isinstance(group, str) for group in groups)
        or len(set(groups)) != len(groups)
        or not isinstance(metrics, list)
        or len(metrics) > MAX_PAGE_ITEMS
        or any(
            not isinstance(metric, dict)
            or set(metric) != {"column", "op"}
            or not isinstance(metric["column"], str)
            or not isinstance(metric["op"], str)
            or metric["op"] not in {"sum", "mean", "count", "min", "max"}
            for metric in metrics
        )
    ):
        raise DocumentPageError("invalid_aggregation_metrics")
    if action == "aggregate" and not metrics:
        raise DocumentPageError("missing_aggregation_metrics")
    if action != "aggregate" and (groups or metrics):
        raise DocumentPageError("document_metrics_require_aggregate")
    if action != "statistics" and any(
        key in arguments for key in ("expected_row_count", "expected_totals")
    ):
        raise DocumentPageError("document_verification_requires_statistics")
    selection.update(
        action=action,
        column_types=conversions,
        query_expression=expression,
        group_by=groups,
        metrics=metrics,
        operation_backend={"name": "pandas", "version": pd.__version__},
    )
    return offset, limit, selection, digest


def _frame(document: dict, selection: dict) -> tuple[pd.DataFrame, dict]:
    _validate_document(document, "table")
    positions: dict[tuple[int, int], Any] = {}
    rows, columns = set(), set()
    for number, cell in enumerate(_items(document, "cells", selection["table_id"]), 1):
        if number > MAX_SCAN_ITEMS:
            raise DocumentPageError("document_table_cell_budget_exceeded")
        row, column = _coordinates(cell)
        if (row, column) in positions:
            raise DocumentPageError("document_table_duplicate_coordinates")
        positions[row, column] = cell["value"]
        rows.add(row)
        columns.add(column)
    selected_columns = selection["native_columns"] or sorted(columns)
    if not set(selected_columns).issubset(columns):
        raise DocumentPageError("document_native_column_not_found")
    if len(selected_columns) > MAX_PAGE_ITEMS:
        raise DocumentPageError("document_table_column_budget_exceeded")
    selected_rows = sorted(
        row
        for row in rows
        if selection["row_range"] is None
        or selection["row_range"][0] <= row <= selection["row_range"][1]
    )
    if len(selected_rows) * len(selected_columns) > MAX_SCAN_ITEMS:
        raise DocumentPageError("document_table_rectangle_budget_exceeded")
    # Original coordinates are the index. Gaps do not create synthetic rows,
    # and a merged anchor is never propagated into other rows or columns.
    frame = pd.DataFrame(
        {
            f"c{column}": [positions.get((row, column)) for row in selected_rows]
            for column in selected_columns
        },
        index=selected_rows,
        dtype=object,
    )
    for column in selection["column_types"]:
        if column not in frame.columns:
            raise DocumentPageError("document_native_column_not_found")
        original = frame[column]
        try:
            converted = pd.to_numeric(original, errors="raise", dtype_backend="numpy_nullable")
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise DocumentPageError("document_numeric_conversion_failed", column=column) from exc
        if (
            (original.notna() & converted.isna()).any()
            or any(isinstance(value, bool) for value in original)
            or any(
                not isinstance(value, Real) or not math.isfinite(value)
                for value in converted.dropna()
            )
        ):
            raise DocumentPageError("document_numeric_conversion_failed", column=column)
        try:
            if any(
                Decimal(str(before)) != Decimal(str(after))
                for before, after in zip(
                    original[original.notna()], converted[original.notna()], strict=True
                )
            ):
                raise DocumentPageError("document_numeric_conversion_precision_loss", column=column)
        except InvalidOperation as exc:
            raise DocumentPageError("document_numeric_conversion_failed", column=column) from exc
        frame[column] = converted
    return frame, {
        "table_id": selection["table_id"],
        "column_coordinates": {f"c{column}": column for column in selected_columns},
        "source_table_rows": len(rows),
        "range_row_count": len(selected_rows),
        "projection": "native_coordinate_table",
        "count_scope": "derived_result_rows",
        "header_interpretation": "none",
        "missing_positions": "null_in_derived_view",
        "merged_values": "native_anchors_only",
        "readback": {
            "view": "cells",
            "table_id": selection["table_id"],
            "expected_sha256": document["source_ref"]["source_sha256"],
            **{
                key: selection[key]
                for key in ("row_range", "native_columns")
                if selection[key] is not None
            },
        },
    }


def _records(document: dict, rows: Iterator[tuple[Any, dict]], selection: dict) -> Iterator[dict]:
    analysis_id = location_id(document["document_id"], "analysis", selection)
    raw_rows = selection["action"] in {"read", "query"}
    for ordinal, (index, values) in enumerate(rows):
        yield {
            "row_id": location_id(analysis_id, "row", ordinal),
            "values": {
                str(column): None if pd.isna(value) else json_safe(value)
                for column, value in values.items()
            },
            "source_ref": {
                "document_id": document["document_id"],
                "table_id": selection["table_id"],
                **({"row": int(index)} if raw_rows else {"analysis_id": analysis_id}),
                **({"column": int(str(index)[1:])} if selection["action"] == "statistics" else {}),
            },
        }


def _guard_query_arithmetic(frame: pd.DataFrame, expression: str) -> None:
    """Do not let the existing grammar multiply text or containers before paging."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return  # The canonical filter reports the syntax failure.
    if sum(1 for _ in ast.walk(tree)) > _MAX_AST_NODES:
        raise DocumentPageError("invalid_query_expression")

    def numeric(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in frame.columns and pd.api.types.is_numeric_dtype(frame[node.id].dtype)
        if isinstance(node, ast.Constant):
            return (type(node.value) is int and abs(node.value) < 2**64) or (
                type(node.value) is float and math.isfinite(node.value)
            )
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return numeric(node.operand)
        if isinstance(node, ast.BinOp):
            return numeric(node.left) and numeric(node.right)
        return False

    if any(isinstance(node, ast.BinOp) and not numeric(node) for node in ast.walk(tree)):
        raise DocumentPageError("document_query_arithmetic_requires_numeric_operands")


def _finite_result(value: Any, non_null_count: int) -> None:
    if pd.isna(value):
        if non_null_count:
            raise DocumentPageError("document_numeric_result_non_finite")
    elif not isinstance(value, Integral) and (
        not isinstance(value, Real) or not math.isfinite(value)
    ):
        raise DocumentPageError("document_numeric_result_non_finite")


def _check_query_arithmetic_results(frame: pd.DataFrame, expression: str) -> None:
    if not expression:
        return
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return  # The existing filter owns syntax errors.
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp):
            continue
        # Reuse the canonical evaluator after the numeric/resource grammar
        # guard. Overflow inside an expression must not become a false mask.
        computed = _evaluate(node, frame)
        if isinstance(computed, pd.Series):
            present = pd.Series(True, index=frame.index)
            for column in {part.id for part in ast.walk(node) if isinstance(part, ast.Name)}:
                present &= frame[column].notna()
            for value in computed[present]:
                _finite_result(value, 1)
        else:
            _finite_result(computed, 1)


def _check_aggregate_results(frame: pd.DataFrame, result: pd.DataFrame, selection: dict) -> None:
    groups = selection["group_by"]
    counts = (
        frame.groupby(groups, dropna=False)[list(selection["column_types"])].count()
        if groups
        else None
    )
    for metric in selection["metrics"]:
        column = metric["column"]
        if column not in selection["column_types"]:
            continue
        non_null = counts[column] if counts is not None else [frame[column].count()]
        for value, count in zip(result[f"{column}_{metric['op']}"], non_null, strict=True):
            _finite_result(value, int(count))


def analyze_native_table(document: dict, arguments: dict, file_path: str) -> dict:
    """Compute on every selected source row, then page only the derived result."""
    offset, limit, selection, _ = analysis_parameters(arguments)
    frame, evidence = _frame(document, selection)
    statistics: dict[str, dict] = {}
    try:
        _guard_query_arithmetic(frame, selection["query_expression"] or "")
        # pandas' fixed-width integer arithmetic/sum can wrap silently. Its
        # object lane uses Python integers, preserving the declared conversion
        # through filtering and the existing aggregate implementation.
        for column in selection["column_types"]:
            if pd.api.types.is_integer_dtype(frame[column].dtype):
                frame[column] = frame[column].astype(object)
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            _check_query_arithmetic_results(frame, selection["query_expression"] or "")
        frame = safe_filter_dataframe(frame, selection["query_expression"] or "")
        evidence["source_row_count"] = len(frame)
        action = selection["action"]
        if action == "aggregate":
            for metric in selection["metrics"]:
                if metric["column"] not in frame.columns:
                    raise DocumentPageError("document_native_column_not_found")
                if (
                    metric["op"] in {"sum", "mean"}
                    and metric["column"] not in selection["column_types"]
                ):
                    raise DocumentPageError(
                        "document_numeric_conversion_required", column=metric["column"]
                    )
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                result_frame = aggregate_frame(frame, selection)
            _check_aggregate_results(frame, result_frame, selection)
        elif action == "statistics":
            numeric = frame.loc[:, list(selection["column_types"])]
            # Keep the scalar aggregate results. Even dtype=object cannot undo
            # an intermediate Series inference when a nested aggregate matrix
            # mixes integer sums with fractional means.
            for column in numeric.columns:
                count = int(numeric[column].count())
                values: dict[str, Any] = {"count": count}
                for op in ("sum", "mean", "min", "max"):
                    with np.errstate(over="raise", invalid="raise", divide="raise"):
                        value = None if not count and op != "sum" else numeric[column].agg(op)
                    _finite_result(value, count)
                    values[op] = value
                statistics[str(column)] = values
            evidence["numeric_columns"] = list(statistics)
        else:
            result_frame = frame
    except (ValueError, TypeError, ArithmeticError, RuntimeWarning) as exc:
        if isinstance(exc, DocumentPageError):
            raise
        if isinstance(exc, (ArithmeticError, RuntimeWarning)):
            raise DocumentPageError("document_numeric_result_non_finite") from exc
        raise DocumentPageError("document_table_operation_failed", message=str(exc)[:240]) from exc
    rows: Iterator[tuple[Any, dict]]
    if selection["action"] == "statistics":
        rows = iter(statistics.items())
        evidence["result_columns"] = ["count", "sum", "mean", "min", "max"]
    else:
        rows = (
            (values[0], dict(zip(result_frame.columns, values[1:], strict=True)))
            for values in result_frame.itertuples(index=True, name=None)
        )
        evidence["result_columns"] = [str(column) for column in result_frame.columns]
    result = _paginate(
        document,
        arguments,
        file_path,
        view="table",
        selection=selection,
        source_items=_records(document, rows, selection),
        offset=offset,
        limit=limit,
        extra_data=evidence,
    )
    if selection["action"] == "statistics":
        result["row_count"] = len(frame)
        result["numeric_summary"] = {
            str(column): {
                str(key): None if pd.isna(value) else json_safe(value)
                for key, value in values.items()
            }
            for column, values in statistics.items()
        }
    if len(_encoded(result)) > MAX_PAGE_BYTES:
        raise DocumentPageError("document_response_budget_exceeded")
    return result
