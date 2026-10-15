#!/usr/bin/env python3
"""校验 总账 / 原始 JSON / 截图 / 安装结果 四者一致（全部以文件为准，不手写）。"""
import json
import os
import sys

DST = "/Users/a4243342/Desktop/XCMAX/FHD/docs/evidence/e2e/macos-release-1.0.0.5-8d50fe9d"
ledger = json.load(open(os.path.join(DST, "delivery-ledger.json")))
c2 = ledger["chain_2_ota_upgrade"]["steps"]
fails, notes = [], []


def load(name):
    p = os.path.join(DST, name)
    if not os.path.isfile(p):
        fails.append("missing raw json: %s" % name)
        return {}
    try:
        return json.load(open(p))
    except Exception as e:
        fails.append("invalid json %s: %s" % (name, e))
        return {}


def expect(step, field, value):
    got = c2.get(step, {}).get(field)
    if got != value:
        fails.append("%s.%s = %r, raw json says %r" % (step, field, got, value))


# 1) 原始 JSON 必须可解析
raw_ota_check = load("ota-check.json")
raw_ota_download = load("ota-download.json")
raw_install = load("ota-install.json")
raw_obs = load("ota-observation.json")
raw_integ = load("ota-backend-integrity.json")
raw_cont = load("chain2-continuity-ui.json")
raw_step3 = load("ui-post-ota-step3.json")
raw_step4 = load("ui-post-ota-step4.json")
raw_probe = load("phase-c-real-template.json")
raw_post_build = load("post-ota-installed-build-info.json")
raw_prior_build = load("chain2-prior-build-info.json")

# 2) 总账各字段 == 原始 JSON
chk = json.loads(raw_ota_check["check_result"])
vi = chk.get("versionInfo") or {}
expect("ota_check", "isUpdateAvailable", chk.get("isUpdateAvailable"))
expect("ota_check", "target_buildSha", vi.get("buildSha"))
expect("ota_check", "target_zip_sha512", vi.get("sha512"))
expect("ota_check", "verdict", "PASS" if chk.get("isUpdateAvailable") and vi.get("buildSha") else "BLOCKED")

dl = json.loads(raw_ota_download["download_result"] or "[]")
expect("ota_download", "downloaded_file", dl[0] if isinstance(dl, list) and dl else None)
expect("ota_download", "verdict", "PASS" if (raw_ota_download.get("status") or {}).get("type") == "update-downloaded" else "BLOCKED")

expect("ota_install", "verdict", raw_install.get("verdict"))
expect("ota_install", "shipit_markers", (raw_install.get("shipit") or {}).get("markers"))
expect("observation_commit", "verdict", raw_obs.get("verdict"))
expect("backend_integrity", "verdict", raw_integ.get("verdict"))
expect("backend_integrity", "checks", raw_integ.get("checks"))
expect("continuity_ui", "verdict", raw_cont.get("verdict"))
expect("continuity_ui", "checks", raw_cont.get("checks"))
expect("post_ota_real_template_generate", "verdict", raw_step4.get("verdict") or raw_step3.get("verdict"))
expect("merged_template_probe", "verdict", raw_probe.get("verdict"))
expect("post_ota_build", None, None) if False else None
if c2.get("post_ota_build") != raw_post_build.get("gitSha"):
    fails.append("post_ota_build %r != post-ota-installed-build-info.gitSha %r" % (c2.get("post_ota_build"), raw_post_build.get("gitSha")))
if c2.get("prior_build_installed") != raw_prior_build.get("gitSha"):
    fails.append("prior_build_installed %r != chain2-prior-build-info.gitSha %r" % (c2.get("prior_build_installed"), raw_prior_build.get("gitSha")))

# 3) 安装结果关键点必须为真
m = (raw_install.get("shipit") or {}).get("markers") or {}
for k in ("installation_completed", "bundle_replaced_to_target", "post_install_health"):
    if m.get(k) is not True:
        fails.append("install marker %s is not true: %r" % (k, m.get(k)))
if (raw_integ.get("checks") or {}).get("key_source_has_fix") is not True:
    fails.append("backend integrity: installed shipment_document has no fix")
if raw_integ.get("shipment_document", {}).get("installed_md5") != raw_integ.get("shipment_document", {}).get("zip_md5"):
    fails.append("backend integrity: shipment_document md5 mismatch")

# 4) 截图（录像）必须存在且非空
for key in ("pre_ota", "post_ota", "continue"):
    s = c2.get("screenshots", {}).get(key) or {}
    p = os.path.join(DST, s.get("file", ""))
    if not os.path.isfile(p) or os.path.getsize(p) == 0:
        fails.append("screenshot missing/empty: %s" % s.get("file"))

# 5) 总账 verdict == 各段 verdict 的合取
steps = c2
expected_chain2 = "PASS" if all(
    (steps.get(k, {}).get("verdict") == "PASS")
    for k in ("prior_install_identity", "ota_check", "ota_download", "ota_install", "observation_commit", "backend_integrity",
              "continuity_ui", "post_ota_real_template_generate", "merged_template_probe")
) else "BLOCKED"
if ledger["chain_2_ota_upgrade"]["verdict"] != expected_chain2:
    fails.append("chain_2 verdict %r != derived %r" % (ledger["chain_2_ota_upgrade"]["verdict"], expected_chain2))
expected_overall = "PASS" if ledger["chain_1_official_download_and_ui"]["verdict"] == "PASS" and expected_chain2 == "PASS" else "BLOCKED"
if ledger["verdict"] != expected_overall:
    fails.append("overall verdict %r != derived %r" % (ledger["verdict"], expected_overall))

# 6) 总账引用的证据文件必须存在
for name, step in steps.items():
    ev = step.get("evidence") if isinstance(step, dict) else None
    if not ev:
        continue
    for token in str(ev).replace("（", " ").replace("）", " ").split():
        if token.endswith(".json") or token.endswith(".jsonl") or token.endswith(".png"):
            if not os.path.isfile(os.path.join(DST, token)):
                fails.append("ledger references missing evidence: %s (in %s)" % (token, name))

print(json.dumps({
    "chain_1": ledger["chain_1_official_download_and_ui"]["verdict"],
    "chain_2": ledger["chain_2_ota_upgrade"]["verdict"],
    "overall": ledger["verdict"],
    "chain_2_steps": {k: (v.get("verdict") if isinstance(v, dict) else v) for k, v in steps.items()},
    "failures": fails,
}, ensure_ascii=False, indent=1))
print("CONSISTENT" if not fails else "INCONSISTENT")
sys.exit(0 if not fails else 1)
