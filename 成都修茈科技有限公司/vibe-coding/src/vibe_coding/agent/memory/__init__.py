"""Project learning and memory subsystem.

Persists two artefacts to ``<store_dir>/memory.json``:

1. :class:`StyleProfile` — a style fingerprint extracted from the project's
   :class:`RepoIndex`. Covers naming conventions, docstring coverage, type-
   hint density, common imports and common exception types. The fingerprint
   is injected into the multi-file edit / repair prompts so the LLM writes
   code that blends in with the rest of the codebase.

2. :class:`ExemplarStore` — a log of every :class:`ProjectPatch` that
   reached the "passed all tools + sandbox" state. The :class:`Retriever`
   finds the top-K most relevant exemplars for a given brief using a simple
   but effective BM25-like TF-IDF score — zero extra dependencies.

Usage::

    from vibe_coding.agent.memory import ProjectMemory

    mem = ProjectMemory(store_dir="./vibe_coding_data")
    mem.rebuild_style(index)               # update fingerprint
    mem.record_success(brief, patch)        # log a validated patch
    top_k = mem.retrieve(brief, k=3)        # find relevant examples
    prompt_extra = mem.to_prompt_block(brief, k=3)  # ready for injection
"""

from __future__ import annotations

from .embedder import (
    DEFAULT_DIM,
    Embedder,
    HashingEmbedder,
    OpenAIEmbedder,
    SentenceTransformerEmbedder,
    cosine_similarity,
)
from .exemplars import Exemplar, ExemplarStore
from .knowledge_base import (
    GlobalKnowledgeBase,
    KnowledgeRecord,
    auto_promote_to_kb,
)
from .retriever import Retriever
from .style import StyleProfile
from .store import ProjectMemory

__all__ = [
    "DEFAULT_DIM",
    "Embedder",
    "Exemplar",
    "ExemplarStore",
    "GlobalKnowledgeBase",
    "HashingEmbedder",
    "KnowledgeRecord",
    "OpenAIEmbedder",
    "ProjectMemory",
    "Retriever",
    "SentenceTransformerEmbedder",
    "StyleProfile",
    "auto_promote_to_kb",
    "cosine_similarity",
]
