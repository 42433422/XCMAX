"""Vue Single-File Component language adapter.

Splits a ``.vue`` file into ``<script>`` / ``<script setup>`` / ``<template>``
/ ``<style>`` blocks, then:

- Runs the :class:`TypeScriptLanguageAdapter` on the script section so all
  the function / class / type-alias / import detection comes for free.
- Walks the ``<template>`` for PascalCase (component-style) tags and emits
  them as ``"component_use"`` :class:`Symbol` records. This is what the
  agent's "find Foo's references" prompts use to surface "Foo is rendered
  in Page.vue".
- Tracks ``defineProps`` / ``defineEmits`` / ``defineExpose`` /
  ``useXxx()`` calls in the script section as :class:`Reference` records
  so refactors that rename a composable update every Vue file.
- Extracts the **named props / emits / slots** themselves as ``"prop"`` /
  ``"emit"`` / ``"slot"`` symbols. Refactors that rename a prop, an emit
  or a slot can then walk every Vue file with one query.
- Captures template event handlers (``@click="onLogin"``) and reactive
  bindings (``:value="user.name"``) as :class:`Reference` records so the
  index links the script-side handler to its template usage.

Zero external dependencies. The optional ``use_treesitter=True`` constructor
flag is accepted for API stability with the phase-2 tree-sitter
implementation.
"""

from __future__ import annotations

import re

from ..index import Reference, Symbol
from . import ParsedFile
from .typescript import TypeScriptLanguageAdapter

# ``re.DOTALL`` so the script body's newlines are captured.
_SCRIPT_BLOCK_RE = re.compile(
    r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_TEMPLATE_BLOCK_RE = re.compile(
    r"<template\b[^>]*>(?P<body>.*?)</template>",
    re.IGNORECASE | re.DOTALL,
)
# PascalCase component tags inside templates: <FooBar/>, <Foo Bar="…">. We
# require the second character to be lowercase to avoid matching uppercase
# HTML elements like <H1>.
_COMPONENT_TAG_RE = re.compile(
    r"<([A-Z][a-z][\w]*(?:-[\w]+)*)(?:[\s/>])",
    re.MULTILINE,
)
_USE_CALL_RE = re.compile(
    # Allow optional generic params (``defineProps<{...}>()``) between the
    # macro name and its call parens.
    r"\b(use[A-Z][\w]*|defineProps|defineEmits|defineExpose|defineModel)"
    r"\s*(?:<[^>(]*>\s*)?\(",
)

# Vue 3 ``defineProps`` macros — captures both the type-literal form and the
# runtime-array form so we can list every declared prop. Body matching is
# greedy-tolerant: we hand the body to a brace counter, not a single regex.
_DEFINE_PROPS_GENERIC_RE = re.compile(
    r"defineProps\s*<\s*\{(?P<body>.*?)\}\s*>\s*\(",
    re.DOTALL,
)
_DEFINE_PROPS_RUNTIME_ARRAY_RE = re.compile(
    r"defineProps\s*\(\s*(?:<[^>(]*>\s*)?\[(?P<body>.*?)\]",
    re.DOTALL,
)
_DEFINE_PROPS_RUNTIME_OBJECT_RE = re.compile(
    r"defineProps\s*\(\s*(?:<[^>(]*>\s*)?\{(?P<body>.*?)\}\s*\)",
    re.DOTALL,
)

_DEFINE_EMITS_GENERIC_RE = re.compile(
    r"defineEmits\s*<\s*\{(?P<body>.*?)\}\s*>\s*\(",
    re.DOTALL,
)
_DEFINE_EMITS_RUNTIME_ARRAY_RE = re.compile(
    r"defineEmits\s*\(\s*(?:<[^>(]*>\s*)?\[(?P<body>.*?)\]",
    re.DOTALL,
)

# Type-form emit signature: ``(e: 'submit', value: string): void``
_EMIT_TYPE_LINE_RE = re.compile(
    r"""\(\s*e\s*:\s*['"](?P<name>[^'"]+)['"]""",
    re.DOTALL,
)

# Prop type-form line: ``foo: string`` / ``foo?: number`` — inside the
# generic-form ``<{ ... }>`` body. We split on commas-/-newlines and pull
# the leading identifier so a body like ``label: string, count?: number``
# yields two props.
_PROP_TYPE_LINE_RE = re.compile(
    r"""(?P<name>[A-Za-z_$][\w$]*)\??\s*:""",
)

# String literal extractor for runtime-array forms like ``['foo', 'bar']``.
_STRING_LITERAL_RE = re.compile(r"""['"]([^'"]+)['"]""")

# ``<slot name="header" />`` — emits a Symbol so refactors that rename a
# slot can find every consumer. The default slot has ``name=""``.
_SLOT_TAG_RE = re.compile(
    r"""<slot
    (?P<attrs>[^>]*?)
    /?>
    """,
    re.IGNORECASE | re.VERBOSE,
)
_SLOT_NAME_RE = re.compile(r"""name\s*=\s*['"](?P<name>[^'"]+)['"]""")

# Template event handlers: ``@click="onLogin"`` / ``v-on:click="onLogin"``.
# We don't expand inline expressions, only bare identifiers — those are
# the ones a rename can safely propagate.
_EVENT_BIND_RE = re.compile(
    r"""(?:@|v-on:)
    (?P<event>[\w-]+)
    (?:\.[\w-]+)*
    \s*=\s*['"]
    (?P<expr>[^'"]+)
    ['"]
    """,
    re.VERBOSE,
)

# Identifier the binding ultimately calls. Picks ``onLogin`` out of
# ``onLogin``, ``onLogin($event)``, ``user.onLogin``, etc.
_BIND_IDENT_RE = re.compile(r"^[\s(]*([A-Za-z_$][\w$]*)")


class VueLanguageAdapter:
    """Vue SFC adapter (zero extra dependencies)."""

    _language_name = "vue"
    _extensions = (".vue",)

    def __init__(self, *, use_treesitter: bool = False) -> None:
        self._use_treesitter = bool(use_treesitter)
        self._ts = TypeScriptLanguageAdapter(use_treesitter=use_treesitter)

    @property
    def language(self) -> str:
        return self._language_name

    @property
    def extensions(self) -> tuple[str, ...]:
        return self._extensions

    def is_available(self) -> bool:
        return True

    def is_treesitter_available(self) -> bool:
        """Whether the Vue tree-sitter grammar can be loaded right now.

        The Vue adapter still uses regex even when tree-sitter is
        installed because a single ``.vue`` file mixes three different
        grammars (``<template>`` HTML, ``<script>`` TS, ``<style>``
        CSS). The boolean is exposed so callers / tests can decide
        whether to enable per-block tree-sitter parsing.
        """
        try:
            from .._tree_sitter import load_language
        except ImportError:
            return False
        return load_language("vue") is not None

    def parse(self, *, path: str, source: str) -> ParsedFile:
        if not source:
            return ParsedFile(language=self.language)

        symbols: list[Symbol] = []
        imports: list[str] = []
        references: list[Reference] = []
        parse_error = ""

        try:
            script_blocks = list(_SCRIPT_BLOCK_RE.finditer(source))
            for match in script_blocks:
                body = match.group("body")
                # Translate offsets so symbol line numbers point into the
                # ``.vue`` file rather than the extracted body.
                line_offset = source[: match.start("body")].count("\n")
                ts_pf = self._ts.parse(path=path, source=body)
                for sym in ts_pf.symbols:
                    sym.start_line += line_offset
                    sym.end_line += line_offset
                    symbols.append(sym)
                for ref in ts_pf.references:
                    ref.line += line_offset
                    references.append(ref)
                for imp in ts_pf.imports:
                    if imp not in imports:
                        imports.append(imp)
                # Vue 3 composables / macros — record as references.
                for m in _USE_CALL_RE.finditer(body):
                    line = body.count("\n", 0, m.start()) + 1 + line_offset
                    references.append(
                        Reference(
                            name=m.group(1),
                            file=path,
                            line=line,
                            column=0,
                            context="",
                        )
                    )
                # defineProps / defineEmits — extract the named props/emits
                # themselves so a refactor can target a single prop.
                symbols.extend(_extract_props(path, body, line_offset))
                symbols.extend(_extract_emits(path, body, line_offset))

            # Template: components, slots, event bindings.
            for tpl_match in _TEMPLATE_BLOCK_RE.finditer(source):
                body = tpl_match.group("body")
                line_offset = source[: tpl_match.start("body")].count("\n")
                seen_in_template: set[str] = set()
                for tag in _COMPONENT_TAG_RE.finditer(body):
                    name = tag.group(1)
                    if name in seen_in_template:
                        continue
                    seen_in_template.add(name)
                    line = body.count("\n", 0, tag.start()) + 1 + line_offset
                    symbols.append(
                        Symbol(
                            name=name,
                            kind="component_use",
                            file=path,
                            start_line=line,
                            end_line=line,
                            signature=f"<{name} />",
                            docstring="",
                            parent="",
                            exported=False,
                        )
                    )
                # <slot name="..."> or <slot/> → ``slot`` symbol.
                for slot_match in _SLOT_TAG_RE.finditer(body):
                    attrs = slot_match.group("attrs") or ""
                    name_m = _SLOT_NAME_RE.search(attrs)
                    slot_name = name_m.group("name") if name_m else "default"
                    line = body.count("\n", 0, slot_match.start()) + 1 + line_offset
                    symbols.append(
                        Symbol(
                            name=slot_name,
                            kind="slot",
                            file=path,
                            start_line=line,
                            end_line=line,
                            signature=f"<slot name={slot_name!r} />",
                            docstring="",
                            parent="",
                            exported=False,
                        )
                    )
                # ``@click="onLogin"`` → reference to ``onLogin``. We only
                # emit refs for bare identifiers; inline expressions
                # (``@click="count++"``) are skipped.
                for evt in _EVENT_BIND_RE.finditer(body):
                    expr = evt.group("expr").strip()
                    ident_m = _BIND_IDENT_RE.match(expr)
                    if not ident_m:
                        continue
                    ident = ident_m.group(1)
                    line = body.count("\n", 0, evt.start()) + 1 + line_offset
                    references.append(
                        Reference(
                            name=ident,
                            file=path,
                            line=line,
                            column=0,
                            context=evt.group(0),
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            parse_error = f"vue_parse_error:{type(exc).__name__}:{exc}"

        return ParsedFile(
            language=self.language,
            symbols=symbols,
            imports=imports,
            references=references,
            parse_error=parse_error,
        )


def _extract_props(path: str, body: str, line_offset: int) -> list[Symbol]:
    """Pull every prop name out of ``defineProps`` calls in ``body``.

    Three forms are recognised in priority order:

    1. ``defineProps<{ foo: string; bar?: number }>()`` — type literal.
    2. ``defineProps(['foo', 'bar'])`` — runtime array.
    3. ``defineProps({ foo: String, bar: { type: Number } })`` — runtime
       object. Keys at ``depth == 1`` are pulled as prop names.
    """
    out: list[Symbol] = []
    seen: set[str] = set()
    for m in _DEFINE_PROPS_GENERIC_RE.finditer(body):
        inner = m.group("body")
        for prop_match in _PROP_TYPE_LINE_RE.finditer(inner):
            name = prop_match.group("name")
            if name in seen:
                continue
            seen.add(name)
            line = body.count("\n", 0, m.start() + prop_match.start()) + 1 + line_offset
            out.append(
                Symbol(
                    name=name,
                    kind="prop",
                    file=path,
                    start_line=line,
                    end_line=line,
                    signature=f"prop {name}",
                    docstring="",
                    parent="",
                    exported=True,
                )
            )
    for m in _DEFINE_PROPS_RUNTIME_ARRAY_RE.finditer(body):
        inner = m.group("body")
        for s in _STRING_LITERAL_RE.finditer(inner):
            name = s.group(1)
            if name in seen:
                continue
            seen.add(name)
            line = body.count("\n", 0, m.start()) + 1 + line_offset
            out.append(
                Symbol(
                    name=name,
                    kind="prop",
                    file=path,
                    start_line=line,
                    end_line=line,
                    signature=f"prop {name}",
                    docstring="",
                    parent="",
                    exported=True,
                )
            )
    for m in _DEFINE_PROPS_RUNTIME_OBJECT_RE.finditer(body):
        inner = m.group("body")
        for name in _runtime_object_keys(inner):
            if name in seen:
                continue
            seen.add(name)
            line = body.count("\n", 0, m.start()) + 1 + line_offset
            out.append(
                Symbol(
                    name=name,
                    kind="prop",
                    file=path,
                    start_line=line,
                    end_line=line,
                    signature=f"prop {name}",
                    docstring="",
                    parent="",
                    exported=True,
                )
            )
    return out


def _extract_emits(path: str, body: str, line_offset: int) -> list[Symbol]:
    """Pull every emit name out of ``defineEmits`` calls in ``body``."""
    out: list[Symbol] = []
    seen: set[str] = set()
    for m in _DEFINE_EMITS_GENERIC_RE.finditer(body):
        inner = m.group("body")
        for sig in _EMIT_TYPE_LINE_RE.finditer(inner):
            name = sig.group("name")
            if name in seen:
                continue
            seen.add(name)
            line = body.count("\n", 0, m.start() + sig.start()) + 1 + line_offset
            out.append(
                Symbol(
                    name=name,
                    kind="emit",
                    file=path,
                    start_line=line,
                    end_line=line,
                    signature=f"emit {name!r}",
                    docstring="",
                    parent="",
                    exported=True,
                )
            )
    for m in _DEFINE_EMITS_RUNTIME_ARRAY_RE.finditer(body):
        inner = m.group("body")
        for s in _STRING_LITERAL_RE.finditer(inner):
            name = s.group(1)
            if name in seen:
                continue
            seen.add(name)
            line = body.count("\n", 0, m.start()) + 1 + line_offset
            out.append(
                Symbol(
                    name=name,
                    kind="emit",
                    file=path,
                    start_line=line,
                    end_line=line,
                    signature=f"emit {name!r}",
                    docstring="",
                    parent="",
                    exported=True,
                )
            )
    return out


def _runtime_object_keys(body: str) -> list[str]:
    """Return the top-level (depth-1) keys of a JS object literal body.

    Used for ``defineProps({ foo: String, bar: { type: Number } })``. The
    parser tracks ``{[(`` brace depth so nested objects don't pollute the
    output. Bare identifier keys and ``'string'`` keys are both honoured.
    """
    keys: list[str] = []
    depth = 0
    in_str = False
    quote = ""
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if in_str:
            if c == "\\" and i + 1 < n:
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
        if c in "{[(":
            depth += 1
            i += 1
            continue
        if c in "}])":
            depth -= 1
            i += 1
            continue
        if depth == 0:
            # Try to read ``ident :`` or ``"ident":`` at this position.
            m = re.match(r"\s*([A-Za-z_$][\w$]*|'[^']*'|\"[^\"]*\")\s*:", body[i:])
            if m:
                raw = m.group(1)
                if raw.startswith(("'", '"')):
                    raw = raw[1:-1]
                if raw not in keys:
                    keys.append(raw)
                i += m.end()
                continue
        i += 1
    return keys


__all__ = ["VueLanguageAdapter"]
