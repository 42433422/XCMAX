"""Tests for the optional tree-sitter integration.

Two layers are exercised:

1. Loader robustness — :func:`load_language` / :func:`get_parser` should
   return ``None`` (rather than raising) when the grammar is not
   installed, so the regex fallback always kicks in.
2. Parity check — when tree-sitter *is* installed, the adapter
   produces a non-empty :class:`ParsedFile` and the resulting symbol
   names match (or supersede) the regex output. We don't require an
   exact match because tree-sitter sees richer node types.
"""

from __future__ import annotations

import textwrap

import pytest

from vibe_coding.agent.repo_index import TypeScriptLanguageAdapter
from vibe_coding.agent.repo_index._tree_sitter import (
    is_treesitter_available,
    load_language,
    register_language_resolver,
)


# ----------------------------------------------------- loader robustness


def test_is_treesitter_available_is_a_bool() -> None:
    assert isinstance(is_treesitter_available(), bool)


def test_load_language_returns_none_for_unknown() -> None:
    assert load_language("totally-not-a-real-language") is None


def test_register_custom_resolver_overrides_default() -> None:
    sentinel: list[bool] = []

    def custom():
        sentinel.append(True)
        raise RuntimeError("not actually building a grammar")

    register_language_resolver("vibe-test-grammar", custom)
    # The loader is allowed to short-circuit when ``tree_sitter`` itself
    # isn't installed (the resolver couldn't produce a valid Language
    # anyway). When it *is* installed we expect the resolver to fire
    # at least once even though it raises.
    assert load_language("vibe-test-grammar") is None
    if is_treesitter_available():
        assert sentinel == [True]


# ----------------------------------------------------- adapter graceful fallback


def test_adapter_falls_back_to_regex_when_treesitter_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the loader to claim tree-sitter is unavailable.
    monkeypatch.setattr(
        "vibe_coding.agent.repo_index._tree_sitter.is_treesitter_available",
        lambda: False,
    )
    adapter = TypeScriptLanguageAdapter(use_treesitter=True)
    pf = adapter.parse(
        path="x.ts", source="export function foo() { return 1; }\n"
    )
    # Even with tree-sitter forcibly disabled we still get the regex output.
    assert any(s.name == "foo" for s in pf.symbols)


def test_is_treesitter_available_method_on_adapter() -> None:
    adapter = TypeScriptLanguageAdapter()
    # Regardless of whether the extra is installed, the method shouldn't raise.
    assert isinstance(adapter.is_treesitter_available(), bool)


# ----------------------------------------------------- parity (only when grammar present)


_SAMPLE_TS = textwrap.dedent(
    """\
    import { ref } from 'vue';

    export function add(a: number, b: number): number {
      return a + b;
    }

    export class Calc {
      total: number = 0;
      add(n: number): void {
        this.total += n;
      }
    }
    """
)


def test_treesitter_parse_when_grammar_available() -> None:
    adapter = TypeScriptLanguageAdapter(use_treesitter=True)
    if not adapter.is_treesitter_available():
        pytest.skip("tree-sitter typescript grammar not installed")
    pf = adapter.parse(path="x.ts", source=_SAMPLE_TS)
    names = {s.name for s in pf.symbols}
    # Every regex-detected symbol should also appear via tree-sitter.
    assert "add" in names
    assert "Calc" in names
    # Tree-sitter sees the class method too.
    methods = [s for s in pf.symbols if s.kind == "method"]
    assert any(m.name == "add" for m in methods)
