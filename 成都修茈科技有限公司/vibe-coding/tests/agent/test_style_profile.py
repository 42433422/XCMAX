"""Tests for :class:`StyleProfile` extraction from a :class:`RepoIndex`."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from vibe_coding.agent.memory.style import StyleProfile
from vibe_coding.agent.repo_index import build_index


def _make_well_typed_project(root: Path) -> None:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "math.py").write_text(
        textwrap.dedent(
            '''\
            """Math utilities."""
            import dataclasses
            from typing import Protocol


            def add(a: int, b: int) -> int:
                """Add two integers."""
                return a + b


            async def fetch(url: str) -> dict:
                """Fetch data."""
                return {"url": url}


            class ICalc(Protocol):
                """Calculator protocol."""

                def total(self, values: list[int]) -> int: ...


            @dataclasses.dataclass
            class Point:
                """A 2D point."""

                x: float = 0.0
                y: float = 0.0
            '''
        ),
        encoding="utf-8",
    )


def test_style_from_well_typed_project(tmp_path: Path) -> None:
    _make_well_typed_project(tmp_path)
    index = build_index(tmp_path)
    profile = StyleProfile.from_index(index)

    assert profile.naming_convention == "snake_case"
    assert profile.type_hint_rate > 0.5
    assert profile.docstring_rate > 0.5
    assert profile.has_async is True
    assert profile.uses_dataclasses is True
    assert profile.uses_protocols is True


def test_style_empty_project(tmp_path: Path) -> None:
    (tmp_path / "empty.py").write_text("", encoding="utf-8")
    index = build_index(tmp_path)
    profile = StyleProfile.from_index(index)
    assert isinstance(profile.naming_convention, str)
    assert 0.0 <= profile.type_hint_rate <= 1.0


def test_style_roundtrip_dict() -> None:
    profile = StyleProfile(
        naming_convention="camelCase",
        type_hint_rate=0.8,
        docstring_rate=0.5,
        common_imports=["os", "json"],
        uses_dataclasses=True,
    )
    d = profile.to_dict()
    restored = StyleProfile.from_dict(d)
    assert restored.naming_convention == "camelCase"
    assert restored.type_hint_rate == 0.8
    assert restored.uses_dataclasses is True


def test_style_to_prompt_block_renders_text(tmp_path: Path) -> None:
    _make_well_typed_project(tmp_path)
    index = build_index(tmp_path)
    profile = StyleProfile.from_index(index)
    block = profile.to_prompt_block()
    assert "风格" in block or "style" in block.lower()
    assert "snake_case" in block or "camel" in block.lower()
