from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

FHD_ROOT = Path(__file__).resolve().parents[2]
VERIFY_PATH = FHD_ROOT / "scripts" / "deploy" / "lib" / "verify_admin_console.py"


def _verifier():
    spec = importlib.util.spec_from_file_location("verify_admin_console", VERIFY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_dist(root: Path, git_sha: str) -> None:
    (root / "assets" / "js").mkdir(parents=True)
    (root / "assets" / "js" / "app.js").write_text("console.log('ok')\n")
    (root / "index.html").write_text(
        "<html><head>"
        f'<meta name="xcmax-release-git-sha" content="{git_sha}">'
        "</head><body>"
        '<script type="module" src="/admin/assets/js/app.js"></script>'
        "</body></html>",
        encoding="utf-8",
    )


def test_admin_release_identity_detects_stale_or_mutated_assets(tmp_path: Path) -> None:
    verifier = _verifier()
    git_sha = "a" * 40
    _fake_dist(tmp_path, git_sha)

    stamped = verifier.stamp_root(tmp_path, git_sha)
    assert stamped["git_sha"] == git_sha
    assert len(stamped["sha256"]) == 64
    assert verifier.verify_root(tmp_path, git_sha, stamped["sha256"]) == stamped

    (tmp_path / "assets" / "js" / "app.js").write_text("mutated\n", encoding="utf-8")
    with pytest.raises(ValueError, match="asset tree mismatch"):
        verifier.verify_root(tmp_path, git_sha, stamped["sha256"])


def test_admin_release_identity_rejects_missing_bundle(tmp_path: Path) -> None:
    verifier = _verifier()
    git_sha = "b" * 40
    _fake_dist(tmp_path, git_sha)
    (tmp_path / "assets" / "js" / "app.js").unlink()
    with pytest.raises(ValueError, match="missing asset"):
        verifier.stamp_root(tmp_path, git_sha)


def test_fhd_release_chain_carries_and_verifies_admin_identity() -> None:
    pack = (FHD_ROOT / "scripts" / "deploy" / "fhd-pack-release.sh").read_text()
    apply_tar = (FHD_ROOT / "scripts" / "deploy" / "fhd-apply-release.sh").read_text()
    apply_image = (FHD_ROOT / "scripts" / "deploy" / "fhd-apply-release-compose.sh").read_text()
    auto_update = (FHD_ROOT / "scripts" / "deploy" / "fhd-auto-update.sh").read_text()
    push = (FHD_ROOT / "scripts" / "deploy" / "fhd-push-release.sh").read_text()
    compose = (FHD_ROOT / "docker" / "docker-compose.fhd-prod.yml").read_text()
    dockerfile = (FHD_ROOT / "docker" / "Dockerfile.fhd-api").read_text()
    workflow = (FHD_ROOT / ".github" / "workflows" / "ci-cd.yml").read_text()

    assert 'VITE_XCAGI_GIT_SHA="$GIT_SHA" npm run build' in pack
    assert '"admin_console_sha256": admin_console_sha256' in pack
    assert 'rsync -a --delete "$ADMIN_DIST/"' in pack
    assert "verify_admin_console.py" in apply_tar
    assert "ADMIN_BACKUP_PRESENT" in apply_tar
    assert "cleanup_apply" in apply_tar
    assert "verify_admin_console.py" in apply_image
    assert "FHD_ADMIN_CONSOLE_SHA256" in auto_update
    assert "fhd-release-bootstrap" in push
    assert "ADMIN_CONSOLE_SHA256" in push
    assert "XCAGI_ADMIN_CONSOLE_SHA256" in compose
    assert "templates/admin-vue-dist /app/templates/admin-vue-dist" in dockerfile
    assert "Set up Node.js for immutable admin console" in workflow
    assert "Restore CI-built admin console into image context" in workflow
    assert "--exclude 'routing_policies/routing_decisions.jsonl'" in pack
    assert "--exclude 'routing_policies/.online_update_state.json'" in pack
    assert "--exclude 'routing_policies/routing_decisions.jsonl'" in apply_tar
    assert "--exclude 'routing_policies/.online_update_state.json'" in apply_tar

    parsed = yaml.safe_load(workflow)
    jobs = parsed["jobs"]
    assert set(jobs["pack-verify"]["needs"]) == {"backend-test", "frontend-test"}
    assert "pack-verify" in jobs["container-scan"]["needs"]
    assert "container-scan" in jobs["docker-build-fhd-api"]["needs"]
    scan_rendered = str(jobs["container-scan"])
    assert "docker/Dockerfile.fhd-api" in scan_rendered
    assert "Restore CI-built admin console into scan context" in scan_rendered


def test_build_identity_exposes_admin_asset_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.build_identity import build_identity

    expected = "c" * 64
    monkeypatch.setenv("XCAGI_ADMIN_CONSOLE_SHA256", expected)
    assert build_identity()["admin_console_sha256"] == expected


def test_stamped_identity_is_stable_json(tmp_path: Path) -> None:
    verifier = _verifier()
    git_sha = "d" * 40
    _fake_dist(tmp_path, git_sha)
    stamped = verifier.stamp_root(tmp_path, git_sha)
    payload = json.loads((tmp_path / verifier.IDENTITY_NAME).read_text())
    assert payload == {
        "git_sha": git_sha,
        "schema": verifier.SCHEMA,
        "sha256": stamped["sha256"],
    }
