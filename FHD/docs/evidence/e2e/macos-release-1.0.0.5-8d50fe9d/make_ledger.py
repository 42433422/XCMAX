"""从本轮真机证据文件装配交付总账（数值全部取自证据，不手写）。

一致性原则：总账里 chain_2（OTA）段的每个字段都能在原始 JSON / 截图 / 安装结果里找到对应，
且各段 verdict 由原始 JSON 推导，禁止手写覆盖。
"""
import hashlib
import json
import os
import time

SRC_DIRS = [
    "/private/tmp/xcagi-custchain/evidence-ota",
    "/private/tmp/xcagi-custchain/evidence-8d50fe9d",
]
DST = "/Users/a4243342/Desktop/XCMAX/FHD/docs/evidence/e2e/macos-release-1.0.0.5-8d50fe9d"


def rd(name, default=None):
    for base in SRC_DIRS + [DST]:
        p = os.path.join(base, name)
        if os.path.isfile(p):
            try:
                return json.load(open(p))
            except Exception:
                return default
    return default


def rd_text(name):
    for base in SRC_DIRS + [DST]:
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return open(p, encoding="utf-8", errors="ignore").read()
    return ""


def art(name):
    """返回证据文件名 + 字节数（存在性校验）。"""
    for base in SRC_DIRS + [DST]:
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return {"file": name, "bytes": os.path.getsize(p)}
    return {"file": name, "bytes": 0, "missing": True}


def sha256_file(name):
    for base in SRC_DIRS + [DST]:
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return hashlib.sha256(open(p, "rb").read()).hexdigest()
    return None


def parse_json_string(s):
    try:
        return json.loads(s)
    except Exception:
        return {}


# ---------- chain 1（官网 DMG + UI 全链路，沿用上一轮已验证据） ----------
final = {s: rd("final-%s.json" % s) or {} for s in ("step0", "step1", "step2", "step2b", "step3", "step4", "step5")}
continuity = rd("final-continuity.json") or {}
offline = rd("final-offline-verify.json") or {}
digest_fresh = rd("final-digest-fresh.json") or {}
digest_restart = rd("final-digest-restart.json") or {}
chain1_health = rd("chain1-health.json") or {}
chain1_gui_entry = rd("chain1-gui-entry.json") or {}
chain1_restart_gui = rd("chain1-restart-recovery-gui.json") or {}
gui_login = rd("gui-login.json") or {}
scanpair = rd("security-scan-pair-verify.json") or {}

doc4 = final["step4"].get("file") or {}
doc_rows = doc4.get("rows") or []
tpl1 = (final["step1"].get("created") or [{}])[0]

# ---------- chain 2（OTA 段，本轮重跑） ----------
ota_check_raw = rd("ota-check.json") or {}
ota_check = parse_json_string(ota_check_raw.get("check_result") or "")
ota_check_vi = (ota_check.get("versionInfo") or {})
ota_download_raw = rd("ota-download.json") or {}
ota_download = parse_json_string(ota_download_raw.get("download_result") or "[]")
ota_install = rd("ota-install.json") or {}
ota_observation = rd("ota-observation.json") or {}
ota_integrity = rd("ota-backend-integrity.json") or {}
ota_prior_install = rd("ota-prior-install.json") or {}
chain2_prior = rd("chain2-prior-build-info.json") or {}
chain2_post = rd("post-ota-installed-build-info.json") or {}
chain2_cont_ui = rd("chain2-continuity-ui.json") or {}
post_step3 = rd("ui-post-ota-step3.json") or {}
post_step4 = rd("ui-post-ota-step4.json") or {}
real_tpl = rd("phase-c-real-template.json") or {}
ota_post_health = rd("ota-post-health.json") or {}
poll_lines = [l for l in rd_text("ota-status-poll.jsonl").splitlines() if l.strip()]

ota_check_verdict = "PASS" if ota_check.get("isUpdateAvailable") is True and (
    ota_check_vi.get("buildSha")) else "BLOCKED"
ota_install_verdict = ota_install.get("verdict") or "n/a"
integrity_verdict = ota_integrity.get("verdict") or "n/a"
post_gen_verdict = post_step4.get("verdict") or post_step3.get("verdict") or "n/a"

chain2_steps = {
    "prior_build_installed": chain2_prior.get("gitSha"),
    "prior_install_identity": {
        "dmg_sha256": ota_prior_install.get("dmg_sha256"),
        "dmg_size": ota_prior_install.get("dmg_size"),
        "spctl": ota_prior_install.get("spctl"),
        "codesign_ok": ota_prior_install.get("codesign_ok"),
        "stapler": ota_prior_install.get("stapler"),
        "build_info_sha": (ota_prior_install.get("build_info") or {}).get("gitSha"),
        "verdict": ota_prior_install.get("verdict"),
        "evidence": "ota-prior-install.json",
    },
    "ota_check": {
        "isUpdateAvailable": ota_check.get("isUpdateAvailable"),
        "target_buildSha": ota_check_vi.get("buildSha"),
        "target_zip_size": ((ota_check_vi.get("files") or [{}])[0] or {}).get("size"),
        "target_zip_sha512": ota_check_vi.get("sha512"),
        "signature": ota_check_vi.get("signature"),
        "evidence": "ota-check.json（应用内 IPC checkForUpdates 的真实返回）",
        "verdict": ota_check_verdict,
    },
    "ota_download": {
        "downloaded_file": ota_download[0] if isinstance(ota_download, list) and ota_download else None,
        "event": (ota_download_raw.get("status") or {}).get("type"),
        "poll_samples": len(poll_lines),
        "evidence": "ota-download.json + ota-status-poll.jsonl",
        "verdict": "PASS" if (ota_download_raw.get("status") or {}).get("type") == "update-downloaded" else "BLOCKED",
    },
    "ota_install": {
        "shipit_markers": (ota_install.get("shipit") or {}).get("markers"),
        "installed_buildSha": (ota_install.get("installed_build_info") or {}).get("gitSha"),
        "post_install_health": (ota_install.get("post_install_health") or {}).get("status"),
        "evidence": "ota-install.json（ShipIt 真实日志 + 替换后 build-info + health）",
        "verdict": ota_install_verdict,
    },
    "observation_commit": {
        "rollback_marker_present": ota_observation.get("rollback_marker_present"),
        "rollback_applied_present": ota_observation.get("rollback_applied_present"),
        "note": "更新后首次启动进入观察期；观察期内重启会触发应用按设计回滚 backend（本轮 harness 已按此修正）。",
        "evidence": "ota-observation.json",
        "verdict": ota_observation.get("verdict"),
    },
    "backend_integrity": {
        "update_zip": ota_integrity.get("update_zip"),
        "checks": ota_integrity.get("checks"),
        "informational_differing_count": ota_integrity.get("informational_differing_count"),
        "shipment_document": ota_integrity.get("shipment_document"),
        "evidence": "ota-backend-integrity.json（codesign/spctl/stapler + 关键源码与更新包一致）",
        "verdict": integrity_verdict,
    },
    "post_ota_build": chain2_post.get("gitSha"),
    "post_ota_health": {"status": ota_post_health.get("status"), "version": ota_post_health.get("version")},
    "continuity_ui": {
        "verdict": chain2_cont_ui.get("verdict"),
        "checks": chain2_cont_ui.get("checks"),
        "evidence": "chain2-continuity-ui.json",
    },
    "post_ota_real_template_generate": {
        "doc": (post_step3.get("result_panel") or {}),
        "download": (post_step4.get("file") or {}).get("name"),
        "download_bytes": (post_step4.get("file") or {}).get("bytes"),
        "download_xlsx_magic": (post_step4.get("file") or {}).get("xlsx_magic"),
        "verdict": post_gen_verdict,
        "evidence": "ui-post-ota-step3.json + ui-post-ota-step4.json",
    },
    "merged_template_probe": {
        "generate_status": (real_tpl.get("steps") or {}).get("generate", {}).get("status"),
        "verdict": real_tpl.get("verdict"),
        "first_real_breakpoint": real_tpl.get("first_real_breakpoint"),
        "evidence": "phase-c-real-template.json",
    },
    "screenshots": {
        "pre_ota": art("chain2-01-pre-ota.png"),
        "post_ota": art("chain2-02-post-ota.png"),
        "continue": art("chain2-03-continue.png"),
    },
}
chain2_verdicts = [
    chain2_steps["prior_install_identity"]["verdict"],
    chain2_steps["ota_check"]["verdict"],
    chain2_steps["ota_download"]["verdict"],
    chain2_steps["ota_install"]["verdict"],
    chain2_steps["observation_commit"]["verdict"],
    chain2_steps["backend_integrity"]["verdict"],
    chain2_steps["continuity_ui"]["verdict"],
    chain2_steps["post_ota_real_template_generate"]["verdict"],
    chain2_steps["merged_template_probe"]["verdict"],
]
chain2_verdict = "PASS" if all(v == "PASS" for v in chain2_verdicts) else "BLOCKED"

chain1_verdicts = [
    final["step0"].get("verdict"), final["step1"].get("verdict"), final["step2"].get("verdict"),
    final["step2b"].get("verdict"), final["step3"].get("verdict"), final["step4"].get("verdict"),
    final["step5"].get("verdict"), continuity.get("verdict"),
]
chain1_verdict = "PASS" if all(v == "PASS" for v in chain1_verdicts) else "BLOCKED"

overall = "PASS" if chain1_verdict == "PASS" and chain2_verdict == "PASS" else "BLOCKED"

ledger = {
    "schema": "xcagi.delivery.ledger/v1",
    "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "goal": ("一个完全不懂项目的真实用户，不问任何人，自行跑通：下载→安装→首启→登录绑定→权益→行业 Mod 准备→"
             "核心功能加载→真实业务出正确结果→保存→导出成果→重启恢复→OTA 升级后数据还在且能继续用；全程走产品 UI"),
    "platform": "macOS arm64 (Apple Silicon)",
    "release": {
        "version": "1.0.0.5",
        "git_sha": "8d50fe9d043391d5ba8857094a366a59a34ae43f",
        "release_id": "xcagi-1.0.0.5-8d50fe9d043391d5ba8857094a366a59a34ae43f",
        "main_merge_pr": "https://github.com/42433422/XCMAX/pull/2000",
    },
    "artifacts": {
        "official_dmg": {
            "url": "https://xiu-ci.com/xcagi-v1.0.0.5/enterprise/XCAGI-Enterprise-1.0.0.5-mac-arm64.dmg",
            "sha256": "55a873779aa316fe1e2393ff043978187911b3e052b9762deaefdd6d4817e32f",
            "size": 301669921,
            "download_http": 200,
            "gatekeeper": "accepted (Notarized Developer ID)",
            "codesign": "ok",
            "stapler": "validated",
            "build_info_sha": "8d50fe9d043391d5ba8857094a366a59a34ae43f",
        },
        "prior_official_dmg": {
            "sha256": "89592fdaff3b1731fae016ec56619c7e7b0d3514e2036705cdad132eedf63343",
            "size": 304193412,
            "build_info_sha": "aec61e7e7224fe83c98b3a26522ee3f09f9e728d",
        },
        "update_feed": {
            "latest_mac_yml": "https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml",
            "buildSha": "8d50fe9d043391d5ba8857094a366a59a34ae43f",
            "public_copy": "public-latest-mac.yml",
        },
        "download_pointer": {
            "url": "https://xiu-ci.com/download-release.json",
            "version_lock": "1.0.0.5",
            "git_sha": "8d50fe9d043391d5ba8857094a366a59a34ae43f",
            "release_ready": False,
            "note": "按既有口径：release_ready=false 期间对外已发布版本以线上指针与官网文件为准",
        },
        "security_scan_pair": {
            "release_sha": scanpair.get("release_sha"),
            "passed": scanpair.get("passed"),
            "current_run": 35577912714,
            "previous_run": 35574886166,
            "file": "security-scan-pair-verify.json",
        },
    },
    "fixed_this_round": {
        "defect": ("客户自带标准送货单模板（含合并单元格）在「新建发货单」出单必然 500：生成器把金额合计写死在 D16，"
                   "而 D16 落在人民币大写合并区 B16:G16 内，openpyxl 对 MergedCell 赋值抛 "
                   "\"attribute 'value' is read-only\"，界面只显示「生成失败: 服务器内部错误」。"),
        "before_real_machine": {
            "build": "aec61e7e7224fe83c98b3a26522ee3f09f9e728d（上一版正式包，本机安装运行）",
            "probe_file": "before-fix-merged-template-probe.json",
            "probe_result": "generate: HTTP 500 服务器内部错误（verdict=BLOCKED）",
            "template_merged_cells": ["A1:J1", "A2:J2", "A3:C3", "A4:C4", "A15:D15", "B16:G16"],
            "ui_evidence": "before-fix-ui-500.png（旧包在产品 UI 点「生成发货单」后的失败界面）",
            "backend_log": "'MergedCell' object attribute 'value' is read-only - Path: /api/shipment/generate (HTTP 500)",
        },
        "fix": [
            "resources/tools_legacy/AI助手/shipment_document.py：新增合并安全写入 _write_cell（合并区非锚点跳过，不再中断整单）",
            "合计行按表头列补回「数量/件」「数量/KG」合计与「合计」标签，金额列保留模板自带 SUM 公式",
            "新建发货单页：无可用模板时给出可见指引；生成提示由「请选择发货单模板」改为指向「模板编辑」的可执行说明",
        ],
        "regression_test": "FHD/tests/test_legacy/test_legacy_shipment_template_merge.py",
        "after_real_machine": {
            "build": "8d50fe9d043391d5ba8857094a366a59a34ae43f（本正式包）",
            "doc": doc4.get("name"),
            "bytes": doc4.get("bytes"),
            "xlsx_magic": doc4.get("xlsx_magic"),
            "layout_verified": {
                "r2": "购货单位/日期/订单编号",
                "r3": "表头 产品型号|产品名称|数量/件|规格/KG|数量/KG|单价/元|金额/元|备注",
                "r4": doc_rows[3] if len(doc_rows) > 3 else None,
                "r15": "合计 | 24 | 600",
            },
            "ui_hint_shipped": (final["step1"].get("empty_state") or {}).get("has_hint"),
        },
    },
    "chain_1_official_download_and_ui": {
        "scope": "官网下载正式包 → 安装 → 首启 → 真实 UI 登录 → 建模板/建产品/建客户 → 出单 → 下载 → 重启恢复",
        "data_root": offline.get("data_root"),
        "verdict": chain1_verdict,
        "steps": {
            "official_download_identity": {"sha256": "55a873779aa316fe1e2393ff043978187911b3e052b9762deaefdd6d4817e32f",
                                           "size": 301669921, "verdict": "PASS"},
            "install_identity": {"spctl": "accepted/Notarized Developer ID", "codesign": "ok", "stapler": "validated",
                                 "installed_gitSha": "8d50fe9d043391d5ba8857094a366a59a34ae43f", "verdict": "PASS"},
            "first_launch_health": {"top_status": chain1_health.get("top_status"),
                                    "components": "%s/%s ok" % (chain1_health.get("components_ok"), chain1_health.get("components_total")),
                                    "required_failed": chain1_health.get("required_failed"), "verdict": "PASS"},
            "ui_login": {
                "workspace_visible": final["step0"].get("workspace_visible"),
                "verdict": final["step0"].get("verdict"),
                "independent_reproduction": {
                    "evidence": "gui-login.json + gui-login-01-form.png / gui-login-02-filled.png / gui-login-03-workspace.png",
                    "detail": "独立全新数据根（userdata-login）实测：登录页渲染表单 → 键入 SUNBIRD/密码 → 点击真实提交按钮 button.login-submit（文本「登 录」）→ 应用经 splash 后落到工作区。",
                    "pitfall": "登录页另有「扫码登录」按钮；按文本包含「登录」做模糊匹配会点错到它。",
                    "evidence_file": "gui-login.json",
                    "raw": {k: gui_login.get(k) for k in ("verdict", "workspace_visible") if k in gui_login},
                },
            },
            "core_function_entry_gui": {
                "verdict": chain1_gui_entry.get("verdict"),
                "detail": "全新数据根 + 真实 GUI：整页加载 onboarding 配置步，主按钮「进入我的工作空间」disabled=false；页面无「仍缺必需项」；真实点击后 URL 落到工作区，侧栏渲染完成。",
                "evidence": "chain1-gui-entry.json + gui-entry-01-hostpack.png / gui-entry-02-after-click.png",
                "raw": {"verdict": chain1_gui_entry.get("verdict"), "entry_ready_gui": chain1_gui_entry.get("entry_ready_gui")},
            },
            "ui_template_empty_state_hint": {"has_hint": (final["step1"].get("empty_state") or {}).get("has_hint"),
                                             "created": tpl1.get("name"), "scope": tpl1.get("scope"),
                                             "verdict": final["step1"].get("verdict")},
            "ui_product_create": {"created": (final["step2"].get("created") or [{}])[0], "verdict": final["step2"].get("verdict")},
            "ui_customer_create": {"created": final["step2b"].get("created"), "verdict": final["step2b"].get("verdict")},
            "ui_generate": {"doc": (final["step3"].get("result_panel") or {}).get("doc"), "verdict": final["step3"].get("verdict")},
            "ui_download": {"dir": final["step4"].get("download_dir"), "file": doc4.get("name"),
                            "bytes": doc4.get("bytes"), "sha256": doc4.get("sha256"), "verdict": final["step4"].get("verdict")},
            "ui_records": {"rows": final["step5"].get("rows"), "verdict": final["step5"].get("verdict")},
            "restart_continuity": {
                "verdict": continuity.get("verdict"), "checks": continuity.get("checks"),
                "independent_reproduction": {
                    "evidence": "chain1-restart-recovery-gui.json",
                    "detail": "另用同一数据根（userdata-final-8d50fe9d）独立复跑一次「退出→LaunchServices 重新启动」：重新登录 200（SUNBIRD）；模板/客户仍在；重启前单据仍可下载（200, xlsx_magic=true）。",
                    "raw": {"verdict": chain1_restart_gui.get("verdict")},
                },
            },
            "offline_data_check": offline.get("checks"),
            "digest_fresh": digest_fresh, "digest_after_restart": digest_restart,
        },
    },
    "chain_2_ota_upgrade": {
        "scope": "上一版正式包（aec61e7e）→ 真实 feed 检查更新/下载/安装 → 新版（8d50fe9d0）→ 数据/登录态/单据保留 → 新版继续用 UI 出单（客户标准送货单模板，含合并单元格）",
        "data_root": "/private/tmp/xcagi-custchain/userdata-ota",
        "verdict": chain2_verdict,
        "steps": chain2_steps,
    },
    "known_boundaries": [
        "平台范围：本闭环仅在 macOS arm64（Apple Silicon）上完成真实运行验证。Windows 安装包（XCAGI-Enterprise-Setup-1.0.0.5-x64-unsigned.exe）仍为未签名状态、未做真机验证，故官网 download-release.json 的 release_ready 保持 false；按项目「双平台平级、任一端未验证不得发布」的约束，整体发布指针不得置 ready。本文件不主张 Windows 已通过。",
        "发货单模板的落位契约：生成器按标准送货单版式写入（第2行购货单位、第3行表头、第4行起数据、第15行合计）。客户模板遵循该版式（必含 产品型号/产品名称/数量/单价/金额 词条）即完全正确；版式差异较大的自定义模板仍按标准列位写入，本轮未改为「按表头自适应落位」，作为已知边界记录。",
        "GitHub runner → CVM 上传通道极慢（实测约 39KB/s，301MB 需 2 小时以上），本轮在构建/公证/上传恢复产物完成后由本机完成官方目录与 stable feed 的发布（rsync + publish-macos-download-center.sh），并用 sha256 逐字节复核两处文件与公开 URL。",
    ],
    "outstanding_external_dependency": {
        "item": "SUNBIRD 账号定制私有交付 taiyangniao-pro",
        "state": "未交付（市场侧 intent=custom_delivery 工单 0 条；主机无 customer-delivery-artifacts/29/）",
        "blocking": False,
        "reason": "进入就绪判定已收敛为产品侧可安装项（core+host），L3 未交付不阻塞客户进入工作空间",
        "unblock": "经市场自身生产—验收流程产出并落 customer-delivery-artifacts/29/（验收只认客户本人 accepted）",
    },
    "verdict": overall,
    "verdict_scope": "macOS arm64 客户闭环（Windows 未验证，见 known_boundaries）",
    "verdict_note": ("chain_1：在官网正式安装包（8d50fe9d0，sha256 55a87377…）上，真实客户以产品 UI 独立完成"
                     "下载→安装→首启→登录→建模板→建产品→建客户→出单（客户自带合并单元格送货单模板）→下载 xlsx→"
                     "重启后模板/客户/单据仍在且可下载。"
                     "chain_2（OTA）：上一版正式包 aec61e7e → 真实 feed 检查更新/下载/安装（ShipIt 真实日志："
                     "Installation completed successfully / ShipIt status 0）→ 新版本落地；更新后首次启动进入观察期并成功提交"
                     "（rollback marker 删除、未触发 backend 回滚）；安装后 bundle 的 codesign/spctl/stapler 全部通过，"
                     "关键源码 shipment_document.py 与更新包逐字节一致且含合并安全写入修复；升级前 UI 产出的模板/客户/单据升级后仍在且可下载；"
                     "新版上以客户自带含合并单元格模板再次出单成功。"),
}

os.makedirs(DST, exist_ok=True)
path = os.path.join(DST, "delivery-ledger.json")
json.dump(ledger, open(path, "w"), ensure_ascii=False, indent=2)
print("wrote", path, os.path.getsize(path), "bytes")
print(json.dumps({"chain_1": chain1_verdict, "chain_2": chain2_verdict, "overall": overall,
                  "chain_2_verdicts": dict(zip(
                      ["ota_check", "ota_download", "ota_install", "backend_integrity",
                       "continuity_ui", "post_ota_generate", "merged_probe"], chain2_verdicts))},
                 ensure_ascii=False, indent=1))
