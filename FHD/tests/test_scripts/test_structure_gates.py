"""First-party structure counts must not depend on submodule checkout state."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "check_structure_gates.py"
SPEC = importlib.util.spec_from_file_location("structure_gates", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gates = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gates)


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def test_initialized_submodule_does_not_change_first_party_gates(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "host"
    child = tmp_path / "child"
    repo.mkdir()
    child.mkdir()
    git(repo, "init", "-q")
    git(child, "init", "-q")
    for name in ("giant.py", "ports.py", "blueprints.py"):
        (child / name).write_text("#" + "x" * 100_001, encoding="utf-8")
    git(child, "add", ".")
    git(
        child,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )

    (repo / "FHD/app/fastapi_routes").mkdir(parents=True)
    # A similarly named ordinary directory remains host-owned and must still count.
    ordinary = repo / "external/ordinary"
    ordinary.mkdir(parents=True)
    (ordinary / "giant.py").write_text("#" + "x" * 100_001, encoding="utf-8")
    submodule = "external/独立 child"
    git(
        repo,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(child),
        submodule,
    )

    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--repo", str(repo), "--fail-on-warn"])
    initialized_status = gates.main()
    initialized = capsys.readouterr()
    assert "py>40KB=1 testish=0" in initialized.out
    assert "py>100KB nontest=1" in initialized.out
    assert "ports_repo_wide=0" in initialized.out
    assert "blueprints.py=0" in initialized.out

    git(repo, "submodule", "deinit", "--force", "--", submodule)
    assert not (repo / submodule / "giant.py").exists()
    assert gates.main() == initialized_status
    assert capsys.readouterr() == initialized

    git(
        repo,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "update",
        "--init",
        "--",
        submodule,
    )
    assert (repo / submodule / "giant.py").exists()
    assert gates.main() == initialized_status
    assert capsys.readouterr() == initialized


def test_missing_git_ownership_fails_instead_of_reporting_partial_counts(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "FHD/app").mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--repo", str(tmp_path)])
    assert gates.main() == 3
    result = capsys.readouterr()
    assert "cannot read Git index ownership" in result.err
    assert "py>40KB" not in result.out
