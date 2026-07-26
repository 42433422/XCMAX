from __future__ import annotations

from subprocess import CompletedProcess

import pytest

from modstore_server.self_maintenance_diff_quality import (
    changed_modstore_python_files,
    run_quality_tool,
)

pytestmark = pytest.mark.release_gate


def test_changed_python_files_are_complete_and_scope_limited(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    modstore_root = repo_root / "company" / "MODstore_deploy"
    modstore_root.mkdir(parents=True)
    stdout = b"\0".join(
        [
            b"company/MODstore_deploy/modstore_server/a.py",
            b"company/MODstore_deploy/tests/test_a.py",
            b"company/MODstore_deploy/market/not_python.ts",
            b"FHD/app/other.py",
            b"",
        ]
    )
    calls = []

    def _run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0:2] == ["git", "ls-files"]:
            return CompletedProcess(
                args,
                0,
                stdout=b"company/MODstore_deploy/modman/new.py\0",
                stderr=b"",
            )
        return CompletedProcess(args, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr("subprocess.run", _run)

    assert changed_modstore_python_files(
        base_ref="origin/main",
        target_ref="WORKTREE",
        repo_root=repo_root,
        modstore_root=modstore_root,
    ) == ["modman/new.py", "modstore_server/a.py", "tests/test_a.py"]
    assert calls[0][0][0:4] == [
        "git",
        "diff",
        "--name-only",
        "--diff-filter=ACMR",
    ]


def test_quality_tool_runs_black_on_every_changed_target(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    modstore_root = repo_root / "company" / "MODstore_deploy"
    modstore_root.mkdir(parents=True)
    calls = []

    def _run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0:2] == ["git", "diff"]:
            return CompletedProcess(
                args,
                0,
                stdout=(
                    b"company/MODstore_deploy/modstore_server/a.py\0"
                    b"company/MODstore_deploy/tests/test_a.py\0"
                ),
                stderr=b"",
            )
        return CompletedProcess(args, 0)

    monkeypatch.setattr("subprocess.run", _run)

    assert (
        run_quality_tool(
            tool="black",
            base_ref="origin/main",
            target_ref="HEAD",
            repo_root=repo_root,
            modstore_root=modstore_root,
        )
        == 0
    )
    assert calls[1][0][1:4] == ["-m", "black", "--check"]
    assert calls[1][0][-2:] == ["modstore_server/a.py", "tests/test_a.py"]
    assert calls[1][1]["cwd"] == modstore_root


@pytest.mark.parametrize("ref", ["", "--help", "origin/main..bad", "bad ref"])
def test_unsafe_or_ambiguous_refs_fail_closed(monkeypatch, tmp_path, ref):
    with pytest.raises(ValueError):
        changed_modstore_python_files(
            base_ref=ref,
            target_ref="HEAD",
            repo_root=tmp_path,
            modstore_root=tmp_path,
        )
