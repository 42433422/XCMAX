"""GitHub Release notes and publication depend on exact approved release identity."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "FHD/scripts/release/render_github_release_notes.py"
SHA = "a" * 40
VERSION = "1.0.0.7"


def module():
    spec = importlib.util.spec_from_file_location("release_notes", SRC)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pointer():
    return {"schema": "xcagi.download_release.public/v1",
            "release_ready": True, "version_lock": VERSION,
            "download_version": VERSION, "git_sha": SHA,
            "release_id": f"xcagi-{VERSION}-{SHA}",
            "manifest_url": f"https://xiu-ci.com/xcagi-v{VERSION}/manifest.json",
            "release_history": [{"version": VERSION, "title": "Release",
                                 "notes": ["Fixed release pipeline", "Public readback"]}]}


def test_notes_are_read_from_published_pointer():
    body = module().render(pointer(), VERSION, SHA)
    assert "# XCAGI 1.0.0.7 — Release" in body
    assert "Fixed release pipeline" in body and "Public readback" in body
    assert SHA in body and "manifest.json" in body


@pytest.mark.parametrize("change", [
    {"release_ready": False},
    {"git_sha": "b" * 40},
    {"release_history": []},
    {"manifest_url": "https://evil.invalid/manifest.json"},
])
def test_unverified_release_is_not_rendered(change):
    with pytest.raises(ValueError):
        module().render({**pointer(), **change}, VERSION, SHA)


def test_release_is_draft_until_orchestrator_convergence():
    desktop = (ROOT / "FHD/.github/workflows/release-desktop.yml").read_text()
    orchestrator = (ROOT / "FHD/.github/workflows/release-orchestrator.yml").read_text()
    assert "startsWith(github.ref, 'refs/tags/')" not in desktop
    assert "tag_name: FHD/v${{ inputs.version }}" in desktop
    assert "draft: true" in desktop
    assert "render_github_release_notes.py" in desktop
    assert "publish-converged-github-release:" in orchestrator
    assert "needs: [verify-full-convergence]" in orchestrator
    assert 'gh release edit "$tag" --repo "$GH_REPO" --draft=false' in orchestrator
