#!/bin/bash
# G9 安装链观测：点击「更新并重新加载」后，逐秒采样进程/日志，判定三子项
# 自动退出（应用是否自行退出）/ ShipIt 替换 / 自动重启（新版本是否自行拉起）
OUT="$1"; DUR="${2:-600}"
SHIPIT_DIR="/Users/a4243342/Library/Caches/com.xcagi.desktop.enterprise.ShipIt"
SHIPIT_LOG="$SHIPIT_DIR/ShipIt_stderr.log"
EV="/Users/a4243342/Library/Application Support/XCAGI/logs/updater-events.jsonl"
BOOT_BEFORE=$(sysctl -n kern.boottime)
i=0
while [ $i -lt "$DUR" ]; do
  i=$((i+2))
  ts=$(date -u +%H:%M:%SZ)
  main=$(pgrep -f "XCAGI.app/Contents/MacOS/XCAGI" | tr '\n' ',' )
  be=$(pgrep -f "Resources/backend/xcagi-backend" | tr '\n' ',')
  lines=$(wc -l < "$SHIPIT_LOG" 2>/dev/null | tr -d ' ')
  lastship=$(tail -1 "$SHIPIT_LOG" 2>/dev/null | cut -c1-160)
  lastev=$(tail -1 "$EV" 2>/dev/null | cut -c1-160)
  st=$(plutil -p "$SHIPIT_DIR/ShipItState.plist" 2>/dev/null | tr -d '\n' | cut -c1-200)
  echo "$ts main=[${main}] backend=[${be}] shipit_lines=$lines"
  echo "    shipit: $lastship"
  echo "    event : $lastev"
  echo "    state : $st"
  sleep 2
done
echo "done loop=$i boot_before=$BOOT_BEFORE boot_after=$(sysctl -n kern.boottime)"