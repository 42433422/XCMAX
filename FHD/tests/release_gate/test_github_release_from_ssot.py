"""GitHub Release notes and publication depend on exact approved release identity."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

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
    [
        "FHD/.github/workflows/release-orchestrator.yml",
        ".github/workflows/fhd-release-orchestrator.yml",
    ],
)
def test_client_dispatch_loads_only_the_validated_main_helper(workflow):
    text = (ROOT / workflow).read_text()
    job = text.split("  dispatch-client-releases:", 1)[1].split("  verify-full-convergence:", 1)[0]
    assert "needs: [verify-version-anchors, build-frontend, deploy-servers-in-order]" in job
    verify_ref = job.index('if [[ "$GITHUB_REF" != refs/heads/main ]]')
    verify_sha = job.index("git/ref/heads/main")
    checkout = job.index("uses: actions/checkout@v4")
    assert job.index("working-directory: .") < checkout
    assert verify_ref < verify_sha < checkout
    assert "ref: ${{ inputs.release_sha }}\n          persist-credentials: false" in job
    assert (
        checkout
        < job.index('test "$(git rev-parse HEAD)"')
        < job.index("FHD/scripts/release/dispatch_workflow_and_wait.sh")
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
            {"name": name, "state": "uploaded", **entry} for name, entry in inventory.items()
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


@pytest.mark.parametrize(
    "drift",
    [
        None,
        "tag",
        "missing_tag",
        "sha",
        "asset",
        "published_at",
        "public",
        "production",
        "main",
        "orchestrator",
    ],
)
def test_published_release_retry_only_reads_the_same_frozen_evidence(tmp_path, formal, drift):
    """Run the real shell and identity verifier; only GitHub/HTTPS I/O is inert."""
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    data = json.loads(json.dumps(formal).replace(SHA, sha))
    proof = tmp_path / "formal-release"
    fixtures = tmp_path / "fixtures"
    binary = tmp_path / "bin"
    for directory in (proof, fixtures, binary):
        directory.mkdir()

    def save(name, value):
        (fixtures / name).write_text(json.dumps(value), encoding="utf-8")

    for name, key in (
        ("public-pointer.json", "pointer"),
        ("download-release.json", "pointer"),
        ("manifest.json", "manifest"),
        ("public-manifest.json", "public_manifest"),
        ("stable-manifest.json", "stable_manifest"),
        ("asset-inventory.json", "inventory"),
        ("release-convergence.json", "convergence"),
    ):
        save(name, data[key])
    for name, signature in zip(
        ("windows-signature.json", "mac-signatures.jsonl"), data["signatures"], strict=True
    ):
        save(name, signature)
    (proof / "production-deployment.json").write_text(json.dumps(data["deployment"]))
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "release": {**data["github_release"], "id": 17},
                "tag": None,
                "writes": [],
                "fail_readback": True,
            }
        )
    )
    boundary = "#!/usr/bin/env python3\n" + textwrap.dedent(
        """\
        import json, os, shutil, sys
        from pathlib import Path
        args = sys.argv[1:]
        state_path = Path(os.environ['RELEASE_TEST_STATE'])
        state = json.loads(state_path.read_text())
        fixtures = Path(os.environ['RELEASE_TEST_FIXTURES'])
        sha = os.environ['RELEASE_SHA']
        def persist():
            state_path.write_text(json.dumps(state))
        if Path(sys.argv[0]).name == 'curl':
            if not state['release']['draft'] and state['fail_readback']:
                state['fail_readback'] = False
                persist()
                print('temporary public readback failure', file=sys.stderr)
                sys.exit(22)
            name = Path(args[args.index('-o') + 1]).name
            shutil.copyfile(fixtures / name, args[args.index('-o') + 1])
        elif args[:2] == ['run', 'download']:
            names = {
                'xcagi-download-manifest': ['manifest.json', 'download-release.json'],
                'xcagi-mac-release-signatures': ['mac-signatures.jsonl'],
                'xcagi-windows-release-signature': ['windows-signature.json'],
                'xcagi-github-release-asset-inventory': ['asset-inventory.json'],
                'xcagi-release-convergence': ['release-convergence.json'],
            }[args[args.index('--name') + 1]]
            for name in names:
                shutil.copyfile(fixtures / name, Path(args[args.index('--dir') + 1]) / name)
        elif args[0] == 'api':
            path = next(arg for arg in args if arg.startswith('repos/'))
            method = args[args.index('--method') + 1] if '--method' in args else 'GET'
            if method == 'POST' and path.endswith('/git/refs'):
                state['writes'].append('POST')
                state['tag'] = next(arg[4:] for arg in args if arg.startswith('sha='))
                persist()
            elif method == 'PATCH' and path.endswith('/releases/17'):
                assert 'draft=false' in args
                state['writes'].append('PATCH')
                state['release'].update(draft=False, published_at='2026-11-20T00:00:00Z')
                persist()
            elif path.endswith('/actions/runs/12'):
                print(json.dumps({'head_sha': sha, 'head_branch': 'main',
                    'event': 'workflow_dispatch', 'path': '.github/workflows/fhd-release-desktop.yml',
                    'conclusion': 'success'}))
            elif '/releases?' in path:
                print(json.dumps([[state['release']]]))
            elif path.endswith('/releases/17'):
                print(json.dumps(state['release']))
            elif path.endswith('/git/ref/heads/main'):
                print(state.get('main_sha', sha))
            elif '/git/ref/tags/' in path:
                if state['tag'] is None: sys.exit(1)
                print(state['tag'])
            else:
                raise AssertionError(args)
        else:
            raise AssertionError(args)
        """
    )
    for name in ("gh", "curl"):
        executable = binary / name
        executable.write_text(boundary)
        executable.chmod(0o755)
    runs = []
    for path in (
        ROOT / "FHD/.github/workflows/release-orchestrator.yml",
        ROOT / ".github/workflows/fhd-release-orchestrator.yml",
    ):
        job = yaml.safe_load(path.read_text())["jobs"]["publish-converged-github-release"]
        runs.append(next(step["run"] for step in job["steps"] if "run" in step))
    assert runs[0] == runs[1]
    verifier_log = tmp_path / "verifier.log"
    env = {
        **os.environ,
        "PATH": f"{binary}:{Path(sys.executable).parent}:{os.environ['PATH']}",
        "RELEASE_TEST_STATE": str(state_path),
        "RELEASE_TEST_FIXTURES": str(fixtures),
        "RELEASE_SHA": sha,
        "PRODUCT_VERSION": VERSION,
        "CONVERGENCE_RUN": "44",
        "GITHUB_RUN_ID": "33",
        "GH_REPO": "fixture/release",
        "RUNNER_TEMP": str(tmp_path),
        "VERIFIER_LOG": str(verifier_log),
    }
    command = (
        'python3() { printf "%s\\n" "$*" >> "$VERIFIER_LOG"; command python3 "$@"; }\n' + runs[0]
    )

    def run():
        return subprocess.run(
            ["bash", "-c", command],
            cwd=ROOT / "FHD",
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    first = run()
    assert first.returncode == 22, first.stdout + first.stderr
    assert "temporary public readback failure" in first.stderr
    state = json.loads(state_path.read_text())
    assert state["writes"] == ["POST", "PATCH"] and state["release"]["draft"] is False
    if drift == "tag":
        state["tag"] = "b" * 40
    elif drift == "missing_tag":
        state["tag"] = None
    elif drift == "sha":
        state["release"]["target_commitish"] = "b" * 40
    elif drift == "asset":
        state["release"]["assets"][0]["digest"] = "sha256:" + "b" * 64
    elif drift == "published_at":
        state["release"].pop("published_at")
    elif drift == "public":
        save("public-pointer.json", {**data["pointer"], "git_sha": "b" * 40})
    elif drift == "production":
        data["convergence"]["data"]["sources"][2]["artifact_sha256"] = "b" * 64
        save("release-convergence.json", data["convergence"])
    elif drift == "main":
        state["main_sha"] = "b" * 40
    elif drift == "orchestrator":
        env["GITHUB_RUN_ID"] = "34"
    state_path.write_text(json.dumps(state))
    before = verifier_log.read_text().splitlines()
    second = run()
    assert json.loads(state_path.read_text())["writes"] == ["POST", "PATCH"]
    if drift is None:
        assert second.returncode == 0, second.stdout + second.stderr
        retried = verifier_log.read_text().splitlines()[len(before) :]
        assert len(retried) == 1 and retried[0].endswith("--published")
        assert json.loads(second.stdout)["git_sha"] == sha
    else:
        assert second.returncode != 0, "Published identity drift must still fail closed"
