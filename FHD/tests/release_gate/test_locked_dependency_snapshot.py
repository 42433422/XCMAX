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


def test_snapshot_uses_exact_lock_and_local_editable_metadata(tmp_path):
    mod = _module()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    uv = (
        '[[package]]\nname="Pillow"\nversion="12.3.0"\n'
        '[[package]]\nname="langgraph-local"\nversion="1.2.3"\n'
        'source = { editable = "packages/local" }\n'
        '[[package]]\nname="numpy"\nversion="2.3.0"\n'
        '[[package]]\nname="numpy"\nversion="2.4.0"\n'
    )
    for filename in mod.LOCKFILES:
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        content = (
            uv
            if filename.endswith("uv.lock")
            else "-e ../packages/local\nPillow==12.3.0\ncoverage[toml]==7.13.5\n"
            if filename == "FHD/XCAGI/requirements.lock.txt"
            else "Pillow==12.3.0\n"
        )
        path.write_text(content)
    project = tmp_path / "FHD/packages/local/pyproject.toml"
    project.parent.mkdir(parents=True)
    project.write_text('[project]\nname="langgraph-local"\nversion="1.2.3"\n')
    subprocess.run(["git", "add", "FHD"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "commit", "-qm", "pins"], cwd=tmp_path, check=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    for filename in mod.LOCKFILES:
        (tmp_path / filename).write_text("invalid dirty content\n")
    project.write_text('[project]\nname="langgraph-local"\nversion="9.9.9"\n')
    snapshot = mod.build_snapshot(tmp_path, sha, "job-1")
    requirements = snapshot["manifests"]["FHD/XCAGI/requirements.lock.txt"]["resolved"]
    assert requirements["langgraph-local"] == {"package_url": "pkg:pypi/langgraph-local@1.2.3"}
    assert requirements["coverage"] == {"package_url": "pkg:pypi/coverage@7.13.5"}
    assert {
        name
        for name in snapshot["manifests"]["FHD/uv.lock"]["resolved"]
        if name.startswith("numpy@")
    } == {
        "numpy@2.3.0",
        "numpy@2.4.0",
    }
    for invalid in ("pillow>=12.3", "-r another.txt", "pillow @ https://example.test/p.whl"):
        with pytest.raises(ValueError):
            mod.parse_pins(invalid)
    with pytest.raises(ValueError, match="duplicate"):
        mod.parse_pins("numpy==2.3.0\nnumpy==2.3.0", multiple_versions=True)
    with pytest.raises(ValueError, match="full lowercase"):
        mod.build_snapshot(tmp_path, sha[:8], "job-2")
