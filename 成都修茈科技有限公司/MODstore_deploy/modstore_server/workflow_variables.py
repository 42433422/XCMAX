"""工作流变量解析与安全表达式求值。"""

from __future__ import annotations

import ast
import re
from typing import Any, Dict

_VAR_RE = re.compile(r"\{\{\s*([^}]+)\s*\}\}")


def _read_path(ctx: Dict[str, Any], expr: str) -> Any:
    cur: Any = ctx
    for seg in expr.split("."):
        seg = seg.strip()
        if not seg:
            continue
        if isinstance(cur, dict):
            cur = cur.get(seg)
        else:
            return None
    return cur


def resolve_value(template: Any, context: Dict[str, Any]) -> Any:
    if isinstance(template, str):
        if template.strip().startswith("{{") and template.strip().endswith("}}"):
            inner = template.strip()[2:-2].strip()
            return _read_path(context, inner)

        def repl(m):
            val = _read_path(context, m.group(1).strip())
            return "" if val is None else str(val)

        return _VAR_RE.sub(repl, template)
    if isinstance(template, dict):
        return {k: resolve_value(v, context) for k, v in template.items()}
    if isinstance(template, list):
        return [resolve_value(v, context) for v in template]
    return template


class _SafeExpr(ast.NodeVisitor):
    ALLOWED = (
        ast.Expression,
        ast.BoolOp,
        ast.BinOp,
        ast.UnaryOp,
        ast.Compare,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.And,
        ast.Or,
        ast.Eq,
        ast.NotEq,
        ast.Gt,
        ast.GtE,
        ast.Lt,
        ast.LtE,
        ast.Not,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Mod,
    )

    def generic_visit(self, node):
        if not isinstance(node, self.ALLOWED):
            raise ValueError(f"unsafe expression: {type(node).__name__}")
        super().generic_visit(node)


def eval_condition(expr: str, context: Dict[str, Any]) -> bool:
    try:
        tree = ast.parse(expr, mode="eval")
        _SafeExpr().visit(tree)
        return bool(eval(compile(tree, "<workflow>", "eval"), {"__builtins__": {}}, context))
    except Exception:
        return False
