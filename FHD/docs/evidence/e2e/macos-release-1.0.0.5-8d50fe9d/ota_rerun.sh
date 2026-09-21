#!/usr/bin/env bash
# OTA 段一次性收口重跑：上一版正式包 aec61e7e → 真实 feed 升级到 8d50fe9d。
# 目标：总账、原始 JSON、关键节点截图、安装结果四者同源一致。
# 全程 LaunchServices(open -a) 启动；直接 exec 二进制会破坏 Squirrel ShipIt 路径。
set -uo pipefail
W=/private/tmp/xcagi-custchain
PY=/tmp/py311shim/python3
PRIOR_DMG="$W/dmg/XCAGI-Enterprise-1.0.0.5-mac-arm64.dmg"
PRIOR_SHA=89592fdaff3b1731fae016ec56619c7e7b0d3514e2036705cdad132eedf63343
PRIOR_SIZE=304193412
TARGET_SHA=8d50fe9d043391d5ba8857094a366a59a34ae43f
APP=/Applications/XCAGI.app
DATA="$W/userdata-ota"
EV="$W/evidence-ota"
MP="$W/mnt/ota"
SHIPIT_DIR="$HOME/Library/Caches/com.xcagi.desktop.enterprise.ShipIt"
UPD_DIR="$HOME/Library/Caches/xcagi-desktop-updater"
SIMPLE_NAME="客户发货单模板-简版"; SIMPLE_XLSX="$W/客户发货单模板.xlsx"
CANON_NAME="客户送货单模板-UI";   CANON_XLSX="$W/客户送货单模板-标准.xlsx"
UNIT_NAME="UI客户-0921"
rm -rf "$EV"; mkdir -p "$EV" "$DATA" "$MP"
export XCAGI_CHAIN_DATA="$DATA" XCAGI_CHAIN_WORKDIR="$W" XCAGI_CHAIN_EVIDENCE="$EV"
export EV_DIR="$EV" DL_DIR="$W/ui-downloads" UNIT_NAME="$UNIT_NAME"
log(){ echo "[$(date -u +%H:%M:%SZ)] $*" | tee -a "$EV/ota.log"; }

stop_app(){
  osascript -e 'quit app "XCAGI"' >/dev/null 2>&1 || true
  for i in $(seq 1 30); do pgrep -f 'XCAGI.app/Contents/MacOS/XCAGI' >/dev/null || return 0; sleep 1; done
  pkill -f 'XCAGI.app/Contents/MacOS/XCAGI' >/dev/null 2>&1 || true; sleep 3
}
wait_health(){ for i in $(seq 1 150); do curl -sf --noproxy '*' -o /dev/null --max-time 5 http://127.0.0.1:17500/api/health && return 0; sleep 2; done; return 1; }
wait_auth(){ for i in $(seq 1 60); do
    code=$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:17500/api/auth/me)
    [ "$code" = "200" ] || [ "$code" = "401" ] || [ "$code" = "403" ] && return 0; sleep 2; done; return 1; }
wait_cdp(){ for i in $(seq 1 60); do curl -sf --noproxy '*' -o /dev/null --max-time 5 http://127.0.0.1:9222/json/version && return 0; sleep 1; done; return 1; }
bundle_sha(){ cat "$APP/Contents/Resources/build-info.json" 2>/dev/null | $PY -c 'import json,sys;print(json.load(sys.stdin).get("gitSha",""))' 2>/dev/null; }
launch_app(){
  launchctl setenv XCAGI_DESKTOP_USER_DATA_DIR "$DATA"
  open -a "$APP" --args --remote-debugging-port=9222 >> "$EV/app-launch.log" 2>&1
  wait_health || { log "FATAL: 后台未就绪"; tail -40 "$EV/app-launch.log"; exit 1; }
  wait_cdp  || log "WARN: CDP 未就绪"
  log "backend up; bundle_sha=$(bundle_sha)"
}

log "=== OTA rerun start target=$TARGET_SHA ==="
stop_app
rm -rf "$DATA" && mkdir -p "$DATA"
# 更新器缓存已由 ota_probe.sh 验证过：全量下载得到的 update.zip 与 feed sha512 一致且含修复；
# 本轮直接复用缓存（electron-updater 仍会按 feed 声明的 sha512 校验），避免重复 264MB 下载。
cp "$SHIPIT_DIR/ShipIt_stderr.log" "$EV/shipit-before.log" 2>/dev/null || true
cp "$SHIPIT_DIR/ShipItState.plist" "$EV/shipit-state-before.plist" 2>/dev/null || true
log "updater cache reused"

log "--- 1) 上一版正式包校验 + 安装 ---"
GOT=$(shasum -a 256 "$PRIOR_DMG" | awk '{print $1}'); SIZE=$(stat -f %z "$PRIOR_DMG")
[ "$GOT" = "$PRIOR_SHA" ] && [ "$SIZE" = "$PRIOR_SIZE" ] || { log "FATAL: 上一版包校验不一致 got=$GOT size=$SIZE"; exit 1; }
hdiutil detach "$MP" >/dev/null 2>&1 || true
hdiutil attach "$PRIOR_DMG" -nobrowse -mountpoint "$MP" -quiet || { log "FATAL: 挂载失败"; exit 1; }
SRC="$MP/XCAGI.app"; test -d "$SRC" || { log "FATAL: DMG 内无 XCAGI.app"; exit 1; }
$PY - "$SRC" "$EV/ota-prior-install.json" "$PRIOR_SHA" "$PRIOR_SIZE" <<'PYEOF'
import json, subprocess, sys, time
src, out, sha, size = sys.argv[1:5]
def run(c):
    p = subprocess.run(c, shell=True, capture_output=True, text=True)
    return (p.stdout + p.stderr).strip()
d = {"schema": "xcagi.gate.evidence.v1", "gate": "ota-prior-install",
     "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
     "dmg_sha256": sha, "dmg_size": int(size),
     "spctl": run('spctl -a -vvv -t install "%s" 2>&1' % src),
     "spctl_ok": run('spctl -a -vvv -t install "%s" >/dev/null 2>&1; echo $?' % src) == "0",
     "codesign_ok": run('codesign --verify --deep --strict "%s" && echo ok' % src).endswith("ok"),
     "stapler": run('xcrun stapler validate "%s" 2>&1 | tail -1' % src),
     "build_info": json.load(open(src + "/Contents/Resources/build-info.json"))}
d["verdict"] = "PASS" if d["spctl_ok"] and d["codesign_ok"] and "worked" in d["stapler"] else "BLOCKED"
json.dump(d, open(out, "w"), ensure_ascii=False, indent=2)
print("prior-install verdict:", d["verdict"], "build:", d["build_info"]["gitSha"])
PYEOF
stop_app; rm -rf "$APP"; ditto "$SRC" "$APP" || { log "FATAL: 安装失败"; exit 1; }
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
hdiutil detach "$MP" -quiet >/dev/null 2>&1 || true
cat "$APP/Contents/Resources/build-info.json" | tee "$EV/chain2-prior-build-info.json"; echo | tee -a "$EV/ota.log"

log "--- 2) 首启 + 升级前真实 UI 业务数据（简版模板） ---"
launch_app
export TPL_NAME="$SIMPLE_NAME" TPL_XLSX="$SIMPLE_XLSX"
for s in step0 step1 step2 step2b step3 step4; do
  log "  · pre-OTA $s"
  OUT="$EV/ui-$s.json" $PY "$W/ui_drive.py" $s 2>&1 | tail -5 | tee -a "$EV/ota.log"
done
$PY "$W/chain.py" digest "$EV/digest-pre-ota.json" 2>&1 | tee -a "$EV/ota.log"
$PY "$W/chain.py" shot "$EV/chain2-01-pre-ota.png" 2>&1 | tee -a "$EV/ota.log"

log "--- 3) 检查更新 / 下载 / 触发安装 ---"
$PY "$W/chain.py" ota-check 2>&1 | tee "$EV/ota-check.json"
$PY "$W/chain.py" ota-download 2>&1 | tee "$EV/ota-download.json"
for i in $(seq 1 60); do
  st=$($PY "$W/chain.py" ota-status 2>&1); echo "$st" >> "$EV/ota-status-poll.jsonl"
  echo "$st" | grep -q 'update-downloaded' && { log "downloaded"; break; }
  sleep 10
done
# 安装前快照：ShipIt 日志行数 + 待安装包身份
SHIPIT_LINES=$(wc -l < "$SHIPIT_DIR/ShipIt_stderr.log" 2>/dev/null || echo 0)
cp "$UPD_DIR/pending/update-info.json" "$EV/ota-pending-update-info.json" 2>/dev/null || true
log "shipit_lines_before=$SHIPIT_LINES"
$PY "$W/chain.py" ota-install 2>&1 | tee "$EV/ota-install-call.log" || true

log "--- 4) 等待应用退出 + 新版本落地 ---"
NEWOK=0
for i in $(seq 1 90); do
  sleep 5
  sha=$(bundle_sha); hs=$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:17500/api/health 2>/dev/null)
  log "bundle_sha=${sha:-none} health=${hs:-none}"
  if [ "$sha" = "$TARGET_SHA" ] && [ "$hs" = "200" ]; then NEWOK=1; break; fi
done
[ "$NEWOK" = 1 ] || { log "FATAL: OTA 后未就绪"; exit 1; }

log "--- 5) 等待更新观察期提交（观察期内禁止重启，否则触发后端自动回滚） ---"
COMMIT=0
for i in $(seq 1 120); do
  if [ ! -f "$DATA/rollback-marker.json" ]; then COMMIT=1; break; fi
  sleep 2
done
log "observation_committed=$COMMIT marker=$([ -f "$DATA/rollback-marker.json" ] && echo present || echo gone)"
[ "$COMMIT" = 1 ] || { log "FATAL: 更新观察期未提交"; exit 1; }
$PY - "$DATA" "$EV/ota-observation.json" <<'PYEOF'
import json, os, sys, time
data, out = sys.argv[1:3]
d = {"schema": "xcagi.gate.evidence.v1", "gate": "ota-observation",
     "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
     "rollback_marker_present": os.path.isfile(os.path.join(data, "rollback-marker.json")),
     "rollback_applied_present": os.path.isfile(os.path.join(data, "rollback-applied.json")),
     "note": "更新后首次启动进入观察期；后端+业务路由+主界面就绪后提交并删除 marker。观察期内不得重启，否则应用按设计回滚 backend。",
     "verdict": "PASS" if not os.path.isfile(os.path.join(data, "rollback-marker.json")) else "BLOCKED"}
json.dump(d, open(out, "w"), ensure_ascii=False, indent=2)
print("observation verdict:", d["verdict"])
PYEOF

log "--- 5a) 干净重启到新版（挂 CDP）并采集安装结果 ---"
stop_app; sleep 3; launch_app
wait_auth || log "WARN: auth 路由未就绪"
cat "$APP/Contents/Resources/build-info.json" | tee "$EV/post-ota-installed-build-info.json"; echo | tee -a "$EV/ota.log"
curl -s --noproxy '*' --max-time 5 http://127.0.0.1:17500/api/health > "$EV/ota-post-health.json" 2>/dev/null
$PY - "$EV/ota-install.json" "$SHIPIT_LINES" "$TARGET_SHA" "$EV/post-ota-installed-build-info.json" "$EV/ota-post-health.json" <<'PYEOF'
import json, os, sys, time
out, before, target, binfo, health = sys.argv[1:6]
before = int(before)
sp = os.path.expanduser("~/Library/Caches/com.xcagi.desktop.enterprise.ShipIt/ShipIt_stderr.log")
lines = []
if os.path.isfile(sp):
    all_lines = open(sp, errors="ignore").read().splitlines()
    lines = [l for l in all_lines[before:] if l.strip()][-40:]
joined = "\n".join(lines)
installed = json.load(open(binfo))
health_ok = False
try:
    health_ok = json.load(open(health)).get("status") == "healthy"
except Exception:
    pass
markers = {
    "installation_completed": "Installation completed successfully" in joined,
    "launched_after_install": "Successfully launched application" in joined,
    "shipit_status_0": "ShipIt status 0" in joined,
    "bundle_replaced_to_target": installed.get("gitSha") == target,
    "post_install_health": health_ok,
}
d = {"schema": "xcagi.gate.evidence.v1", "gate": "ota-install",
     "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
     "install_trigger": {"via": "window.xcagiDesktop.installUpdate() (electron-updater quitAndInstall)",
                          "note": "installUpdate 会立即退出应用，CDP 连接随之断开；因此安装结果以 ShipIt 真实日志 + 替换后 build-info + health 为证。",
                          "raw_call": open(os.path.join(os.path.dirname(out), "ota-install-call.log")).read().strip() if os.path.isfile(os.path.join(os.path.dirname(out), "ota-install-call.log")) else None},
     "shipit": {"log": sp, "new_lines": lines, "markers": markers},
     "installed_build_info": installed,
     "post_install_health": {"status": "healthy" if health_ok else "unknown", "file": os.path.basename(health)},
     "target_buildSha": target}
d["verdict"] = "PASS" if all([markers["installation_completed"], markers["bundle_replaced_to_target"], markers["post_install_health"]]) else "BLOCKED"
json.dump(d, open(out, "w"), ensure_ascii=False, indent=2)
print("install verdict:", d["verdict"], json.dumps(markers, ensure_ascii=False))
PYEOF

log "--- 5b) 后端完整性：安装后 bundle 是否与更新包一致（codesign/spctl/关键源码） ---"
$PY "$W/ota_backend_integrity.py" "$UPD_DIR/update.zip" "/Applications/XCAGI.app" "$EV/ota-backend-integrity.json" 2>&1 | tee -a "$EV/ota.log"

log "--- 6) 升级后连续性（API）+ 关键节点截图 ---"
$PY "$W/chain.py" digest "$EV/digest-post-ota.json" 2>&1 | tee -a "$EV/ota.log"
EV_DIR="$EV" $PY "$W/chain.py" continuity-ui POST-OTA "$EV/chain2-continuity-ui.json" 2>&1 | tee -a "$EV/ota.log"
$PY "$W/chain.py" shot "$EV/chain2-02-post-ota.png" 2>&1 | tee -a "$EV/ota.log"

log "--- 7) 新版上继续用 UI 出单（客户标准送货单模板：合并单元格） ---"
export TPL_NAME="$CANON_NAME" TPL_XLSX="$CANON_XLSX"
for s in step1 step3 step4; do
  log "  · post-OTA $s"
  OUT="$EV/ui-post-ota-$s.json" $PY "$W/ui_drive.py" $s 2>&1 | tail -5 | tee -a "$EV/ota.log"
done
$PY "$W/chain.py" shot "$EV/chain2-03-continue.png" 2>&1 | tee -a "$EV/ota.log"
$PY "$W/merged_template_probe.py" "$EV/phase-c-real-template.json" PHASE-C 2>&1 | tail -3 | tee -a "$EV/ota.log"

log "=== OTA rerun done ==="
