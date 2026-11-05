#!/usr/bin/env bash
# shared-brain-sync-mac.sh — macOS 端"自动共享大脑"守护（与 Windows 版对等）
# 推：本地 ~/.trae 记忆摘要 → 知识库 8 个槽位文档（≤480 字/槽，单分块可精确回读）
# 拉：知识库其他设备的共享记忆 → 本地镜像 ~/.trae/memory/shared_brain_kb.md
# 安装（LaunchAgent 常驻）：
#   bash shared-brain-sync-mac.sh install
# 手动前台运行调试：bash shared-brain-sync-mac.sh run
set -euo pipefail

TUNNEL_BASE="${TUNNEL_BASE:-http://127.0.0.1:15100/api/knowledge/v1}"
DATASET="${DATASET:-persy-knowledge}"
ACTOR_ID="${ACTOR_ID:-agent-mac-trae}"
DEVICE="${DEVICE:-mac}"
MEMORY_DIR="${MEMORY_DIR:-$HOME/.trae/memory}"
INTERVAL="${INTERVAL:-90}"
SLOTS=8; CHUNK_LIMIT=480; MAX_PUSH_CHARS=3600
JAR="$(mktemp /tmp/shared-brain-csrf.XXXX)"
STATE="$MEMORY_DIR/.shared-brain-state.json"
MIRROR="$MEMORY_DIR/shared_brain_kb.md"

mkdir -p "$MEMORY_DIR" "$HOME/Library/Logs/XCMAX" 2>/dev/null || true

H=(-H "X-Dataset-Actor-ID: $ACTOR_ID" -H "X-Dataset-Tenant-ID: default"
   -H "X-Dataset-Permissions: dataset.read,dataset.write")

csrf() { curl -s -m 8 --noproxy '*' -c "$JAR" "$TUNNEL_BASE/health" "${H[@]}" -o /dev/null
         awk '$6=="csrf_token" {print $7}' "$JAR" | tail -n1; }

kb_post() { local c; c=$(csrf); [ -n "$c" ] || return 1
            curl -s -m 25 --noproxy '*' -X POST "$1" -H "X-CSRF-Token: $c" -b "$JAR" \
                 -H "Content-Type: application/json" "${H[@]}" -d "$2"; }

local_brain_text() {
  local out=""
  local pm="$MEMORY_DIR/../projects"; local f
  f=$(ls -t "$pm"/*/project_memory.md 2>/dev/null | head -n1 || true)
  [ -n "${f:-}" ] && out+="## 本地 project_memory（最新在后）"$'\n'"$(sed 's/\r$//' "$f")"$'\n\n'
  f=$(ls -t "$pm"/*/20*/topics.md 2>/dev/null | head -n1 || true)
  [ -n "${f:-}" ] && out+="## 最近会话 topics（尾部最新）"$'\n'"$(tail -c 1800 "$f")"
  printf '%s' "$out" | tail -c "$MAX_PUSH_CHARS"
}

push_local() {
  local text; text=$(local_brain_text); [ -n "$text" ] || return 0
  local len=${#text}; local chunks=$(( (len + CHUNK_LIMIT - 1) / CHUNK_LIMIT ))
  (( chunks > SLOTS )) && chunks=$SLOTS
  local i start docid body part
  for ((i=1;i<=SLOTS;i++)); do
    docid="agent-auto-$DEVICE-part$i"
    if (( i <= chunks )); then
      start=$(( (i-1)*CHUNK_LIMIT )); part="${text:$start:$CHUNK_LIMIT}"
      [ -z "$part" ] && continue
      body=$(python3 -c 'import json,sys;print(json.dumps({"source":sys.argv[1],"document_id":sys.argv[2],"text":sys.argv[3],"metadata":{"type":"agent-auto-sync","device":sys.argv[4],"part":int(sys.argv[5]),"author":"shared-brain-daemon"},"tenant_id":"default","chunk_strategy":"fixed"}))' \
             "agent-shared-memory/auto-$DEVICE-part$i.md" "$docid" "$part" "$DEVICE" "$i")
      kb_post "$TUNNEL_BASE/datasets/$DATASET/documents" "$body" >/dev/null || true
    else
      local c; c=$(csrf)
      [ -n "$c" ] && curl -s -m 15 --noproxy '*' -X DELETE \
        "$TUNNEL_BASE/datasets/$DATASET/documents/$docid" -H "X-CSRF-Token: $c" -b "$JAR" \
        "${H[@]}" -o /dev/null || true
    fi
  done
}

pull_remote() {
  local st; st=$(curl -s -m 10 --noproxy '*' "$TUNNEL_BASE/datasets/$DATASET/status?include_documents=true" "${H[@]}") || return 0
  echo "$st" | python3 -c '
import json,sys,subprocess,os
d=json.load(sys.stdin)
if not d.get("success"): sys.exit(0)
print("# 共享大脑镜像（自动同步，勿手编；源=persy-knowledge）")
print("")
me=os.environ.get("DEVICE","mac")
for doc in d.get("documents",[]):
    m=doc.get("metadata",{})
    if m.get("device")==me and m.get("type")=="agent-auto-sync": continue
    q=json.dumps({"query":"shared memory","top_k":1,"metadata_filter":{"document_id":doc["document_id"]}})
    r=subprocess.run(["curl","-s","-m","25","--noproxy","*","-X","POST",
      os.environ["TUNNEL_BASE"]+"/datasets/"+os.environ["DATASET"]+"/query",
      "-H","X-Dataset-Actor-ID: "+os.environ.get("ACTOR_ID","agent-mac-trae"),
      "-H","X-Dataset-Tenant-ID: default",
      "-H","X-Dataset-Permissions: dataset.read,dataset.write",
      "-H","Content-Type: application/json","-d",q],capture_output=True,text=True)
    try:
      j=json.loads(r.stdout); c=j["chunks"][0]["text"]
      print("## [%s/%s] %s (v%s)"%(m.get("device","?"),m.get("author","?"),doc["document_id"],doc.get("version","?")))
      print(c); print("")
    except Exception: pass
'
}

hash_of() { printf '%s' "$1" | md5 -q; }

tick() {
  local text ph mh st
  text=$(local_brain_text || true)
  if [ -n "$text" ]; then
    ph=$(hash_of "$text")
    st=$(cat "$STATE" 2>/dev/null || echo "{}")
    if [ "$(echo "$st" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("push_hash",""))')" != "$ph" ]; then
      push_local || true
      echo "{\"push_hash\":\"$ph\"}" > "$STATE"
    fi
  fi
  local mirror; mirror=$(DEVICE="$DEVICE" ACTOR_ID="$ACTOR_ID" TUNNEL_BASE="$TUNNEL_BASE" DATASET="$DATASET" pull_remote 2>/dev/null || true)
  if [ -n "$mirror" ]; then
    mh=$(hash_of "$mirror")
    st=$(cat "$STATE" 2>/dev/null || echo "{}")
    if [ "$(echo "$st" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("mirror_hash",""))')" != "$mh" ]; then
      printf '%s\n' "$mirror" > "$MIRROR"
      echo "{\"push_hash\":\"$(echo "$st" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("push_hash",""))')\",\"mirror_hash\":\"$mh\"}" > "$STATE"
    fi
  fi
}

run() { while true; do tick || true; sleep "$INTERVAL"; done; }

install() {
  local plist="$HOME/Library/LaunchAgents/com.xcmax.shared-brain-sync.plist"
  cat > "$plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.xcmax.shared-brain-sync</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>$0</string><string>run</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/XCMAX/shared-brain-sync.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/XCMAX/shared-brain-sync.log</string>
</dict></plist>
PL
  launchctl unload "$plist" 2>/dev/null || true
  launchctl load "$plist"
  echo "installed: $plist (KeepAlive 常驻，日志 ~/Library/Logs/XCMAX/shared-brain-sync.log)"
}

case "${1:-run}" in
  install) install ;;
  run) run ;;
  *) echo "usage: $0 {install|run}"; exit 1 ;;
esac
