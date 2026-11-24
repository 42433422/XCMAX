"""Workbook comparison shared by the authorized workbook read adapter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app.application.tools.workflow_tools.contracts import ExcelIO, Payload


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


@dataclass(frozen=True)
class WorkbookOperations:
    io: ExcelIO
    read_plain: Callable[[Path], pd.DataFrame]

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
