"""GitHub Release notes and publication depend on exact approved release identity."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.release.verify_formal_release_identity import deployment_identity, verify

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
    return {
        "schema": "xcagi.download_release.public/v1",
        "release_ready": True,
        "version_lock": VERSION,
        "download_version": VERSION,
        "git_sha": SHA,
        "release_id": f"xcagi-{VERSION}-{SHA}",
        "manifest_url": f"https://xiu-ci.com/releases/builds/{VERSION}/{SHA}/manifest.json",
        "release_history": [
            {
                "version": VERSION,
                "title": "Release",
                "notes": ["Fixed release pipeline", "Public readback"],
            }
        ],
    }


def test_notes_are_read_from_published_pointer():
    body = module().render(pointer(), VERSION, SHA)
    assert "# XCAGI 1.0.0.7 — Release" in body
    assert "Fixed release pipeline" in body and "Public readback" in body
    assert SHA in body and "manifest.json" in body


@pytest.mark.parametrize(
    "change",
    [
        {"release_ready": False},
        {"git_sha": "b" * 40},
        {"release_history": []},
        {"manifest_url": "https://evil.invalid/manifest.json"},
    ],
)
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
    assert "verify_formal_release_identity.py" in orchestrator
    assert desktop.index('cmp "$proof/production-deployment.json"') < desktop.index(
        "Publish unified Windows + macOS release"
    )
    assert (
        'gh api --method PATCH "repos/${GH_REPO}/releases/${github_release_id}" -F draft=false'
        in orchestrator
    )


@pytest.mark.parametrize(
    "workflow",
    ["FHD/.github/workflows/release-orchestrator.yml", ".github/workflows/fhd-release-orchestrator.yml"],
)
def test_client_dispatch_loads_only_the_validated_main_helper(workflow):
    text = (ROOT / workflow).read_text()
    job = text.split("  dispatch-client-releases:", 1)[1].split("  verify-full-convergence:", 1)[0]
    assert "needs: [verify-version-anchors, build-frontend, deploy-servers-in-order]" in job
    verify_ref = job.index('if [[ "$GITHUB_REF" != refs/heads/main ]]')
    verify_sha = job.index('git/ref/heads/main')
    checkout = job.index("uses: actions/checkout@v4")
    assert job.index("working-directory: .") < checkout
    assert verify_ref < verify_sha < checkout
    assert "ref: ${{ inputs.release_sha }}\n          persist-credentials: false" in job
    assert checkout < job.index('test "$(git rev-parse HEAD)"') < job.index(
        "FHD/scripts/release/dispatch_workflow_and_wait.sh"
    )


@pytest.fixture
def formal():
    release_id = f"xcagi-{VERSION}-{SHA}"
    identity = {"git_sha": SHA, "version": VERSION, "build_workflow_run_id": "12"}
    frozen = {"build_workflow_run_id": "12", "frontend_workflow_run_id": "33"}
    public = {**pointer(), **frozen}
    base = public["manifest_url"].removesuffix("/manifest.json")
    signatures = [
        {
            **identity,
            "filename": name,
            "sha256": digest * 64,
            "size": 10,
            "verifier": verifier,
        }
        for name, digest, verifier in [
            ("enterprise.exe", "c", "authenticode"),
            ("enterprise.dmg", "d", "codesign_stapler"),
        ]
    ]
    win, mac = [
        {
            **{k: row[k] for k in ("filename", "sha256", "size")},
            "url": f"{base}/enterprise/{row['filename']}",
        }
        for row in signatures
    ]
    manifest = {
        **identity,
        **frozen,
        "schema": "xcagi.download_manifest/v1",
        "release_id": release_id,
        "release_ready": True,
        "channels": {
            name: {"enterprise": {"win": win, "mac": [mac]}}
            for name in ("official_download", "auto_update")
        },
    }
    inventory = {
        row["filename"]: {"size": row["size"], "digest": f"sha256:{row['sha256']}"}
        for row in signatures
    } | {"latest-mac.yml": {"size": 1, "digest": "sha256:" + "f" * 64}}
    sources = [
        {
            "name": name,
            "status": "matched",
            "git_sha": SHA,
            "release_id": release_id,
            "artifact_sha256": "e" * 64,
        }
        for name in (
            "origin_main",
            "modstore_production",
            "fhd_production",
            "desktop_stable_manifest",
            "windows_stable_feed",
            "macos_stable_feed",
        )
    ]
    convergence = {
        "ok": True,
        "data": {
            "schema": "release-convergence/v1",
            "release_sha": SHA,
            "release_id": release_id,
            "sources": sources,
            "converged": True,
            "blockers": [],
        },
    }
    draft = {
        "draft": True,
        "prerelease": False,
        "tag_name": f"FHD/v{VERSION}",
        "target_commitish": SHA,
        "assets": [
            {"name": name, "state": "uploaded", **entry}
            for name, entry in inventory.items()
        ],
    }
    return {
        "pointer": public,
        "manifest": manifest,
        "public_manifest": deepcopy(manifest),
        "stable_manifest": deepcopy(manifest),
        "signatures": signatures,
        "convergence": convergence,
        "inventory": inventory,
        "deployment": deployment_identity(
            convergence, sha=SHA, version=VERSION, orchestrator_run="33"
        ),
        "github_release": draft,
        "sha": SHA,
        "version": VERSION,
        "desktop_run": "12",
        "orchestrator_run": "33",
    }


def test_formal_release_requires_all_identity_sources(formal):
    result = verify(**formal)
    assert result["git_sha"] == SHA
    assert len(result["installers"]) == 2
    formal["github_release"].update(draft=False, published_at="2026-11-20T00:00:00Z")
    assert verify(**formal, published=True) == result


@pytest.mark.parametrize(
    "path,value,message",
    [
        (("pointer", "release_id"), None, "release_id_missing"),
        (("pointer", "release_ready"), False, "release_not_ready"),
        (("stable_manifest", "git_sha"), "b" * 40, "frozen desktop build"),
        (("signatures", 0, "sha256"), "b" * 64, "signature receipt"),
        (
            ("github_release", "assets", 2, "digest"),
            "sha256:" + "b" * 64,
            "frozen build",
        ),
        (
            ("convergence", "data", "sources", 2, "artifact_sha256"),
            "b" * 64,
            "deployed artifacts",
        ),
    ],
)
def test_formal_identity_drift_blocks_promotion(formal, path, value, message):
    target = formal
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=message):
        verify(**formal)
