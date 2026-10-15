#!/bin/bash
# G9 更新下载自动重试：反复走真实「下载更新」按钮，直到 update_downloaded 或达到上限。
EV="/Users/a4243342/Library/Application Support/XCAGI/logs/updater-events.jsonl"
CACHE="/Users/a4243342/Library/Caches/xcagi-desktop-updater/pending/temp-XCAGI-Enterprise-1.0.0.5-mac-arm64.zip"
cd "$(dirname "$0")" || exit 1
MAX=${1:-6}
for n in $(seq 1 "$MAX"); do
  echo "===== attempt $n @ $(date -u +%H:%M:%SZ) ====="
  pre=$(tail -1 "$EV")
  python3 cdp_driver.py click "下载更新" 2>&1 | tail -1
  sleep 5
  for i in $(seq 1 80); do
    sleep 15
    last=$(tail -1 "$EV")
    s=$(stat -f%z "$CACHE" 2>/dev/null || echo 0)
    echo "  $(date -u +%H:%M:%SZ) bytes=$s"
    case "$last" in
      *update_downloaded*) echo "RESULT=DOWNLOADED attempt=$n"; exit 0;;
      *download_failed*)
        if [ "$last" != "$pre" ]; then echo "  failed: $last"; break; fi;;
    esac
  done
  sleep 10
done
echo "RESULT=EXHAUSTED attempts=$MAX"
exit 1