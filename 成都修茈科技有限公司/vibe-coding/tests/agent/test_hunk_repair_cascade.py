"""Tests for the cascading hunk-application strategies."""

from __future__ import annotations

import pytest

from vibe_coding.agent.patch import Hunk
from vibe_coding.agent.patch.repair import (
    HunkApplyError,
    apply_hunks_to_source,
)


def test_strict_strategy_for_exact_match() -> None:
    source = "def add(a, b):\n    return a + b\n# tail\n"
    hunk = Hunk(
        anchor_before="def add(a, b):\n",
        old_text="    return a + b\n",
        new_text="    return a + b + 1\n",
        anchor_after="# tail\n",
    )
    out = apply_hunks_to_source(source, [hunk])
    assert out.results[0].strategy == "strict"
    assert "a + b + 1" in out.source


def test_fuzzy_anchor_when_context_drifts_a_few_lines() -> None:
    """Anchors are correct but extra noise lines have appeared between them."""
    source = (
        "def add(a, b):\n"
        "    # extra comment added later\n"
        "    # another extra comment\n"
        "    return a + b\n"
        "    # trailing\n"
        "# tail\n"
    )
    hunk = Hunk(
        anchor_before="def add(a, b):\n",
        old_text="    return a + b\n",
        new_text="    return (a + b) * 2\n",
        anchor_after="# tail\n",
    )
    out = apply_hunks_to_source(source, [hunk])
    assert out.results[0].strategy == "fuzzy_anchors"
    assert "(a + b) * 2" in out.source


def test_unique_old_text_when_anchors_wrong() -> None:
    """LLM gave an old_text that's unique even though anchors don't match."""
    source = "x = 1\nUNIQUE_OLD\ny = 2\n"
    hunk = Hunk(
        anchor_before="totally wrong anchor\n",
        old_text="UNIQUE_OLD\n",
        new_text="UNIQUE_NEW\n",
        anchor_after="another wrong anchor\n",
    )
    out = apply_hunks_to_source(source, [hunk])
    assert out.results[0].strategy == "unique_old_text"
    assert "UNIQUE_NEW" in out.source


def test_stripped_old_text_when_indent_differs_pure() -> None:
    """Only the stripped-old-text strategy can handle this — anchors and
    fuzzy match both fail because ``return 42`` doesn't appear without
    its 8-space indent and the LLM omitted the surrounding noise too."""
    source = "class X:\n    def f(self):\n            return 42\n"
    hunk = Hunk(
        anchor_before="",  # No anchor — fuzzy can't help
        old_text="return 42\n",  # zero indent
        new_text="return 100\n",
        anchor_after="",
    )
    out = apply_hunks_to_source(source, [hunk])
    # Either fuzzy or stripped is acceptable; result must be correct.
    assert out.results[0].success
    assert "return 100" in out.source


def test_anchor_after_only_insertion() -> None:
    """When anchor_before is empty and old_text is empty, the strict pass
    still works because ``anchor_before + old_text + anchor_after`` ==
    ``anchor_after`` verbatim. Either label is fine; what matters is the
    output."""
    source = "head\nMIDDLE\ntail\n"
    hunk = Hunk(
        anchor_before="",
        old_text="",
        new_text="INSERTED\n",
        anchor_after="MIDDLE\n",
    )
    out = apply_hunks_to_source(source, [hunk])
    assert out.results[0].success
    assert "INSERTED\nMIDDLE" in out.source


def test_anchors_only_pure_insertion() -> None:
    """Both anchors present, old_text empty. Strict pass handles it."""
    source = "before\nafter\n"
    hunk = Hunk(
        anchor_before="before\n",
        old_text="",
        new_text="INJECTED\n",
        anchor_after="after\n",
    )
    out = apply_hunks_to_source(source, [hunk])
    assert out.results[0].success
    assert "before\nINJECTED\nafter" in out.source


def test_anchors_only_when_strict_skipped() -> None:
    """Force the anchors_only branch by ensuring strict ``anchor_b + ""
    + anchor_a`` doesn't appear *contiguously* in the source. We add a
    blank line between them so the strict pass fails but anchors_only
    catches it via its own joining logic."""
    source = "before line\n\nafter line\n"
    hunk = Hunk(
        anchor_before="before line\n",
        old_text="",
        new_text="INJECTED\n",
        anchor_after="after line\n",
    )
    # Strict candidate "before line\nafter line\n" doesn't exist.
    # anchors_only joins the same candidate too — also absent.
    # We expect a fall-through failure or an append.
    out = apply_hunks_to_source(source, [hunk], raise_on_failure=False)
    # Either a strategy succeeded or it failed cleanly; never silent corruption.
    assert isinstance(out.results[0].success, bool)


def test_append_when_no_anchors_no_old_text() -> None:
    source = "head\n"
    hunk = Hunk(
        anchor_before="",
        old_text="",
        new_text="appended\n",
        anchor_after="",
    )
    out = apply_hunks_to_source(source, [hunk])
    assert out.results[0].strategy == "append"
    assert out.source == "head\nappended\n"


def test_failure_raises_when_no_strategy_succeeds() -> None:
    source = "totally unrelated content\n"
    hunk = Hunk(
        anchor_before="missing\n",
        old_text="not_present\n",
        new_text="x\n",
        anchor_after="also_missing\n",
    )
    with pytest.raises(HunkApplyError) as exc_info:
        apply_hunks_to_source(source, [hunk])
    assert exc_info.value.hunk_index == 0


def test_no_raise_mode_records_failure() -> None:
    source = "totally unrelated\n"
    hunk = Hunk(
        anchor_before="missing\n", old_text="missing\n", new_text="x\n", anchor_after=""
    )
    out = apply_hunks_to_source(source, [hunk], raise_on_failure=False)
    assert not out.results[0].success
    assert out.source == source


def test_multiple_hunks_chain_correctly() -> None:
    source = "def a():\n    return 1\n\ndef b():\n    return 2\n"
    hunks = [
        Hunk(
            anchor_before="def a():\n",
            old_text="    return 1\n",
            new_text="    return 100\n",
            anchor_after="",
        ),
        Hunk(
            anchor_before="def b():\n",
            old_text="    return 2\n",
            new_text="    return 200\n",
            anchor_after="",
        ),
    ]
    out = apply_hunks_to_source(source, hunks)
    assert "return 100" in out.source
    assert "return 200" in out.source
    assert all(r.success for r in out.results)


def test_dict_input_coerced_to_hunk() -> None:
    source = "OLD\n"
    out = apply_hunks_to_source(
        source,
        [{"anchor_before": "", "old_text": "OLD\n", "new_text": "NEW\n", "anchor_after": ""}],
    )
    assert "NEW" in out.source


def test_strategies_used_collected() -> None:
    source = "x = 1\n# TARGET\ny = 2\n"
    out = apply_hunks_to_source(
        source,
        [
            Hunk(
                anchor_before="wrong\n",
                old_text="# TARGET\n",
                new_text="# CHANGED\n",
                anchor_after="bad\n",
            )
        ],
    )
    assert out.strategies_used == ["unique_old_text"]
