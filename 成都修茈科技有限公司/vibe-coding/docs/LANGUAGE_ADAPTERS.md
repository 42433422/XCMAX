# Language Adapters

## How adapters work

A `LanguageAdapter` satisfies the `Protocol` defined in
`vibe_coding.agent.repo_index.adapters`:

```python
class LanguageAdapter(Protocol):
    @property
    def language(self) -> str: ...

    @property
    def extensions(self) -> tuple[str, ...]: ...

    def parse(self, *, path: str, source: str) -> ParsedFile: ...
```

`ParsedFile` carries `symbols`, `imports`, `references` and `parse_error`.
Adapters must be **tolerant** — partial output with `parse_error` populated
is preferred over raising.

## Built-in adapters

### PythonLanguageAdapter (shipped, zero dependencies)

Uses Python's built-in `ast` module. Extracts:

- Functions, async functions, classes (with signatures + docstrings)
- Class methods (with `parent=ClassName`)
- Top-level assignments (constants + variables)
- All import statements
- Call-expression references

### TypeScriptLanguageAdapter (phase-2 stub)

Location: `vibe_coding/agent/repo_index/adapters/typescript.py`

Requires `pip install vibe-coding[agent-treesitter]`. Until the
implementation lands, `parse()` raises `NotImplementedError` but
`is_available()` returns `False` so the builder skips `.ts` / `.tsx` files
silently.

### VueLanguageAdapter (phase-2 stub)

Location: `vibe_coding/agent/repo_index/adapters/vue.py`

Same requirements as TypeScript. Plans to split the SFC into `<script>` /
`<template>` sections and process them separately.

## Writing a new adapter

```python
from vibe_coding.agent.repo_index.adapters import LanguageAdapter, ParsedFile
from vibe_coding.agent.repo_index.index import Symbol, Reference

class GoLanguageAdapter:
    @property
    def language(self) -> str:
        return "go"

    @property
    def extensions(self) -> tuple[str, ...]:
        return (".go",)

    def parse(self, *, path: str, source: str) -> ParsedFile:
        symbols: list[Symbol] = []
        imports: list[str] = []
        references: list[Reference] = []
        try:
            # ... your parsing logic here ...
            pass
        except Exception as exc:
            return ParsedFile(
                language=self.language,
                symbols=symbols,
                imports=imports,
                references=references,
                parse_error=f"parse_error:{exc}",
            )
        return ParsedFile(
            language=self.language,
            symbols=symbols,
            imports=imports,
            references=references,
        )
```

Pass the adapter to `build_index`:

```python
from vibe_coding.agent.repo_index import build_index

index = build_index(
    root="./my_go_project",
    adapters=[GoLanguageAdapter()],
)
```

Or combine with the built-in Python adapter:

```python
from vibe_coding.agent.repo_index import PythonLanguageAdapter, build_index

index = build_index(
    root="./polyglot_project",
    adapters=[PythonLanguageAdapter(), GoLanguageAdapter()],
)
```

## Tree-sitter base class

Phase-2 adapters extend `TreeSitterAdapter` from
`vibe_coding.agent.repo_index._tree_sitter`:

```python
from vibe_coding.agent.repo_index._tree_sitter import TreeSitterAdapter

class RustLanguageAdapter(TreeSitterAdapter):
    _language_name = "rust"
    _extensions = (".rs",)

    def parse(self, *, path: str, source: str):
        import tree_sitter_rust as tsr
        # ... parse with tree-sitter ...
```
