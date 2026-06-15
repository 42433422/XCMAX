"""Python language adapter for :class:`RepoIndex`.

Uses Python's built-in :mod:`ast` module — no external dependency. We extract:

- Module / class / function definitions (with signatures + docstrings)
- Top-level assignments (treated as ``"variable"`` symbols)
- Import statements (kept as a flat list of dotted names)
- Name and attribute references in callable positions (``foo()`` /
  ``obj.method()``) plus loaded names — enough for "where is X used?".

The adapter is **tolerant**: a syntax error doesn't stop indexing the rest of
the project; the offending file simply records ``parse_error`` and any
symbols/imports the partial parse already collected.
"""

from __future__ import annotations

import ast
from typing import Any

from . import LanguageAdapter, ParsedFile
from ..index import Reference, Symbol


class PythonLanguageAdapter:
    """Built-in :mod:`ast`-based adapter — zero external dependencies."""

    @property
    def language(self) -> str:
        return "python"

    @property
    def extensions(self) -> tuple[str, ...]:
        return (".py", ".pyi")

    def parse(self, *, path: str, source: str) -> ParsedFile:
        symbols: list[Symbol] = []
        imports: list[str] = []
        references: list[Reference] = []
        parse_error = ""

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return ParsedFile(
                language=self.language,
                symbols=symbols,
                imports=imports,
                references=references,
                parse_error=f"syntax_error:{exc.lineno}:{exc.msg}",
            )

        try:
            symbols = list(_extract_symbols(path, tree))
            imports = list(_extract_imports(tree))
            references = list(_extract_references(path, source, tree))
        except Exception as exc:  # noqa: BLE001 — adapter must stay tolerant
            parse_error = f"extract_error:{type(exc).__name__}:{exc}"

        return ParsedFile(
            language=self.language,
            symbols=symbols,
            imports=imports,
            references=references,
            parse_error=parse_error,
        )


# ---------------------------------------------------------------------- helpers


def _extract_symbols(path: str, tree: ast.AST) -> list[Symbol]:
    """Walk top-level + class members; emit a Symbol for each definition.

    Nested functions inside other functions are *not* indexed (they're
    typically helpers; surfacing them adds noise without much value). Class
    methods are indexed with ``parent`` set to the class name.
    """
    out: list[Symbol] = []

    if not isinstance(tree, ast.Module):
        return out

    module_doc = ast.get_docstring(tree) or ""
    if module_doc:
        out.append(
            Symbol(
                name="__module__",
                kind="module",
                file=path,
                start_line=1,
                end_line=1,
                signature="",
                docstring=module_doc.strip().splitlines()[0] if module_doc.strip() else "",
                parent="",
            )
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(_function_symbol(path, node, parent=""))
        elif isinstance(node, ast.ClassDef):
            out.append(_class_symbol(path, node))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append(_function_symbol(path, sub, parent=node.name))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            out.extend(_assignment_symbols(path, node))

    return out


def _function_symbol(
    path: str, node: ast.FunctionDef | ast.AsyncFunctionDef, *, parent: str
) -> Symbol:
    sig = _format_signature(node)
    doc = (ast.get_docstring(node) or "").strip()
    first_line = doc.splitlines()[0] if doc else ""
    is_private = node.name.startswith("_")
    kind = "method" if parent else ("async_function" if isinstance(node, ast.AsyncFunctionDef) else "function")
    return Symbol(
        name=node.name,
        kind=kind,
        file=path,
        start_line=node.lineno,
        end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
        signature=sig,
        docstring=first_line,
        parent=parent,
        exported=not is_private,
    )


def _class_symbol(path: str, node: ast.ClassDef) -> Symbol:
    bases: list[str] = []
    for base in node.bases:
        try:
            bases.append(ast.unparse(base))
        except Exception:  # noqa: BLE001
            bases.append("?")
    sig = f"class {node.name}" + (f"({', '.join(bases)})" if bases else "")
    doc = (ast.get_docstring(node) or "").strip()
    first_line = doc.splitlines()[0] if doc else ""
    return Symbol(
        name=node.name,
        kind="class",
        file=path,
        start_line=node.lineno,
        end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
        signature=sig,
        docstring=first_line,
        parent="",
        exported=not node.name.startswith("_"),
    )


def _assignment_symbols(path: str, node: ast.AST) -> list[Symbol]:
    targets: list[str] = []
    if isinstance(node, ast.Assign):
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                targets.append(tgt.id)
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        targets.append(node.target.id)
    out: list[Symbol] = []
    for name in targets:
        if name.isupper() or not name.startswith("_"):
            out.append(
                Symbol(
                    name=name,
                    kind="constant" if name.isupper() else "variable",
                    file=path,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
                    signature="",
                    docstring="",
                    parent="",
                    exported=not name.startswith("_"),
                )
            )
    return out


def _format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = node.args
    parts: list[str] = []
    pos_count = len(args.posonlyargs) + len(args.args)
    defaults = list(args.defaults)
    pad = pos_count - len(defaults)
    flat = list(args.posonlyargs) + list(args.args)
    for idx, arg in enumerate(flat):
        ann = f": {_unparse(arg.annotation)}" if arg.annotation else ""
        default = ""
        if idx >= pad:
            default = f" = {_unparse(defaults[idx - pad])}"
        parts.append(f"{arg.arg}{ann}{default}")
    if args.posonlyargs:
        parts.insert(len(args.posonlyargs), "/")
    if args.vararg:
        ann = f": {_unparse(args.vararg.annotation)}" if args.vararg.annotation else ""
        parts.append(f"*{args.vararg.arg}{ann}")
    elif args.kwonlyargs:
        parts.append("*")
    for kwarg, kdef in zip(args.kwonlyargs, args.kw_defaults):
        ann = f": {_unparse(kwarg.annotation)}" if kwarg.annotation else ""
        default = f" = {_unparse(kdef)}" if kdef is not None else ""
        parts.append(f"{kwarg.arg}{ann}{default}")
    if args.kwarg:
        ann = f": {_unparse(args.kwarg.annotation)}" if args.kwarg.annotation else ""
        parts.append(f"**{args.kwarg.arg}{ann}")
    ret = f" -> {_unparse(node.returns)}" if node.returns else ""
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    return f"{prefix}{node.name}({', '.join(parts)}){ret}"


def _unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001
        return "?"


def _extract_imports(tree: ast.AST) -> list[str]:
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    out.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = "." * (node.level or 0)
            if module:
                out.append(f"{level}{module}")
            elif level:
                out.append(level)
    return sorted(dict.fromkeys(out))


def _extract_references(path: str, source: str, tree: ast.AST) -> list[Reference]:
    lines = source.splitlines()
    out: list[Reference] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = _call_name(node.func)
            if target:
                lineno = getattr(node, "lineno", 1)
                out.append(
                    Reference(
                        name=target,
                        file=path,
                        line=lineno,
                        column=getattr(node, "col_offset", 0),
                        context=_line_context(lines, lineno),
                    )
                )
    return out


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        head = _call_name(func.value)
        return f"{head}.{func.attr}" if head else func.attr
    return ""


def _line_context(lines: list[str], lineno: int) -> str:
    if lineno < 1 or lineno > len(lines):
        return ""
    snippet = lines[lineno - 1].strip()
    return snippet[:200]


__all__ = ["PythonLanguageAdapter"]


# Provide ``Any`` re-export for type hints in ParsedFile (avoids circular import).
_ = Any
