import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

FHD_ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = FHD_ROOT / "config" / "windows_signing_acceptance.json"


def _workflow() -> str:
    return (FHD_ROOT / ".github" / "workflows" / "windows-macalign-hotfix.yml").read_text(
        encoding="utf-8"
    )


def test_unsigned_windows_lane_is_quarantined_and_has_no_publish_job() -> None:
    workflow = _workflow()

    assert "windows:\n    runs-on: windows-latest" in workflow
    assert "Public delivery: forbidden" in workflow
    assert "WINDOWS-QUARANTINE.json" in workflow
    assert "publish:" not in workflow
    assert "Publish mac-align hotfix to CVM" not in workflow
    assert "SERVER_SSH_KEY" not in workflow
    assert "/var/www/" not in workflow


def test_unsigned_windows_lane_requires_exact_sha_two_day_security_evidence() -> None:
    workflow = _workflow()

    assert "release_sha:" in workflow
    assert "security_scan_run_id:" in workflow
    assert "previous_security_scan_run_id:" in workflow
    assert "ref: ${{ inputs.release_sha }}" in workflow
    assert "verify_security_scan_pair.py" in workflow
    assert '--release-sha "${{ inputs.release_sha }}"' in workflow


def test_unsigned_windows_artifact_cannot_be_mistaken_for_an_update_feed() -> None:
    workflow = _workflow()

    assert "xcagi-windows-unsigned-quarantine-${{ inputs.release_sha }}" in workflow
    assert "latest.yml" not in workflow
    assert "download-windows-hotfix.json" not in workflow
    assert "xiu-ci.com" not in workflow


def _interim_public_download_text() -> str:
    workflow = (FHD_ROOT / ".github" / "workflows" / "release-desktop.yml").read_text(
        encoding="utf-8"
    )
    return workflow.split("  publish-interim-windows-pointer:", 1)[1].split(
        "\n  release-preflight:", 1
    )[0]


def test_unsigned_public_download_requires_an_owner_risk_acceptance() -> None:
    text = _interim_public_download_text()

    assert "needs: [windows-installer-delivery]" in text
    assert "inputs.windows_installer_only == true" in text
    assert "--risk-acceptance FHD/config/windows_signing_acceptance.json" in text
    assert "--release-metadata-source FHD/config/download_release.json" in text
    # 交付回执必须自证未签名且安装冒烟已通过，才能公开
    assert '.signature_status == "signed" and .authenticode_status == "Valid"' in text
    assert '.signature_status == "unsigned" and .authenticode_status == "NotSigned"' in text
    assert '.runner_install_smoke == "passed"' in text


def test_unsigned_public_download_stays_off_the_update_feed() -> None:
    text = _interim_public_download_text()

    assert "latest.yml" not in text
    assert "publish_stable_metadata_atomically" not in text
    assert "/var/www/update/releases/stable/enterprise/download-windows-hotfix.json" in text
    assert "/var/www/update/releases/stable/enterprise/latest" not in text


def test_unsigned_public_download_is_verified_over_public_http() -> None:
    text = _interim_public_download_text()

    assert (
        "https://xiu-ci.com/xcagi-v${version}/enterprise/${release_sha,,}/${artifact_sha}/${filename}"
        in text
    )
    assert "${release_sha,,}/${local_sha}/${filename}" in text
    assert 'mv -n "$staging_dir/$filename" "$official_dir/$filename"' in text
    assert 'test "$existing_sha" = "$expected_sha"' in text
    assert "curl --http1.1 -fsSI" in text
    assert 'public_sha="$(curl --http1.1 -fsSL --max-time 900' in text
    assert 'test "$artifact_sha" = "$receipt_sha" && test "$artifact_sha" = "$sidecar_sha"' in text
    assert "sha256sum" in text
    assert "Published installer SHA256 mismatch" in text
    assert "download-windows-hotfix.json" in text


def test_owner_signing_acceptance_is_bounded_and_independently_reviewed() -> None:
    record = json.loads(ACCEPTANCE.read_text(encoding="utf-8"))
    body = {
        key: value
        for key, value in record.items()
        if key not in ("schema", "decision_record_sha256")
    }
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    assert record["schema"] == "xcagi.windows_signing_acceptance/v1"
    assert record["status"] == "accepted_risk"
    assert record["scope"] == "public_download"
    assert record["author"].casefold() != record["reviewer"].casefold()
    assert record["windows_stable_feed"] == "closed"
    assert record["disclosed_risks"]
    assert record["decision_record_sha256"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_owner_signing_acceptance_term_is_three_years_and_unexpired() -> None:
    record = json.loads(ACCEPTANCE.read_text(encoding="utf-8"))
    accepted_at = datetime.fromisoformat(record["accepted_at"])
    expires_at = datetime.fromisoformat(record["expires_at"])

    # 业主指定 3 年（含 2028 闰日，共 1096 天），而非既有的 30 天重估惯例。
    assert (expires_at - accepted_at).days == 1096
    assert expires_at > datetime.now(UTC)


def test_test_candidate_keeps_explicit_frozen_upgrade_baselines() -> None:
    workflow = (FHD_ROOT / ".github/workflows/windows-candidate-acceptance.yml").read_text()
    collector = (FHD_ROOT / "scripts/package/accept-windows-candidate.ps1").read_text("utf-8-sig")
    for version in ("1.0.0.5", "1.0.0.6"):
        assert f"inputs.baseline_version == '{version}'" in workflow
    metadata = json.loads((FHD_ROOT / "config/download_release.json").read_text())
    baselines = metadata["windows_acceptance_baselines"]
    assert (
        baselines["1.0.0.6"]["sha256"]
        == "5d4b75c831a78185eab53787c7dfd3ebe9d066fe27daadd147e208d4666cb855"
    )
    assert (
        baselines["1.0.0.5"]["sha256"]
        == "92810ed68e146e886888f0ab58ec6b1788f195eb8bd284b38b114c186dd27acf"
    )
    assert baselines["1.0.0.6"]["size"] == 345730149
    assert baselines["1.0.0.6"]["git_sha"] == "13fccf867a592708dbd2347ca52b30f92e899550"
    assert "$OldSha = $baseline.git_sha; $OldSha256 = $baseline.sha256" in collector
    assert "$installer.Length -ne $baseline.size -or $hash -ne $baseline.sha256" in workflow
    assert "baseline_sha=$OldSha" in collector and "baseline_sha256=$OldSha256" in collector
    assert "$restored.version -eq $BaselineVersion" in collector
    assert (
        "($baseline.allow_missing_health_identity -eq $true -and -not $health.git_sha)" in collector
    )
    assert baselines["1.0.0.5"]["allow_missing_health_identity"] is True
    assert baselines["1.0.0.6"]["allow_missing_health_identity"] is False
    metadata = json.loads((FHD_ROOT / "config/download_release.json").read_text())
    assert metadata["release_ready"] is False
    assert "测试候选" in metadata["windows_interim_release"]["title"]
    assert metadata["release_history"][0]["version"] == "1.0.0.6"


@pytest.mark.parametrize("baseline", ["1.0.0.5", "1.0.0.6"])
@pytest.mark.parametrize(
    "change",
    [
        "none",
        "from_version",
        "from_sha",
        "to_version",
        "to_sha",
        "toolchain_from",
        "from_short",
        "to_short",
        "from_same_prefix",
        "to_same_prefix",
        "toolchain_to",
        "suffix",
        "mode",
    ],
)
def test_snapshot_identity_contract_rejects_wrong_version_or_sha(baseline, change):
    """Validate the collector's exact string contract; Windows executes PowerShell in CI."""
    collector = (FHD_ROOT / "scripts/package/accept-windows-candidate.ps1").read_text("utf-8-sig")
    record = json.loads((FHD_ROOT / "config/download_release.json").read_text())[
        "windows_acceptance_baselines"
    ][baseline]
    values = {
        "OldSha": record["git_sha"],
        "CandidateSha": "a" * 40,
    }
    assert "throw 'Unknown frozen acceptance baseline'" in collector
    expected = {"From": f"{baseline}+{values['OldSha']}", "To": f"1.0.0.7+{values['CandidateSha']}"}
    assert '$expectedFromVersion = "$BaselineVersion+$OldSha"' in collector
    assert '$expectedToVersion = "$productVersion+$CandidateSha"' in collector
    for field in expected:
        assert f"$naturalMarker.{field.lower()}Version -ceq $expected{field}Version" in collector
    assert "$naturalMarker.mode -eq 'windows-full') 'app_update.snapshot_identity'" in collector
    actual = dict(expected)
    if change.endswith("_version"):
        actual[change.split("_")[0].title()] = (
            "9.9.9.9+" + actual[change.split("_")[0].title()].split("+")[1]
        )
    elif change.endswith("_sha"):
        key = change.split("_")[0].title()
        actual[key] = actual[key].split("+")[0] + "+" + "b" * 40
    elif change == "suffix":
        actual["From"] += "-wrong-build"
    elif change.endswith("_short") or change.endswith("_same_prefix"):
        key = change.split("_")[0].title()
        version, sha = actual[key].split("+")
        tail = "" if change.endswith("_short") else "0" * 28
        actual[key] = f"{version}+{sha[:12]}{tail}"
    elif change == "toolchain_from":
        actual["From"] = f"1.0.0+{values['OldSha']}"
    elif change == "toolchain_to":
        actual["To"] = f"1.0.0+{values['CandidateSha']}"
    mode = "not-windows-full" if change == "mode" else "windows-full"
    assert (actual == expected and mode == "windows-full") is (change == "none")
