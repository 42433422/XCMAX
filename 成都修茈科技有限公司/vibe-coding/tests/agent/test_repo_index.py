"""Unit tests for :mod:`vibe_coding.agent.repo_index`."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from vibe_coding.agent.repo_index import (
    PythonLanguageAdapter,
    RepoIndex,
    Symbol,
    build_index,
)


def _make_project(root: Path) -> None:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VERSION = '1.0'\n", encoding="utf-8")
    (root / "pkg" / "math.py").write_text(
        textwrap.dedent(
            '''\
            """Math helpers."""

            from __future__ import annotations

            CONSTANT = 42


            def add(a: int, b: int = 0) -> int:
                """Add two integers."""
                return a + b


            class Calculator:
                """A small calculator."""

                def total(self, values: list[int]) -> int:
                    return sum(values)


            async def fetch(url: str) -> dict:
                return {"url": url}
            '''
        ),
        encoding="utf-8",
    )
    (root / "pkg" / "broken.py").write_text("def oops(:\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "run.py").write_text(
        "from pkg.math import add\nprint(add(1, 2))\n", encoding="utf-8"
    )
    (root / ".gitignore").write_text("scripts/\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "stub.py").write_text("def banned(): ...\n", encoding="utf-8")


def test_build_index_finds_symbols(tmp_path: Path) -> None:
    _make_project(tmp_path)
    index = build_index(tmp_path)

    summary = index.summary()
    assert summary["files"] >= 2
    assert summary["languages"] == {"python": summary["files"]}
    assert "scripts/run.py" not in index.files, "gitignore must skip scripts/"
    assert all("node_modules" not in p for p in index.files), "hard-skip dirs"

    syms = index.find_symbol("add")
    assert any(s.kind == "function" and s.parent == "" for s in syms)
    add_sym = next(s for s in syms if s.kind == "function")
    assert "def add(a: int, b: int = 0) -> int" in add_sym.signature
    assert add_sym.docstring == "Add two integers."

    cls = index.find_qualified("Calculator")
    assert cls and cls[0].kind == "class"
    method = index.find_qualified("Calculator.total")
    assert method and method[0].parent == "Calculator"

    async_fn = index.find_symbol("fetch")
    assert async_fn and async_fn[0].kind == "async_function"


def test_broken_file_records_parse_error(tmp_path: Path) -> None:
    _make_project(tmp_path)
    index = build_index(tmp_path)
    broken = index.get_file("pkg/broken.py")
    assert broken is not None
    assert broken.parse_error.startswith("syntax_error")


def test_imports_extracted(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "import json\nimport re as r\nfrom collections import deque\nfrom . import sibling\n",
        encoding="utf-8",
    )
    index = build_index(tmp_path)
    entry = index.get_file("a.py")
    assert entry is not None
    assert "json" in entry.imports
    assert "re" in entry.imports
    assert "collections" in entry.imports
    assert "." in entry.imports


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    _make_project(tmp_path)
    out = tmp_path / "_index.json"
    index = build_index(tmp_path)
    index.save(out)
    loaded = RepoIndex.load(tmp_path, out)
    assert loaded is not None
    assert loaded.summary() == index.summary()
    assert set(loaded.files) == set(index.files)


def test_incremental_skips_unchanged(tmp_path: Path) -> None:
    _make_project(tmp_path)
    initial = build_index(tmp_path)
    same = build_index(tmp_path, previous=initial)
    for path, entry in initial.files.items():
        if entry.parse_error:
            continue
        assert same.files[path] is entry, f"{path}: incremental should reuse entry"


def test_incremental_rebuilds_changed(tmp_path: Path) -> None:
    _make_project(tmp_path)
    initial = build_index(tmp_path)
    target = tmp_path / "pkg" / "math.py"
    text = target.read_text(encoding="utf-8")
    target.write_text(text + "\n\ndef brand_new(x):\n    return x\n", encoding="utf-8")
    refreshed = build_index(tmp_path, previous=initial)
    new_syms = refreshed.find_symbol("brand_new")
    assert new_syms, "incremental should pick up new symbols"


def test_references_to(tmp_path: Path) -> None:
    _make_project(tmp_path)
    (tmp_path / "extra.py").write_text(
        "from pkg.math import add\nresult = add(1, 2)\n", encoding="utf-8"
    )
    index = build_index(tmp_path)
    refs = index.references_to("add")
    assert refs, "should find at least one call to add(...)"


def test_python_adapter_extensions() -> None:
    adapter = PythonLanguageAdapter()
    assert ".py" in adapter.extensions
    assert ".pyi" in adapter.extensions
    assert adapter.language == "python"
