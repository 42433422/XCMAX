"""Runtime contract samples for native workbook reads and table operations."""

from __future__ import annotations

from typing import Any

_WORKBOOK_TOOL_CONTRACTS: dict[tuple[str, str], list[dict[str, Any]]] = {
    ("excel_analysis", "read"): [
        {
            "name": "workbook_native_cells_page_contract",
            "input": {
                "file_path": "sample.xlsx",
                "view": "cells",
                "sheet_name": "Sheet1",
                "offset": 1,
                "max_rows": 1,
                "expected_sha256": "a" * 64,
            },
            "output": {
                "success": True,
                "data": {
                    "view": "cells",
                    "sheet_name": "Sheet1",
                    "source_sha256": "a" * 64,
                    "offset": 1,
                    "cells": [{"address": "A2", "value": 7}],
                    "has_more": False,
                    "next_offset": None,
                },
            },
        }
    ],
    ("excel_analysis", "export"): [
        {
            "name": f"workbook_export_{extension}_contract",
            "input": {
                "file_path": f"result.{extension}",
                "rows": [{"name": "item", "quantity": 1}],
            },
            "output": {
                "success": True,
                "data": {
                    "file_path": f"/workspace/result.{extension}",
                    "row_count": 1,
                    "columns": ["name", "quantity"],
                },
            },
        }
        for extension in ("xlsx", "csv")
    ],
    ("excel_analysis", "aggregate"): [
        {
            "name": "workbook_aggregate_contract",
            "input": {
                "file_path": "sample.xlsx",
                "metrics": [{"column": "amount", "op": "sum"}],
            },
            "output": {"success": True},
        }
    ],
    ("excel_join_compare", "join"): [
        {
            "name": "workbook_join_contract",
            "input": {"file_paths": ["left.xlsx", "right.xlsx"], "join_keys": ["id"]},
            "output": {"success": True, "action": "join", "row_count": 1},
        }
    ],
    ("excel_join_compare", "diff"): [
        {
            "name": "workbook_diff_contract",
            "input": {
                "file_path_a": "left.xlsx",
                "file_path_b": "right.xlsx",
                "key_columns": ["id"],
            },
            "output": {
                "success": True,
                "action": "diff",
                "rows_with_value_changes": {"count": 1},
            },
        }
    ],
}
