"""A rotated release directory must not break a remote Git branch check."""

import os
import subprocess
from pathlib import Path

from modstore_server.para_delegate_handler_merged import _git_preflight_branch


def test_git_preflight_survives_deleted_process_working_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("MODSTORE_PARA_SKIP_GIT_PREFLIGHT", raising=False)
    repo = tmp_path / "repository"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    original = Path.cwd()
    retired = tmp_path / "retired-release"
    retired.mkdir()
    try:
        os.chdir(retired)
        retired.rmdir()
        assert _git_preflight_branch(str(repo), "main") == {"ok": True}
        missing = _git_preflight_branch(str(repo), "missing-branch")
        assert not missing["ok"] and missing["failure_kind"] == "git_prep"
    finally:
        os.chdir(original)
