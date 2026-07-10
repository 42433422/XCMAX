from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from modstore_server import app_config_api as ota


_OTA_ENV_KEYS = {
    "XCAGI_ANDROID_RELEASE_ROOT",
    "XCAGI_ANDROID_RELEASE_MANIFEST",
    "XCAGI_ANDROID_RELEASE_MANIFEST_ENTERPRISE",
    "XCAGI_ANDROID_RELEASE_MANIFEST_PERSONAL",
    "XCAGI_ANDROID_DELTA_MANIFEST",
    "XCAGI_ANDROID_DELTA_MANIFEST_ENTERPRISE",
    "XCAGI_ANDROID_DELTA_MANIFEST_PERSONAL",
    "XCAGI_ANDROID_LEGACY_SKU",
    "XCAGI_ANDROID_DOWNLOAD_BASE",
    "XCAGI_ANDROID_DOWNLOAD_HOSTS",
    "XCAGI_ANDROID_LATEST_VERSION_CODE",
    "XCAGI_ANDROID_LATEST_VERSION_NAME",
    "XCAGI_ANDROID_MIN_VERSION_CODE",
    "XCAGI_ANDROID_FORCE_UPDATE",
    "XCAGI_ANDROID_APK_SHA256",
    "XCAGI_ANDROID_APK_SIZE",
    "XCAGI_ANDROID_APK_DOWNLOAD_URL",
    "XCAGI_ANDROID_LATEST_VERSION_CODE_ENTERPRISE",
    "XCAGI_ANDROID_LATEST_VERSION_NAME_ENTERPRISE",
    "XCAGI_ANDROID_MIN_VERSION_CODE_ENTERPRISE",
    "XCAGI_ANDROID_FORCE_UPDATE_ENTERPRISE",
    "XCAGI_ANDROID_APK_SHA256_ENTERPRISE",
    "XCAGI_ANDROID_APK_SIZE_ENTERPRISE",
    "XCAGI_ANDROID_APK_DOWNLOAD_URL_ENTERPRISE",
    "XCAGI_ANDROID_LATEST_VERSION_CODE_PERSONAL",
    "XCAGI_ANDROID_LATEST_VERSION_NAME_PERSONAL",
    "XCAGI_ANDROID_MIN_VERSION_CODE_PERSONAL",
    "XCAGI_ANDROID_FORCE_UPDATE_PERSONAL",
    "XCAGI_ANDROID_APK_SHA256_PERSONAL",
    "XCAGI_ANDROID_APK_SIZE_PERSONAL",
    "XCAGI_ANDROID_APK_DOWNLOAD_URL_PERSONAL",
    "XCAGI_PRIVACY_URL",
    "XCAGI_TERMS_URL",
    "XCAGI_LEGAL_PRIVACY_URL",
    "XCAGI_LEGAL_TERMS_URL",
    "XCAGI_PUBLIC_BASE_URL",
}


@pytest.fixture(autouse=True)
def _clean_ota_env(monkeypatch):
    for key in _OTA_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    ota._artifact_sha256.cache_clear()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _create_release(
    root: Path,
    *,
    sku: str,
    version_code: int,
    version_name: str,
    content: bytes | None = None,
    overrides: dict | None = None,
) -> tuple[Path, Path, dict]:
    release_dir = root / sku
    release_dir.mkdir(parents=True, exist_ok=True)
    artifact_name = ota._expected_apk_name(sku, version_name)
    artifact = release_dir / artifact_name
    apk = content or f"{sku}-{version_code}".encode()
    artifact.write_bytes(apk)
    raw = {
        "schema_version": 1,
        "platform": "android",
        "channel": "stable",
        "sku": sku,
        "version_code": version_code,
        "version_name": version_name,
        "min_version_code": 10,
        "force_update": False,
        "download_url": f"https://xiu-ci.com/download/{sku}/{artifact_name}",
        "sha256": _sha256(apk),
        "size": len(apk),
        "artifact": artifact_name,
    }
    raw.update(overrides or {})
    manifest = release_dir / "android_release_manifest.json"
    manifest.write_text(json.dumps(raw), encoding="utf-8")
    return manifest, artifact, raw


def test_valid_manifest_wins_over_stale_process_env(monkeypatch, tmp_path):
    _create_release(
        tmp_path,
        sku="enterprise",
        version_code=200,
        version_name="12.0.0",
        content=b"enterprise-apk",
    )
    monkeypatch.setenv("XCAGI_ANDROID_RELEASE_ROOT", str(tmp_path))
    monkeypatch.setenv("XCAGI_ANDROID_LATEST_VERSION_CODE", "999")
    monkeypatch.setenv("XCAGI_ANDROID_LATEST_VERSION_NAME", "99.0.0")
    monkeypatch.setenv("XCAGI_ANDROID_APK_SHA256", "f" * 64)
    monkeypatch.setenv("XCAGI_ANDROID_APK_SIZE", "999")

    config = ota.api_app_config(
        platform="android", sku="enterprise", current_version_code=100
    )

    assert config["update_available"] is True
    assert config["latest_android_version"] == 200
    assert config["latest_android_version_name"] == "12.0.0"
    assert config["apk_download_url"].endswith(
        "/enterprise/XCAGI-Enterprise-Android-12.0.0.apk"
    )
    assert config["apk_sha256"] == _sha256(b"enterprise-apk")
    assert config["apk_size"] == len(b"enterprise-apk")
    assert config["release_source"] == "manifest"


def test_manifest_downgrade_is_safe_no_update(monkeypatch, tmp_path):
    _create_release(
        tmp_path,
        sku="enterprise",
        version_code=200,
        version_name="12.0.0",
    )
    monkeypatch.setenv("XCAGI_ANDROID_RELEASE_ROOT", str(tmp_path))

    config = ota.api_app_config(
        platform="android", sku="enterprise", current_version_code=201
    )

    assert config["update_available"] is False
    assert config["latest_android_version"] == 0
    assert config["latest_android_version_name"] == ""
    assert config["apk_download_url"] == ""
    assert config["apk_sha256"] == ""
    assert config["apk_size"] == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"sha256": "0" * 64},
        {"size": 999},
        {"version_code": 200.5},
        {"download_url": "https://xiu-ci.com/download/personal/evil.apk"},
        {"sku": "personal"},
    ],
)
def test_tampered_or_cross_sku_manifest_never_falls_back_to_old_env(
    monkeypatch, tmp_path, overrides
):
    _create_release(
        tmp_path,
        sku="enterprise",
        version_code=200,
        version_name="12.0.0",
        overrides=overrides,
    )
    monkeypatch.setenv("XCAGI_ANDROID_RELEASE_ROOT", str(tmp_path))
    monkeypatch.setenv("XCAGI_ANDROID_LATEST_VERSION_CODE", "300")
    monkeypatch.setenv("XCAGI_ANDROID_LATEST_VERSION_NAME", "13.0.0")
    monkeypatch.setenv("XCAGI_ANDROID_APK_SHA256", "a" * 64)
    monkeypatch.setenv("XCAGI_ANDROID_APK_SIZE", "100")

    config = ota.api_app_config(
        platform="android", sku="enterprise", current_version_code=100
    )

    assert config["update_available"] is False
    assert config["release_source"] == "none"


def test_enterprise_and_personal_manifests_are_isolated(monkeypatch, tmp_path):
    _create_release(
        tmp_path,
        sku="enterprise",
        version_code=210,
        version_name="12.1.0",
        content=b"enterprise",
    )
    monkeypatch.setenv("XCAGI_ANDROID_RELEASE_ROOT", str(tmp_path))

    personal_missing = ota.api_app_config(
        platform="android", sku="personal", current_version_code=100
    )
    assert personal_missing["update_available"] is False
    assert personal_missing["apk_download_url"] == ""

    _create_release(
        tmp_path,
        sku="personal",
        version_code=150,
        version_name="11.5.0",
        content=b"personal",
    )
    personal = ota.api_app_config(
        platform="android", sku="personal", current_version_code=100
    )
    enterprise = ota.api_app_config(
        platform="android", sku="enterprise", current_version_code=100
    )
    assert personal["latest_android_version"] == 150
    assert "/download/personal/" in personal["apk_download_url"]
    assert enterprise["latest_android_version"] == 210
    assert "/download/enterprise/" in enterprise["apk_download_url"]


def test_missing_manifest_and_incomplete_env_return_no_update(monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_ANDROID_RELEASE_ROOT", str(tmp_path))
    monkeypatch.setenv("XCAGI_ANDROID_LATEST_VERSION_CODE", "300")
    monkeypatch.setenv("XCAGI_ANDROID_LATEST_VERSION_NAME", "13.0.0")

    config = ota.api_app_config(
        platform="android", sku="enterprise", current_version_code=100
    )

    assert config["update_available"] is False
    assert config["latest_android_version"] == 0


def test_complete_legacy_env_remains_enterprise_only_compatible(monkeypatch, tmp_path):
    release_dir = tmp_path / "enterprise"
    release_dir.mkdir(parents=True)
    name = "12.2.0"
    apk = b"legacy-enterprise-apk"
    (release_dir / ota._expected_apk_name("enterprise", name)).write_bytes(apk)
    monkeypatch.setenv("XCAGI_ANDROID_RELEASE_ROOT", str(tmp_path))
    monkeypatch.setenv("XCAGI_ANDROID_LATEST_VERSION_CODE", "220")
    monkeypatch.setenv("XCAGI_ANDROID_LATEST_VERSION_NAME", name)
    monkeypatch.setenv("XCAGI_ANDROID_APK_SHA256", _sha256(apk))
    monkeypatch.setenv("XCAGI_ANDROID_APK_SIZE", str(len(apk)))

    enterprise = ota.api_app_config(
        platform="android", sku="enterprise", current_version_code=100
    )
    personal = ota.api_app_config(
        platform="android", sku="personal", current_version_code=100
    )
    assert enterprise["release_source"] == "legacy_env"
    assert enterprise["latest_android_version"] == 220
    assert personal["update_available"] is False


def test_delta_must_match_release_sku_hash_size_and_adjacent_artifact(
    monkeypatch, tmp_path
):
    manifest, _artifact, raw = _create_release(
        tmp_path,
        sku="enterprise",
        version_code=300,
        version_name="13.0.0",
        content=b"target-apk",
    )
    patch_bytes = b"delta-patch"
    patch_name = "XCAGI-Enterprise-Android-12.0.0-to-13.0.0.xcapkdiff"
    patch_path = manifest.parent / patch_name
    patch_path.write_bytes(patch_bytes)
    delta = {
        "format_version": 1,
        "sku": "enterprise",
        "target_version_code": 300,
        "target_version_name": "13.0.0",
        "patches": [
            {
                "format": "xcagi-copy-data-v1",
                "base_version_code": 200,
                "base_version_name": "12.0.0",
                "target_version_code": 300,
                "target_version_name": "13.0.0",
                "patch_url": f"https://xiu-ci.com/download/enterprise/{patch_name}",
                "patch_sha256": _sha256(patch_bytes),
                "base_apk_sha256": "a" * 64,
                "target_apk_sha256": raw["sha256"],
                "patch_size": len(patch_bytes),
                "apk_size": raw["size"],
            }
        ],
    }
    (manifest.parent / "android_delta_manifest.json").write_text(
        json.dumps(delta), encoding="utf-8"
    )
    monkeypatch.setenv("XCAGI_ANDROID_RELEASE_ROOT", str(tmp_path))

    valid = ota.api_app_config(
        platform="android", sku="enterprise", current_version_code=200
    )
    assert valid["apk_delta"]["available"] is True

    delta["sku"] = "personal"
    (manifest.parent / "android_delta_manifest.json").write_text(
        json.dumps(delta), encoding="utf-8"
    )
    isolated = ota.api_app_config(
        platform="android", sku="enterprise", current_version_code=200
    )
    assert isolated["apk_delta"]["available"] is False


@pytest.mark.parametrize(
    "bad_delta",
    [
        [],
        {
            "sku": "enterprise",
            "target_version_code": 300,
            "target_version_name": "13.0.0",
            "patches": [{"base_version_code": "not-an-int"}],
        },
        {
            "sku": "enterprise",
            "target_version_code": 300,
            "target_version_name": "13.0.0",
            "patches": [
                {
                    "base_version_code": 200,
                    "target_version_code": 300,
                    "target_version_name": "13.0.0",
                    "format": "xcagi-copy-data-v1",
                    "patch_url": "https://[invalid",
                }
            ],
        },
    ],
)
def test_malformed_delta_is_rejected_without_breaking_config(
    monkeypatch, tmp_path, bad_delta
):
    manifest, _artifact, _raw = _create_release(
        tmp_path,
        sku="enterprise",
        version_code=300,
        version_name="13.0.0",
    )
    (manifest.parent / "android_delta_manifest.json").write_text(
        json.dumps(bad_delta), encoding="utf-8"
    )
    monkeypatch.setenv("XCAGI_ANDROID_RELEASE_ROOT", str(tmp_path))

    config = ota.api_app_config(
        platform="android", sku="enterprise", current_version_code=200
    )

    assert config["update_available"] is True
    assert config["apk_delta"]["available"] is False


def test_privacy_and_terms_use_real_policy_page_with_safe_https_overrides(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XCAGI_ANDROID_RELEASE_ROOT", str(tmp_path))
    monkeypatch.setenv("XCAGI_PUBLIC_BASE_URL", "https://xiu-ci.com")
    default = ota.api_app_config(platform="ios", sku="personal", current_version_code=0)
    assert default["privacy_url"] == "https://xiu-ci.com/privacy.html"
    assert default["terms_url"] == "https://xiu-ci.com/privacy.html"

    monkeypatch.setenv("XCAGI_PRIVACY_URL", "https://legal.xiu-ci.com/privacy")
    monkeypatch.setenv("XCAGI_TERMS_URL", "https://legal.xiu-ci.com/terms")
    overridden = ota.api_app_config(
        platform="ios", sku="personal", current_version_code=0
    )
    assert overridden["privacy_url"] == "https://legal.xiu-ci.com/privacy"
    assert overridden["terms_url"] == "https://legal.xiu-ci.com/terms"

    monkeypatch.setenv("XCAGI_TERMS_URL", "http://evil.example/terms")
    unsafe_ignored = ota.api_app_config(
        platform="ios", sku="personal", current_version_code=0
    )
    assert unsafe_ignored["terms_url"] == "https://xiu-ci.com/privacy.html"

    monkeypatch.delenv("XCAGI_PRIVACY_URL")
    monkeypatch.delenv("XCAGI_TERMS_URL")
    monkeypatch.setenv("XCAGI_PUBLIC_BASE_URL", "http://xiu-ci.com")
    unsafe_base_ignored = ota.api_app_config(
        platform="ios", sku="personal", current_version_code=0
    )
    assert unsafe_base_ignored["privacy_url"] == "https://xiu-ci.com/privacy.html"
    assert unsafe_base_ignored["terms_url"] == "https://xiu-ci.com/privacy.html"


def test_app_config_is_registered_on_real_api_router(client):
    response = client.get(
        "/api/app/config",
        params={"platform": "ios", "sku": "personal", "current_version_code": 0},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["privacy_url"] == "https://xiu-ci.com/privacy.html"
    assert body["terms_url"] == "https://xiu-ci.com/privacy.html"


def test_manifest_cli_writes_and_checks_atomically(tmp_path):
    release_dir = tmp_path / "enterprise"
    release_dir.mkdir(parents=True)
    apk = release_dir / "XCAGI-Enterprise-Android-14.0.0.apk"
    apk.write_bytes(b"cli-generated-apk")
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "android_release_manifest.py"
    )
    output = release_dir / "android_release_manifest.json"
    write = subprocess.run(
        [
            sys.executable,
            str(script),
            "write",
            "--sku",
            "enterprise",
            "--apk",
            str(apk),
            "--output",
            str(output),
            "--version-code",
            "400",
            "--version-name",
            "14.0.0",
            "--download-url",
            "https://xiu-ci.com/download/enterprise/XCAGI-Enterprise-Android-14.0.0.apk",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        env={**os.environ, "XCAGI_ANDROID_DOWNLOAD_HOSTS": "xiu-ci.com"},
        check=False,
    )
    assert write.returncode == 0, write.stderr or write.stdout
    assert output.is_file()
    assert not list(release_dir.glob(".android_release_manifest.json.tmp-*"))
    check = subprocess.run(
        [
            sys.executable,
            str(script),
            "check",
            "--sku",
            "enterprise",
            "--manifest",
            str(output),
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )
    assert check.returncode == 0, check.stderr or check.stdout
    assert json.loads(check.stdout)["ok"] is True

    lower_apk = release_dir / "XCAGI-Enterprise-Android-13.9.0.apk"
    lower_apk.write_bytes(b"older-cli-apk")
    rollback = subprocess.run(
        [
            sys.executable,
            str(script),
            "write",
            "--sku",
            "enterprise",
            "--apk",
            str(lower_apk),
            "--output",
            str(output),
            "--version-code",
            "399",
            "--version-name",
            "13.9.0",
            "--download-url",
            "https://xiu-ci.com/download/enterprise/XCAGI-Enterprise-Android-13.9.0.apk",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )
    assert rollback.returncode == 2
    assert "refusing non-increasing" in rollback.stdout
    assert json.loads(output.read_text(encoding="utf-8"))["version_code"] == 400
