"""Tests for the cross-project knowledge base + embedder primitives."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from vibe_coding.agent.memory import (
    Exemplar,
    GlobalKnowledgeBase,
    HashingEmbedder,
    KnowledgeRecord,
    OpenAIEmbedder,
    ProjectMemory,
    SentenceTransformerEmbedder,
    auto_promote_to_kb,
    cosine_similarity,
)


# --------------------------------------------------------------- embedder


def test_hashing_embedder_is_deterministic() -> None:
    e = HashingEmbedder(dim=32)
    a = e.embed(["hello world"])[0]
    b = e.embed(["hello world"])[0]
    assert a == b
    assert len(a) == 32


def test_hashing_embedder_distinguishes_distinct_strings() -> None:
    e = HashingEmbedder(dim=64)
    a = e.embed(["rename foo to bar"])[0]
    b = e.embed(["add caching layer with redis"])[0]
    assert cosine_similarity(a, b) < 0.95


def test_cosine_similarity_handles_zero_vectors() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_openai_embedder_falls_back_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPUAI_API_KEY", raising=False)
    e = OpenAIEmbedder()
    vectors = e.embed(["hi"])
    assert len(vectors) == 1
    assert len(vectors[0]) == e.dim


def test_openai_embedder_falls_back_on_http_error() -> None:
    e = OpenAIEmbedder(api_key="key", base_url="https://x.example/v1")

    def boom(*args, **kwargs):
        raise OSError("network down")

    with patch("urllib.request.urlopen", side_effect=boom):
        vectors = e.embed(["hi"])
    assert len(vectors[0]) > 0  # fallback hashing returned a vector


def test_sentence_transformer_falls_back_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    e = SentenceTransformerEmbedder()
    # Force the lazy import to fail.
    monkeypatch.setattr(e, "_ensure_model", lambda: None)
    vectors = e.embed(["x"])
    assert len(vectors[0]) > 0


# --------------------------------------------------------------- KB CRUD


def _make_exemplar(brief: str, *, patch_id: str = "p", outcome="success", langs=None) -> Exemplar:
    return Exemplar(
        brief=brief,
        patch_id=patch_id,
        summary=brief[:30],
        diff_text=f"+ {brief}\n",
        languages=list(langs or []),
        outcome=outcome,
    )


def test_kb_add_and_search_returns_top_k(tmp_path: Path) -> None:
    kb = GlobalKnowledgeBase(store_dir=tmp_path)
    kb.add_exemplar(_make_exemplar("rename foo to bar"), project_id="p1")
    kb.add_exemplar(_make_exemplar("add Redis caching layer"), project_id="p2")
    kb.add_exemplar(_make_exemplar("write Vue component for login"), project_id="p3")

    results = kb.search("vue login form", k=2)
    assert results
    # The Vue exemplar should rank above the Redis exemplar.
    top_briefs = [r.exemplar.brief for r in results]
    assert any("Vue" in b for b in top_briefs)


def test_kb_filters_by_language(tmp_path: Path) -> None:
    kb = GlobalKnowledgeBase(store_dir=tmp_path)
    kb.add_exemplar(_make_exemplar("write tests", langs=["python"]), project_id="p1")
    kb.add_exemplar(_make_exemplar("write tests", langs=["typescript"]), project_id="p2")
    py = kb.search("write tests", k=5, language="python")
    assert all("python" in r.languages for r in py)


def test_kb_filters_by_framework(tmp_path: Path) -> None:
    kb = GlobalKnowledgeBase(store_dir=tmp_path)
    kb.add_exemplar(_make_exemplar("a"), project_id="p1", framework="django")
    kb.add_exemplar(_make_exemplar("a"), project_id="p2", framework="fastapi")
    out = kb.search("a", k=5, framework="fastapi")
    assert all(r.framework == "fastapi" for r in out)


def test_kb_filters_failures_by_default(tmp_path: Path) -> None:
    kb = GlobalKnowledgeBase(store_dir=tmp_path)
    kb.add_exemplar(_make_exemplar("ok", outcome="success"), project_id="a")
    kb.add_exemplar(_make_exemplar("oops", outcome="failure"), project_id="b")
    successes = kb.search("ok oops", k=5, outcome="success")
    assert all(r.exemplar.outcome == "success" for r in successes)
    both = kb.search("ok oops", k=5, outcome="any")
    outcomes = {r.exemplar.outcome for r in both}
    assert outcomes == {"success", "failure"}


def test_kb_persists_to_disk(tmp_path: Path) -> None:
    kb1 = GlobalKnowledgeBase(store_dir=tmp_path)
    kb1.add_exemplar(_make_exemplar("persist me"), project_id="p")
    # New instance reads from disk.
    kb2 = GlobalKnowledgeBase(store_dir=tmp_path)
    assert len(kb2) == 1
    payload = json.loads((tmp_path / "knowledge_base.json").read_text("utf-8"))
    assert payload["records"][0]["project_id"] == "p"


def test_kb_promote_from_project_dedupes(tmp_path: Path) -> None:
    kb = GlobalKnowledgeBase(store_dir=tmp_path)
    ex_list = [
        _make_exemplar("a", patch_id="p-1"),
        _make_exemplar("b", patch_id="p-2"),
    ]
    n1 = kb.promote_from_project(ex_list, project_id="proj-A")
    n2 = kb.promote_from_project(ex_list, project_id="proj-A")  # second call
    assert n1 == 2
    assert n2 == 0
    assert len(kb) == 2


def test_kb_remove_project(tmp_path: Path) -> None:
    kb = GlobalKnowledgeBase(store_dir=tmp_path)
    kb.add_exemplar(_make_exemplar("x"), project_id="p1")
    kb.add_exemplar(_make_exemplar("y"), project_id="p2")
    removed = kb.remove_project("p1")
    assert removed == 1
    assert len(kb) == 1


def test_kb_to_prompt_block_renders_records(tmp_path: Path) -> None:
    kb = GlobalKnowledgeBase(store_dir=tmp_path)
    kb.add_exemplar(_make_exemplar("rename foo to bar"), project_id="p")
    block = kb.to_prompt_block("rename")
    assert "跨项目知识" in block
    assert "rename foo to bar" in block


def test_kb_stats(tmp_path: Path) -> None:
    kb = GlobalKnowledgeBase(store_dir=tmp_path)
    kb.add_exemplar(_make_exemplar("a", langs=["python"]), project_id="p")
    s = kb.stats()
    assert s["records"] == 1
    assert s["languages"]["python"] == 1
    assert s["embedder"] == "HashingEmbedder"


# --------------------------------------------------------------- promotion


def test_auto_promote_success(tmp_path: Path) -> None:
    kb = GlobalKnowledgeBase(store_dir=tmp_path)
    ex = _make_exemplar("good", outcome="success")
    promoted = auto_promote_to_kb(kb=kb, exemplar=ex, project_id="proj")
    assert promoted is True
    assert len(kb) == 1


def test_auto_promote_skips_low_quality_failure(tmp_path: Path) -> None:
    kb = GlobalKnowledgeBase(store_dir=tmp_path, promotion_threshold=0.7)
    ex = _make_exemplar("oops", outcome="failure")
    ex.metadata["promotion_score"] = 0.5
    promoted = auto_promote_to_kb(kb=kb, exemplar=ex, project_id="proj")
    assert promoted is False
    assert len(kb) == 0


def test_auto_promote_keeps_high_quality_failure(tmp_path: Path) -> None:
    kb = GlobalKnowledgeBase(store_dir=tmp_path, promotion_threshold=0.7)
    ex = _make_exemplar("oops", outcome="failure")
    ex.metadata["promotion_score"] = 0.9
    assert auto_promote_to_kb(kb=kb, exemplar=ex, project_id="proj") is True


# --------------------------------------------------------------- ProjectMemory


def test_project_memory_auto_promotes_to_kb(tmp_path: Path) -> None:
    kb = GlobalKnowledgeBase(store_dir=tmp_path / "kb")
    mem = ProjectMemory(
        store_dir=tmp_path / "proj",
        knowledge_base=kb,
        project_id="proj-123",
        framework="fastapi",
    )

    class _Patch:
        patch_id = "p-1"
        summary = "demo"
        edits = []

    mem.record_success("rename foo", _Patch())
    assert len(kb) == 1
    rec = kb.all()[0]
    assert rec.project_id == "proj-123"
    assert rec.framework == "fastapi"


def test_project_memory_promotion_can_be_disabled(tmp_path: Path) -> None:
    kb = GlobalKnowledgeBase(store_dir=tmp_path / "kb")
    mem = ProjectMemory(
        store_dir=tmp_path / "proj",
        knowledge_base=kb,
        project_id="proj-x",
        auto_promote=False,
    )

    class _Patch:
        patch_id = "p-1"
        summary = "demo"
        edits = []

    mem.record_success("anything", _Patch())
    assert len(kb) == 0
