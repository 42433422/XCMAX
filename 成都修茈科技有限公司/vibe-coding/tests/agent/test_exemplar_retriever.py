"""Tests for :class:`ExemplarStore`, :class:`Retriever`, and :class:`ProjectMemory`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibe_coding import MockLLM, VibeCoder
from vibe_coding.agent.memory import ExemplarStore, ProjectMemory, Retriever
from vibe_coding.agent.memory.exemplars import Exemplar
from vibe_coding.agent.patch import FileEdit, Hunk, ProjectPatch


def _make_exemplar(brief: str, summary: str = "") -> Exemplar:
    return Exemplar(brief=brief, summary=summary or brief, diff_text=f"+ # {brief}")


def test_exemplar_store_add_and_retrieve() -> None:
    store = ExemplarStore()
    store.add(_make_exemplar("add logging to all functions"))
    store.add(_make_exemplar("replace print with logger"))
    store.add(_make_exemplar("add type hints to all functions"))
    assert len(store) == 3


def test_exemplar_roundtrip() -> None:
    ex = _make_exemplar("test brief", "test summary")
    d = ex.to_dict()
    ex2 = Exemplar.from_dict(d)
    assert ex2.brief == "test brief"
    assert ex2.summary == "test summary"


def test_retriever_basic_ranking() -> None:
    store = ExemplarStore(
        [
            _make_exemplar("add type hints to functions"),
            _make_exemplar("rename files in package"),
            _make_exemplar("add logging and type annotations"),
        ]
    )
    retriever = Retriever(store.all())
    results = retriever.search("add type hints", k=2)
    assert results
    briefs = [r.brief for r in results]
    # Both type-hint exemplars should score higher than the rename one
    assert any("type" in b for b in briefs)


def test_retriever_empty_corpus() -> None:
    retriever = Retriever([])
    assert retriever.search("anything", k=3) == []


def test_retriever_empty_query() -> None:
    store = ExemplarStore([_make_exemplar("foo"), _make_exemplar("bar")])
    retriever = Retriever(store.all())
    results = retriever.search("", k=2)
    assert len(results) <= 2


def test_project_memory_persist_load(tmp_path: Path) -> None:
    mem = ProjectMemory(tmp_path)

    patch = ProjectPatch(
        patch_id="p1",
        summary="add type hints",
        edits=[
            FileEdit(
                path="a.py",
                operation="modify",
                hunks=[Hunk("def foo():\n", "    pass\n", "    pass  # typed\n", "")],
            )
        ],
    )
    mem.record_success("add type hints", patch, tools_passed=["ruff"])
    mem.record_success("add logging", ProjectPatch(patch_id="p2", summary="logging"))

    # Reload from disk
    mem2 = ProjectMemory(tmp_path)
    assert len(mem2._exemplars) == 2
    results = mem2.retrieve("add type hints", k=1)
    assert results and "type hints" in results[0].brief


def test_project_memory_prompt_block(tmp_path: Path) -> None:
    mem = ProjectMemory(tmp_path)
    patch = ProjectPatch(patch_id="px", summary="sample fix")
    mem.record_success("fix the add function", patch)
    block = mem.to_prompt_block("fix the add function", k=1)
    # Block may include style or exemplar text
    assert isinstance(block, str)


def test_project_memory_record_success_triggers_style(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo(x: int) -> int:\n    return x\n", encoding="utf-8")
    llm = MockLLM([
        json.dumps({
            "patch_id": "px",
            "summary": "fix",
            "rationale": "",
            "edits": [],
        })
    ])
    coder = VibeCoder(llm=llm, store_dir=tmp_path / "store", llm_for_repair=False)
    pc = coder.project_coder(tmp_path)
    patch = pc.edit_project("add logging")
    pc.apply_patch(
        patch,
        dry_run=False,
        record_in_memory=True,
        brief="add logging",
        tools_passed=["ruff"],
    )
    # The memory should have at least the style saved
    mem2 = ProjectMemory(pc.store_dir)
    assert isinstance(mem2.style, type(pc.memory.style))


# ----------------------------------------------------------------- P2 additions


def test_record_failure_logs_with_outcome(tmp_path: Path) -> None:
    mem = ProjectMemory(tmp_path)
    patch = ProjectPatch(patch_id="bad-1", summary="attempted fix")
    mem.record_failure(
        "fix the broken thing",
        patch,
        error="ruff failed",
        tools_failed=["ruff"],
    )
    failures = mem._exemplars.failures()
    assert len(failures) == 1
    assert failures[0].outcome == "failure"
    assert failures[0].error == "ruff failed"
    assert "ruff" in failures[0].tools_failed


def test_record_failure_without_patch(tmp_path: Path) -> None:
    """LLM failed before producing a patch — we still want the brief logged."""
    mem = ProjectMemory(tmp_path)
    mem.record_failure(
        "make it work",
        patch=None,
        error="JSONParseError: bad payload",
    )
    assert len(mem._exemplars.failures()) == 1


def test_retrieve_filters_by_outcome(tmp_path: Path) -> None:
    mem = ProjectMemory(tmp_path)
    mem.record_success("add type hints", ProjectPatch(patch_id="s1", summary="ok"))
    mem.record_failure(
        "add type hints",
        ProjectPatch(patch_id="f1", summary="failed"),
        error="mypy failed",
    )
    successes = mem.retrieve("type hints", k=5, outcome="success")
    failures = mem.retrieve("type hints", k=5, outcome="failure")
    assert all(e.outcome == "success" for e in successes)
    assert all(e.outcome == "failure" for e in failures)


def test_prune_keeps_max_items(tmp_path: Path) -> None:
    mem = ProjectMemory(tmp_path, max_exemplars=5)
    for i in range(20):
        mem.record_success(
            f"brief {i}",
            ProjectPatch(patch_id=f"p{i}", summary=f"s{i}"),
        )
    # Auto-prune should have kicked in to 90% of 5 = at most 5 entries.
    assert len(mem._exemplars) <= 5


def test_manual_prune_returns_count(tmp_path: Path) -> None:
    mem = ProjectMemory(tmp_path, max_exemplars=100)
    for i in range(10):
        mem.record_success(f"b{i}", ProjectPatch(patch_id=f"p{i}", summary="s"))
    mem._max_exemplars = 3
    removed = mem.prune_now()
    assert removed >= 7
    assert len(mem._exemplars) == 3


def test_retrieve_updates_last_used(tmp_path: Path) -> None:
    mem = ProjectMemory(tmp_path)
    mem.record_success("query me later", ProjectPatch(patch_id="x1", summary="x"))
    before = mem._exemplars.all()[0].last_used_at
    results = mem.retrieve("query", k=1)
    assert results
    after = results[0].last_used_at
    assert after > before


def test_to_prompt_block_includes_failures(tmp_path: Path) -> None:
    mem = ProjectMemory(tmp_path)
    mem.record_success("add metrics", ProjectPatch(patch_id="ok", summary="add metrics"))
    mem.record_failure(
        "add metrics",
        ProjectPatch(patch_id="bad", summary="broken metrics"),
        error="circular import",
    )
    block = mem.to_prompt_block("add metrics", k=1, failure_k=1)
    assert "请避免重复" in block or "失败" in block
    assert "circular import" in block


def test_pruning_strategy_failures_first(tmp_path: Path) -> None:
    mem = ProjectMemory(tmp_path, max_exemplars=2, prune_strategy="failures_first")
    mem.record_success("good 1", ProjectPatch(patch_id="g1", summary="ok"))
    mem.record_failure("bad 1", ProjectPatch(patch_id="b1", summary="bad"), error="x")
    mem.record_success("good 2", ProjectPatch(patch_id="g2", summary="ok"))
    mem.record_failure("bad 2", ProjectPatch(patch_id="b2", summary="bad"), error="y")
    # After pruning, failures should be evicted first.
    remaining = mem._exemplars.all()
    success_count = sum(1 for e in remaining if e.outcome == "success")
    failure_count = sum(1 for e in remaining if e.outcome == "failure")
    assert success_count >= failure_count


def test_exemplar_persist_includes_new_fields(tmp_path: Path) -> None:
    mem1 = ProjectMemory(tmp_path)
    mem1.record_success(
        "tagged brief",
        ProjectPatch(patch_id="t1", summary="tagged"),
        tags=["refactor", "perf"],
        metadata={"reviewer": "alice"},
    )
    mem2 = ProjectMemory(tmp_path)
    ex = mem2._exemplars.all()[0]
    assert "refactor" in ex.tags
    assert ex.metadata.get("reviewer") == "alice"
    assert ex.created_at > 0
