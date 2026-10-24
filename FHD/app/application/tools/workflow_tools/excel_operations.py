"""Workbook comparison, trend estimates, schema, and indexing operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app.application.tools.workflow_tools.contracts import (
    ExcelIO,
    Payload,
    VectorIngest,
    WorkbookSchema,
)


def compare_frames(left: pd.DataFrame, right: pd.DataFrame, keys: list[str]) -> Payload:
    if not keys:
        return {"action": "diff", "row_count": len(left)}
    a, b = left.set_index(keys), right.set_index(keys)
    only_left = [index for index in a.index if index not in b.index]
    only_right = [index for index in b.index if index not in a.index]
    common = [index for index in a.index if index in b.index]
    changed = sum(not a.loc[index].equals(b.loc[index]) for index in common)
    return {
        "action": "diff",
        "only_in_left": {"count": len(only_left)},
        "only_in_right": {"count": len(only_right)},
        "rows_with_value_changes": {"count": changed},
    }


def linear_forecast(values: pd.Series, periods: int) -> Payload:
    if len(values) < 2:
        return {
            "action": "forecast",
            "future_forecast": [{"yhat": 0.0}] * periods,
            "note": "数据不足，使用零预测",
        }
    x = list(range(len(values)))
    n, sx, sy = len(x), sum(x), float(values.sum())
    sxy = sum(xi * yi for xi, yi in zip(x, values))
    sxx = sum(xi**2 for xi in x)
    denominator = n * sxx - sx * sx
    slope = (n * sxy - sx * sy) / denominator if denominator else 0
    intercept = (sy - slope * sx) / n
    return {
        "action": "forecast",
        "future_forecast": [
            {"period": i + 1, "yhat": round(intercept + slope * (len(values) + i), 4)}
            for i in range(periods)
        ],
        "model": "linear_regression",
        "periods": periods,
    }


@dataclass(frozen=True)
class WorkbookOperations:
    io: ExcelIO
    read_plain: Callable[[Path], pd.DataFrame]
    schema_factory: Callable[[], WorkbookSchema]
    ingest: VectorIngest

    def join_compare(self, args: Payload, workspace_root: str | None) -> Payload:
        action = str(args.get("action") or "join")
        if action == "join":
            left, right = (args.get("file_paths") or [None, None])[:2]
            path_args = (str(left), str(right))
        elif action == "diff":
            left, right = args.get("file_path_a"), args.get("file_path_b")
            path_args = (str(left or ""), str(right or ""))
        else:
            return {"success": False, "error": f"unknown action: {action}"}
        root = workspace_root or str(Path.cwd())
        first, second = (self.io.resolve(root, value) for value in path_args)
        if not first.exists():
            return {"success": False, "error": f"file not found: {left}"}
        if not second.exists():
            return {"success": False, "error": f"file not found: {right}"}
        a, b = self.read_plain(first), self.read_plain(second)
        key_arg = "join_keys" if action == "join" else "key_columns"
        keys = [str(value) for value in args.get(key_arg) or [] if str(value)]
        if action == "diff":
            return compare_frames(a, b, keys)
        result = a.merge(b, on=keys, how=str(args.get("how") or "inner")) if keys else a
        return {
            "action": "join",
            "row_count": len(result),
            "columns": list(result.columns.astype(str)),
        }

    def forecast(self, args: Payload, workspace_root: str | None) -> Payload:
        file_path = str(args.get("file_path") or "")
        column = str(args.get("value_column") or args.get("y") or "").strip()
        periods = max(1, min(30, int(args.get("periods") or 6)))
        values = pd.Series([], dtype=float)
        if file_path:
            path = self.io.resolve(workspace_root or str(Path.cwd()), file_path)
            df = self.io.read(path, sheet_name=None, header_row_1based=None)
            if not column or column not in df.columns:
                numeric = [
                    c for c in df.columns if pd.to_numeric(df[c], errors="coerce").notna().sum() > 2
                ]
                column = numeric[0] if numeric else ""
            if column:
                values = pd.to_numeric(df[column], errors="coerce").dropna()
        return linear_forecast(values, periods)

    def schema(self, args: Payload, workspace_root: str | None) -> Payload:
        file_path = str(args.get("file_path") or "")
        sheet, header = args.get("sheet_name"), self.io.header(args)
        root = workspace_root or str(Path.cwd())
        path = self.io.resolve(root, file_path)
        if not path.exists():
            return {
                "success": False,
                "error": "file_not_found",
                "message": f"找不到文件: {file_path}",
                "hint": "请确认文件已正确上传，或重新上传文件。",
                "workspace_root": root,
                "resolved_path": str(path),
            }
        df = self.io.read(path, sheet_name=sheet, header_row_1based=header)
        return self.schema_factory().understand_dataframe(df, file_path=file_path)

    def vector_index(self, args: Payload, workspace_root: str | None) -> Payload:
        file_path = str(args.get("file_path") or "").strip()
        if not file_path:
            return {"success": False, "error": "file_path is required"}
        path = self.io.resolve(workspace_root or str(Path.cwd()), file_path)
        if not path.exists():
            return {
                "success": False,
                "error": "file_not_found",
                "file_path": file_path,
                "resolved_path": str(path),
            }
        result = self.ingest(
            file_path=str(path),
            index_name=str(args.get("index_name") or "").strip() or None,
            index_id=str(args.get("index_id") or "").strip() or None,
        )
        if isinstance(result, dict) and result.get("success") and result.get("index_id"):
            result["excel_vector_index_id"] = result.get("index_id")
            result["excel_index_id"] = result.get("index_id")
        return result
