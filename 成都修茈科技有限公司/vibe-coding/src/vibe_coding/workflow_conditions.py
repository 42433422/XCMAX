"""Safe condition evaluator for :class:`VibeWorkflowEdge` conditions.

Edges in a vibe-coding workflow now support a non-empty ``condition``
string. The engine follows the edge only if the condition evaluates to
something truthy in the current run context.

Supported syntax (a strict subset of Python expressions):

- Literals: ``True`` / ``False`` / ``None``, integers, floats, single- and
  double-quoted strings, list / tuple / dict literals.
- Names: ``foo`` reads ``context["foo"]``. Missing names raise
  :class:`ConditionError` so typos surface early instead of silently
  evaluating to ``None`` (which would always be falsy and silently disable
  the branch).
- Attribute / item access: ``foo.bar`` and ``foo["bar"]`` walk into dict
  values (equivalent semantics; ``.bar`` on a dict means ``["bar"]``).
- Comparisons: ``==`` / ``!=`` / ``<`` / ``<=`` / ``>`` / ``>=`` / ``in`` /
  ``not in`` / ``is`` / ``is not``.
- Boolean ops: ``and`` / ``or`` / ``not``.
- Unary: ``-x`` / ``+x``.
- Membership tests: ``key in dict``, ``item in list``, ``substr in str``.

NOT supported (would raise :class:`ConditionError`):

- Function calls (``len(...)`` etc).
- Lambdas / comprehensions / generators / starred expressions.
- Walrus assignments.
- f-strings.
- Any attribute that resolves to a Python object's dunder.

The evaluator never touches ``__import__`` / ``getattr`` / ``builtins`` so
the worst a malicious condition string can do is raise
:class:`ConditionError`.
"""

from __future__ import annotations

import ast
import operator
from typing import Any, Mapping

_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}

_MISSING = object()


class ConditionError(ValueError):
    """Raised for any unsupported syntax or runtime error in a condition."""


def evaluate_condition(expression: str, context: Mapping[str, Any]) -> bool:
    """Return whether ``expression`` is truthy in ``context``.

    An empty expression ``""`` is treated as ``True`` so the legacy "no
    condition = always follow" semantics still work.
    """
    expr = (expression or "").strip()
    if not expr:
        return True
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ConditionError(f"invalid condition syntax: {exc}") from exc
    try:
        value = _eval(tree.body, context)
    except ConditionError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ConditionError(f"condition raised {type(exc).__name__}: {exc}") from exc
    return bool(value)


def _eval(node: ast.AST, ctx: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, str, bool)) or node.value is None:
            return node.value
        raise ConditionError(f"unsupported constant type: {type(node.value).__name__}")

    if isinstance(node, ast.Name):
        if node.id in ctx:
            return ctx[node.id]
        # Treat ``True`` / ``False`` / ``None`` as identifiers in older
        # Python parsers (3.8+ uses Constant, but be defensive).
        if node.id == "True":
            return True
        if node.id == "False":
            return False
        if node.id == "None":
            return None
        raise ConditionError(f"unknown name in condition: {node.id!r}")

    if isinstance(node, ast.Attribute):
        target = _eval(node.value, ctx)
        return _lookup(target, node.attr, node)

    if isinstance(node, ast.Subscript):
        target = _eval(node.value, ctx)
        key = _eval(node.slice, ctx)
        return _lookup(target, key, node)

    if isinstance(node, ast.Compare):
        left = _eval(node.left, ctx)
        for op, right_node in zip(node.ops, node.comparators):
            right = _eval(right_node, ctx)
            op_type = type(op)
            if op_type not in _CMP_OPS:
                raise ConditionError(f"unsupported comparator: {op_type.__name__}")
            if not _CMP_OPS[op_type](left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for value_node in node.values:
                value = _eval(value_node, ctx)
                if not value:
                    return value
            return value
        if isinstance(node.op, ast.Or):
            for value_node in node.values:
                value = _eval(value_node, ctx)
                if value:
                    return value
            return value
        raise ConditionError(f"unsupported BoolOp: {type(node.op).__name__}")

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARY_OPS:
            raise ConditionError(f"unsupported unary op: {op_type.__name__}")
        return _UNARY_OPS[op_type](_eval(node.operand, ctx))

    if isinstance(node, ast.List):
        return [_eval(elt, ctx) for elt in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval(elt, ctx) for elt in node.elts)
    if isinstance(node, ast.Dict):
        return {
            _eval(k, ctx): _eval(v, ctx)
            for k, v in zip(node.keys, node.values)
            if k is not None
        }

    raise ConditionError(f"unsupported expression: {type(node).__name__}")


def _lookup(target: Any, key: Any, node: ast.AST) -> Any:
    """Resolve ``target[key]`` for dicts and attribute-style for namespaces.

    Lists / tuples are indexed with integer keys. Dicts are indexed by any
    hashable key. Anything else returns ``None`` instead of raising — the
    convention is "missing context is falsy".
    """
    if isinstance(target, dict):
        if key in target:
            return target[key]
        return None
    if isinstance(target, (list, tuple)):
        try:
            return target[int(key)]
        except (IndexError, TypeError, ValueError):
            return None
    # Anything else: be conservative and refuse — we don't want LLM-supplied
    # conditions to read user-defined Python attributes.
    raise ConditionError(
        f"cannot resolve {key!r} on {type(target).__name__} value at "
        f"line {getattr(node, 'lineno', '?')}"
    )


__all__ = ["ConditionError", "evaluate_condition"]
