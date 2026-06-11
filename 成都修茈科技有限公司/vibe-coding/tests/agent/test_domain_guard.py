"""Tests for :class:`ProjectDomainGuard`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibe_coding import MockLLM, VibeCoder
from vibe_coding.agent.domain import (
    DomainViolation,
    ProjectDomainGuard,
)
from vibe_coding.agent.patch import FileEdit, Hunk, ProjectPatch


def _make_patch(*edits: FileEdit, summary: str = "test") -> ProjectPatch:
    return ProjectPatch(patch_id="t-1", summary=summary, edits=list(edits))


def test_allowed_paths_accepts_match() -> None:
    guard = ProjectDomainGuard(allowed_paths=("src/**",))
    patch = _make_patch(
        FileEdit(path="src/foo.py", operation="create", contents="x = 1\n")
    )
    assert guard.is_safe(patch)


def test_allowed_paths_rejects_outside() -> None:
    guard = ProjectDomainGuard(allowed_paths=("src/**",))
    patch = _make_patch(
        FileEdit(path="docs/secret.md", operation="create", contents="x")
    )
    violations = guard.validate(patch)
    assert any(v.code == "path_not_allowed" for v in violations)


def test_forbidden_paths_blocks_match() -> None:
    guard = ProjectDomainGuard(forbidden_paths=("**/.env", "secrets/*"))
    patch = _make_patch(
        FileEdit(path="secrets/keys.txt", operation="create", contents="x")
    )
    violations = guard.validate(patch)
    assert any(v.code == "path_forbidden" for v in violations)


def test_max_files_changed_enforced() -> None:
    guard = ProjectDomainGuard(max_files_changed=2)
    patch = _make_patch(
        FileEdit(path="a.py", operation="create", contents="x"),
        FileEdit(path="b.py", operation="create", contents="x"),
        FileEdit(path="c.py", operation="create", contents="x"),
    )
    violations = guard.validate(patch)
    assert any(v.code == "too_many_files" for v in violations)


def test_max_lines_added_enforced() -> None:
    guard = ProjectDomainGuard(max_lines_added=5)
    huge_content = "\n".join(f"line {i}" for i in range(100)) + "\n"
    patch = _make_patch(
        FileEdit(path="a.py", operation="create", contents=huge_content)
    )
    violations = guard.validate(patch)
    assert any(v.code == "too_many_lines" for v in violations)


def test_forbidden_python_imports() -> None:
    guard = ProjectDomainGuard(forbidden_imports=("subprocess", "os.system"))
    patch = _make_patch(
        FileEdit(
            path="a.py",
            operation="create",
            contents="import subprocess\nimport os\n",
        )
    )
    violations = guard.validate(patch)
    assert any(v.code == "forbidden_import" for v in violations)


def test_forbidden_js_imports() -> None:
    guard = ProjectDomainGuard(forbidden_imports=("child_process", "fs"))
    patch = _make_patch(
        FileEdit(
            path="x.ts",
            operation="create",
            contents=(
                "import { exec } from 'child_process';\n"
                "const fs = require('fs');\n"
            ),
        )
    )
    violations = guard.validate(patch)
    forbidden_codes = [v for v in violations if v.code == "forbidden_import"]
    assert len(forbidden_codes) >= 2


def test_custom_predicate_runs() -> None:
    def predicate(p: ProjectPatch) -> str:
        if "secret" in p.summary.lower():
            return "summary mentions a secret"
        return ""

    guard = ProjectDomainGuard(custom_predicates=(predicate,))
    patch = _make_patch(
        FileEdit(path="a.py", operation="create", contents="x"),
        summary="add new secret to config",
    )
    violations = guard.validate(patch)
    assert any(v.code == "custom_predicate" for v in violations)


def test_custom_predicate_error_caught() -> None:
    def predicate(p: ProjectPatch) -> str:
        raise RuntimeError("boom")

    guard = ProjectDomainGuard(custom_predicates=(predicate,))
    patch = _make_patch(FileEdit(path="a.py", operation="create", contents="x"))
    violations = guard.validate(patch)
    assert any(v.code == "predicate_error" for v in violations)


def test_violation_to_dict() -> None:
    v = DomainViolation(code="x", message="y", file="a.py")
    assert v.to_dict() == {"code": "x", "message": "y", "file": "a.py"}


def test_modified_file_with_added_import_caught() -> None:
    guard = ProjectDomainGuard(forbidden_imports=("subprocess",))
    patch = _make_patch(
        FileEdit(
            path="a.py",
            operation="modify",
            hunks=[
                Hunk(
                    anchor_before="x = 1\n",
                    old_text="x = 1\n",
                    new_text="import subprocess\nx = 1\n",
                    anchor_after="",
                )
            ],
        )
    )
    violations = guard.validate(patch)
    assert any(v.code == "forbidden_import" for v in violations)


def test_existing_import_in_old_text_not_flagged() -> None:
    """If the file already has the import (in old_text), don't re-flag it."""
    guard = ProjectDomainGuard(forbidden_imports=("subprocess",))
    patch = _make_patch(
        FileEdit(
            path="a.py",
            operation="modify",
            hunks=[
                Hunk(
                    anchor_before="",
                    old_text="import subprocess\nx = 1\n",
                    new_text="import subprocess\nx = 2\n",
                    anchor_after="",
                )
            ],
        )
    )
    assert guard.is_safe(patch)


# ----------------------------------------------------------------- integration


def test_guard_blocks_apply_when_attached(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.py").write_text("x = 1\n", encoding="utf-8")

    patch_response = json.dumps(
        {
            "patch_id": "blocked",
            "summary": "tries to write outside allowed",
            "rationale": "",
            "edits": [
                {
                    "path": "secrets/keys.txt",
                    "operation": "create",
                    "contents": "leaked\n",
                }
            ],
        }
    )

    llm = MockLLM([patch_response])
    coder = VibeCoder(llm=llm, store_dir=tmp_path / "store", llm_for_repair=False)
    pc = coder.project_coder(project)
    pc.domain_guard = ProjectDomainGuard(allowed_paths=("src/**", "*.py"))
    patch = pc.edit_project("write secrets")
    result = pc.apply_patch(patch)
    assert not result.applied
    assert "domain_guard" in result.error
    assert not (project / "secrets" / "keys.txt").exists()


def test_guard_per_call_override(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.py").write_text("x = 1\n", encoding="utf-8")

    patch_response = json.dumps(
        {
            "patch_id": "ok",
            "summary": "harmless",
            "rationale": "",
            "edits": [
                {"path": "b.py", "operation": "create", "contents": "y = 2\n"}
            ],
        }
    )

    llm = MockLLM([patch_response])
    coder = VibeCoder(llm=llm, store_dir=tmp_path / "store", llm_for_repair=False)
    pc = coder.project_coder(project)
    patch = pc.edit_project("add b")
    # Per-call guard rejects everything outside src/.
    result = pc.apply_patch(
        patch,
        domain_guard=ProjectDomainGuard(allowed_paths=("src/**",)),
    )
    assert not result.applied
    assert "domain_guard" in result.error
