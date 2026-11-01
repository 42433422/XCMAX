import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.dev.mods_ssot import EXPORT_ONLY_MODS, EXPORT_ROOT, SSOT_ROOT  # noqa: E402


def test_enterprise_bundle_covers_required_host_bridges():
    base = json.loads((ROOT / "config/host_profiles/_base.json").read_text())
    enterprise = json.loads((ROOT / "config/host_profiles/enterprise.json").read_text())
    required = set(base["generic_host_mod_ids"])
    assert required <= set(enterprise["package_stage_ids"])
    assert required <= set(enterprise["sku_bundled_mod_ids"])


def _mod_manifest_exists(mod_id: str) -> bool:
    """双路径解析：编辑源 SSOT 优先；EXPORT_ONLY mod 落在运行时副本 SSOT。"""
    if mod_id in EXPORT_ONLY_MODS:
        return (EXPORT_ROOT / mod_id / "manifest.json").is_file()
    return (SSOT_ROOT / mod_id / "manifest.json").is_file()


def test_attendance_workspace_open_to_generic_users():
    """考勤工作区通用开放：enterprise 捆绑 attendance-industry；suppress 只压太阳鸟 legacy。"""
    base = json.loads((ROOT / "config/host_profiles/_base.json").read_text())
    enterprise = json.loads((ROOT / "config/host_profiles/enterprise.json").read_text())
    suppress = base["client_mod_policies"]["suppress_generic_shell_mod_ids"]
    assert "attendance-industry" not in suppress
    assert "taiyangniao-pro" in suppress
    for field in ("package_stage_ids", "sku_bundled_mod_ids"):
        assert "attendance-industry" in enterprise[field], field


def test_profile_stage_lists_only_existing_modules():
    for sku in ("personal", "enterprise"):
        profile = json.loads((ROOT / f"config/host_profiles/{sku}.json").read_text())
        for field in ("package_stage_ids", "sku_bundled_mod_ids"):
            assert "wechat-contacts-ai-employee" not in profile[field]
            for mod_id in profile[field]:
                assert _mod_manifest_exists(mod_id), mod_id


def test_manual_installer_is_part_of_official_workflow_without_stable_publication():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release-desktop.yml").read_text())
    job = workflow["jobs"]["windows-installer-delivery"]
    assert job["runs-on"] == "windows-latest"
    assert "inputs.windows_installer_only == true" in job["if"]
    assert "inputs.windows_installer_only != true" in workflow["jobs"]["release-preflight"]["if"]
    assert "inputs.candidate_only != true" in workflow["jobs"]["release-preflight"]["if"]
    runs = "\n".join(step.get("run", "") for step in job["steps"])
    assert "Candidate must bind to the selected main SHA" in runs
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
    upload = next(step for step in job["steps"] if step.get("uses") == "actions/upload-artifact@v4")
    paths = upload["with"]["path"].strip().splitlines()
    assert len(paths) == 3
    assert all(path.startswith("FHD/delivery/") and not path.endswith("/") for path in paths)
    assert paths[-1] == "FHD/delivery/delivery-receipt.json"
    assert "sunbird-seed" not in upload["with"]["path"]
    publish = workflow["jobs"]["publish-interim-windows-pointer"]
    assert "inputs.candidate_only != true" in publish["if"]
    assert "inputs.candidate_run_id != ''" in publish["if"]
    assert "result == 'success'" not in publish["if"]
    runs = "\n".join(step.get("run", "") for step in publish["steps"])
    assert "for mode in Clean Upgrade Gui Recovery Rollback; do" in runs
    acceptance = (ROOT / ".github/workflows/windows-candidate-acceptance.yml").read_text()
    assert '["Clean","Upgrade","Gui","Recovery","Rollback"]' in acceptance
    assert '["Clean","Upgrade","Rollback"]' in acceptance
    assert "max-parallel: 1" in acceptance
    assert "run-id: 36661745977" in acceptance
    assert "https://xiu-ci.com/xcagi-v1.0.0.5" not in acceptance
    assert "matrix.mode != 'Clean' && matrix.mode != 'Rollback'" not in acceptance
    collector = (ROOT / "scripts/package/accept-windows-candidate.ps1").read_text("utf-8-sig")
    lifecycle = collector.partition("  if ($Mode -in @('Upgrade','Rollback')) {")[2]
    assert "Run-Gui 'identity' (Join-Path $EvidenceDir 'old-gui')" in lifecycle
    assert (
        lifecycle.index("Fixture 'main-seed'")
        < lifecycle.index("Invoke-AppUpdate")
        < lifecycle.index("Invoke-FailedRollback")
    )
    assert "Invoke-FailedRollback $oldAuth.tenant" in lifecycle
    assert "robocopy $installRoot" not in collector
    assert "[IO.File]::WriteAllText((Join-Path $dataRoot 'rollback-marker.json')" not in collector
    baselines = json.loads((ROOT / "config/download_release.json").read_text())[
        "windows_acceptance_baselines"
    ]
    assert (
        baselines["1.0.0.5"]["sha256"]
        == "92810ed68e146e886888f0ab58ec6b1788f195eb8bd284b38b114c186dd27acf"
    )
    assert "$OldSha256 = $baseline.sha256" in collector
    assert "XCAGI_DESKTOP_TEST" not in collector
    assert "Run-Gui 'identity' (Join-Path $EvidenceDir 'rollback-gui')" in collector
    assert "@('Gui','Upgrade','Recovery','Rollback')" in collector


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
    assert "(Get-Item -LiteralPath $installedExe).VersionInfo.ProductVersion" in script
    assert "if ($exeProductVersion -ne $ExpectedProductVersion)" in script
    assert 'throw "Installed XCAGI.exe ProductVersion mismatch:' in script
    assert script.index("Installed XCAGI.exe ProductVersion mismatch") < script.index(
        "Launching installed desktop runtime"
    )
    assert "& $runtimeSmoke" in script
    assert "Uninstall unexpectedly deleted XCAGI user data" in script


def test_stable_lane_still_requires_signing():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release-desktop.yml").read_text())
    assert workflow["jobs"]["windows"]["env"]["XCAGI_REQUIRE_WINDOWS_SIGNING"] == "1"
    assert "verify-public-windows-signature" in workflow["jobs"]["publish-website-pointer"]["needs"]


def test_branch_backend_runtime_candidate_builds_without_release_privileges():
    workflow = yaml.safe_load((ROOT / ".github/workflows/windows-backend-runtime.yml").read_text())
    trigger = workflow.get("on", workflow.get(True))
    assert set(trigger) == {"pull_request"}
    assert "FHD/pyproject.toml" in trigger["pull_request"]["paths"]
    assert "FHD/scripts/package/xcagi_backend.spec" in trigger["pull_request"]["paths"]
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["frozen-backend-runtime"]
    assert job["runs-on"] == "windows-latest"
    assert job["steps"][0]["with"]["ref"] == "${{ github.sha }}"
    runs = "\n".join(step.get("run", "") for step in job["steps"])
    assert "python -m venv $venv" in runs
    assert "build-backend.ps1 -ProductSku enterprise" in runs
    assert "pip_audit" in runs
    assert "source_sha = (git rev-parse HEAD).Trim()" in runs
    assert "installer_tested = $false; published = $false" in runs
    assert "secrets." not in yaml.safe_dump(workflow)
    assert "build-installer.ps1" not in runs


def test_retired_customer_workflow_cannot_checkout_old_sources(tmp_path):
    workflow = yaml.safe_load((ROOT / ".github/workflows/sunbird-installer.yml").read_text())
    trigger = workflow.get("on", workflow.get(True))
    assert not (trigger["workflow_dispatch"] or {}).get("inputs")
    assert workflow["defaults"]["run"]["working-directory"] == "."
    steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
    assert len(steps) == 1
    assert all("uses" not in step for step in steps)
    # Execute the actual sole job command: historical acknowledgements and refs
    # cannot cause checkout, packaging or publication before this refusal.
    result = subprocess.run(
        ["bash", "-c", steps[0]["run"]],
        cwd=tmp_path,
        env={"acknowledge_retired": "retired-ok", "source_ref": "feat/enterprise-deploy-maturity"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "retired" in (result.stdout + result.stderr).lower()
    assert list(tmp_path.iterdir()) == []


def test_standard_installer_refuses_customer_seed_before_building():
    script = (ROOT / "scripts/package/build-installer.ps1").read_text()
    guard = script.index("if ($SunbirdSeedZipPath)")
    setup = script.index("$Root = Resolve-Path")
    assert guard < setup
    assert 'throw "Customer seed embedding is retired.' in script[guard:setup]
    assert "-p:SunbirdSeedZipPath=" not in script


def test_frozen_promotion_accepts_real_mode_results_and_rejects_failures(tmp_path):
    workflow = yaml.safe_load((ROOT / ".github/workflows/release-desktop.yml").read_text())
    steps = workflow["jobs"]["publish-interim-windows-pointer"]["steps"]
    script = next(
        s["run"]
        for s in steps
        if s.get("name") == "Verify all five frozen candidate acceptance modes"
    )
    script = script.replace("${{ inputs.release_sha }}", "a" * 40)
    (tmp_path / "delivery").mkdir()
    (tmp_path / "delivery/delivery-receipt.json").write_text(json.dumps({"sha256": "b" * 64}))
    results = {
        "Clean": "passed",
        "Upgrade": "passed",
        "Gui": "gui_regression_passed",
        "Recovery": "gui_recovery_regression_passed",
        "Rollback": "rollback_passed",
    }
    for mode, result in results.items():
        path = tmp_path / "acceptance" / f"windows-candidate-evidence-{mode}-{'a' * 40}"
        path.mkdir(parents=True)
        (path / "acceptance.json").write_text(
            json.dumps(
                {
                    "mode": mode,
                    "result": result,
                    "candidate_sha": "a" * 40,
                    "candidate_sha256": "b" * 64,
                    "checks": [{"passed": True}],
                }
            )
        )
    command = f'export RUNNER_TEMP="{tmp_path}";\n{script}'
    assert subprocess.run(["bash", "-eu", "-c", command], capture_output=True).returncode == 0
    for path in (tmp_path / "acceptance").glob("*/acceptance.json"):
        original = path.read_text()
        path.write_text(original.replace('"passed": true', '"passed": false'))
        assert subprocess.run(["bash", "-eu", "-c", command], capture_output=True).returncode != 0
        path.write_text(original)


def test_legacy_rollback_address_keeps_strict_ui_and_field_checks():
    script = ROOT / "scripts/dev/record_enterprise_desktop_init.mjs"
    harness = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
const guard = source.split('const legacyRollback = ')[1].split('\nconst seed')[0];
const body = source.split("if (kind === 'customer' && legacyRollback) {\n")[1]
  .split('\n      }')[0];
const fieldFilter = source.match(/\.filter\(\(\[key, value\]\) => ([^)]+)\)\)/)[1] + ')';
const old = '2e6f03bf67b88965e450721e5b8432ab6395782b';
for (const [phase, mode, sha, wanted] of [
  ['readback', 'Rollback', old, true], ['readback', 'Upgrade', old, false],
  ['readback', 'Recovery', old, false], ['seed', 'Rollback', old, false],
  ['readback', 'Rollback', '37c6de2293a4724dd32d1712d240ac72e3ba8889', false],
  ['readback', 'Rollback', '', false],
]) {
  const process = { env: { XCAGI_GUI_MODE: mode, XCAGI_GUI_BUILD_SHA: sha } };
  assert.equal(vm.runInNewContext(guard, { phase, process }), wanted);
}
for (const legacyRollback of [true, false]) {
  const keep = key => vm.runInNewContext(fieldFilter, { key, value: 'original', legacyRollback });
  assert.equal(keep('contact_address'), !legacyRollback);
  assert.equal(keep('contact_person'), true); assert.equal(keep('contact_phone'), true);
}
async function run(address, screenshotFails = false) {
  const calls = [], row = {}, dialog = { locator: () => 'heading' };
  const context = {
    row, kind: 'customer', dir: '/evidence', path: require('node:path'),
    seed: { cases: [{ id: 'customer', actual: { original_fields: { contact_address: 'original' } } }] },
    click: async (name, scope) => { calls.push(name); assert.equal(scope, name === '编辑' ? row : dialog); },
    modal: () => dialog,
    field: label => { assert.equal(label, '地址'); return { locator: () => ({ first: () => address }) }; },
    expect: actual => ({
      toHaveText: async wanted => { assert.equal(actual, 'heading'); assert.equal(wanted, '编辑客户'); },
      toHaveValue: async wanted => assert.equal(actual, wanted),
      toHaveCount: async wanted => { assert.equal(wanted, 0); assert.equal(calls.at(-1), '取消'); },
    }),
    page: { screenshot: async options => {
      calls.push('screenshot'); assert.equal(options.timeout, 60000);
      if (screenshotFails) throw new Error('capture failed');
    } },
  };
  await vm.runInNewContext('(async () => {' + body + '\n})()', context);
  assert.deepEqual(calls, ['编辑', 'screenshot', '取消']);
}
(async () => {
  await run('original');
  await assert.rejects(run('lost-address')); await assert.rejects(run('original', true));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(["node", "-e", harness, str(script)], check=True)
    text = script.read_text()
    assert "observedRows.get(name)?.[key] ?? ''" in text
    collector = (ROOT / "scripts/package/accept-windows-candidate.ps1").read_text()
    assert "$env:XCAGI_GUI_MODE = $Mode" in collector
    assert "'resources/build-info.json') -Raw | ConvertFrom-Json).gitSha" in collector


def test_gui_login_uses_backend_identity_not_transient_shell():
    harness = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
assert.ok(source.includes('async function hasRetainedSession() {'));
const probe = 'async function hasRetainedSession() {' + source.split('async function hasRetainedSession() {')[1].split('\nasync function main()')[0];
async function run(status, body, expected, reject = false) {
  const page = { url: () => 'http://127.0.0.1:17500/chat', request: { get: async (url, options) => {
    assert.equal(url, 'http://127.0.0.1:17500/api/auth/me');
    assert.equal(options.maxRedirects, 0); assert.equal(options.timeout, 10000);
    return { status: () => status, json: async () => {
      assert.equal(status, 200); if (body instanceof Error) throw body; return body;
    } };
  } } };
  const result = vm.runInNewContext(probe + '; hasRetainedSession()', { page, URL });
  if (reject) await assert.rejects(result); else assert.equal(await result, expected);
}
(async () => {
  await run(401, null, false);
  await run(200, { success: false, valid: false, error: { code: 'UNAUTHORIZED' } }, false);
  await run(200, { success: true, data: { user: { id: 1 } } }, true);
  for (const status of [302, 403, 429, 500, 503]) await run(status, null, null, true);
  for (const body of [{}, { success: true }, { success: true, data: { user: {} } },
    { success: false, valid: false, error: { code: 'ACCOUNT_DISABLED' } }, new Error('invalid JSON')]) {
    await run(200, body, null, true);
  }
  const setup = source.split("await step('normal_login', async () => {\n")[1].split("    await page.locator('#lv-username').fill")[0];
  for (const retained of [false, true]) {
    const calls = [], confirmation = { getByRole: () => ({ click: async () => calls.push('confirm') }) };
    const page = {
      url: () => 'http://127.0.0.1:17500/chat',
      goto: async url => { assert.equal(url, 'http://127.0.0.1:17500/login'); calls.push('login'); },
      locator: selector => selector === '.app-dialog-host-panel' ? confirmation : { first() { return this; } },
      waitForResponse: async predicate => { assert.ok(predicate({ url: () => 'http://127.0.0.1:17500/api/auth/logout' })); calls.push('logout'); return { ok: () => true }; },
    };
    await vm.runInNewContext('(async () => {' + setup + '})()', {
      page, URL, process: { env: { XCAGI_GUI_MODE: 'Upgrade' } }, hasRetainedSession: async () => retained,
      nav: async key => { assert.equal(key, 'settings'); calls.push('settings'); },
      click: async name => { assert.equal(name, '退出登录'); calls.push('signout'); },
      expect: () => ({ toBeVisible: async () => {}, toContainText: async () => {} }),
    });
    assert.deepEqual(calls, retained ? ['settings', 'signout', 'logout', 'confirm'] : ['login']);
    for (const mode of ['Gui', 'Recovery']) {
      await assert.rejects(vm.runInNewContext('(async () => {' + setup + '})()', {
        process: { env: { XCAGI_GUI_MODE: mode } }, hasRetainedSession: async () => true,
      }), /Fresh acceptance requires a logged-out session/);
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(
        ["node", "-e", harness, str(ROOT / "scripts/dev/record_enterprise_desktop_init.mjs")],
        check=True,
        capture_output=True,
        text=True,
    )
