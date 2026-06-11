"""Tests for :class:`DebugReasoner`."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from vibe_coding import MockLLM
from vibe_coding.agent.context import AgentContext
from vibe_coding.agent.debug_reasoner import DebugReasoner, Hypothesis, DebugReport
from vibe_coding.agent.repo_index import build_index


_MOCK_HYPOTHESES = json.dumps(
    {
        "hypotheses": [
            {
                "id": "h1",
                "hypothesis": "foo() 传参类型错误",
                "evidence": "frame 0 line 3 in foo",
                "affected_symbols": ["foo"],
                "fix_sketch": "在 foo 内加类型检查",
                "verification_plan": "run test_foo_bad_input",
                "confidence": "high",
            },
            {
                "id": "h2",
                "hypothesis": "调用者传了 None",
                "evidence": "frame 1 line 10 in bar",
                "affected_symbols": ["bar"],
                "fix_sketch": "bar 中加 if value is None 短路",
                "verification_plan": "run test_bar_none",
                "confidence": "medium",
            },
        ],
        "suggested_patch_briefing": "在 foo 中加入参数校验",
    }
)


def test_parse_frames_basic() -> None:
    tb = textwrap.dedent(
        """\
        Traceback (most recent call last):
          File "src/a.py", line 5, in main
            foo(x)
          File "src/b.py", line 12, in foo
            raise ValueError("bad")
        ValueError: bad
        """
    )
    frames = DebugReasoner._parse_frames(tb)
    assert len(frames) == 2
    assert frames[0].file == "src/a.py"
    assert frames[0].line == 5
    assert frames[1].function == "foo"


def test_analyse_with_mock_llm(tmp_path: Path) -> None:
    llm = MockLLM([_MOCK_HYPOTHESES])
    reasoner = DebugReasoner(llm)
    err = ValueError("something went wrong")
    tb = 'File "src/a.py", line 3, in foo\n    bad_call()\nValueError: something went wrong'
    report = reasoner.analyse(err, traceback_str=tb)
    assert report.error_type == "ValueError"
    assert len(report.hypotheses) == 2
    assert report.hypotheses[0].confidence == "high"
    best = report.best_hypothesis()
    assert best is not None and best.id == "h1"
    assert report.suggested_patch_briefing == "在 foo 中加入参数校验"


def test_analyse_enriches_frames_from_index(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "math.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    index = build_index(tmp_path)
    llm = MockLLM([_MOCK_HYPOTHESES])
    reasoner = DebugReasoner(llm, index=index, root=tmp_path)
    tb = f'File "{tmp_path / "pkg" / "math.py"}", line 2, in add\n    return a + b\nTypeError: bad'
    report = reasoner.analyse(TypeError("bad"), traceback_str=tb)
    assert report.frames
    enriched = [f for f in report.frames if f.source_context]
    assert enriched, "at least one frame should be enriched with source context"


def test_analyse_handles_llm_error(tmp_path: Path) -> None:
    from vibe_coding.nl.llm import LLMError

    class BadLLM:
        def chat(self, system, user, **kwargs):
            raise LLMError("boom")

    reasoner = DebugReasoner(BadLLM())  # type: ignore[arg-type]
    report = reasoner.analyse(RuntimeError("test"), traceback_str="")
    assert report.hypotheses == []
    assert "llm_error" in report.raw_llm_response


def test_debug_report_to_dict() -> None:
    report = DebugReport(
        error_type="TypeError",
        error_message="bad",
        traceback_str="...",
        hypotheses=[
            Hypothesis(id="h1", hypothesis="foo", evidence="bar", confidence="high")
        ],
        suggested_patch_briefing="fix foo",
    )
    d = report.to_dict()
    assert d["error_type"] == "TypeError"
    assert len(d["hypotheses"]) == 1
