"""Unit tests for :mod:`vibe_coding.agent.patch.differ`."""

from __future__ import annotations

import pytest

from vibe_coding.agent.patch import minimise_diff
from vibe_coding.agent.patch.differ import unified_diff


def test_identical_returns_empty() -> None:
    assert minimise_diff("a\nb\n", "a\nb\n") == []


def test_pure_creation_one_hunk() -> None:
    hunks = minimise_diff("", "hello\n")
    assert len(hunks) == 1
    assert hunks[0].new_text == "hello\n"
    assert hunks[0].old_text == ""


def test_pure_deletion_one_hunk() -> None:
    hunks = minimise_diff("hello\n", "")
    assert len(hunks) == 1
    assert hunks[0].old_text == "hello\n"
    assert hunks[0].new_text == ""


def test_single_line_change_minimised() -> None:
    a = "one\ntwo\nthree\nfour\nfive\n"
    b = "one\ntwo\nTHREE\nfour\nfive\n"
    hunks = minimise_diff(a, b)
    assert len(hunks) == 1
    h = hunks[0]
    assert h.old_text == "three\n"
    assert h.new_text == "THREE\n"
    assert "two\n" in h.anchor_before
    assert "four\n" in h.anchor_after


def test_multiple_changes_become_multiple_hunks() -> None:
    a = "one\ntwo\nthree\nfour\nfive\n"
    b = "ONE\ntwo\nthree\nfour\nFIVE\n"
    hunks = minimise_diff(a, b)
    assert len(hunks) == 2


def test_round_trip_via_concat() -> None:
    a = "alpha\nbeta\ngamma\ndelta\n"
    b = "alpha\nbravo\ngamma\ndelta\n"
    hunks = minimise_diff(a, b)
    assert len(hunks) == 1
    h = hunks[0]
    rebuilt = h.anchor_before + h.new_text + h.anchor_after
    expected = h.anchor_before + h.old_text + h.anchor_after
    assert expected in a
    assert rebuilt in b


def test_unified_diff_renders_human_readable() -> None:
    out = unified_diff("a\nb\n", "a\nB\n", path="x.py")
    assert "--- a/x.py" in out
    assert "+++ b/x.py" in out
    assert "-b" in out
    assert "+B" in out
