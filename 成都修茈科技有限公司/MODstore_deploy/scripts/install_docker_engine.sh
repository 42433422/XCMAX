#!/usr/bin/env bash
# 在 Debian/Ubuntu（及 get.docker.com 支持的其它发行版）上安装 Docker Engine + Compose 插件。
# 若已可执行 docker compose 且 docker info 正常则直接退出 0。
set -euo pipefail

log() { printf '[install-docker] %s\n' "$*"; }

if docker compose version >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  log "已安装且可用: $(docker --version)"
  docker compose version
  exit 0
fi

if [[ "$(id -u)" -ne 0 ]]; then
  log "请使用 root 执行，或: sudo bash $0"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl >/dev/null
elif ! command -v curl >/dev/null 2>&1; then
  log "未找到 apt-get 且未安装 curl，请手动安装 curl 后重试。"
  exit 1
fi

log "下载并执行 Docker 官方安装脚本…"
curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
sh /tmp/get-docker.sh
rm -f /tmp/get-docker.sh

if command -v systemctl >/dev/null 2>&1; then
  systemctl enable docker >/dev/null 2>&1 || true
  systemctl start docker || true
fi

docker compose version
log "完成: $(docker --version)"
