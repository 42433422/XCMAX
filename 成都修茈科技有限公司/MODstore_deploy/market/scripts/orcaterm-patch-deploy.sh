#!/usr/bin/env bash
# 在腾讯云 OrcaTerm 网页终端：复制「PASTE_FROM_HERE」到「PASTE_TO_HERE」整段粘贴执行
# 或在本机: bash scripts/orcaterm-patch-deploy.sh --print-remote
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
B64_FILE="${SCRIPT_DIR}/market-patch-min.tgz.b64"
REMOTE_DIST_PRIMARY="/root/成都修茈科技有限公司/MODstore_deploy/market/dist"
REMOTE_DIST_ALT="/root/modstore-git/MODstore_deploy/market/dist"

print_remote() {
  if [[ ! -f "$B64_FILE" ]]; then
    echo "[err] 缺少 $B64_FILE，请在本机 market 目录运行: bash scripts/orcaterm-patch-deploy.sh --regen-b64" >&2
    exit 2
  fi
  echo "# ===== PASTE_FROM_HERE (OrcaTerm) ====="
  cat << 'REMOTE_HEAD'
set -euo pipefail
REMOTE_DIST_PRIMARY="/root/成都修茈科技有限公司/MODstore_deploy/market/dist"
REMOTE_DIST_ALT="/root/modstore-git/MODstore_deploy/market/dist"
apply_patch() {
  local dest="$1"
  local parent
  parent="$(dirname "$dest")"
  if [[ ! -d "$parent" ]; then echo "[skip] $parent"; return 0; fi
  mkdir -p "$dest/assets"
  tar -C "$dest" -xzf /tmp/market-patch-min.tgz
  chmod o+x /root /root/成都修茈科技有限公司 /root/成都修茈科技有限公司/MODstore_deploy /root/成都修茈科技有限公司/MODstore_deploy/market 2>/dev/null || true
  chmod o+x /root/modstore-git /root/modstore-git/MODstore_deploy /root/modstore-git/MODstore_deploy/market 2>/dev/null || true
  chmod 755 "$dest" && chmod -R a+rX "$dest"
  echo "========== $dest =========="
  grep -oE 'index-[a-zA-Z0-9_-]+\.js' "$dest/index.html" | head -1
  grep -q '试跑并自动生成报告' "$dest/assets/EmployeeExamView-C8xdB9P_.js" && echo "[ok] EmployeeExamView"
}
(base64 -d 2>/dev/null || base64 -D) << 'PATCH_B64' > /tmp/market-patch-min.tgz
REMOTE_HEAD
  cat "$B64_FILE"
  cat << 'REMOTE_TAIL'
PATCH_B64
apply_patch "$REMOTE_DIST_PRIMARY"
apply_patch "$REMOTE_DIST_ALT"
curl -sk 'https://127.0.0.1/market/' 2>/dev/null | grep -oE 'index-[a-zA-Z0-9_-]+\.js' | head -1 || true
rm -f /tmp/market-patch-min.tgz
echo "完成"
# ===== PASTE_TO_HERE =====
REMOTE_TAIL
}

regen_b64() {
  local dist="${SCRIPT_DIR}/../dist"
  local tmp
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/assets"
  cp "$dist/index.html" "$tmp/"
  cp "$dist/assets/index-BakUJOiD.js" "$dist/assets/EmployeeExamView-C8xdB9P_.js" "$dist/assets/tabularReadEmployees-BI0bnGdx.js" "$tmp/assets/"
  tar -C "$tmp" -czf /tmp/market-patch-min.tgz .
  base64 -i /tmp/market-patch-min.tgz -o "$B64_FILE" 2>/dev/null || base64 /tmp/market-patch-min.tgz > "$B64_FILE"
  rm -rf "$tmp" /tmp/market-patch-min.tgz
  echo "[ok] wrote $B64_FILE ($(wc -c < "$B64_FILE") bytes)"
}

case "${1:-}" in
  --print-remote) print_remote ;;
  --regen-b64) regen_b64 ;;
  *)
    echo "用法:"
    echo "  bash scripts/orcaterm-patch-deploy.sh --print-remote   # 输出 OrcaTerm 粘贴块"
    echo "  bash scripts/orcaterm-patch-deploy.sh --regen-b64      # 从 dist 重建 b64"
    echo ""
    echo "本地 dist 路径（可 scp 到服务器后 tar -xzf）:"
    echo "  ${SCRIPT_DIR}/../dist/index.html"
    echo "  ${SCRIPT_DIR}/../dist/assets/index-BakUJOiD.js"
    echo "  ${SCRIPT_DIR}/../dist/assets/EmployeeExamView-C8xdB9P_.js"
    echo "  ${SCRIPT_DIR}/../dist/assets/tabularReadEmployees-BI0bnGdx.js"
    ;;
esac
