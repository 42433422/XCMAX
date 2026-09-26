import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

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

    assert "https://xiu-ci.com/xcagi-v${version}/enterprise/${release_sha,,}/${artifact_sha}/${filename}" in text
    assert "${release_sha,,}/${local_sha}/${filename}" in text
    assert "mv -n \"$staging_dir/$filename\" \"$official_dir/$filename\"" in text
    assert "test \"$existing_sha\" = \"$expected_sha\"" in text
    assert "curl --http1.1 -fsSI" in text
    assert "public_sha=\"$(curl --http1.1 -fsSL --max-time 900" in text
    assert 'test "$artifact_sha" = "$receipt_sha" && test "$artifact_sha" = "$sidecar_sha"' in text
    assert "sha256sum" in text
    assert "Published installer SHA256 mismatch" in text
    assert "download-windows-hotfix.json" in text


def test_owner_signing_acceptance_is_bounded_and_independently_reviewed() -> None:
    record = json.loads(ACCEPTANCE.read_text(encoding="utf-8"))
    canonical = json.dumps(
        {
            key: value
            for key, value in record.items()
            if key not in ("schema", "decision_record_sha256")
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )

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
