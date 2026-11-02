"""Exercise account isolation using synthetic metadata; never call a login service."""

import base64
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/package/windows-acceptance-accounts.mjs"
MODES = ("Clean", "Upgrade", "Gui", "Recovery", "Rollback")
HARNESS = """
import fs from 'node:fs';
const request = JSON.parse(fs.readFileSync(0, 'utf8'));
try {
  const api = await import(process.argv[1]);
  const value = request.operation === 'identity'
    ? api.assertIdentity(request.identity, request.env)
    : api.selectAccounts(request.env);
  console.log(JSON.stringify({ok: true, value: value ?? null}));
} catch (error) {
  console.log(JSON.stringify({ok: false, error: error.message}));
}
"""


def invoke(env, identity=None):
    request = {"env": env, "operation": "plan" if identity is None else "identity"}
    if identity is not None:
        request["identity"] = identity
    process = subprocess.run(
        ["node", "--input-type=module", "-e", HARNESS, MODULE.as_uri()],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=True,
        timeout=15,
    )
    assert process.stderr == ""
    return json.loads(process.stdout)


def pool():
    env = {"ACCOUNT_MODE": "isolated-parallel"}
    for index, mode in enumerate(MODES, 101):
        prefix = f"XCAGI_TEST_{mode.upper()}"
        env.update(
            {
                f"{prefix}_USER": f"synthetic-{mode}-user",
                f"{prefix}_PASS": f"synthetic-{mode}-password",
                f"{prefix}_MARKET_USER_ID": str(index),
            }
        )
    return env


def process_env():
    # Node needs Windows OS paths; do not inherit unrelated application credentials.
    return {
        key: os.environ[key]
        for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP")
        if key in os.environ
    }


@pytest.mark.parametrize(
    "only,modes",
    [("", MODES), ("Lifecycle", ("Clean", "Upgrade", "Rollback")), ("Rollback", ("Rollback",))],
)
def test_isolated_plan_binds_each_mode_to_its_own_complete_identity(only, modes):
    env = {**pool(), "ONLY": only}
    result = invoke(env)
    assert result["ok"] is True
    assert result["value"]["parallel"] == 5
    assert result["value"]["matrix"] == [
        {
            "mode": mode,
            "user_secret": f"XCAGI_TEST_{mode.upper()}_USER",
            "pass_secret": f"XCAGI_TEST_{mode.upper()}_PASS",
            "market_user_id": env[f"XCAGI_TEST_{mode.upper()}_MARKET_USER_ID"],
        }
        for mode in modes
    ]
    encoded = json.dumps(result)
    assert all(
        value not in encoded for key, value in env.items() if key.endswith(("_USER", "_PASS"))
    )


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("field", ("USER", "PASS", "MARKET_USER_ID"))
def test_missing_isolated_configuration_never_falls_back_to_shared_credentials(mode, field):
    env = {
        **pool(),
        "XCAGI_TEST_USER": "shared-sentinel-user",
        "XCAGI_TEST_PASS": "shared-sentinel-password",
        "ONLY": "Rollback",
    }
    env.pop(f"XCAGI_TEST_{mode.upper()}_{field}")
    result = invoke(env)
    assert result["ok"] is False
    encoded = json.dumps(result)
    assert all(
        value not in encoded for key, value in env.items() if key.endswith(("_USER", "_PASS"))
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("XCAGI_TEST_GUI_USER", "  SYNTHETIC-clean-USER  "),
        ("XCAGI_TEST_GUI_MARKET_USER_ID", "101"),
        ("XCAGI_TEST_GUI_MARKET_USER_ID", "0101"),
        ("XCAGI_TEST_GUI_MARKET_USER_ID", "0"),
        ("XCAGI_TEST_GUI_MARKET_USER_ID", "-1"),
        ("XCAGI_TEST_GUI_MARKET_USER_ID", "1e2"),
        ("XCAGI_TEST_GUI_MARKET_USER_ID", "not-an-id"),
        ("XCAGI_TEST_GUI_PASS", "   "),
        ("ACCOUNT_MODE", "unknown-mode"),
        ("ONLY", "Unknown"),
    ],
)
def test_unsafe_or_ambiguous_pool_is_rejected_without_echoing_credentials(key, value):
    env = {**pool(), key: value}
    result = invoke(env)
    assert result["ok"] is False
    encoded = json.dumps(result)
    assert "synthetic-" not in encoded.lower()


@pytest.mark.parametrize("explicit", [False, True])
def test_legacy_credentials_remain_explicitly_serial(explicit):
    env = {"XCAGI_TEST_USER": "legacy-user", "XCAGI_TEST_PASS": "legacy-password"}
    if explicit:
        env["ACCOUNT_MODE"] = "shared-serial"
    result = invoke(env)
    assert result["ok"] is True
    assert result["value"]["parallel"] == 1
    assert [entry["mode"] for entry in result["value"]["matrix"]] == list(MODES)
    assert all(
        entry["user_secret"] == "XCAGI_TEST_USER"
        and entry["pass_secret"] == "XCAGI_TEST_PASS"
        and not entry["market_user_id"]
        for entry in result["value"]["matrix"]
    )


def identity():
    return {
        "account_kind": "enterprise",
        "market_is_enterprise": True,
        "market_is_admin": False,
        "market_user_id": 101,
        "impersonating_market_user_id": None,
        "tenant_id": 1,
    }


IDENTITY_ENV = {
    "XCAGI_ACCEPTANCE_ACCOUNT_MODE": "isolated-parallel",
    "XCAGI_TEST_MARKET_USER_ID": "101",
}


@pytest.mark.parametrize(
    "patch",
    [
        {"market_user_id": None},
        {"market_user_id": 102},
        {"market_is_admin": True},
        {"market_is_enterprise": False},
        {"impersonating_market_user_id": 101},
        {"account_kind": "personal"},
    ],
)
def test_real_login_identity_must_match_pinned_enterprise_without_impersonation(patch):
    result = invoke(IDENTITY_ENV, {**identity(), **patch})
    assert result["ok"] is False
    assert "101" not in result["error"] and "102" not in result["error"]


def test_local_tenant_numbers_are_not_treated_as_cross_machine_account_identity():
    for market_id in (101, 102):
        result = invoke(
            {**IDENTITY_ENV, "XCAGI_TEST_MARKET_USER_ID": str(market_id)},
            {**identity(), "market_user_id": market_id},
        )
        assert result == {"ok": True, "value": hashlib.sha256(str(market_id).encode()).hexdigest()}
    assert invoke({}, {})["ok"] is True  # Existing serial collectors need no new pin.
    assert invoke({**IDENTITY_ENV, "XCAGI_TEST_MARKET_USER_ID": ""}, identity())["ok"] is False


@pytest.mark.parametrize("complete", [True, False])
def test_preflight_cli_only_publishes_secret_names_after_validation(tmp_path, complete):
    output = tmp_path / "github-output"
    env = {**process_env(), **pool(), "GITHUB_OUTPUT": str(output), "ONLY": ""}
    if not complete:
        env.pop("XCAGI_TEST_GUI_PASS")
    process = subprocess.run(
        ["node", str(MODULE)],
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert process.returncode == (0 if complete else 1)
    assert output.exists() is complete
    text = process.stdout + process.stderr + (output.read_text() if output.exists() else "")
    assert "synthetic-" not in text
    if complete:
        fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
        assert fields["parallel"] == "5"
        assert len(json.loads(fields["matrix"])) == 5


def test_workflow_wires_validated_pool_and_preserves_release_provenance():
    text = (ROOT / ".github/workflows/windows-candidate-acceptance.yml").read_text("utf-8")
    workflow = yaml.safe_load(text)
    inputs = (workflow.get("on") or workflow[True])["workflow_dispatch"]["inputs"]
    assert inputs["account_mode"]["default"] == "shared-serial"
    assert inputs["account_mode"]["options"] == ["shared-serial", "isolated-parallel"]
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert "github.run_id" not in str(workflow["concurrency"]["group"])
    selection = workflow["jobs"]["select-modes"]
    preflight = next(
        step
        for step in selection["steps"]
        if "windows-acceptance-accounts.mjs" in step.get("run", "")
    )
    for mode in MODES:
        prefix = f"XCAGI_TEST_{mode.upper()}"
        assert preflight["env"][f"{prefix}_USER"] == "${{ secrets." + f"{prefix}_USER" + " }}"
        assert preflight["env"][f"{prefix}_PASS"] == "${{ secrets." + f"{prefix}_PASS" + " }}"
        assert (
            preflight["env"][f"{prefix}_MARKET_USER_ID"]
            == "${{ vars." + f"{prefix}_MARKET_USER_ID" + " }}"
        )
    install = workflow["jobs"]["isolated-install"]
    assert "needs.select-modes.outputs" in str(install["strategy"]["max-parallel"])
    assert install["runs-on"] == "windows-latest"
    assert install["strategy"]["fail-fast"] is False
    acceptance = next(
        step for step in install["steps"] if "accept-windows-candidate.ps1" in step.get("run", "")
    )
    assert acceptance["env"]["XCAGI_TEST_USER"] == "${{ secrets[matrix.user_secret] }}"
    assert acceptance["env"]["XCAGI_TEST_PASS"] == "${{ secrets[matrix.pass_secret] }}"
    assert acceptance["env"]["XCAGI_TEST_MARKET_USER_ID"] == "${{ matrix.market_user_id }}"
    assert "Candidate file SHA-256 mismatch" in acceptance["run"]
    assert "Candidate receipt SHA mismatch" in acceptance["run"]
    assert "run.head_sha !== sha" in text and "run.head_branch !== 'main'" in text
    publish = (ROOT / ".github/workflows/release-desktop.yml").read_text("utf-8")
    assert "for mode in Clean Upgrade Gui Recovery Rollback; do" in publish


def test_gui_checks_cloud_identity_before_business_and_names_fixtures_by_mode():
    gui = (ROOT / "scripts/dev/record_enterprise_desktop_init.mjs").read_text("utf-8")
    check = gui.index("assertIdentity(", gui.index("async function main"))
    assert check < gui.index("if (phase === 'identity')") < gui.index("step('customer'")
    marker = next(line for line in gui.splitlines() if line.startswith("const marker ="))
    assert "mode" in marker.lower()
    collector = (ROOT / "scripts/package/accept-windows-candidate.ps1").read_text("utf-8-sig")
    assert "XCAGI_TEST_MARKET_USER_ID" in collector
    assert "market_user_id" in collector and "market_is_admin" in collector
    assert "same_enterprise" in collector and "backup_restore_enterprise" in collector


@pytest.mark.skipif(
    not shutil.which("pwsh"), reason="PowerShell is needed to exercise the Windows collector"
)
def test_powershell_login_rejects_wrong_cloud_identity_before_acceptance():
    collector = (ROOT / "scripts/package/accept-windows-candidate.ps1").read_text("utf-8-sig")
    digest = (
        "function Digest"
        + collector.split("function Digest", 1)[1].split("function Uninstall-OldApp", 1)[0]
    )
    login = (
        "function Login"
        + collector.split("function Login", 1)[1].split("function Backup-And-Version", 1)[0]
    )
    cases = [
        identity(),
        *[
            {**identity(), **patch}
            for patch in (
                {"market_user_id": 102},
                {"market_is_admin": True},
                {"market_is_enterprise": None},
                {"impersonating_market_user_id": 101},
                {"market_is_enterprise": "true", "market_is_admin": "false"},
            )
        ],
    ]
    harness = (
        r"""
$ErrorActionPreference = 'Stop'
$cases = ConvertFrom-Json -InputObject ([Console]::In.ReadToEnd())
$accountMode = 'isolated-parallel'; $base = 'http://unused.invalid'
$env:XCAGI_TEST_USER = 'synthetic-user'; $env:XCAGI_TEST_PASS = 'synthetic-password'
$env:XCAGI_TEST_MARKET_USER_ID = '101'
function Check([bool]$ok, [string]$name, [string]$detail) {
  $script:checks += @{name=$name; passed=$ok; detail=$detail}
  if (-not $ok) { throw "$name failed: $detail" }
}
function Invoke-WebRequest { return @{ StatusCode=200; Content='{"success":true}' } }
function Invoke-RestMethod { return @{ data=$script:identity } }
"""
        + digest
        + login
        + r"""
$results = @(foreach ($case in $cases) {
  $script:identity=$case; $script:evidence=@{}; $script:checks=@()
  try { $auth = Login 'candidate'; @{ok=$true; tenant=$auth.tenant; evidence=$script:evidence; checks=$script:checks} }
  catch { @{ok=$false; error=$_.Exception.Message; checks=$script:checks} }
})
ConvertTo-Json -InputObject $results -Depth 8 -Compress
"""
    )
    process = subprocess.run(
        [
            shutil.which("pwsh"),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(harness.encode("utf-16le")).decode(),
        ],
        input=json.dumps(cases),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    results = json.loads(process.stdout)
    assert [result["ok"] for result in results] == [True, False, False, False, False, False]
    assert results[0]["tenant"] == "1"
    assert results[0]["evidence"]["market_user_sha256"] == hashlib.sha256(b"101").hexdigest()
    assert "synthetic-user" not in process.stdout and "synthetic-password" not in process.stdout


@pytest.mark.parametrize(
    "credentials",
    [
        {"XCAGI_TEST_USER": "synthetic-user", "XCAGI_TEST_PASS": "synthetic-password"},
        {"XCAGI_TEST_USER": 'synthetic-"user', "XCAGI_TEST_PASS": 'synthetic-"password\\value'},
    ],
)
def test_gui_failure_evidence_redacts_credentials_before_text_and_json_encoding(credentials):
    source = ROOT / "scripts/dev/record_enterprise_desktop_init.mjs"
    harness = r"""
import fs from 'node:fs'; import path from 'node:path';
const source = fs.readFileSync(process.argv[1], 'utf8');
const env = JSON.parse(fs.readFileSync(0, 'utf8'));
const fragment = source.slice(source.indexOf('const redact ='), source.indexOf('async function click'));
const writer = source.split('\n').find(line => line.includes("fs.writeFileSync(path.join(dir, 'gui-business.json')"));
const files = {}, screenshots = [], evidence = {cases: []};
const secrets = Object.values(env).join(' / ');
const page = {screenshot: async options => screenshots.push(options),
  getByText: (value, options) => {
    if (value !== env.XCAGI_TEST_USER || options.exact !== true) throw new Error('Account screenshot mask is not exact');
    return {selector: 'exact-username'};
  }, locator: selector => ({
  selector, innerText: async () => secrets,
  evaluateAll: async action => action([{textContent: secrets, getAttribute: () => null, disabled: false}]),
})};
await new Function('process', 'fs', 'path', 'page', 'evidence', 'names', 'dir', 'secrets',
  `return (async () => {${fragment}
    await step('good', async () => ({value: secrets}));
    try { await step('bad', async () => {throw new Error(secrets)}) } catch {}
    ${writer}
  })()`
)({env}, {writeFileSync: (name, value) => {files[path.basename(name)] = value}}, path,
  page, evidence, {}, 'unused', secrets);
console.log(JSON.stringify({files, masks: screenshots.map(shot => shot.mask.map(mask => mask.selector))}));
"""
    process = subprocess.run(
        ["node", "--input-type=module", "-e", harness, str(source)],
        input=json.dumps(credentials),
        text=True,
        capture_output=True,
        check=True,
        timeout=15,
    )
    result = json.loads(process.stdout)
    business = json.loads(result["files"]["gui-business.json"])
    decoded = json.dumps(business) + result["files"]["bad-ui.txt"]
    for secret in credentials.values():
        assert secret not in result["files"]["bad-ui.txt"]
        assert secret not in json.dumps(business, ensure_ascii=False)
        assert secret not in business["cases"][0]["actual"]["value"]
    assert "[REDACTED]" in decoded
    assert business["cases"][1]["status"] == "failed"
    assert result["masks"] == [["#lv-username,#lv-password", "exact-username"]] * 2


@pytest.mark.parametrize(
    "scenario", ["redraw", "wrong-version", "changed-readback", "detached", "missing"]
)
def test_visible_version_retries_entire_dom_read_and_rejects_persistent_failures(scenario):
    source = ROOT / "scripts/dev/record_enterprise_desktop_init.mjs"
    harness = r"""
import fs from 'node:fs';
const source = fs.readFileSync(process.argv[1], 'utf8');
const {scenario} = JSON.parse(fs.readFileSync(0, 'utf8'));
const helper = source.slice(source.indexOf('async function visibleVersion('), source.indexOf('async function main('));
const expected = '1.0.0.7', events = [];
let attempts = 0, clock = 0, outerOptions;
function bounded(options) {
  if (!(options.timeout > 0 && options.timeout <= 3000)) throw new Error('Unbounded DOM operation');
}
const page = {locator(selector) {
  if (selector !== '.settings-card--about summary .settings-row__meta') throw new Error('Wrong version element');
  const id = ++attempts;
  return {id, text: scenario === 'wrong-version' ? '1.0.0.6' : expected,
    async scrollIntoViewIfNeeded(options) {
      bounded(options); events.push(['scroll', id]);
      if (scenario === 'missing') {clock += options.timeout; throw new Error('Version element missing')}
      if (scenario === 'detached' || (scenario === 'redraw' && id === 1)) throw new Error('Element detached at scroll');
    },
    async innerText(options) {
      bounded(options); events.push(['read', id]);
      if (scenario === 'redraw' && id === 2) throw new Error('Element detached at read');
      return `  ${scenario === 'changed-readback' ? '1.0.0.6' : this.text}\n`;
    },
  };
}};
function expect(value) {
  if (typeof value === 'function') return {async toPass(options) {
    outerOptions = options;
    if (!(options.timeout > 0 && options.timeout <= 20000)
      || !options.intervals?.length || options.intervals.some(delay => delay < 200)) throw new Error('Unbounded retry');
    let lastError, retry = 0;
    while (clock < options.timeout) {
      try {await value(); return} catch (error) {lastError = error}
      clock += options.intervals[Math.min(retry++, options.intervals.length - 1)];
    }
    throw lastError;
  }};
  if (value && typeof value === 'object') return {async toHaveText(wanted, options) {
    bounded(options); events.push(['text', value.id]);
    if (wanted !== expected || value.text !== wanted) {clock += options.timeout; throw new Error('Version mismatch')}
  }};
  return {toBe(wanted) {if (value !== wanted) throw new Error('Readback version mismatch')}};
}
let result;
try {
  const value = await new Function('page', 'expect', `${helper}; return visibleVersion('${expected}')`)(page, expect);
  result = {ok: true, value};
} catch (error) {result = {ok: false, error: error.message}}
console.log(JSON.stringify({...result, attempts, clock, outerOptions, events}));
"""
    process = subprocess.run(
        ["node", "--input-type=module", "-e", harness, str(source)],
        input=json.dumps({"scenario": scenario}),
        text=True,
        capture_output=True,
        check=True,
        timeout=15,
    )
    result = json.loads(process.stdout)
    assert result["outerOptions"]["timeout"] <= 20000
    if scenario == "redraw":
        assert result["ok"] is True
        assert result["value"] == {"expected_version": "1.0.0.7", "visible_version": "1.0.0.7"}
        assert result["attempts"] == 3
        assert result["events"] == [
            ["scroll", 1],
            ["scroll", 2],
            ["text", 2],
            ["read", 2],
            ["scroll", 3],
            ["text", 3],
            ["read", 3],
        ]
    else:
        assert result["ok"] is False
        assert 1 < result["attempts"] <= 101
        assert 20000 <= result["clock"] <= 23000
        assert (
            result["error"]
            == {
                "wrong-version": "Version mismatch",
                "changed-readback": "Readback version mismatch",
                "detached": "Element detached at scroll",
                "missing": "Version element missing",
            }[scenario]
        )
