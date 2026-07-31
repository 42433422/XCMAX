from __future__ import annotations

from modstore_server.download_release import public_subset


def test_public_subset_preserves_enterprise_release_identity() -> None:
    desktop_sha = "b" * 40
    android_sha = "a" * 40
    history = [
        {"version": "1.0.0.0", "platforms": ["Windows", "macOS", "Android"]},
        {"version": "10.0.0", "platforms": ["Windows", "macOS"]},
    ]
    release = {
        "version_lock": "1.0.0.1",
        "download_version": "1.0.0.1",
        "android_version": "1.0.0.1",
        "android_git_sha": android_sha,
        "release_ready": True,
        "active_skus": ["enterprise"],
        "frozen_skus": ["personal"],
        "primary_sku": "enterprise",
        "win_installer_mb": 204,
        "cos_base_url": "https://xiu-ci.com",
        "last_push": {"git_sha": desktop_sha},
        "release_history": history,
    }

    public = public_subset(release)

    assert public["release_ready"] is True
    assert public["active_skus"] == ["enterprise"]
    assert public["frozen_skus"] == ["personal"]
    assert public["primary_sku"] == "enterprise"
    assert public["git_sha"] == desktop_sha
    assert public["android_git_sha"] == android_sha
    assert public["manifest_url"] == "https://xiu-ci.com/xcagi-v1.0.0.1/manifest.json"
    assert public["auto_update_base"] == "https://xiu-ci.com/releases/stable"
    assert public["release_history"] == history
