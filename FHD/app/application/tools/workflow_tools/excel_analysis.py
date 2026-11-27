"""Read and summarize workbooks through bounded, safe DataFrame operations."""

from __future__ import annotations

import inspect
import json
import logging
import os
import zipfile
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from itertools import groupby, islice
from math import fsum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, cast

import pandas as pd

from app.application import excel_export_limits
from app.application.tools.workflow_tools.contracts import ExcelIO, Payload
from app.infrastructure.excel.date_norm import cn_date, date_like_columns, to_number
from app.infrastructure.excel.schema_service import dataframe_schema_snapshot
from app.utils.json_safe import json_safe
from app.utils.operational_errors import RECOVERABLE_ERRORS

_EXCEL_ANALYSIS_DEFAULT_PAGE_ROWS = 1000
_EXCEL_ANALYSIS_MAX_PAGE_ROWS = 5000
# 依赖列语义的动作和自然语言问题需要确认表头；原始读取和显式筛选沿用指定表头。
_AUTO_HEADER_ACTIONS = frozenset({"statistics", "structure", "aggregate"})
_TOTAL_ROW_MARKERS = ("合计", "总计", "小计", "累计")


def _env_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def page_rows(requested: Any = None) -> int:
    hard_max = _env_positive_int("FHD_EXCEL_ANALYSIS_MAX_PAGE_ROWS", _EXCEL_ANALYSIS_MAX_PAGE_ROWS)
    default_rows = min(
        _env_positive_int("FHD_EXCEL_ANALYSIS_PAGE_ROWS", _EXCEL_ANALYSIS_DEFAULT_PAGE_ROWS),
        hard_max,
    )
    try:
        rows = int(requested) if requested is not None else default_rows
    except (TypeError, ValueError):
        rows = default_rows
    return min(max(1, rows), hard_max)


def page_budget(args: Payload) -> tuple[int, int]:
    try:
        offset = max(0, int(args.get("offset") or 0))
    except (TypeError, ValueError):
        offset = 0
    return offset, page_rows(args.get("max_rows"))


def read_excel_dataframe(
    p: Path, *, sheet_name: Any, header_row_1based: int | None
) -> pd.DataFrame:
    if p.suffix.lower() == ".csv":
        df = pd.read_csv(p, header=None if header_row_1based == 0 else (header_row_1based or 1) - 1)
    else:
        options: Payload = {}
        if p.suffix.lower() in (".xlsx", ".xlsm"):
            options["engine"] = "openpyxl"
        if sheet_name:
            options["sheet_name"] = sheet_name
        if header_row_1based is not None:
            options["header"] = header_row_1based - 1 if header_row_1based else None
        df = cast(pd.DataFrame, pd.read_excel(p, **options))
    if header_row_1based == 0:
        from openpyxl.utils.cell import get_column_letter

        df.columns = [get_column_letter(index) for index in range(1, len(df.columns) + 1)]
        return df
    return _clean_header_columns(df)


def _clean_header_columns(df: pd.DataFrame) -> pd.DataFrame:
    """合并单元格表头读入后会出现 ``Unnamed: n``，用左侧标签补齐并去掉全空列。"""
    original = [str(name) for name in df.columns]
    if not any(name.startswith("Unnamed:") for name in original):
        return df
    keep = [
        index
        for index, name in enumerate(original)
        if not (name.startswith("Unnamed:") and df.iloc[:, index].isna().all())
    ]
    if not keep:
        return df
    frame = df.iloc[:, keep].copy()
    names: list[str] = []
    seen: dict[str, int] = {}
    previous: str | None = None
    for index in keep:
        name = original[index]
        if name.startswith("Unnamed:") and previous is not None:
            name = previous
        else:
            previous = name
        count = seen.get(name, 0) + 1
        seen[name] = count
        names.append(name if count == 1 else f"{name}_{count}")
    frame.columns = names
    return frame


def auto_header_row(path: Path, sheet_name: str | None) -> int | None:
    """Infer an unspecified header; model failures remain failures at the tool boundary."""
    from app.infrastructure.excel.header_detection import detect_header_row_1based

    return detect_header_row_1based(path, sheet_name)


def _suspected_total_rows(df: pd.DataFrame, limit: int = 20) -> list[int]:
    """标出疑似合计行（0-based 位置），供上层决定是否剔除，避免直接改动数据。"""
    text_columns = [name for name in df.columns if df[name].dtype.kind in "OUS"]
    rows: list[int] = []
    for position, (_, row) in enumerate(df.iterrows()):
        if position >= limit:
            break
        for name in text_columns:
            value = row[name]
            if pd.isna(value):
                continue
            if any(marker in str(value) for marker in _TOTAL_ROW_MARKERS):
                rows.append(position)
                break
    return rows


def workbook_sheet_names(path: Path) -> list[str]:
    """Read the worksheet directory without scanning cell rows."""
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xltx", ".xltm"} or not zipfile.is_zipfile(
        path
    ):
        return []
    try:
        from openpyxl import load_workbook

        workbook = load_workbook(str(path), read_only=True)
        try:
            return [sheet.title for sheet in workbook.worksheets]
        finally:
            workbook.close()
    except RECOVERABLE_ERRORS:
        return []


def frame_records(df: pd.DataFrame, limit: int = 200) -> list[Payload]:
    return cast(
        list[Payload],
        json.loads(df.head(limit).replace({float("nan"): None}).to_json(orient="records")),
    )


def _row_evidence(index: pd.Index, header: int) -> Payload:
    """Bound machine-generated coordinates without hiding that the list was truncated."""
    groups = groupby(enumerate(index.sort_values()), lambda pair: pair[1] - pair[0])
    ranges = []
    for _, rows in islice(groups, 33):
        first = last = int(next(rows)[1]) + header + 1
        for _, row in rows:
            last = int(row) + header + 1
        ranges.append([first, last])
    return {
        "row_ranges": ranges[:32],
        "row_ranges_truncated": len(ranges) > 32,
        "source_row_count": len(index),
    }


def table_result(df: pd.DataFrame, *, offset: int = 0, max_rows: Any = None) -> Payload:
    offset = max(0, int(offset or 0))
    rows = page_rows(max_rows)
    page = df.iloc[offset : offset + rows]
    returned = len(page)
    has_more = offset + returned < len(df)
    source_header = df.attrs.get("source_header")
    evidence = {}
    if type(source_header) is int:
        matching = df.attrs.get("matched_source_rows")
        evidence = _row_evidence(matching if matching is not None else page.index, source_header)
    return {
        "row_count": len(df),
        "returned_rows": returned,
        "offset": offset,
        "page_rows": rows,
        "truncated": has_more,
        "has_more": has_more,
        "next_offset": offset + returned if has_more else None,
        "columns": list(df.columns.astype(str)),
        "records": frame_records(page, limit=returned),
        **({"source_rows": evidence} if evidence else {}),
    }


def _supports_error_feedback(fn: Callable[..., Any]) -> bool:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return "error_feedback" in params or any(
        param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values()
    )


def natural_language_query(
    df: pd.DataFrame,
    natural_language: str,
    translate: Callable[[str, pd.DataFrame], str | None],
    execute: Callable[[str, pd.DataFrame], pd.DataFrame],
    *,
    offset: int = 0,
    max_rows: Any = None,
) -> Payload:
    generated_code = ""
    error: str | None = None
    result = df
    try:
        code = translate(natural_language, df)
    except ValueError:
        code, error = None, "invalid_pandas_query"
    except RECOVERABLE_ERRORS:
        code, error = None, "excel_query_failed"
    if error is None and not (code and code.strip()):
        error = "query_translation_failed"
    if error is None:
        generated_code = str(code)
        try:
            result = execute(generated_code, df)
        except RECOVERABLE_ERRORS as exc:
            # 成熟的表格 agent 会把「失败的代码 + 异常」回传模型重写一次，
            # 而不是把首次生成的错误直接抛给用户。
            retry_code = _retry_translation(
                translate, natural_language, df, f"{generated_code}\n# error: {exc}"
            )
            if retry_code and retry_code.strip():
                generated_code = retry_code
                try:
                    result = execute(retry_code, df)
                except ValueError:
                    error = "invalid_pandas_query"
                except RECOVERABLE_ERRORS:
                    error = "excel_query_failed"
            else:
                error = (
                    "invalid_pandas_query" if isinstance(exc, ValueError) else "excel_query_failed"
                )
    messages = {
        "invalid_pandas_query": "查询条件无法转换为可执行的表格计算，请换一种描述。",
        "excel_query_failed": "表格查询执行失败，请核对问题描述或文件内容后重试。",
        "query_translation_failed": "未能从问题中识别出表格查询条件，已返回原始表格；请指明列名或日期范围。",
    }
    return {
        "generated_code": generated_code,
        "result_kind": "dataframe",
        **table_result(result, offset=offset, max_rows=max_rows),
        **(
            {"error": error, "message": messages[error], "success": False}
            if error
            else {"success": True}
        ),
    }


def _retry_translation(
    translate: Callable[..., str | None],
    natural_language: str,
    df: pd.DataFrame,
    feedback: str,
) -> str | None:
    if not _supports_error_feedback(translate):
        return None
    try:
        return translate(natural_language, df, error_feedback=feedback)
    except RECOVERABLE_ERRORS:
        return None


def aggregate_frame(df: pd.DataFrame, args: Payload) -> pd.DataFrame:
    group_by = [str(value) for value in args.get("group_by") or [] if str(value)]
    metrics = args.get("metrics") or []
    operations: dict[str, list[str]] = {}
    for metric in metrics if isinstance(metrics, list) else []:
        if not isinstance(metric, dict):
            continue
        column, op = str(metric.get("column") or "").strip(), str(metric.get("op") or "").strip()
        if column not in df.columns or op not in {"sum", "mean", "count", "min", "max"}:
            raise ValueError("invalid_aggregation_metrics")
        if op not in operations.setdefault(column, []):
            operations[column].append(op)
    if not operations:
        raise ValueError("missing_aggregation_metrics")
    if any(column not in df.columns for column in group_by):
        raise ValueError("invalid_group_by")
    try:
        if not group_by:
            return pd.DataFrame(
                [
                    {
                        f"{column}_{op}": df[column].agg(op)
                        for column, ops in operations.items()
                        for op in ops
                    }
                ]
            )
        result = df.groupby(group_by, dropna=False).agg(operations)
    except TypeError as exc:
        raise ValueError(
            "aggregation requires compatible column types; use an explicit conversion"
        ) from exc
    result = result.reset_index()
    result.columns = [
        "_".join(str(part) for part in column if str(part)).strip("_")
        if isinstance(column, tuple)
        else str(column)
        for column in result.columns
    ]
    return result


def physical_range_sum(
    path: Path, sheet: str, frame: pd.DataFrame, args: Payload, *, offset: int, max_rows: int
) -> Payload:
    from openpyxl import load_workbook
    from openpyxl.utils.cell import get_column_letter, range_boundaries
    from openpyxl.utils.exceptions import InvalidFileException

    metrics = args["metrics"]
    invalid = {"success": False, "error": "invalid_sum_cell_range"}
    if len(metrics) != 1 or args.get("group_by") or frame.attrs.get("source_header") != 0:
        return invalid
    metric = metrics[0]
    try:
        left, start, right, stop = range_boundaries(str(metric.get("cell_range") or ""))
    except ValueError:
        return invalid
    column = metric.get("column")
    if left is None or start is None or right is None or stop is None:
        return invalid
    if (
        metric.get("op") != "sum"
        or left != right
        or not 1 <= start <= stop <= len(frame)
        or not isinstance(column, str)
        or column not in frame.columns
        or get_column_letter(left) != column
    ):
        return invalid

    numbers: list[float] = []
    ignored: list[int] = []
    read_errors: tuple[type[Exception], ...] = RECOVERABLE_ERRORS + (
        InvalidFileException,
        KeyError,
        zipfile.BadZipFile,
    )
    try:
        with (
            closing(
                load_workbook(path, read_only=True, data_only=True, keep_links=False)
            ) as values,
            closing(load_workbook(path, read_only=True, keep_links=False)) as formulas,
        ):
            cells = zip(
                values[sheet].iter_rows(min_row=start, max_row=stop, min_col=left, max_col=left),
                formulas[sheet].iter_rows(min_row=start, max_row=stop, min_col=left, max_col=left),
                strict=True,
            )
            for row, ((value,), (formula,)) in enumerate(cells, start):
                if value.data_type == "e" or (formula.data_type == "f" and value.value is None):
                    error = (
                        "sum_cell_error"
                        if value.data_type == "e"
                        else "sum_formula_value_unavailable"
                    )
                    return {"success": False, "error": error, "cell": f"{column}{row}"}
                if value.data_type == "d":
                    return {
                        "success": False,
                        "error": "sum_range_date_cell",
                        "cell": f"{column}{row}",
                    }
                if type(value.value) is int or type(value.value) is float:
                    numbers.append(value.value)
                elif value.value is not None:
                    ignored.append(row - 1)
    except read_errors:
        return {"success": False, "error": "read_excel_failed"}
    evidence = {
        "cell_range": f"{column}{start}:{column}{stop}",
        "source_rows": _row_evidence(pd.RangeIndex(start - 1, stop), 0),
        "ignored_non_numeric_rows": _row_evidence(pd.Index(ignored), 0),
        "numeric_cell_count": len(numbers),
    }
    if ignored and not numbers:
        return {**evidence, "success": False, "error": "sum_range_has_no_numeric_cells"}
    result = pd.DataFrame([{f"{column}_sum": fsum(numbers)}])
    return {**evidence, **table_result(result, offset=offset, max_rows=max_rows)}


def execute_query_plan(value: str, df: pd.DataFrame) -> pd.DataFrame:
    """Compose existing bounded filtering and aggregation; never execute model code."""
    from app.application.tools.safe_dataframe_query import safe_filter_dataframe
    from app.infrastructure.excel.schema_service import load_query_plan

    plan = load_query_plan(value)
    if plan.get("unsupported_reason"):
        raise ValueError("query is not supported by the read-only table operations")
    result = df.copy()
    result.columns = [str(column) for column in df.columns]
    if not result.columns.is_unique:
        raise ValueError("query requires unique column names")
    for conversion in plan.get("conversions", []):
        column = conversion["column"]
        if column not in result.columns:
            raise ValueError(f"unknown dataframe column: {column}")
        result[column] = (
            cn_date(result[column], default_year=conversion.get("default_year"))
            if conversion["kind"] == "date"
            else to_number(result[column])
        )
    # Stable aliases handle arbitrary Excel labels without extending the filter grammar.
    aliases = {f"c{index}": name for index, name in enumerate(result.columns)}
    result.columns = list(aliases)
    result = safe_filter_dataframe(result, plan.get("query_expression", ""))
    result = result.rename(columns=aliases)
    if plan.get("metrics"):
        source_index = result.index
        result = aggregate_frame(result, plan)
        if "source_header" in df.attrs:
            result.attrs.update(
                source_header=df.attrs["source_header"], matched_source_rows=source_index
            )
    elif plan.get("group_by"):
        raise ValueError("missing_aggregation_metrics")
    for field in ("columns", "sort_by"):
        if any(column not in result.columns for column in plan.get(field, [])):
            raise ValueError(f"unknown dataframe column in {field}")
    if plan.get("sort_by"):
        try:
            result = result.sort_values(plan["sort_by"], ascending=plan.get("ascending", True))
        except TypeError as exc:
            raise ValueError(
                "query sort requires comparable column values; use an explicit conversion"
            ) from exc
    if plan.get("columns"):
        result = result.loc[:, plan["columns"]]
    if "limit" in plan:
        result = result.head(plan["limit"])
    if not result.columns.is_unique:
        raise ValueError("query result has ambiguous column names")
    if "source_header" in df.attrs:
        result.attrs["source_header"] = df.attrs["source_header"]
    return result


def _native_workbook_page(path: Path, args: Payload) -> Payload:
    """Read exact native facts inside the caller's existing authorized file snapshot."""
    from openpyxl.utils.cell import range_boundaries

    from app.application.tabular_workbook import read_workbook_facts

    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        raise ValueError("native_facts_unsupported_format")
    offset, limit = page_budget(args)
    expected = args.get("expected_sha256")
    if offset and not expected:
        raise ValueError("native_page_requires_source_sha256")
    document = read_workbook_facts(path, expected_sha256=expected)
    if document.get("status") in {"blocked", "unsupported"}:
        raise ValueError("native_facts_blocked")
    view = args["view"]
    sheets = document["sheets"]
    sheet_name = args.get("sheet_name")
    if view == "sheets":
        items = [
            {
                "sheet_id": sheet["sheet_id"],
                "sheet": sheet["sheet"],
                "sheet_state": sheet["sheet_state"],
                "cell_count": len(sheet["cells"]),
                "rows": sheet.get("max_row"),
                "columns": sheet.get("max_column"),
                "content_range": sheet.get("content_range"),
                "status": sheet.get("status"),
            }
            for sheet in sheets
        ]
    else:
        sheet = next((sheet for sheet in sheets if sheet["sheet"] == sheet_name), None)
        if sheet is None:
            raise ValueError("native_cells_require_existing_sheet_name")
        if sheet.get("status") == "unsupported":
            raise ValueError("native_sheet_unsupported")
        items = sheet["cells"]
        if area := args.get("cell_range"):
            if not isinstance(area, str):
                raise ValueError("invalid_native_cell_range")
            left, top, right, bottom = range_boundaries(area)
            if left is None or top is None or right is None or bottom is None:
                raise ValueError("invalid_native_cell_range")
            if not (
                all(type(n) is int for n in (left, top, right, bottom))
                and 1 <= left <= right <= 16384
                and 1 <= top <= bottom <= 1048576
            ):
                raise ValueError("invalid_native_cell_range")
            items = [
                cell
                for cell in items
                if top <= cell["row"] <= bottom and left <= cell["column"] <= right
            ]
    page: list[dict[str, Any]] = []
    page_bytes = 2
    for item in items[offset : offset + limit]:
        item_bytes = len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode())
        if page_bytes + item_bytes + bool(page) > 40000:
            if not page:
                raise ValueError("native_fact_exceeds_page_byte_budget")
            break
        page_bytes += item_bytes + bool(page)
        page.append(item)
    has_more = offset + len(page) < len(items)
    source_ref = document["source_ref"]
    data = {
        "schema_version": document["schema_version"],
        "document_id": document["document_id"],
        "source_ref": source_ref,
        "source_sha256": source_ref["source_sha256"],
        "view": view,
        "sheet_name": sheet_name,
        "cell_range": args.get("cell_range"),
        "source_status": document.get("status"),
        "partial": document.get("status") != "complete",
        "total_items": len(items),
        "returned_items": len(page),
        "page_byte_budget": 40000,
        "page_bytes": page_bytes,
        "offset": offset,
        "has_more": has_more,
        "truncated": has_more,
        "next_offset": offset + len(page) if has_more else None,
        view: page,
        "warnings": document.get("warnings") or [],
    }
    return {"success": True, "action": "read", "file_path": str(path), **data, "data": data}


@dataclass(frozen=True)
class ExcelAnalysis:
    io: ExcelIO
    filter_frame: Callable[[pd.DataFrame, str], pd.DataFrame]
    customer_hint: Callable[[str, str | None], str]
    logger: logging.Logger

    def analyze(self, args: Payload, workspace_root: str | None = None) -> Payload:
        from app.infrastructure.document_parsing.archive_safety import inspect_office_archive
        from app.infrastructure.excel.header_detection import (
            HeaderConfirmationRequired,
            HeaderDetectionFailed,
        )

        file_path = str(args.get("file_path") or "")
        action = str(args.get("action") or "read")
        sheet = args.get("sheet_name")
        raw_header = args.get("header_row")
        if raw_header is not None and (type(raw_header) is not int or raw_header < 0):
            return {"success": False, "error": "invalid_header_row", "required_field": "header_row"}
        header = self.io.header(args)
        if type(args.get("header_row")) is int and args["header_row"] == 0:
            header = 0
        if not file_path:
            return {"success": False, "error": "file_path is required"}
        expression = args.get("query_expression")
        question = args.get("question")
        if action == "query" and "query_expression" in args and "question" in args:
            return {
                "success": False,
                "error_code": "ambiguous_query_input",
                "message": "查询问题与筛选表达式只能选择一种",
            }
        if action == "query" and not (
            isinstance(expression, str)
            and expression.strip()
            or isinstance(question, str)
            and question.strip()
        ):
            return {
                "success": False,
                "error_code": "missing_query_expression",
                "message": "查询需要非空的问题或受限筛选表达式",
            }
        root = workspace_root or str(Path.cwd())
        if action == "export":
            return self.export_table(args, root)
        try:
            path = self.io.resolve(root, file_path)
        except RECOVERABLE_ERRORS:
            return {
                "success": False,
                "error": "invalid_excel_path",
                "workspace_root": root,
                "file_path": file_path,
            }
        if not path.exists():
            return {
                "success": False,
                "error": "file not found",
                "file_path": file_path,
                "workspace_root": root,
                "resolved_path": str(path),
            }
        if action == "read" and args.get("view", "table") != "table":
            if args.get("view") not in {"cells", "sheets"}:
                return {"success": False, "error": "invalid_read_view"}
            try:
                return _native_workbook_page(path, args)
            except (ValueError, OSError, zipfile.BadZipFile) as exc:
                return {"success": False, "error": "native_facts_read_failed", "message": str(exc)}
        try:
            if path.suffix.lower() in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
                inspect_office_archive(path)
            infer_header = action in _AUTO_HEADER_ACTIONS or (
                action == "query" and isinstance(question, str) and bool(question.strip())
            )
            if header is None and infer_header:
                header = auto_header_row(path, str(sheet).strip() if sheet else None)
            df = self.io.read(path, sheet_name=sheet, header_row_1based=header)
        except HeaderConfirmationRequired as exc:
            return {
                "success": False,
                "error": "header_confirmation_required",
                "message": str(exc),
                "required_field": "header_row",
                "header_candidates": list(exc.candidate_rows),
                "physical_preview": exc.sample_rows,
            }
        except HeaderDetectionFailed as exc:
            return {
                "success": False,
                "error": "header_detection_failed",
                "message": str(exc),
                "required_field": "header_row",
            }
        except RECOVERABLE_ERRORS:
            return {
                "success": False,
                "error": "read_excel_failed",
                "file_path": file_path,
                "resolved_path": str(path),
                "sheet_name": sheet,
                "header_row": header,
            }
        offset, max_rows = page_budget(args)
        sheets = workbook_sheet_names(path) if action == "structure" or not sheet else []
        source_sheet = str(sheet).strip() if sheet else next(iter(sheets), None)
        source_header = header if header is not None else 1
        if source_sheet and path.suffix.lower() in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
            df.attrs["source_header"] = source_header
        base = {
            "success": True,
            "action": action,
            "file_path": file_path,
            "sheet_name": source_sheet,
            "header_row": source_header,
        }
        if action == "structure":
            snapshot = dataframe_schema_snapshot(df)
            return {
                **base,
                "data": {**json_safe(snapshot), "sheet_names": sheets},
                "row_count": snapshot["row_count"],
                "columns": snapshot["columns"],
                "dtypes": snapshot["dtypes"],
                "sample_rows": snapshot["sample_rows"],
                "numeric_columns": [
                    str(name) for name in df.select_dtypes(include="number").columns
                ],
                "date_like_columns": date_like_columns(df),
                "suspected_total_rows": _suspected_total_rows(df),
            }
        if action == "read":
            out = {
                **base,
                **table_result(df, offset=offset, max_rows=max_rows),
            }
            if path.suffix.lower() in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
                try:
                    hint = str(
                        self.customer_hint(str(path), str(sheet).strip() or None) or ""
                    ).strip()
                    if hint:
                        out["customer_hint"] = hint
                except RECOVERABLE_ERRORS:
                    self.logger.debug("suppressed exception", exc_info=True)
            return out
        if action == "query":
            if isinstance(question, str) and question.strip():
                from app.infrastructure.excel.pandas_translator import LLMPandasTranslator

                result = natural_language_query(
                    df,
                    question.strip(),
                    LLMPandasTranslator().translate,
                    execute_query_plan,
                    offset=offset,
                    max_rows=max_rows,
                )
                return {**base, **result}
            try:
                result = self.filter_frame(df, str(expression).strip())
            except ValueError as exc:
                return {
                    "success": False,
                    "error_code": "invalid_query_expression",
                    "message": str(exc),
                }
            return {**base, **table_result(result, offset=offset, max_rows=max_rows)}
        if action == "aggregate":
            if any(
                isinstance(metric, dict) and "cell_range" in metric
                for metric in args.get("metrics") or []
            ):
                return {
                    **base,
                    **physical_range_sum(
                        path, source_sheet or "", df, args, offset=offset, max_rows=max_rows
                    ),
                }
            try:
                result = aggregate_frame(df, args)
            except (ValueError, TypeError) as exc:
                code = str(exc)
                if code not in {
                    "invalid_aggregation_metrics",
                    "missing_aggregation_metrics",
                    "invalid_group_by",
                }:
                    code = "aggregation_failed"
                return {"success": False, "error": code}
            return {
                **base,
                **table_result(result, offset=offset, max_rows=max_rows),
                "source_row_count": len(df),
                **(
                    {"source_rows": _row_evidence(df.index, source_header)}
                    if "source_header" in df.attrs
                    else {}
                ),
            }
        if action == "statistics":
            numeric = df.select_dtypes(include="number")
            numeric_summary = (
                json.loads(numeric.agg(["count", "sum", "mean", "min", "max"]).to_json())
                if len(numeric.columns)
                else {}
            )
            return {
                **base,
                "row_count": len(df),
                **(
                    {"source_rows": _row_evidence(df.index, source_header)}
                    if "source_header" in df.attrs
                    else {}
                ),
                "dtypes": {str(k): str(v) for k, v in df.dtypes.items()},
                "numeric_summary": numeric_summary,
            }
        return {"success": False, "error": f"unsupported_action:{action}"}

    def export_table(self, args: Payload, workspace_root: str) -> Payload:
        """Write a small csv or xlsx under the task workspace and return its on-disk path."""
        if error := excel_export_limits.export_input_error(args):
            return error
        rows = args.get("rows")
        relative = str(args.get("file_path") or "").strip()
        if not relative or Path(relative).is_absolute():
            return {"success": False, "error": "invalid_excel_path", "message": "文件路径无效"}
        root = Path(workspace_root).resolve()
        path = (root / relative).resolve()
        if root != path and root not in path.parents:
            return {"success": False, "error": "invalid_excel_path", "message": "文件路径无效"}
        staging: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            frame = pd.DataFrame(rows)
            with NamedTemporaryFile(
                dir=path.parent, prefix=".excel-export-", suffix=path.suffix, delete=False
            ) as temporary:
                staging = Path(temporary.name)
            if path.suffix.lower() == ".csv":
                frame.to_csv(staging, index=False)
            else:
                frame.to_excel(staging, index=False)
            if staging.stat().st_size > excel_export_limits.MAX_EXPORT_FILE_BYTES:
                raise excel_export_limits.ExcelExportLimitError("导出文件超过产物大小预算")
            os.replace(staging, path)
        except excel_export_limits.ExcelExportLimitError as exc:
            return exc.result()
        except RECOVERABLE_ERRORS as exc:
            self.logger.exception("excel export failed")
            return {
                "success": False,
                "error_code": "file_write_failed",
                "message": "文件写入失败",
                "exception_type": type(exc).__name__,
            }
        finally:
            if staging is not None:
                staging.unlink(missing_ok=True)
        return {
            "success": True,
            "data": {
                "file_path": str(path),
                "row_count": int(len(frame)),
                "columns": [str(column) for column in frame.columns],
            },
        }
