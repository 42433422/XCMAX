#!/usr/bin/env bash
# 释放本地 XCAGI 常用端口，避免「关了再起」仍连到旧进程或错端口。
set -euo pipefail

PORTS=(5000 5001 5002 5003 5011 5100 5101)

echo "释放端口: ${PORTS[*]}"
for p in "${PORTS[@]}"; do
  pids=$(lsof -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null || true)
  if [[ -z "${pids}" ]]; then
    echo "  :$p — 空闲"
    continue
  fi
  echo "  :$p — 结束 PID ${pids//$'\n'/, }"
  # shellcheck disable=SC2086
  kill ${pids} 2>/dev/null || true
  sleep 0.2
  pids2=$(lsof -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null || true)
  if [[ -n "${pids2}" ]]; then
    # shellcheck disable=SC2086
    kill -9 ${pids2} 2>/dev/null || true
  fi
done
echo "完成。请用 start-enterprise-dev.sh 或 start-desktop.command 按固定组合重启。"
