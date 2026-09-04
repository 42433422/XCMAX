from __future__ import annotations

import json

from app.build_identity import build_identity


def test_build_identity_prefers_injected_exact_sha(monkeypatch, tmp_path) -> None:
    (tmp_path / ".build-identity.json").write_text(
        json.dumps({"git_sha": "packaged", "built_at": "2026-07-21T00:00:00Z"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FHD_DEPLOY_ROOT", str(tmp_path))
    monkeypatch.setenv("XCAGI_GIT_SHA", "a" * 40)
    monkeypatch.setenv("XCAGI_IMAGE_DIGEST", "sha256:" + "b" * 64)

    identity = build_identity()

    assert identity["git_sha"] == "a" * 40
    assert identity["image_digest"] == "sha256:" + "b" * 64
    assert identity["built_at"] == "2026-07-21T00:00:00Z"


def test_build_identity_uses_packaged_file_without_git(monkeypatch, tmp_path) -> None:
    (tmp_path / ".build-identity.json").write_text(
        json.dumps(
            {
                "git_sha": "c" * 40,
                "artifact_sha256": "d" * 64,
                "built_at": "2026-07-21T00:00:00Z",
                "version": "1.0.0.1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FHD_DEPLOY_ROOT", str(tmp_path))
    for name in ("XCAGI_GIT_SHA", "FHD_GIT_SHA", "GIT_SHA"):
        monkeypatch.delenv(name, raising=False)

    identity = build_identity()

    assert identity["git_sha"] == "c" * 40
    assert identity["artifact_sha256"] == "d" * 64
    assert identity["release_id"] == "xcagi-1.0.0.1-" + "c" * 40


def test_build_identity_reads_deploy_stamps(monkeypatch, tmp_path) -> None:
    (tmp_path / ".build-identity.json").write_text(
        json.dumps({"git_sha": "a" * 40}), encoding="utf-8"
    )
    (tmp_path / ".deploy-sha256").write_text("b" * 64 + "\n", encoding="utf-8")
    (tmp_path / ".deploy-image-digest").write_text("sha256:" + "c" * 64 + "\n", encoding="utf-8")
    monkeypatch.setenv("FHD_DEPLOY_ROOT", str(tmp_path))
    for name in (
        "XCAGI_ARTIFACT_SHA256",
        "XCAGI_IMAGE_DIGEST",
        "FHD_API_IMAGE_DIGEST",
    ):
        monkeypatch.delenv(name, raising=False)

    identity = build_identity()

    assert identity["artifact_sha256"] == "b" * 64
    assert identity["image_digest"] == "sha256:" + "c" * 64


def test_build_identity_reads_admin_console_release_identity(monkeypatch, tmp_path) -> None:
    admin_dist = tmp_path / "templates" / "admin-vue-dist"
    admin_dist.mkdir(parents=True)
    (admin_dist / ".release-identity.json").write_text(
        json.dumps({"git_sha": "e" * 40, "sha256": "f" * 64}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FHD_DEPLOY_ROOT", str(tmp_path))

    identity = build_identity()

    assert identity["admin_console_git_sha"] == "e" * 40
    assert identity["admin_console_sha256"] == "f" * 64
