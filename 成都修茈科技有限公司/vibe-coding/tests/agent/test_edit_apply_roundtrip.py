"""End-to-end test: NL brief → ProjectPatch → applied workspace → rollback."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from vibe_coding import MockLLM, VibeCoder


def _make_project(root: Path) -> None:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VERSION = '1.0'\n", encoding="utf-8")
    (root / "pkg" / "math.py").write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )


def test_edit_apply_rollback_e2e(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _make_project(project)

    patch_response = json.dumps(
        {
            "patch_id": "demo-patch",
            "summary": "double the result of add",
            "rationale": "the brief asked for it",
            "edits": [
                {
                    "path": "pkg/math.py",
                    "operation": "modify",
                    "hunks": [
                        {
                            "anchor_before": "def add(a, b):\n",
                            "old_text": "    return a + b\n",
                            "new_text": "    return (a + b) * 2\n",
                            "anchor_after": "",
                            "description": "double the sum",
                        }
                    ],
                },
                {
                    "path": "README.md",
                    "operation": "create",
                    "contents": "# proj\n",
                },
            ],
        }
    )

    llm = MockLLM([patch_response])
    coder = VibeCoder(llm=llm, store_dir=tmp_path / "store", llm_for_repair=False)

    index = coder.index_project(project)
    assert index.summary()["files"] >= 2

    patch = coder.edit_project("double the add result", root=project)
    assert patch.patch_id == "demo-patch"

    apply_result = coder.apply_patch(patch, root=project)
    assert apply_result.applied, apply_result.error
    text = (project / "pkg" / "math.py").read_text(encoding="utf-8")
    assert "(a + b) * 2" in text
    assert (project / "README.md").read_text(encoding="utf-8") == "# proj\n"

    ok = coder.rollback_patch(patch.patch_id, root=project)
    assert ok
    assert (project / "pkg" / "math.py").read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"
    assert not (project / "README.md").exists()


def test_full_rewrite_is_minimised(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _make_project(project)

    # The "lazy" LLM dropped the whole new file into ``contents`` of a
    # ``modify`` edit instead of producing hunks. The agent must downgrade
    # this to anchored hunks so the applier accepts it.
    rewritten = "def add(a, b):\n    return (a + b) * 3\n"
    patch_response = json.dumps(
        {
            "patch_id": "lazy",
            "summary": "tripled add",
            "rationale": "lazy llm",
            "edits": [
                {
                    "path": "pkg/math.py",
                    "operation": "modify",
                    "hunks": [],
                    "contents": rewritten,
                }
            ],
        }
    )
    llm = MockLLM([patch_response])
    coder = VibeCoder(llm=llm, store_dir=tmp_path / "store", llm_for_repair=False)
    patch = coder.edit_project("triple add", root=project)
    assert any(edit.hunks for edit in patch.edits), "minimiser must produce hunks"
    result = coder.apply_patch(patch, root=project)
    assert result.applied
    assert (project / "pkg" / "math.py").read_text(encoding="utf-8") == rewritten


def test_heal_project_without_tools(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _make_project(project)

    patch_response = json.dumps(
        {
            "patch_id": "heal-1",
            "summary": "trivial heal",
            "rationale": "fix",
            "edits": [
                {
                    "path": "pkg/math.py",
                    "operation": "modify",
                    "hunks": [
                        {
                            "anchor_before": "def add(a, b):\n",
                            "old_text": "    return a + b\n",
                            "new_text": "    return a + b  # fixed\n",
                            "anchor_after": "",
                        }
                    ],
                }
            ],
        }
    )
    llm = MockLLM([patch_response])
    coder = VibeCoder(llm=llm, store_dir=tmp_path / "store", llm_for_repair=False)
    result = coder.heal_project("fix the math", root=project, max_rounds=1)
    assert result.success
    assert result.final_patch_id == "heal-1"
    assert "# fixed" in (project / "pkg" / "math.py").read_text(encoding="utf-8")
