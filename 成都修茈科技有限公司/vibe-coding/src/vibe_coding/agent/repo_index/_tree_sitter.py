"""Shared tree-sitter infrastructure for higher-fidelity adapters.

When the ``agent-treesitter`` extra is installed, language adapters can
delegate parsing to a real grammar instead of the regex fallback. This
module:

1. Lazy-imports ``tree_sitter`` so the rest of the package stays
   zero-deps.
2. Caches loaded :class:`Language` and :class:`Parser` instances so
   repeated indexing doesn't reload grammars.
3. Provides a :class:`TreeSitterAdapter` base that subclasses extend
   with a :meth:`extract` method translating a parsed tree into the
   adapter's :class:`ParsedFile`.
4. Exposes :func:`load_language` so adapters / users can plug in
   custom grammars without a vibe-coding patch.

Grammar resolution is best-effort across the multiple shipping models
of tree-sitter for Python:

- Modern packages (``tree-sitter-python``, ``tree-sitter-typescript``,
  ``tree-sitter-vue``) expose a ``language()`` callable that returns
  a tree-sitter ``Language`` capsule.
- The legacy bundle path (one big ``Language.build_library`` shared
  object) is also detected when present.

Failures **never raise** at import time. They surface as
``is_available() → False`` so callers fall back to regex without
caller code knowing the difference.
"""

from __future__ import annotations

import importlib
import threading
from typing import Any, Callable, Iterable

# Lazy globals — populated by :func:`_init_treesitter` on first use.
_LOCK = threading.Lock()
_TS_MODULE: Any = None
_LANGUAGE_CACHE: dict[str, Any] = {}
_PARSER_CACHE: dict[str, Any] = {}


def is_treesitter_available() -> bool:
    """``True`` when the optional ``tree_sitter`` package is importable."""
    try:
        importlib.import_module("tree_sitter")
        return True
    except ImportError:
        return False


def _init_treesitter() -> Any:
    """Load and return the ``tree_sitter`` module, caching the lookup."""
    global _TS_MODULE
    if _TS_MODULE is not None:
        return _TS_MODULE
    _TS_MODULE = importlib.import_module("tree_sitter")
    return _TS_MODULE


# Common (package_name, callable_name) pairs we know about. Other vendors
# can extend the list at runtime via :func:`register_language_resolver`.
_DEFAULT_LANGUAGE_RESOLVERS: dict[str, list[tuple[str, str]]] = {
    "python": [("tree_sitter_python", "language")],
    "typescript": [
        ("tree_sitter_typescript", "language_typescript"),
        ("tree_sitter_typescript", "language_tsx"),
    ],
    "tsx": [
        ("tree_sitter_typescript", "language_tsx"),
    ],
    "javascript": [
        ("tree_sitter_javascript", "language"),
    ],
    "vue": [
        ("tree_sitter_vue", "language"),
    ],
}

_CUSTOM_RESOLVERS: dict[str, Callable[[], Any]] = {}


def register_language_resolver(name: str, resolver: Callable[[], Any]) -> None:
    """Register a custom resolver that returns a tree-sitter ``Language``.

    Useful for in-house grammars or vendored ``.so`` bundles. The
    resolver is called lazily; failures fall back to the built-in
    package list.
    """
    _CUSTOM_RESOLVERS[name] = resolver
    _LANGUAGE_CACHE.pop(name, None)
    _PARSER_CACHE.pop(name, None)


def load_language(name: str) -> Any | None:
    """Resolve the named language to a tree-sitter ``Language`` instance.

    Returns ``None`` when no grammar can be loaded — callers should
    fall back to their regex parser.
    """
    cached = _LANGUAGE_CACHE.get(name)
    if cached is not None:
        return cached
    if not is_treesitter_available():
        return None
    ts = _init_treesitter()
    Language = getattr(ts, "Language", None)
    if Language is None:  # pragma: no cover - very old tree_sitter
        return None
    with _LOCK:
        # Double-check after acquiring the lock.
        cached = _LANGUAGE_CACHE.get(name)
        if cached is not None:
            return cached

        candidates: list[Any] = []
        # 1. Custom resolver wins.
        custom = _CUSTOM_RESOLVERS.get(name)
        if custom is not None:
            try:
                candidates.append(custom())
            except Exception:  # noqa: BLE001
                pass
        # 2. Walk the default resolver table.
        for pkg_name, attr in _DEFAULT_LANGUAGE_RESOLVERS.get(name, []):
            try:
                module = importlib.import_module(pkg_name)
            except ImportError:
                continue
            attr_value = getattr(module, attr, None)
            if attr_value is None:
                continue
            try:
                value = attr_value() if callable(attr_value) else attr_value
            except Exception:  # noqa: BLE001
                continue
            candidates.append(value)
        for raw in candidates:
            language = _coerce_language(Language, raw)
            if language is not None:
                _LANGUAGE_CACHE[name] = language
                return language
    return None


def _coerce_language(Language: Any, raw: Any) -> Any | None:
    """Wrap ``raw`` into a tree-sitter ``Language`` if needed.

    Handles three return shapes seen in the wild:

    - Raw ``Language`` instance — return as-is.
    - PyCapsule pointer (``tree_sitter_python.language()``) — wrap with
      ``Language(capsule)``.
    - Integer pointer (older bindings) — same as the capsule case.
    """
    if raw is None:
        return None
    if isinstance(raw, Language):
        return raw
    try:
        return Language(raw)
    except Exception:  # noqa: BLE001
        return None


def get_parser(name: str) -> Any | None:
    """Return a cached :class:`tree_sitter.Parser` configured for ``name``."""
    cached = _PARSER_CACHE.get(name)
    if cached is not None:
        return cached
    language = load_language(name)
    if language is None:
        return None
    ts = _init_treesitter()
    Parser = getattr(ts, "Parser", None)
    if Parser is None:  # pragma: no cover
        return None
    parser = Parser()
    # Newer tree-sitter requires ``Parser(language)`` ctor; older accepts
    # ``set_language``. Try both.
    try:
        parser.language = language
    except Exception:  # noqa: BLE001
        try:
            parser.set_language(language)
        except Exception:  # noqa: BLE001
            try:
                parser = Parser(language)  # type: ignore[call-arg]
            except Exception:  # noqa: BLE001
                return None
    _PARSER_CACHE[name] = parser
    return parser


# ----------------------------------------------------------- adapter base


class TreeSitterAdapter:
    """Base class for tree-sitter-backed language adapters.

    Subclasses set :attr:`_language_name` / :attr:`_extensions` and
    implement :meth:`_extract_from_tree` to translate a parsed
    :class:`tree_sitter.Tree` into a :class:`ParsedFile`.

    The ``parse`` method auto-falls-back to the subclass's
    :meth:`_regex_parse` (when defined) if tree-sitter is unavailable
    or grammar loading fails — so callers always get a result.
    """

    _language_name: str = ""
    _extensions: tuple[str, ...] = ()

    @property
    def language(self) -> str:
        return self._language_name

    @property
    def extensions(self) -> tuple[str, ...]:
        return self._extensions

    @classmethod
    def is_treesitter_available(cls) -> bool:
        return is_treesitter_available() and load_language(cls._language_name) is not None

    def _treesitter_parse(self, source: str) -> Any | None:
        parser = get_parser(self._language_name)
        if parser is None:
            return None
        try:
            return parser.parse(source.encode("utf-8"))
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def iter_named_descendants(node: Any) -> Iterable[Any]:
        """Yield every named descendant of ``node`` in DFS order."""
        if node is None:
            return
        stack = [node]
        while stack:
            current = stack.pop()
            yield current
            for child in reversed(getattr(current, "named_children", [])):
                stack.append(child)

    @staticmethod
    def text_for(node: Any, source: bytes) -> str:
        """Pull the original source text covered by ``node``."""
        try:
            return source[node.start_byte : node.end_byte].decode(
                "utf-8", errors="replace"
            )
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def line_of(node: Any) -> int:
        """1-based start line for ``node``; 1 when unknown."""
        try:
            return int(getattr(node, "start_point", (0, 0))[0]) + 1
        except Exception:  # noqa: BLE001
            return 1


__all__ = [
    "TreeSitterAdapter",
    "get_parser",
    "is_treesitter_available",
    "load_language",
    "register_language_resolver",
]
