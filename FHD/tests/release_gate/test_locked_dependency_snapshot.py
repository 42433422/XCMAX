from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


def _module():
    path = (
        Path(__file__).resolve().parents[2]
        / "scripts/security/export_locked_dependency_snapshot.py"
    )
    spec = importlib.util.spec_from_file_location("locked_dependency_snapshot", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_retains_every_pin_and_normalizes_names():
    parsed = _module().parse_pins(
        "# generated\nPillow==12.3.0\n    # via pdfplumber\ncoverage[toml]==7.13.5\na_b.c==1.2.3+local\n"
    )
    assert parsed == {
        "pillow": {"package_url": "pkg:pypi/pillow@12.3.0"},
        "coverage": {"package_url": "pkg:pypi/coverage@7.13.5"},
        "a-b-c": {"package_url": "pkg:pypi/a-b-c@1.2.3%2Blocal"},
    }


@pytest.mark.parametrize(
    "content",
    [
        "",
        "# empty",
        "pillow>=12.3",
        "pillow==12.*",
        "-r another.txt",
        "pillow @ https://example.test/p.whl",
        "pillow==12.3.0\nPillow==12.2.0",
        "pillow==12.3.0; sys_platform == 'darwin'",
    ],
)
def test_ambiguous_or_incomplete_lockfiles_fail_closed(content):
    with pytest.raises(ValueError):
        _module().parse_pins(content)


def test_snapshot_uses_commit_content_not_dirty_worktree(tmp_path):
    mod = _module()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for filename in mod.LOCKFILES:
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '[[package]]\nname="Pillow"\nversion="12.3.0"\n'
            if filename.endswith("uv.lock")
            else "pillow==12.3.0\n"
        )
        subprocess.run(["git", "add", filename], cwd=tmp_path, check=True)
    settings = ["user.name=Test", "user.email=test@example.invalid", "commit.gpgsign=false"]
    subprocess.run(
        ["git", *[arg for setting in settings for arg in ("-c", setting)], "commit", "-qm", "pins"],
        cwd=tmp_path,
        check=True,
    )
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    for filename in mod.LOCKFILES:
        (tmp_path / filename).write_text("invalid dirty content\n")
    first = mod.build_snapshot(tmp_path, sha, "job-1")
    second = mod.build_snapshot(tmp_path, sha, "job-2")
    assert first["job"]["correlator"] == second["job"]["correlator"]
    assert first["detector"] == second["detector"]
    assert all(
        row["package_url"] == "pkg:pypi/pillow@12.3.0"
        for m in first["manifests"].values()
        for row in m["resolved"].values()
    )
    with pytest.raises(ValueError, match="full lowercase"):
        mod.build_snapshot(tmp_path, sha[:8], "job-3")


def test_uv_keeps_distinct_platform_versions_and_rejects_duplicate_exact_pin():
    mod = _module()
    pins = "numpy==2.3.0\nnumpy==2.4.0"
    assert len(mod.parse_pins(pins, multiple_versions=True)) == 2
    with pytest.raises(ValueError, match="duplicate"):
        mod.parse_pins(pins + "\nnumpy==2.3.0", multiple_versions=True)
