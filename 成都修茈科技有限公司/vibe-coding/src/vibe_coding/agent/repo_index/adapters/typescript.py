"""TypeScript / TSX language adapter.

Two implementation tiers, transparent to callers:

1. **Regex-based (default).** No external dependency. Covers the symbols
   that matter for the agent's "where is X used?" prompts:

   - ``function``, ``async function`` declarations
   - ``const``/``let``/``var`` arrow function bindings
   - ``class``, ``interface``, ``type``, ``enum`` declarations
   - ``import { … } from 'mod'`` / ``import 'mod'`` / ``require('mod')``
   - ``export { foo } from 'mod'`` re-exports (P2)
   - ``export default function/class`` (with implicit name "default")
   - ``@Decorator`` references (P2 — TypeScript decorators / experimental)
   - ``<Component prop>`` JSX usages emitted as ``component_use`` symbols
     so React/Solid/Preact projects show component graphs (P2)
   - Class methods (best-effort; one indent level)
   - Top-level call references (``foo()`` / ``obj.method()``)

2. **tree-sitter (opt-in).** When the ``agent-treesitter`` extra is
   installed AND ``use_treesitter=True`` is passed, we delegate to a
   tree-sitter grammar for full fidelity (handles JSX, decorators,
   computed property names …). The default stays regex-based so the
   common case keeps zero extra deps.

The regex parser is intentionally tolerant — partial output is preferred
over raising. The :class:`ParsedFile.parse_error` field carries any
diagnostics so callers can surface them when needed.
"""

from __future__ import annotations

import re
from typing import Any

from ..index import Reference, Symbol
from . import ParsedFile

# Compiled patterns. Multiline so ``^`` matches start-of-line; verbose so
# the regex stays readable.

_FUNCTION_RE = re.compile(
    r"""^[ \t]*
    (?P<export>export\s+(?:default\s+)?)?
    (?P<async>async\s+)?
    function\s*\*?\s+
    (?P<name>[A-Za-z_$][\w$]*)\s*
    (?:<[^>]*>)?\s*
    \(
    """,
    re.MULTILINE | re.VERBOSE,
)

_ARROW_RE = re.compile(
    r"""^[ \t]*
    (?P<export>export\s+(?:default\s+)?)?
    (?:const|let|var)\s+
    (?P<name>[A-Za-z_$][\w$]*)\s*
    (?::\s*[^=]+)?         # optional type annotation
    =\s*
    (?P<async>async\s+)?
    (?:
        (?:<[^>]*>\s*)?     # optional generic params
        \([^)]*\)\s*
        (?::\s*[^=]+\s*)?
        =>
        |
        function\s*\*?\s*\([^)]*\)
    )
    """,
    re.MULTILINE | re.VERBOSE,
)

_CLASS_RE = re.compile(
    r"""^[ \t]*
    (?P<export>export\s+(?:default\s+)?)?
    (?P<abstract>abstract\s+)?
    (?P<kind>class|interface|enum)\s+
    (?P<name>[A-Za-z_$][\w$]*)
    (?:\s*<[^>]*>)?
    """,
    re.MULTILINE | re.VERBOSE,
)

_TYPE_ALIAS_RE = re.compile(
    r"""^[ \t]*
    (?P<export>export\s+)?
    type\s+
    (?P<name>[A-Za-z_$][\w$]*)
    (?:\s*<[^>]*>)?
    \s*=
    """,
    re.MULTILINE | re.VERBOSE,
)

_IMPORT_FROM_RE = re.compile(
    r"""^\s*
    import\s+
    (?:type\s+)?
    (?:[^'"\n]+\s+from\s+)?
    ['"](?P<mod>[^'"]+)['"]
    """,
    re.MULTILINE | re.VERBOSE,
)

_REQUIRE_RE = re.compile(r"""require\s*\(\s*['"](?P<mod>[^'"]+)['"]\s*\)""")

_DYNAMIC_IMPORT_RE = re.compile(r"""import\s*\(\s*['"](?P<mod>[^'"]+)['"]\s*\)""")

# ``export { foo } from 'mod'`` / ``export * from 'mod'`` re-exports. Picked
# up so the index records the dependency even when nothing local is imported.
_REEXPORT_RE = re.compile(
    r"""^[ \t]*
    export\s+
    (?:type\s+)?
    (?:\*|\{[^}]*\})\s+
    from\s+
    ['"](?P<mod>[^'"]+)['"]
    """,
    re.MULTILINE | re.VERBOSE,
)

# ``export default function foo() {}`` / ``export default class Foo {}``
# / ``export default function () {}`` / ``export default Foo`` — first three
# branches give us an extractable name; the last leaves ``name == "default"``.
_DEFAULT_FN_RE = re.compile(
    r"""^[ \t]*
    export\s+default\s+
    (?P<async>async\s+)?
    function\s*\*?\s*
    (?P<name>[A-Za-z_$][\w$]*)?
    \s*\(
    """,
    re.MULTILINE | re.VERBOSE,
)
_DEFAULT_CLASS_RE = re.compile(
    r"""^[ \t]*
    export\s+default\s+
    (?P<abstract>abstract\s+)?
    class\s+
    (?P<name>[A-Za-z_$][\w$]*)?
    """,
    re.MULTILINE | re.VERBOSE,
)

# ``@Component({...})`` TypeScript decorators (Angular, NestJS, class-validator
# etc). Emitted as :class:`Reference` so refactors that rename a decorator
# also surface every usage site.
_DECORATOR_RE = re.compile(
    r"""(?<![A-Za-z0-9_$.])
    @(?P<name>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)
    (?=\s*[\(\n])
    """,
    re.MULTILINE | re.VERBOSE,
)

# JSX tag uses: ``<FooBar prop>`` / ``<Foo.Bar>`` / ``<F />``. The first
# character must be uppercase (component) and the second lowercase or
# dot to avoid matching HTML tags like ``<H1>`` or ``<TR>``. Self-closing
# and namespaced/qualified components (``Foo.Bar``) are both allowed.
_JSX_TAG_RE = re.compile(
    r"""<
    (?P<name>[A-Z][a-zA-Z0-9_$]*(?:\.[A-Z][a-zA-Z0-9_$]*)*)
    (?=[\s/>])
    """,
    re.VERBOSE,
)

_METHOD_RE = re.compile(
    r"""^[ \t]+
    (?:public\s+|private\s+|protected\s+|static\s+|readonly\s+|async\s+|abstract\s+)*
    (?P<name>[A-Za-z_$][\w$]*)\s*
    (?:<[^>]*>)?\s*
    \([^)]*\)\s*
    (?::\s*[^{]+)?
    \s*\{
    """,
    re.MULTILINE | re.VERBOSE,
)

# Reserved words we should never treat as method names (helps strip
# false positives like ``if (x) { … }``).
_RESERVED = frozenset(
    {
        "if", "else", "for", "while", "switch", "catch", "do", "try",
        "return", "throw", "new", "typeof", "instanceof", "void", "case",
        "default", "in", "of", "delete", "yield", "await", "this",
        "import", "export", "from", "as", "function", "class", "interface",
        "type", "enum", "extends", "implements", "readonly", "constructor",
    }
)

_CALL_RE = re.compile(r"""(?<![\w$.])([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(""")


class TypeScriptLanguageAdapter:
    """Regex-based TypeScript / TSX adapter (no extra dependencies)."""

    _language_name = "typescript"
    _extensions = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")

    def __init__(self, *, use_treesitter: bool = False) -> None:
        self._use_treesitter = bool(use_treesitter)
        self._ts_adapter = None  # lazy

    @property
    def language(self) -> str:
        return self._language_name

    @property
    def extensions(self) -> tuple[str, ...]:
        return self._extensions

    def is_available(self) -> bool:
        if not self._use_treesitter:
            return True
        try:
            import tree_sitter  # noqa: F401

            return True
        except ImportError:
            return False

    def parse(self, *, path: str, source: str) -> ParsedFile:
        if self._use_treesitter:
            try:
                return self._parse_with_treesitter(path=path, source=source)
            except Exception as exc:  # noqa: BLE001
                # Fall through to regex parser; record the failure.
                ts_err = f"treesitter_failed:{type(exc).__name__}:{exc}"
                pf = self._parse_with_regex(path=path, source=source)
                pf.parse_error = (
                    f"{pf.parse_error}|{ts_err}" if pf.parse_error else ts_err
                )
                return pf
        return self._parse_with_regex(path=path, source=source)

    def is_treesitter_available(self) -> bool:
        """Whether the optional tree-sitter grammar can be loaded right now."""
        try:
            from .._tree_sitter import load_language
        except ImportError:
            return False
        return load_language("typescript") is not None

    # ----------------------------------------------------------------- regex

    def _parse_with_regex(self, *, path: str, source: str) -> ParsedFile:
        symbols: list[Symbol] = []
        imports: list[str] = []
        references: list[Reference] = []
        parse_error = ""

        if not source:
            return ParsedFile(language=self.language)

        source_no_comments = _strip_ts_comments(source)
        lines = source_no_comments.splitlines()
        is_jsx = path.endswith((".tsx", ".jsx"))

        try:
            symbols.extend(_extract_top_level_symbols(path, source_no_comments, lines))
            symbols.extend(_extract_default_exports(path, source_no_comments, lines))
            symbols.extend(_extract_class_methods(path, source_no_comments, lines))
            if is_jsx:
                symbols.extend(_extract_jsx_components(path, source_no_comments, lines))
            imports = _extract_imports(source_no_comments)
            references = _extract_call_references(path, source_no_comments, lines)
            references.extend(_extract_decorators(path, source_no_comments, lines))
        except Exception as exc:  # noqa: BLE001
            parse_error = f"regex_extract_error:{type(exc).__name__}:{exc}"

        return ParsedFile(
            language=self.language,
            symbols=symbols,
            imports=imports,
            references=references,
            parse_error=parse_error,
        )

    # ------------------------------------------------------------- treesitter

    def _parse_with_treesitter(self, *, path: str, source: str) -> ParsedFile:
        """Parse via the tree-sitter ``typescript`` / ``tsx`` grammar.

        We pick the grammar variant from the file extension (``.tsx``
        / ``.jsx`` use the JSX-aware grammar). When the grammar fails
        to load we let the caller fall back to regex; there's no point
        re-implementing the regex path here.
        """
        from .._tree_sitter import get_parser, load_language

        is_jsx = path.endswith((".tsx", ".jsx"))
        grammar = "tsx" if is_jsx else "typescript"
        parser = get_parser(grammar)
        if parser is None:
            # ``tsx`` grammar may be packaged separately; fall back to
            # the plain ``typescript`` grammar before giving up.
            parser = get_parser("typescript")
        if parser is None or load_language(grammar) is None and load_language("typescript") is None:
            raise RuntimeError(
                "tree-sitter typescript grammar not available; "
                "install with `pip install tree-sitter-typescript`"
            )
        tree = parser.parse(source.encode("utf-8"))
        symbols, imports, references = _extract_from_tree(
            tree, source.encode("utf-8"), path=path, is_jsx=is_jsx
        )
        return ParsedFile(
            language=self.language,
            symbols=symbols,
            imports=imports,
            references=references,
        )


# ---------------------------------------------------------------------- helpers


def _strip_ts_comments(text: str) -> str:
    """Remove ``//`` and ``/* … */`` comments while preserving string spans.

    Borrowed in spirit from :func:`vibe_coding.nl.parsing._strip_comments`
    but stays inline so the adapter has no cross-package import.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    in_str = False
    quote = ""
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\" and i + 1 < n:
                out.append(c)
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                in_str = False
            out.append(c)
            i += 1
            continue
        if c in '"\'`':
            in_str = True
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                end = text.find("\n", i + 2)
                if end < 0:
                    return "".join(out)
                # Keep newline so line numbers stay roughly aligned.
                out.append("\n")
                i = end + 1
                continue
            if nxt == "*":
                end = text.find("*/", i + 2)
                if end < 0:
                    return "".join(out)
                # Replace block with equivalent number of newlines so
                # downstream line numbers don't shift.
                block = text[i : end + 2]
                out.append("\n" * block.count("\n"))
                i = end + 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _line_for_offset(text: str, offset: int) -> int:
    """Convert a string offset to a 1-based line number."""
    return text.count("\n", 0, offset) + 1


def _extract_top_level_symbols(path: str, source: str, lines: list[str]) -> list[Symbol]:
    out: list[Symbol] = []
    seen: set[tuple[str, int]] = set()
    for match in _FUNCTION_RE.finditer(source):
        line = _line_for_offset(source, match.start())
        name = match.group("name")
        key = (name, line)
        if key in seen:
            continue
        seen.add(key)
        kind = "async_function" if match.group("async") else "function"
        out.append(
            Symbol(
                name=name,
                kind=kind,
                file=path,
                start_line=line,
                end_line=line,
                signature=lines[line - 1].strip()[:200] if line - 1 < len(lines) else "",
                docstring="",
                parent="",
                exported=bool(match.group("export")),
            )
        )
    for match in _ARROW_RE.finditer(source):
        line = _line_for_offset(source, match.start())
        name = match.group("name")
        key = (name, line)
        if key in seen:
            continue
        seen.add(key)
        kind = "async_function" if match.group("async") else "function"
        out.append(
            Symbol(
                name=name,
                kind=kind,
                file=path,
                start_line=line,
                end_line=line,
                signature=lines[line - 1].strip()[:200] if line - 1 < len(lines) else "",
                docstring="",
                parent="",
                exported=bool(match.group("export")),
            )
        )
    for match in _CLASS_RE.finditer(source):
        line = _line_for_offset(source, match.start())
        name = match.group("name")
        kind = match.group("kind")
        key = (name, line)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Symbol(
                name=name,
                kind=kind,
                file=path,
                start_line=line,
                end_line=line,
                signature=lines[line - 1].strip()[:200] if line - 1 < len(lines) else "",
                docstring="",
                parent="",
                exported=bool(match.group("export")),
            )
        )
    for match in _TYPE_ALIAS_RE.finditer(source):
        line = _line_for_offset(source, match.start())
        name = match.group("name")
        key = (name, line)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Symbol(
                name=name,
                kind="type_alias",
                file=path,
                start_line=line,
                end_line=line,
                signature=lines[line - 1].strip()[:200] if line - 1 < len(lines) else "",
                docstring="",
                parent="",
                exported=bool(match.group("export")),
            )
        )
    return out


def _extract_class_methods(path: str, source: str, lines: list[str]) -> list[Symbol]:
    """Best-effort: methods are extracted per-class via brace tracking.

    For each class declaration, find its opening ``{`` then scan forward
    counting braces until depth returns to zero. Inside that span, every
    indented identifier followed by ``(...)`` and ``{`` is treated as a
    method. False positives on ``if (cond) {`` are filtered via the
    reserved-word list.
    """
    out: list[Symbol] = []
    for class_match in _CLASS_RE.finditer(source):
        if class_match.group("kind") != "class":
            continue
        cls_name = class_match.group("name")
        body_start = source.find("{", class_match.end())
        if body_start < 0:
            continue
        depth = 0
        i = body_start
        in_str = False
        quote = ""
        while i < len(source):
            c = source[i]
            if in_str:
                if c == "\\" and i + 1 < len(source):
                    i += 2
                    continue
                if c == quote:
                    in_str = False
                i += 1
                continue
            if c in '"\'`':
                in_str = True
                quote = c
                i += 1
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    body_end = i
                    break
            i += 1
        else:
            body_end = len(source)
        body = source[body_start + 1 : body_end]
        body_offset = body_start + 1
        for m in _METHOD_RE.finditer(body):
            name = m.group("name")
            if name in _RESERVED:
                continue
            line = _line_for_offset(source, body_offset + m.start())
            out.append(
                Symbol(
                    name=name,
                    kind="method",
                    file=path,
                    start_line=line,
                    end_line=line,
                    signature=lines[line - 1].strip()[:200] if line - 1 < len(lines) else "",
                    docstring="",
                    parent=cls_name,
                    exported=not name.startswith("_"),
                )
            )
    return out


def _extract_imports(source: str) -> list[str]:
    seen: list[str] = []
    for m in _IMPORT_FROM_RE.finditer(source):
        mod = m.group("mod")
        if mod and mod not in seen:
            seen.append(mod)
    for m in _REQUIRE_RE.finditer(source):
        mod = m.group("mod")
        if mod and mod not in seen:
            seen.append(mod)
    for m in _DYNAMIC_IMPORT_RE.finditer(source):
        mod = m.group("mod")
        if mod and mod not in seen:
            seen.append(mod)
    for m in _REEXPORT_RE.finditer(source):
        mod = m.group("mod")
        if mod and mod not in seen:
            seen.append(mod)
    return seen


def _extract_default_exports(path: str, source: str, lines: list[str]) -> list[Symbol]:
    """Capture ``export default function/class`` plus their (optional) name.

    The fallback name ``"default"`` is intentionally re-exposed so that a
    refactor walking the index can still find the symbol — our hunk-based
    differ matches by anchor + text rather than name, so the name only
    needs to be deterministic.
    """
    out: list[Symbol] = []
    for match in _DEFAULT_FN_RE.finditer(source):
        line = _line_for_offset(source, match.start())
        name = match.group("name") or "default"
        kind = "async_function" if match.group("async") else "function"
        out.append(
            Symbol(
                name=name,
                kind=kind,
                file=path,
                start_line=line,
                end_line=line,
                signature=lines[line - 1].strip()[:200] if line - 1 < len(lines) else "",
                docstring="",
                parent="",
                exported=True,
            )
        )
    for match in _DEFAULT_CLASS_RE.finditer(source):
        line = _line_for_offset(source, match.start())
        name = match.group("name") or "default"
        out.append(
            Symbol(
                name=name,
                kind="class",
                file=path,
                start_line=line,
                end_line=line,
                signature=lines[line - 1].strip()[:200] if line - 1 < len(lines) else "",
                docstring="",
                parent="",
                exported=True,
            )
        )
    return out


def _extract_jsx_components(path: str, source: str, lines: list[str]) -> list[Symbol]:
    """Emit a ``component_use`` :class:`Symbol` for each PascalCase JSX tag.

    JSX-only — guarded by extension so plain ``.ts`` files don't get
    polluted with TypeScript generic syntax (``<T>``) that happens to
    look JSX-like.
    """
    out: list[Symbol] = []
    seen: set[tuple[str, int]] = set()
    for match in _JSX_TAG_RE.finditer(source):
        name = match.group("name")
        if name.split(".")[0] in _RESERVED:
            continue
        line = _line_for_offset(source, match.start())
        key = (name, line)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Symbol(
                name=name,
                kind="component_use",
                file=path,
                start_line=line,
                end_line=line,
                signature=lines[line - 1].strip()[:200] if line - 1 < len(lines) else "",
                docstring="",
                parent="",
                exported=False,
            )
        )
    return out


def _extract_decorators(path: str, source: str, lines: list[str]) -> list[Reference]:
    """Pick up ``@Decorator`` references (Angular / NestJS / class-validator)."""
    out: list[Reference] = []
    for match in _DECORATOR_RE.finditer(source):
        name = match.group("name")
        if not name:
            continue
        if name.split(".")[0] in _RESERVED:
            continue
        line = _line_for_offset(source, match.start())
        snippet = lines[line - 1].strip()[:200] if line - 1 < len(lines) else ""
        out.append(
            Reference(
                name=name,
                file=path,
                line=line,
                column=max(0, match.start() - source.rfind("\n", 0, match.start()) - 1),
                context=snippet,
            )
        )
    return out


def _extract_call_references(path: str, source: str, lines: list[str]) -> list[Reference]:
    out: list[Reference] = []
    for m in _CALL_RE.finditer(source):
        name = m.group(1)
        if name.split(".")[0] in _RESERVED:
            continue
        line = _line_for_offset(source, m.start())
        snippet = lines[line - 1].strip()[:200] if line - 1 < len(lines) else ""
        out.append(
            Reference(
                name=name,
                file=path,
                line=line,
                column=m.start() - source.rfind("\n", 0, m.start()) - 1,
                context=snippet,
            )
        )
    return out


# --------------------------------------------------------- tree-sitter glue


def _extract_from_tree(
    tree: Any,
    source_bytes: bytes,
    *,
    path: str,
    is_jsx: bool,
) -> tuple[list[Symbol], list[str], list[Reference]]:
    """Walk a tree-sitter Tree → ``(symbols, imports, references)``.

    The walker is intentionally tolerant — unknown node types are
    skipped silently. This keeps adapter behaviour stable across
    grammar version bumps.
    """
    symbols: list[Symbol] = []
    imports: list[str] = []
    references: list[Reference] = []
    seen_imports: set[str] = set()

    def text(node: Any) -> str:
        try:
            return source_bytes[node.start_byte : node.end_byte].decode(
                "utf-8", errors="replace"
            )
        except Exception:  # noqa: BLE001
            return ""

    def line_of(node: Any) -> int:
        try:
            return int(node.start_point[0]) + 1
        except Exception:  # noqa: BLE001
            return 1

    def child_field(node: Any, field: str) -> Any | None:
        # tree-sitter exposes ``child_by_field_name`` on nodes.
        try:
            return node.child_by_field_name(field)
        except Exception:  # noqa: BLE001
            return None

    def named_children(node: Any) -> list[Any]:
        return list(getattr(node, "named_children", []))

    # Build a nested index of nodes → parent class so methods can attribute.
    class_stack: list[str] = []

    def emit_symbol(node: Any, name: str, kind: str, *, parent: str = "", exported: bool = True) -> None:
        signature = text(node).strip().splitlines()[0][:200] if node else ""
        symbols.append(
            Symbol(
                name=name,
                kind=kind,
                file=path,
                start_line=line_of(node),
                end_line=int(getattr(node, "end_point", (line_of(node) - 1, 0))[0]) + 1,
                signature=signature,
                docstring="",
                parent=parent,
                exported=exported,
            )
        )

    def emit_reference(node: Any, name: str) -> None:
        references.append(
            Reference(
                name=name,
                file=path,
                line=line_of(node),
                column=int(getattr(node, "start_point", (0, 0))[1]),
                context=text(node)[:200],
            )
        )

    root = tree.root_node

    def walk(node: Any) -> None:
        ntype = node.type

        if ntype in {"function_declaration", "generator_function_declaration"}:
            name_node = child_field(node, "name")
            if name_node is not None:
                emit_symbol(node, text(name_node), "function")
        elif ntype == "class_declaration":
            name_node = child_field(node, "name")
            if name_node is not None:
                cls_name = text(name_node)
                emit_symbol(node, cls_name, "class")
                class_stack.append(cls_name)
                body = child_field(node, "body")
                if body is not None:
                    for child in named_children(body):
                        walk(child)
                class_stack.pop()
                return
        elif ntype == "interface_declaration":
            name_node = child_field(node, "name")
            if name_node is not None:
                emit_symbol(node, text(name_node), "interface")
        elif ntype == "enum_declaration":
            name_node = child_field(node, "name")
            if name_node is not None:
                emit_symbol(node, text(name_node), "enum")
        elif ntype == "type_alias_declaration":
            name_node = child_field(node, "name")
            if name_node is not None:
                emit_symbol(node, text(name_node), "type_alias")
        elif ntype == "method_definition":
            name_node = child_field(node, "name")
            if name_node is not None:
                parent = class_stack[-1] if class_stack else ""
                method_name = text(name_node)
                if method_name not in _RESERVED:
                    emit_symbol(
                        node,
                        method_name,
                        "method",
                        parent=parent,
                        exported=not method_name.startswith("_"),
                    )
        elif ntype == "lexical_declaration" or ntype == "variable_declaration":
            for declarator in named_children(node):
                if declarator.type != "variable_declarator":
                    continue
                name_node = child_field(declarator, "name")
                value = child_field(declarator, "value")
                if name_node is not None and value is not None and value.type in {
                    "arrow_function",
                    "function_expression",
                    "generator_function",
                }:
                    is_async = "async" in text(value)[:8]
                    emit_symbol(
                        declarator,
                        text(name_node),
                        "async_function" if is_async else "function",
                    )
        elif ntype == "import_statement":
            src_node = child_field(node, "source") or _last_string_child(node)
            if src_node is not None:
                module = text(src_node).strip("'\"`")
                if module and module not in seen_imports:
                    seen_imports.add(module)
                    imports.append(module)
        elif ntype == "export_statement":
            src_node = child_field(node, "source")
            if src_node is not None:
                module = text(src_node).strip("'\"`")
                if module and module not in seen_imports:
                    seen_imports.add(module)
                    imports.append(module)
            # ``export default function/class`` shows the inner declaration as a child.
            for child in named_children(node):
                if child.type in {"function_declaration", "class_declaration"}:
                    walk(child)
                if child.type in {"function", "class"}:
                    name_node = child_field(child, "name")
                    fallback = "default"
                    chosen = text(name_node) if name_node is not None else fallback
                    kind = "class" if child.type == "class" else "function"
                    emit_symbol(node, chosen, kind, exported=True)
        elif ntype == "decorator":
            ident = _decorator_name_node(node)
            if ident is not None:
                emit_reference(node, text(ident))
        elif ntype == "call_expression":
            fn_node = child_field(node, "function")
            if fn_node is not None:
                name = text(fn_node).split("(", 1)[0].strip()
                if name and name.split(".")[0] not in _RESERVED:
                    emit_reference(node, name)
        elif ntype == "jsx_element" or ntype == "jsx_self_closing_element":
            tag_node = (
                child_field(node, "opening_element") or node
            )
            name_node = child_field(tag_node, "name") or _first_named(tag_node)
            if name_node is not None:
                tag_name = text(name_node)
                head = tag_name.split(".")[0]
                if head and head[0].isupper() and head not in _RESERVED:
                    emit_symbol(node, tag_name, "component_use", exported=False)

        for child in named_children(node):
            walk(child)

    walk(root)
    return symbols, imports, references


def _last_string_child(node: Any) -> Any | None:
    last: Any | None = None
    for child in getattr(node, "named_children", []):
        if "string" in child.type:
            last = child
    return last


def _first_named(node: Any) -> Any | None:
    children = getattr(node, "named_children", [])
    return children[0] if children else None


def _decorator_name_node(node: Any) -> Any | None:
    for child in getattr(node, "named_children", []):
        if child.type in {
            "identifier",
            "member_expression",
            "call_expression",
            "type_identifier",
        }:
            if child.type == "call_expression":
                fn_field = None
                try:
                    fn_field = child.child_by_field_name("function")
                except Exception:  # noqa: BLE001
                    fn_field = None
                return fn_field or child
            return child
    return None


__all__ = ["TypeScriptLanguageAdapter"]
