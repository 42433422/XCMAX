import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_enterprise_bundle_covers_required_host_bridges():
    base = json.loads((ROOT / "config/host_profiles/_base.json").read_text())
    enterprise = json.loads((ROOT / "config/host_profiles/enterprise.json").read_text())
    required = set(base["generic_host_mod_ids"])
    assert required <= set(enterprise["package_stage_ids"])
    assert required <= set(enterprise["sku_bundled_mod_ids"])


def test_profile_stage_lists_only_existing_modules():
    for sku in ("personal", "enterprise"):
        profile = json.loads((ROOT / f"config/host_profiles/{sku}.json").read_text())
        for field in ("package_stage_ids", "sku_bundled_mod_ids"):
            assert "wechat-contacts-ai-employee" not in profile[field]
            for mod_id in profile[field]:
                assert (ROOT / "mods" / mod_id / "manifest.json").is_file(), mod_id


def test_manual_installer_is_part_of_official_workflow_without_stable_publication():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release-desktop.yml").read_text())
    job = workflow["jobs"]["windows-installer-delivery"]
    assert job["runs-on"] == "windows-latest"
    assert "inputs.windows_installer_only == true" in job["if"]
    assert "inputs.windows_installer_only != true" in workflow["jobs"]["release-preflight"]["if"]
    text = yaml.safe_dump(job)
    assert "Partial signing configuration" in text
    assert "test-windows-signature-policy.ps1" in text
    assert "pre-release-security.ps1" in text
    assert "verify-windows-installed-runtime.ps1" in text
    assert "stable_auto_update = $false" in text
    assert "customer_machine_acceptance = 'not_verified'" in text
    assert "Get-FileHash" in text
    assert "latest.yml" not in text
    assert "publish_cvm" not in text
    assert "actions/upload-artifact@v4" in text


def test_unsigned_opt_in_never_accepts_invalid_signatures():
    script = (ROOT / "scripts/package/verify-windows-signature.ps1").read_text()
    assert "[switch]$AllowUnsigned" in script
    assert "$AllowUnsigned -and $signature.Status -eq 'NotSigned'" in script
    assert "if ($signature.Status -ne 'Valid')" in script
    assert 'throw "Invalid Authenticode signature:' in script
    assert "Unexpected Authenticode signer subject" in script


def test_installer_mode_keeps_identity_and_runtime_checks():
    script = (ROOT / "scripts/package/verify-windows-installed-runtime.ps1").read_text()
    assert script.count("-AllowUnsigned:$AllowUnsigned") == 3
    assert "Installed build-info Git SHA mismatch" in script
    assert "Installed build-info version mismatch" in script
    assert "& $runtimeSmoke" in script
    assert "Uninstall unexpectedly deleted XCAGI user data" in script


def test_stable_lane_still_requires_signing():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release-desktop.yml").read_text())
    assert workflow["jobs"]["windows"]["env"]["XCAGI_REQUIRE_WINDOWS_SIGNING"] == "1"
    assert "verify-public-windows-signature" in workflow["jobs"]["publish-website-pointer"]["needs"]
