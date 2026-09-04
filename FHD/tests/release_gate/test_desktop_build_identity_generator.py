from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _module():
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "package"
        / "generate-desktop-build-info.py"
    )
    spec = importlib.util.spec_from_file_location("desktop_build_identity", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_desktop_identity_uses_exact_git_sha_and_release_id(tmp_path: Path) -> None:
    mod = _module()
    sha = "a" * 40
    output = tmp_path / "build-info.json"

    mod.write_build_info(version="1.0.0.1", git_sha=mod.resolve_git_sha(sha), output=output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["gitSha"] == sha
    assert payload["releaseId"] == f"xcagi-1.0.0.1-{sha}"


@pytest.mark.parametrize("invalid", ["abc123", "b" * 64, "G" * 40])
def test_desktop_identity_rejects_non_git_sha(invalid: str) -> None:
    with pytest.raises(ValueError, match="full Git SHA"):
        _module().resolve_git_sha(invalid)


def test_windows_installer_writes_same_release_identity() -> None:
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "package" / "build-installer.ps1"
    ).read_text(encoding="utf-8")
    assert "^[0-9a-fA-F]{40}$" in script
    assert '$releaseId = "xcagi-$Version-$buildSha"' in script
    assert "releaseId = $releaseId" in script
