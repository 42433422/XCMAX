"""E2E: heal_project from broken → tool-validated green state.

Uses MockLLM and a tiny fixture project so no real LLM or network is needed.
The ToolRunner is swapped for a stub that first fails (simulating broken
tests) then passes after the patch is applied.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from vibe_coding import MockLLM, VibeCoder
from vibe_coding.agent.tools.runner import ToolReport


class _FakeToolRunner:
    """Fails on the first call, passes on all subsequent calls."""

    def __init__(self) -> None:
        self._calls = 0

    def run_all(self, root: Any) -> list[ToolReport]:
        self._calls += 1
        if self._calls == 1:
            return [ToolReport(tool="fake", passed=False, issues=["assertion failed"])]
        return [ToolReport(tool="fake", passed=True)]


def _patch_response(patch_id: str, old_text: str, new_text: str) -> str:
    return json.dumps(
        {
            "patch_id": patch_id,
            "summary": f"round {patch_id}",
            "rationale": "fix",
            "edits": [
                {
                    "path": "pkg/math.py",
                    "operation": "modify",
                    "hunks": [
                        {
                            "anchor_before": "def add(a, b):\n",
                            "old_text": old_text,
                            "new_text": new_text,
                            "anchor_after": "",
                        }
                    ],
                }
            ],
        }
    )


def test_heal_project_with_tool_runner(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "pkg").mkdir()
    (project / "pkg" / "math.py").write_text(
        "def add(a, b):\n    return a + b  # broken\n", encoding="utf-8"
    )

    # Round 1: patch changes "broken" → "fixed"; tool runner fails → triggers round 2.
    # Round 2: patch changes "fixed" to itself (no-op is fine) and tool runner passes.
    r1 = _patch_response("patch-r1", "    return a + b  # broken\n", "    return a + b  # fixed\n")
    r2 = _patch_response("patch-r2", "    return a + b  # fixed\n", "    return a + b  # healed\n")
    llm = MockLLM([r1, r2])
    coder = VibeCoder(llm=llm, store_dir=tmp_path / "store", llm_for_repair=False)
    tool_runner = _FakeToolRunner()

    result = coder.heal_project(
        "fix the math module",
        root=project,
        max_rounds=3,
        tool_runner=tool_runner,
    )
    assert result.success, result.error
    assert tool_runner._calls == 2
    assert "# healed" in (project / "pkg" / "math.py").read_text(encoding="utf-8")
    assert len(result.rounds) == 2
    assert result.rounds[0].success is False
    assert result.rounds[1].success is True


def test_heal_project_max_rounds_exceeded(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.py").write_text("def f(): return 1\n", encoding="utf-8")

    always_fail = json.dumps(
        {
            "patch_id": "p",
            "summary": "noop",
            "rationale": "nothing",
            "edits": [
                {
                    "path": "a.py",
                    "operation": "modify",
                    "hunks": [
                        {
                            "anchor_before": "def f(): return 1\n",
                            "old_text": "def f(): return 1\n",
                            "new_text": "def f(): return 1  # still broken\n",
                            "anchor_after": "",
                        }
                    ],
                }
            ],
        }
    )

    class _AlwaysFail:
        def run_all(self, root: Any) -> list[ToolReport]:
            return [ToolReport(tool="test", passed=False, issues=["still bad"])]

    llm = MockLLM([always_fail] * 3)
    coder = VibeCoder(llm=llm, store_dir=tmp_path / "store2", llm_for_repair=False)
    result = coder.heal_project(
        "keep failing",
        root=project,
        max_rounds=2,
        tool_runner=_AlwaysFail(),
    )
    assert not result.success
    assert len(result.rounds) == 2
