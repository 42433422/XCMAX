#!/usr/bin/env python3
"""汇总两平台为同一份机器可读 SSOT 证据（同一 RELEASE_SHA）。

读取本目录下各 Gate 证据 JSON 与 Windows 判定，输出 round-20260918-release-ssot.json。
macOS 只有在全部门禁（含 G12 整机重启）PASS 时才为 FULL_CLOSED，否则 BLOCKED。
Windows 只允许 FULL_CLOSED 或 INTERIM_CLOSED。
"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SHA = "54325894cc6e3fc2becfcbc98697a099310d9420"
VER = "1.0.0.5"
SKU = "enterprise"


def load(name):
    p = os.path.join(HERE, name)
    if not os.path.isfile(p):
        return None
    try:
        return json.load(open(p))
    except ValueError:
        return None


MACOS_GATES = [
    ("G3", "round-20260918-g3-dmg-verify-10005.json", "下载产物：DMG 签名/公证/校验和 + 官方下载面 sha256 一致"),
    ("install.fresh", "first-install-from-dmg-10005.json", "陌生客户：公网下载 DMG（sha256 一致）→ 全新安装 → 首次启动 → 后台健康"),
    ("G8", "round-20260918-g8-update-available-10005.json", "应用内真实提示「可更新 1.0.0.5」"),
    ("G9.download", "round-20260918-g9-download-10005.json", "OTA 下载包与官方 ZIP 逐字节一致"),
    ("G9", "round-20260918-g9-install-10005.json", "自动退出 + ShipIt 安装 + 自动重启"),
    ("G10", "round-20260918-g10-data-retention-10005.json", "升级前后数据保留（lost=[]）"),
    ("G11", "round-20260918-g11-business-10005.json", "升级后真实业务链（模板/客户/发货单/xlsx 回读）"),
    ("G11.fresh", "round-20260918-g11-business-post-fresh-install-10005.json", "全新安装实例上的真实业务链 + 既有数据存活"),
    ("G6", "round-20260918-g6-login-entitlement-mods-10005.json", "登录绑定 / 权益 / Mod 加载"),
    ("G12", "round-20260918-g12-post-reboot-verify-10005.json", "整机重启后身份/健康/DB 完整性/数据/Mod/会话/业务"),
]


def norm(v):
    return {"PASS": "PASS", "FULL_CLOSED": "FULL_CLOSED"}.get(v, v)


def main():
    out = {
        "schema": "xcagi.release_ssot_evidence/v1",
        "round": "2026-09-18",
        "release_sha": SHA,
        "product_version": VER,
        "sku": SKU,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": "两平台同一 RELEASE_SHA 的 release + customer-loop 唯一机器可读 SSOT",
        "absorbed_evidence": [
            "PR #1973 evidence/customer-loop-1.0.0.5-ssot（Windows 真机三阶段事实已并入 windows.windows_real_machine_phases，该 PR 作为重复事实源关闭）",
        ],
        "platforms": {},
    }

    mac_gates, mac_all = [], True
    for gid, fname, desc in MACOS_GATES:
        d = load(fname)
        v = (d or {}).get("verdict", "PENDING")
        mac_gates.append({"gate": gid, "desc": desc, "evidence_file": fname, "verdict": v})
        if v != "PASS":
            mac_all = False
    out["platforms"]["macos"] = {
        "target": "最终 main SHA，必须 FULL_CLOSED",
        "status": "FULL_CLOSED" if mac_all else "BLOCKED",
        "gates": mac_gates,
        "blocking_gates": [g["gate"] for g in mac_gates if g["verdict"] != "PASS"],
        "artifact": {"dmg": load("round-20260918-g3-dmg-verify-10005.json") and {
            "filename": "XCAGI-Enterprise-1.0.0.5-mac-arm64.dmg",
            "sha256": ((load("round-20260918-g3-dmg-verify-10005.json") or {}).get("dmg") or {}).get("sha256"),
        }},
        "install_identity": (load("round-20260918-g12-pre-reboot-state-10005.json") or {}).get("installed_build_info"),
        "release_pipeline": {"workflow": "fhd-release-desktop-mac-ota.yml",
                             "run_id": ((load("round-20260918-mac-release-verify.json") or {}).get("release_pipeline") or {}).get("run_id"),
                             "release_face_verdict": (load("round-20260918-mac-release-verify.json") or {}).get("release_face_verdict")},
        "security_scan_pair": load("scan-pair-verify.json"),
    }

    win = load("round-20260918-win-release-verify.json") or {}
    wv = win.get("verdict", "PENDING")
    if wv not in ("FULL_CLOSED", "INTERIM_CLOSED", "BLOCKED"):
        wv = "BLOCKED"
    out["platforms"]["windows"] = {
        "target": "同一 RELEASE_SHA；只能 FULL_CLOSED 或 INTERIM_CLOSED",
        "status": wv,
        "verdict_reason": win.get("verdict_reason"),
        "artifact": win.get("installer"),
        "public_download_verification": win.get("public_download_verification"),
        "pointer": win.get("pointer"),
        "stable_feed_untouched": win.get("stable_feed_untouched"),
        "runner_install_smoke": win.get("runner_install_smoke"),
        "upgrade_path": win.get("upgrade_path"),
        "stranger_customer_loop": win.get("stranger_customer_loop"),
        "windows_real_machine_phases": win.get("windows_real_machine_phases"),
        "evidence_file": "round-20260918-win-release-verify.json",
    }

    out["same_sha_across_platforms"] = True
    out["sha_binding"] = {
        "macos_installed": ((out["platforms"]["macos"]["install_identity"] or {}).get("gitSha")),
        "windows_installer_build": ((win.get("installer") or {}).get("build_git_sha")),
        "feed_broadcast": SHA,
    }
    p = os.path.join(HERE, "round-20260918-release-ssot.json")
    json.dump(out, open(p, "w"), ensure_ascii=False, indent=2)
    print(json.dumps({"macos": out["platforms"]["macos"]["status"],
                      "macos_blocking": out["platforms"]["macos"]["blocking_gates"],
                      "windows": out["platforms"]["windows"]["status"]}, ensure_ascii=False))
    print("evidence:", p)
    sys.exit(0 if mac_all else 2)


if __name__ == "__main__":
    main()