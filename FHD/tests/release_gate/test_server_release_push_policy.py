import hashlib
import json
import os
import subprocess
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = FHD_ROOT.parent


def test_normal_cvm_release_skips_optional_image_archive() -> None:
    script = (FHD_ROOT / "scripts/deploy/fhd-push-release.sh").read_text(encoding="utf-8")

    assert 'PUSH_IMAGE_TAR="${FHD_PUSH_IMAGE_TAR:-auto}"' in script
    assert '"${DEPLOY_MODE:-tarball}" == "image"' in script
    assert '[[ -f "$IMAGE_TAR" && "$PUSH_IMAGE_TAR" == "1" ]]' in script
    assert 'deploy_emit push skipped "artifact=fhd-api-image.tar.gz reason=optional"' in script


def test_tarball_push_does_not_scp_optional_image_archive(tmp_path: Path) -> None:
    out_dir = tmp_path / "dist"
    out_dir.mkdir()
    artifact = out_dir / "fhd-full-1.0.0.0-test.tar.gz"
    artifact.write_bytes(b"server-release")
    (out_dir / "fhd-api-image.tar.gz").write_bytes(b"optional-image")
    (out_dir / "fhd-manifest.json").write_text(
        json.dumps(
            {
                "artifact": artifact.name,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "version": "1.0.0.0",
                "git_sha": "test-sha",
                "deploy_mode": "tarball",
            }
        ),
        encoding="utf-8",
    )

    calls = tmp_path / "calls.log"
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    for name, body in {
        "scp": '#!/usr/bin/env bash\nprintf "scp %s\\n" "$*" >> "$CALLS_LOG"\n',
        "ssh": (
            '#!/usr/bin/env bash\nprintf "ssh %s\\n" "$*" >> "$CALLS_LOG"\nprintf \'OK_MOVED\\n\'\n'
        ),
    }.items():
        executable = mock_bin / name
        executable.write_text(body, encoding="utf-8")
        executable.chmod(0o755)

    result = subprocess.run(
        ["bash", str(FHD_ROOT / "scripts/deploy/fhd-push-release.sh")],
        cwd=FHD_ROOT,
        env={
            **os.environ,
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "CALLS_LOG": str(calls),
            "FHD_SKIP_PACK": "1",
            "FHD_RELEASE_OUT_DIR": str(out_dir),
            "FHD_PUSH_HOST": "example.invalid",
            "FHD_PUSH_IMAGE_TAR": "0",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    call_log = calls.read_text(encoding="utf-8")
    assert artifact.name in call_log
    assert "fhd-manifest.json" in call_log
    assert "fhd-api-image.tar.gz" not in call_log
    assert "跳过可选镜像归档" in result.stdout


def test_ci_requires_explicit_manual_opt_in_for_image_archive() -> None:
    source = (FHD_ROOT / ".github/workflows/ci-cd.yml").read_text(encoding="utf-8")
    published = (REPO_ROOT / ".github/workflows/fhd-ci-cd.yml").read_text(encoding="utf-8")

    for workflow in (source, published):
        assert "push_image_tar:" in workflow
        assert (
            "group: cvm-push-release-${{ github.event_name == 'workflow_dispatch' "
            "&& inputs.release_channel || (contains(github.ref, '-rc') "
            "&& 'staging' || 'stable') }}"
        ) in workflow
        assert "cancel-in-progress: true" in workflow
        assert (
            "FHD_PUSH_IMAGE_TAR: ${{ github.event_name == 'workflow_dispatch' "
            "&& inputs.push_image_tar && '1' || '0' }}"
        ) in workflow
        assert (
            "FHD_CVM_PUSH_TIMEOUT: ${{ github.event_name == 'workflow_dispatch' "
            "&& inputs.push_image_tar && '55m' || '15m' }}"
        ) in workflow
