"""Tests for :class:`AgentContext` and its injection into prompts."""

from __future__ import annotations

from pathlib import Path

import pytest

from vibe_coding.agent.context import AgentContext


def test_empty_context_produces_empty_dict() -> None:
    assert AgentContext().to_dict() == {}


def test_populated_context_roundtrips() -> None:
    ctx = AgentContext(
        active_file="src/main.py",
        cursor_line=42,
        cursor_column=8,
        selection=(40, 45),
        recent_files=["src/main.py", "tests/test_main.py"],
        notes="look at line 42",
    )
    d = ctx.to_dict()
    ctx2 = AgentContext.from_dict(d)
    assert ctx2.active_file == "src/main.py"
    assert ctx2.cursor_line == 42
    assert ctx2.cursor_column == 8
    assert ctx2.selection == (40, 45)
    assert ctx2.notes == "look at line 42"
    assert ctx2.recent_files == ["src/main.py", "tests/test_main.py"]


def test_to_prompt_block_renders_json() -> None:
    ctx = AgentContext(active_file="x.py", cursor_line=1)
    block = ctx.to_prompt_block()
    assert "当前编辑器上下文" in block
    assert "x.py" in block
    assert "```json" in block


def test_empty_context_prompt_block_is_empty() -> None:
    assert AgentContext().to_prompt_block() == ""


def test_from_git_returns_context_object(tmp_path: Path) -> None:
    ctx = AgentContext.from_git(tmp_path)
    # tmp_path is not a git repo so recent_files should be empty
    assert isinstance(ctx, AgentContext)
    assert ctx.recent_files == []


def test_from_git_on_real_repo() -> None:
    from pathlib import Path

    here = Path(__file__).resolve().parent
    ctx = AgentContext.from_git(here)
    # This file's directory is inside the vibe-coding git repo
    assert isinstance(ctx, AgentContext)


def test_from_dict_handles_none() -> None:
    ctx = AgentContext.from_dict(None)
    assert ctx.to_dict() == {}


def test_selection_invalid_coercion() -> None:
    raw = {"selection": [42, "not-int"]}
    ctx = AgentContext.from_dict(raw)
    assert ctx.selection is None


def test_git_status_populates_recent_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock git subprocess to simulate a git repo with dirty files."""
    import subprocess as _sp
    import shutil

    if shutil.which("git") is None:
        pytest.skip("git not on PATH")

    outputs: list[str] = [
        "M  src/foo.py\n?? tests/new.py\n",
        "",
        "",  # git log call
    ]
    call_count = [0]

    def fake_run(args, **kwargs):  # type: ignore[override]
        class FakeProc:
            returncode = 0
            stdout = outputs[min(call_count[0], len(outputs) - 1)]
            stderr = ""

        call_count[0] += 1
        return FakeProc()

    monkeypatch.setattr(_sp, "run", fake_run)
    ctx = AgentContext.from_git(tmp_path)
    assert "src/foo.py" in ctx.recent_files


# ----------------------------------------------------------------- P1 additions


def test_merge_prefers_self_then_other() -> None:
    a = AgentContext(active_file="a.py", recent_files=["a.py"], notes="explicit")
    b = AgentContext(
        active_file="b.py",
        recent_files=["a.py", "b.py", "c.py"],
        notes="fallback",
    )
    merged = a.merge(b)
    assert merged.active_file == "a.py"
    assert merged.notes == "explicit"
    assert merged.recent_files == ["a.py", "b.py", "c.py"]


def test_merge_concatenates_lists_dedupe() -> None:
    a = AgentContext(open_files=["x.py", "y.py"])
    b = AgentContext(open_files=["y.py", "z.py"])
    merged = a.merge(b)
    assert merged.open_files == ["x.py", "y.py", "z.py"]


def test_merge_falls_back_when_self_empty() -> None:
    a = AgentContext()
    b = AgentContext(active_file="b.py", notes="from b")
    merged = a.merge(b)
    assert merged.active_file == "b.py"
    assert merged.notes == "from b"


def test_select_focus_files_promotes_active() -> None:
    ctx = AgentContext(
        active_file="src/main.py",
        open_files=["src/util.py", "src/main.py"],
        recent_files=["tests/test_main.py"],
    )
    candidates = ["tests/test_main.py", "src/util.py", "docs/readme.md", "src/main.py"]
    ranked = ctx.select_focus_files(candidates)
    assert ranked[0] == "src/main.py"
    assert "src/util.py" in ranked
    assert "tests/test_main.py" in ranked
    assert "docs/readme.md" in ranked  # tail order preserved


def test_select_focus_files_respects_limit() -> None:
    ctx = AgentContext(active_file="a.py", recent_files=["b.py", "c.py", "d.py"])
    candidates = ["a.py", "b.py", "c.py", "d.py", "e.py"]
    out = ctx.select_focus_files(candidates, limit=2)
    assert len(out) == 2
    assert out[0] == "a.py"


def test_select_focus_files_filters_unknown() -> None:
    ctx = AgentContext(active_file="not-in-index.py")
    candidates = ["a.py", "b.py"]
    out = ctx.select_focus_files(candidates)
    assert "not-in-index.py" not in out
    assert "a.py" in out and "b.py" in out


def test_truncate_tail_in_to_prompt_block() -> None:
    big = "X" * 50_000
    ctx = AgentContext(shell_output=big)
    block = ctx.to_prompt_block()
    # The serialised block should not contain the full payload.
    assert "truncated" in block
    assert len(block) < len(big) + 2_000


def test_recent_files_truncated_in_prompt() -> None:
    files = [f"file{i}.py" for i in range(200)]
    ctx = AgentContext(recent_files=files)
    block = ctx.to_prompt_block()
    # Only first 50 should appear (MAX_RECENT_FILES).
    assert "file49.py" in block
    assert "file100.py" not in block
