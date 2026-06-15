"""Code-understanding engine: parse a project, surface symbols and references.

The :class:`RepoIndex` is the agent's view of an existing project. It is built
once (:func:`build_index`) and refreshed incrementally on subsequent calls; the
``LanguageAdapter`` protocol lets new languages plug in (Python ships in tree;
TypeScript and Vue adapters are scaffolded under ``adapters/_treesitter.py``
for the second phase).

Persisted to ``<store_dir>/repo_index.json`` so subsequent runs in the same
workspace skip rescanning unchanged files.
"""

from __future__ import annotations

from .adapters import LanguageAdapter, ParsedFile
from .adapters.python import PythonLanguageAdapter
from .adapters.typescript import TypeScriptLanguageAdapter
from .adapters.vue import VueLanguageAdapter
from .index import FileEntry, Reference, RepoIndex, Symbol
from .builder import build_index

__all__ = [
    "FileEntry",
    "LanguageAdapter",
    "ParsedFile",
    "PythonLanguageAdapter",
    "Reference",
    "RepoIndex",
    "Symbol",
    "TypeScriptLanguageAdapter",
    "VueLanguageAdapter",
    "build_index",
]
