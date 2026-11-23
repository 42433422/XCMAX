import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.dev.mods_ssot import EXPORT_ONLY_MODS, EXPORT_ROOT, find_source_dir


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
    return find_source_dir(mod_id) is not None


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
    unsigned = workflow[True]["workflow_dispatch"]["inputs"]["windows_unsigned"]
    assert unsigned["type"] == "boolean"
    assert unsigned["default"] is False
    job = workflow["jobs"]["windows-installer-delivery"]
    assert job["runs-on"] == "windows-latest"
    assert "inputs.windows_installer_only == true" in job["if"]
    assert "inputs.windows_installer_only != true" in workflow["jobs"]["release-preflight"]["if"]
    assert "inputs.candidate_only != true" in workflow["jobs"]["release-preflight"]["if"]
    runs = "\n".join(step.get("run", "") for step in job["steps"])
    assert "Candidate must bind to the selected main SHA" in runs
    text = yaml.safe_dump(job)
    assert "Partial signing configuration" in text
    assert all(
        "!inputs.windows_unsigned" in job["env"][name]
        for name in (
            "ES_USERNAME",
            "ES_PASSWORD",
            "CREDENTIAL_ID",
            "ES_TOTP_SECRET",
            "XCAGI_WINDOWS_PUBLISHER_NAME",
        )
    )
    assert "The selected delivery requires an unsigned installer." in runs
    assert "test-windows-signature-policy.ps1" in text
    assert "pre-release-security.ps1" in text
    assert "verify-windows-installed-runtime.ps1" in text
    assert "stable_auto_update = $false" in text
    assert "customer_machine_acceptance = 'not_verified'" in runs
    assert "Get-FileHash" in text
    assert "latest.yml" not in text
    assert "publish_cvm" not in text
    assert "actions/upload-artifact@v4" in text
    upload = next(step for step in job["steps"] if step.get("uses") == "actions/upload-artifact@v4")
    paths = upload["with"]["path"].strip().splitlines()
    assert len(paths) == 4
    assert all(path.startswith("FHD/delivery/") and not path.endswith("/") for path in paths)
    assert paths[-2:] == [
        "FHD/delivery/delivery-receipt.json",
        "FHD/delivery/notice-publication.json",
    ]
    assert "sunbird-seed" not in upload["with"]["path"]
    publish = workflow["jobs"]["publish-interim-windows-pointer"]
    assert "inputs.candidate_only != true" in publish["if"]
    assert "inputs.candidate_run_id != ''" in publish["if"]
    assert "needs.windows-installer-delivery.result == 'success'" not in publish["if"]
    assert "needs.windows-installer-delivery.result == 'skipped'" in publish["if"]
    assert "needs.notice-publication-policy.result == 'success'" in publish["if"]
    runs = "\n".join(step.get("run", "") for step in publish["steps"])
    assert '($unsigned != "true" or .signature_status == "unsigned")' in runs
    assert "verify_upgrade_rollback_evidence.py" in runs
    assert "--windows-native-dir" in runs
    acceptance = (ROOT / ".github/workflows/windows-candidate-acceptance.yml").read_text()
    assert "windows-acceptance-accounts.mjs" in acceptance
    assert "max-parallel: ${{ fromJson(needs.select-modes.outputs.parallel) }}" in acceptance
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


def _copy_native_controller(destination):
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("verify_upgrade_rollback_evidence.py", "build_closure_reports.py"):
        (destination / name).write_bytes((ROOT / "scripts/release" / name).read_bytes())


def test_frozen_promotion_rejects_result_only_claims_without_raw_measurements(tmp_path):
    workflow = yaml.safe_load((ROOT / ".github/workflows/release-desktop.yml").read_text())
    steps = workflow["jobs"]["publish-interim-windows-pointer"]["steps"]
    script = next(
        s["run"]
        for s in steps
        if s.get("name") == "Verify all five frozen candidate acceptance modes"
    )
    script = script.replace("${{ inputs.release_sha }}", "a" * 40)
    script = script.replace("${{ github.repository }}", "fixture/repo").replace(
        "${{ inputs.acceptance_run_id }}", "123"
    )
    _copy_native_controller(tmp_path / "release-controller/FHD/scripts/release")
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
    command = f'export RUNNER_TEMP="{tmp_path}" XCAGI_BUILD_SHA="{"a" * 40}" DELIVERY_VERSION="1.0.0.7";\n{script}'
    result = subprocess.run(["bash", "-eu", "-c", command], cwd=tmp_path, capture_output=True)
    assert result.returncode == 1, result.stdout + result.stderr
    proof = json.loads((tmp_path / "windows-lifecycle-verification.json").read_text())
    assert proof["passed"] is False
    assert "windows_rollback_native_evidence_invalid" in proof["blockers"]
    for path in (tmp_path / "acceptance").glob("*/acceptance.json"):
        original = path.read_text()
        path.write_text(original.replace('"passed": true', '"passed": false'))
        assert (
            subprocess.run(
                ["bash", "-eu", "-c", command], cwd=tmp_path, capture_output=True
            ).returncode
            != 0
        )
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
    row, kind: 'customer', dir: '/evidence', path: require('node:path'), process: { env: { XCAGI_TEST_USER: 'synthetic-user' } },
    seed: { cases: [{ id: 'customer', actual: { original_fields: { contact_address: 'original' } } }] },
    click: async (name, scope) => { calls.push(name); assert.equal(scope, name === '编辑' ? row : dialog); },
    modal: () => dialog,
    field: label => { assert.equal(label, '地址'); return { locator: () => ({ first: () => address }) }; },
    expect: actual => ({
      toHaveText: async wanted => { assert.equal(actual, 'heading'); assert.equal(wanted, '编辑客户'); },
      toHaveValue: async wanted => assert.equal(actual, wanted),
      toHaveCount: async wanted => { assert.equal(wanted, 0); assert.equal(calls.at(-1), '取消'); },
    }),
    page: { locator: () => 'credential-fields', getByText: () => 'account-text', screenshot: async options => {
      calls.push('screenshot'); assert.equal(options.timeout, 60000);
      assert.deepEqual(Array.from(options.mask), ['credential-fields', 'account-text']);
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


@pytest.mark.parametrize(
    "case",
    [
        "same_run",
        "same_run_newer",
        "not_ancestor",
        "feature_controller",
        "completed_previous",
        "previous_newer",
        "missing_call_input",
        "wrong_attempt",
        "stale_build_attempt",
        "wrong_artifact",
        "wrong_workflow",
        "wrong_sha",
        "wrong_branch",
        "previous_running",
        "previous_failed",
        "previous_skipped",
        "previous_cancelled",
    ],
)
def test_reusable_acceptance_keeps_same_run_exception_narrow(case):
    repo = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load(
        (repo / "FHD/.github/workflows/windows-candidate-acceptance.yml").read_text()
    )
    triggers = workflow.get("on", workflow.get(True))
    assert "current_release_attempt" in triggers["workflow_call"]["inputs"]
    assert "current_release_attempt" not in triggers["workflow_dispatch"]["inputs"]
    script = next(
        step["with"]["script"]
        for step in workflow["jobs"]["isolated-install"]["steps"]
        if step.get("uses", "").startswith("actions/github-script@")
    )
    previous = case.startswith("previous_") or case == "completed_previous"
    run = {
        "head_sha": "a" * 40,
        "repository": {"full_name": "fixture/fixture"},
        "head_repository": {"full_name": "fixture/fixture"},
        "path": ".github/workflows/fhd-release-desktop.yml",
        "head_branch": "main",
        "event": "workflow_dispatch",
        "status": "completed" if previous else "in_progress",
        "conclusion": "success" if previous else None,
        "run_attempt": 2,
    }
    environment = {
        "PATH": os.environ["PATH"],
        "CANDIDATE_RUN_ID": "50" if previous else "100",
        "CANDIDATE_SHA": "a" * 40,
        "CURRENT_RELEASE_ATTEMPT": "" if previous else "2",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_WORKFLOW_REF": "fixture/fixture/.github/workflows/fhd-release-desktop.yml@refs/heads/main",
        "CANDIDATE_ARTIFACT": "xcagi-windows-installer-" + "a" * 40
        if previous
        else "xcagi-desktop-windows-enterprise",
    }
    if case == "missing_call_input":
        environment["CURRENT_RELEASE_ATTEMPT"] = ""
    if case == "wrong_attempt":
        environment["CURRENT_RELEASE_ATTEMPT"] = "1"
    if case == "stale_build_attempt":
        run["run_attempt"] = 1
    if case == "wrong_artifact":
        environment["CANDIDATE_ARTIFACT"] = "another-artifact"
    if case == "wrong_workflow":
        run["path"] = ".github/workflows/unrelated.yml"
    if case == "wrong_sha":
        run["head_sha"] = "b" * 40
    if case in {"same_run_newer", "not_ancestor", "previous_newer"}:
        run["head_sha"] = "b" * 40
    if case == "feature_controller":
        environment["GITHUB_WORKFLOW_REF"] = (
            "fixture/fixture/.github/workflows/fhd-release-desktop.yml@refs/heads/feature"
        )
    if case == "wrong_branch":
        run["head_branch"] = "candidate"
    if case == "previous_running":
        run.update(status="in_progress", conclusion=None)
    if case in {"previous_failed", "previous_skipped", "previous_cancelled"}:
        run["conclusion"] = case.removeprefix("previous_")
    harness = """
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const execute = new (Object.getPrototypeOf(async function(){}).constructor)('github', 'context', input.script);
const github = { rest: { actions: { getWorkflowRun: async () => ({ data: input.run }) }, repos: {compareCommits: async ({base}) => ({data: {status: input.ancestry, merge_base_commit: {sha: base}}})} } };
execute(github, {runId: 100, sha: input.controllerSha, repo: {owner: 'fixture', repo: 'fixture'}}).catch(error => { console.error(error.message); process.exitCode = 1; });
"""
    result = subprocess.run(
        ["node", "-e", harness],
        input=json.dumps(
            {
                "script": script,
                "run": run,
                "controllerSha": "b" * 40
                if case in {"same_run_newer", "not_ancestor"}
                else "a" * 40,
                "ancestry": "diverged" if case == "not_ancestor" else "ahead",
            }
        ),
        env=environment,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == (
        0 if case in {"same_run", "same_run_newer", "completed_previous"} else 1
    ), result.stderr


@pytest.mark.parametrize(
    "job_name,working,paths",
    [
        ("publish-interim-windows-pointer", ".", {"FHD/scripts/release"}),
        ("release-preflight", ".", {"FHD/scripts/security", "scripts/ci"}),
        ("macos", "FHD", {"FHD/scripts/release"}),
        ("generate-manifest", "FHD", {"FHD/scripts/release", "FHD/scripts/dev"}),
    ],
)
def test_release_gate_controllers_keep_the_product_checkout_frozen(job_name, working, paths):
    workflow = yaml.safe_load((ROOT / ".github/workflows/release-desktop.yml").read_text())
    job = workflow["jobs"][job_name]
    assert job["steps"][0]["with"]["ref"] == "${{ inputs.release_sha }}"
    controller = next(
        step for step in job["steps"] if step.get("with", {}).get("path") == "release-controller"
    )
    assert controller["with"]["ref"] == "${{ github.sha }}"
    assert controller["with"]["persist-credentials"] is False
    assert set(controller["with"]["sparse-checkout"].splitlines()) == paths
    assert job.get("defaults", workflow["defaults"])["run"]["working-directory"] == working
    gates = (
        "verify_upgrade_rollback_evidence.py",
        "verify_security_scan_pair.py",
        "check_release_scope_evidence.py",
    )
    for step in job["steps"]:
        for token in step.get("run", "").split():
            if token.endswith(gates):
                prefix = "../" if working == "FHD" else ""
                assert token.startswith(prefix + "release-controller/FHD/scripts/")
                assert (ROOT / token.split("release-controller/FHD/", 1)[1]).is_file()
    if job_name in {"release-preflight", "publish-interim-windows-pointer"}:
        assert "github.ref == 'refs/heads/main'" in job["if"]
    if job_name != "publish-interim-windows-pointer":
        runs = "\n".join(step.get("run", "") for step in job["steps"])
        path = "../release-controller" if working == "FHD" else "release-controller"
        assert 'test "$GITHUB_REF" = refs/heads/main' in runs
        assert f'test "$(git -C {path} rev-parse HEAD)" = "$GITHUB_SHA"' in runs


def _frozen_controller_workspace(tmp_path, legacy_verifier=None):
    """Execute real Git/CLI/ZIP paths; only GitHub's external transport is replaced."""
    from tests.release_gate.test_upgrade_rollback_evidence import _native_windows

    source = tmp_path / "source"
    source.mkdir()

    def git(*args, cwd=source):
        return subprocess.check_output(
            ["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL
        ).strip()

    def commit(message, cwd=source):
        git("add", ".", cwd=cwd)
        git(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "-qm",
            message,
            cwd=cwd,
        )
        return git("rev-parse", "HEAD", cwd=cwd)

    git("init", "-q", "-b", "main")
    legacy = source / "FHD/scripts/release/verify_upgrade_rollback_evidence.py"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        legacy_verifier
        or "import argparse\np = argparse.ArgumentParser()\np.add_argument('--evidence', required=True)\np.add_argument('--release-sha', required=True)\np.parse_args()\n"
    )
    release_sha = commit("Frozen product with the legacy claims-only CLI")
    _copy_native_controller(legacy.parent)
    controller_sha = commit("Current native acceptance controller")
    candidate = tmp_path / "candidate"
    git("clone", "-q", str(source), str(candidate))
    git("checkout", "-q", release_sha, cwd=candidate)
    git("clone", "-q", str(source), str(candidate / "release-controller"))
    runner = tmp_path / "runner"
    delivery = runner / "delivery"
    delivery.mkdir(parents=True)
    installer = delivery / "XCAGI-Enterprise-Setup-1.0.0.7-x64-unsigned.exe"
    installer.write_bytes(b"immutable installer fixture")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    installer.with_suffix(".exe.sha256").write_text(f"{digest}  {installer.name}\n")
    (delivery / "delivery-receipt.json").write_text(
        json.dumps(
            {
                "version": "1.0.0.7",
                "git_sha": release_sha,
                "sha256": digest,
                "filename": installer.name,
                "delivery_mode": "manual_installer",
                "runner_install_smoke": "passed",
                "stable_auto_update": False,
                "signature_status": "unsigned",
                "authenticode_status": "NotSigned",
            }
        )
    )
    _native_windows(runner / "acceptance", release_sha)
    run = {
        "id": 12,
        "run_attempt": 2,
        "head_sha": controller_sha,
        "head_branch": "main",
        "path": ".github/workflows/fhd-windows-candidate-acceptance.yml",
        "repository": {"full_name": "fixture/repo"},
        "head_repository": {"full_name": "fixture/repo"},
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "run_started_at": "2026-09-04T00:00:00Z",
        "updated_at": "2026-09-04T00:30:00Z",
    }
    api_root = tmp_path / "api"
    api_root.mkdir()
    routes, artifacts = {}, []

    def response(route, payload):
        filename = str(len(routes))
        (api_root / filename).write_bytes(
            payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        )
        routes[route] = filename

    for number, directory in enumerate(sorted((runner / "acceptance").iterdir()), 20):
        record = directory / "acceptance.json"
        row = json.loads(record.read_text(encoding="utf-8-sig"))
        row["candidate_sha256"] = digest
        record.write_text(json.dumps(row))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as bundle:
            for path in directory.iterdir():
                bundle.writestr(path.name, path.read_bytes())
        raw = stream.getvalue()
        artifacts.append(
            {
                "id": number,
                "name": directory.name,
                "expired": False,
                "size_in_bytes": len(raw),
                "workflow_run": {"id": 12, "head_sha": controller_sha},
                "created_at": "2026-09-04T00:25:00Z",
                "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            }
        )
        response(f"repos/fixture/repo/actions/artifacts/{number}/zip", raw)
    response(
        "repos/fixture/repo/actions/runs/11",
        {
            **run,
            "id": 11,
            "head_sha": release_sha,
            "path": ".github/workflows/fhd-release-desktop.yml",
        },
    )
    response("repos/fixture/repo/actions/runs/12", run)
    response("repos/fixture/repo/actions/runs/12/attempts/2", run)
    response(
        "repos/fixture/repo/actions/runs/12/artifacts?per_page=100&page=1",
        {"total_count": 5, "artifacts": artifacts},
    )
    response(f"repos/fixture/repo/compare/{release_sha}...{controller_sha}", {"status": "ahead"})
    response(f"repos/fixture/repo/compare/{controller_sha}...main", {"status": "identical"})
    (api_root / "routes.json").write_text(json.dumps(routes))
    gh = tmp_path / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\nimport json, os, pathlib, sys\nroot = pathlib.Path(os.environ['FAKE_API'])\nroutes = json.loads((root / 'routes.json').read_text())\nsys.stdout.buffer.write((root / routes[sys.argv[2]]).read_bytes())\n"
    )
    gh.chmod(0o700)
    env = {
        "PATH": os.pathsep.join(
            (str(tmp_path), str(Path(sys.executable).parent), os.environ["PATH"])
        ),
        "FAKE_API": str(api_root),
        "RUNNER_TEMP": str(runner),
        "RELEASE_SHA": release_sha,
        "XCAGI_BUILD_SHA": release_sha,
        "CONTROLLER_SHA": controller_sha,
        "CONTROLLER_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "fixture/repo",
        "CANDIDATE_RUN": "11",
        "ACCEPTANCE_RUN": "12",
        "DELIVERY_VERSION": "1.0.0.7",
        "WINDOWS_UNSIGNED": "false",
    }
    return candidate, installer, env, routes


@pytest.mark.parametrize(
    "corruption",
    [
        "none",
        "feature_controller",
        "wrong_controller_sha",
        "wrong_candidate_sha",
        "wrong_run_sha",
        "bad_zip",
        "changed_installer",
    ],
)
def test_frozen_product_uses_current_native_controller_without_rebuilding(tmp_path, corruption):
    candidate, installer, env, routes = _frozen_controller_workspace(tmp_path)
    legacy = subprocess.run(
        [
            sys.executable,
            "FHD/scripts/release/verify_upgrade_rollback_evidence.py",
            "--evidence",
            "unused",
            "--release-sha",
            env["RELEASE_SHA"],
            "--windows-native-dir",
            "unused",
        ],
        cwd=candidate,
        capture_output=True,
        text=True,
    )
    assert (
        legacy.returncode == 2 and "unrecognized arguments: --windows-native-dir" in legacy.stderr
    )
    if corruption == "feature_controller":
        env["CONTROLLER_REF"] = "refs/heads/feature"
    if corruption == "wrong_controller_sha":
        env["CONTROLLER_SHA"] = "a" * 40
    if corruption == "wrong_candidate_sha":
        env["RELEASE_SHA"] = "a" * 40
    api_root = Path(env["FAKE_API"])
    if corruption == "wrong_run_sha":
        path = api_root / routes["repos/fixture/repo/actions/runs/11"]
        row = json.loads(path.read_text())
        row["head_sha"] = "a" * 40
        path.write_text(json.dumps(row))
    if corruption == "bad_zip":
        path = api_root / routes["repos/fixture/repo/actions/artifacts/20/zip"]
        path.write_bytes(path.read_bytes() + b"corruption")
    if corruption == "changed_installer":
        installer.write_bytes(b"different installer")
    workflow = yaml.safe_load((ROOT / ".github/workflows/release-desktop.yml").read_text())
    steps = {
        step.get("name"): step
        for step in workflow["jobs"]["publish-interim-windows-pointer"]["steps"]
    }
    script = "\n".join(
        steps[name]["run"]
        for name in (
            "Verify frozen mainline source and original run provenance",
            "Verify all five frozen candidate acceptance modes",
            "Assert truthful Windows delivery receipt",
        )
    )
    script += "\n" + steps["Generate bounded interim download pointer"]["run"].split("args=(", 1)[0]
    script = (
        script.replace("${{ inputs.release_sha }}", env["XCAGI_BUILD_SHA"])
        .replace("${{ github.repository }}", "fixture/repo")
        .replace("${{ inputs.acceptance_run_id }}", "12")
    )
    result = subprocess.run(
        ["bash", "-eu", "-c", script],
        cwd=candidate,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == (0 if corruption == "none" else 1), result.stdout + result.stderr
    if corruption == "none":
        proof = json.loads(
            (Path(env["RUNNER_TEMP"]) / "windows-lifecycle-verification.json").read_text()
        )
        assert proof["passed"] is True and proof["release_sha"] == env["RELEASE_SHA"]
        assert all(
            source["controller_sha"] == env["CONTROLLER_SHA"] and source["run_attempt"] == 2
            for source in proof["provenance"].values()
        )
