"""Conservative dataframe filtering without executing user-provided code."""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from typing import Any

import pandas as pd

_MAX_EXPRESSION_LENGTH = 2_048
_MAX_AST_NODES = 128
_MAX_LITERAL_ITEMS = 100

_COMPARE_OPERATORS: dict[type[ast.cmpop], Callable[[Any, Any], Any]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_ARITHMETIC_OPERATORS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}


def safe_filter_dataframe(df: pd.DataFrame, expression: str) -> pd.DataFrame:
    """Filter a dataframe with a small grammar that cannot execute code."""

    value = str(expression or "").strip()
    if not value:
        return df
    if len(value) > _MAX_EXPRESSION_LENGTH:
        raise ValueError("query_expression is too long")
    try:
        tree = ast.parse(value, mode="eval")
    except SyntaxError as exc:
        raise ValueError("query_expression has invalid syntax") from exc
    if sum(1 for _ in ast.walk(tree)) > _MAX_AST_NODES:
        raise ValueError("query_expression is too complex")

    mask = _evaluate(tree.body, df)
    if isinstance(mask, bool):
        return df if mask else df.iloc[0:0]
    if not isinstance(mask, pd.Series) or not pd.api.types.is_bool_dtype(mask.dtype):
        raise ValueError("query_expression must produce a boolean filter")
    return df.loc[mask.fillna(False)]


def _evaluate(node: ast.AST, df: pd.DataFrame) -> Any:
    if isinstance(node, ast.Name):
        if node.id not in df.columns:
            raise ValueError(f"unknown dataframe column: {node.id}")
        return df[node.id]
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (str, int, float, bool, type(None))):
            raise ValueError("unsupported query literal")
        return node.value
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        if len(node.elts) > _MAX_LITERAL_ITEMS:
            raise ValueError("query literal contains too many items")
        values = [_evaluate(item, df) for item in node.elts]
        if any(isinstance(item, pd.Series) for item in values):
            raise ValueError("column references are not allowed inside literals")
        return values
    if isinstance(node, ast.BoolOp):
        values = [_as_boolean(_evaluate(item, df)) for item in node.values]
        result = values[0]
        operation = operator.and_ if isinstance(node.op, ast.And) else operator.or_
        for item in values[1:]:
            result = operation(result, item)
        return result
    if isinstance(node, ast.UnaryOp):
        operand = _evaluate(node.operand, df)
        if isinstance(node.op, ast.Not):
            return operator.invert(_as_boolean(operand))
        if isinstance(node.op, ast.USub) and isinstance(operand, (int, float)):
            return -operand
        if isinstance(node.op, ast.UAdd) and isinstance(operand, (int, float)):
            return operand
        raise ValueError("unsupported unary operator")
    if isinstance(node, ast.BinOp):
        arithmetic_operation = _ARITHMETIC_OPERATORS.get(type(node.op))
        if arithmetic_operation is None:
            raise ValueError("unsupported arithmetic operator")
        return arithmetic_operation(_evaluate(node.left, df), _evaluate(node.right, df))
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, df)
        compare_result: Any = True
        for operation_node, comparator_node in zip(node.ops, node.comparators):
            right = _evaluate(comparator_node, df)
            if isinstance(operation_node, (ast.In, ast.NotIn)):
                if isinstance(left, pd.Series):
                    if not isinstance(right, list):
                        raise ValueError("'in' requires a literal list")
                    current = left.isin(right)
                else:
                    current = left in right
                if isinstance(operation_node, ast.NotIn):
                    current = operator.invert(current)
            else:
                comparison_operation = _COMPARE_OPERATORS.get(type(operation_node))
                if comparison_operation is None:
                    raise ValueError("unsupported comparison operator")
                current = comparison_operation(left, right)
            compare_result = operator.and_(compare_result, current)
            left = right
        return compare_result
    raise ValueError(f"unsupported query construct: {type(node).__name__}")


def _as_boolean(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, pd.Series) and pd.api.types.is_bool_dtype(value.dtype):
        return value.fillna(False)
    raise ValueError("boolean operators require boolean expressions")
