#!/usr/bin/env bash
# Mod 真实商家试点验收清单（可执行）
# SSOT 步骤：FHD/docs/mod-merchant-pilot.md
# 证据目录：FHD/docs/evidence/mod/（4 张 PNG，禁止空宣称 / 假图）
#
# 用法:
#   bash MODstore/scripts/mod-pilot-checklist.sh              # 打印步骤与路径
#   bash MODstore/scripts/mod-pilot-checklist.sh --verify     # 校验 4 张证据 PNG
#   bash MODstore/scripts/mod-pilot-checklist.sh --check-only # 仅校验目录/文档（无需商家）
#   bash MODstore/scripts/mod-pilot-checklist.sh --paths      # 仅输出证据绝对路径
set -euo pipefail

MODSTORE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FHD_ROOT="$(cd "${MODSTORE_DIR}/.." && pwd)"
EVIDENCE_DIR="${FHD_ROOT}/docs/evidence/mod"
PILOT_DOC="${FHD_ROOT}/docs/mod-merchant-pilot.md"
MODSTORE_DEPLOY_ROOT="${MODSTORE_DEPLOY_ROOT:-}"

# 相对 XCMAX 工作区（与 mod-merchant-pilot.md 一致）
XCMAX_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
DEFAULT_DEPLOY_REL="成都修茈科技有限公司/MODstore_deploy"
ALIPAY_PKG_REL="成都修茈科技有限公司/alipay_package"

readonly -a EVIDENCE_FILES=(
  "01-listing.png"
  "02-store-page.png"
  "03-payment.png"
  "04-activated.png"
)

log() { printf '[mod-pilot] %s\n' "$*"; }
fail() { log "FAIL: $*"; exit 1; }

resolve_deploy_root() {
  if [[ -n "${MODSTORE_DEPLOY_ROOT}" && -d "${MODSTORE_DEPLOY_ROOT}" ]]; then
    printf '%s\n' "${MODSTORE_DEPLOY_ROOT}"
    return 0
  fi
  local candidate="${XCMAX_ROOT}/${DEFAULT_DEPLOY_REL}"
  if [[ -d "${candidate}" ]]; then
    printf '%s\n' "${candidate}"
    return 0
  fi
  return 1
}

usage() {
  cat <<EOF
Mod 商家试点验收（上架 → 0.01 元支付 → 宿主开通）

  bash MODstore/scripts/mod-pilot-checklist.sh [选项]

选项:
  (无)           打印前置条件、四步动作、证据路径与禁止项
  --paths        仅输出证据目录与各 PNG 绝对路径
  --check-only   校验 pilot 文档、证据目录、MODstore_deploy 路径（不要求 PNG）
  --verify       校验四张证据 PNG 均存在且非空（试点跑通后使用）
  -h, --help     本帮助

环境变量:
  MODSTORE_DEPLOY_ROOT   MODstore_deploy 根目录（默认尝试 \${XCMAX}/${DEFAULT_DEPLOY_REL}）

证据提交（试点完成后）:
  git add FHD/docs/evidence/mod/*.png

文档: docs/mod-merchant-pilot.md
EOF
}

print_paths() {
  log "证据目录: ${EVIDENCE_DIR}"
  local i=1
  for f in "${EVIDENCE_FILES[@]}"; do
    printf '  %d) %s/%s\n' "$i" "${EVIDENCE_DIR}" "$f"
    i=$((i + 1))
  done
}

print_steps() {
  log "=== Mod 商家试点（与 mod-merchant-pilot.md 一致）==="
  log "状态: 未跑通前禁止对外宣称「Mod 商店已跑通」；与 T36–T37 staging SLO 无关"
  echo
  log "=== 前置（人工）==="
  cat <<'PRE'
  [ ] 1 家友好商家或内部沙箱租户（商务/运营签字）
  [ ] MODstore SSOT：成都修茈科技有限公司/MODstore_deploy/（勿在 FHD/MODstore/ 开发）
  [ ] 支付宝沙箱/生产 0.01 元密钥（alipay_package/），勿提交密钥入仓
  [ ] 试点完成后仅事实更新 docs/CLAIMED_VS_ACTUAL.md「Mod 商店分成」行
PRE
  deploy="$(resolve_deploy_root 2>/dev/null || true)"
  if [[ -n "${deploy}" ]]; then
    log "  MODstore_deploy: ${deploy}"
  else
    log "  MODstore_deploy: 未检出（设置 MODSTORE_DEPLOY_ROOT 或克隆 SSOT 树）"
  fi
  echo
  log "=== 验收步骤 → 证据 PNG ==="
  printf '  1) 商家入驻 / Mod 上架审核通过     → %s/01-listing.png\n' "${EVIDENCE_DIR}"
  printf '  2) 市场页可见、可安装               → %s/02-store-page.png\n' "${EVIDENCE_DIR}"
  printf '  3) 0.01 元支付成功（沙箱或约定环境） → %s/03-payment.png\n' "${EVIDENCE_DIR}"
  printf '  4) FHD 开通：安装并激活 Mod         → %s/04-activated.png\n' "${EVIDENCE_DIR}"
  echo
  log "=== 禁止 ==="
  cat <<'BAN'
  - 无真实商家前对外宣称「Mod 商店已跑通」
  - 伪造流水或截图
  - 将 Mod 试点与 staging SLO（T36–T37）混为一谈
BAN
  echo
  log "=== 参考 ==="
  log "  文档: ${PILOT_DOC}"
  deploy="$(resolve_deploy_root 2>/dev/null || true)"
  if [[ -n "${deploy}" ]]; then
    local runbook="${deploy}/docs/runbooks/xiu-ci-single-modstore-upstream.md"
    [[ -f "${runbook}" ]] && log "  部署: ${runbook}" || log "  部署 runbook: （在 MODstore_deploy 内查找 xiu-ci-single-modstore-upstream.md）"
  fi
  log "  M0 缺口: ${FHD_ROOT}/docs/M0-remaining-gaps.md #2"
}

check_only() {
  local ok=0
  [[ -f "${PILOT_DOC}" ]] || { log "FAIL: 缺少 ${PILOT_DOC}"; ok=1; }
  [[ -d "${EVIDENCE_DIR}" ]] || { log "FAIL: 缺少证据目录 ${EVIDENCE_DIR}"; ok=1; }
  deploy="$(resolve_deploy_root 2>/dev/null || true)"
  if [[ -n "${deploy}" ]]; then
    log "ok MODstore_deploy: ${deploy}"
    [[ -d "${deploy}/modstore_server" || -d "${deploy}/market" ]] \
      || { log "WARN: deploy 树缺少 modstore_server/ 或 market/"; ok=1; }
  else
    log "WARN: 未找到 MODstore_deploy（${XCMAX_ROOT}/${DEFAULT_DEPLOY_REL}）"
    log "      可 export MODSTORE_DEPLOY_ROOT=/path/to/MODstore_deploy"
  fi
  local alipay="${XCMAX_ROOT}/${ALIPAY_PKG_REL}"
  if [[ -d "${alipay}" ]]; then
    log "ok alipay_package 目录存在（勿将密钥 git add）"
  else
    log "WARN: 未找到 ${alipay}（支付步骤需本地配置密钥）"
  fi
  if [[ "${ok}" -eq 0 ]]; then
    log "check-only 通过（尚未要求四张 PNG）"
    return 0
  fi
  fail "check-only 未通过"
}

verify_evidence() {
  [[ -d "${EVIDENCE_DIR}" ]] || fail "证据目录不存在: ${EVIDENCE_DIR}"
  local missing=0 empty=0
  for f in "${EVIDENCE_FILES[@]}"; do
    local path="${EVIDENCE_DIR}/${f}"
    if [[ ! -f "${path}" ]]; then
      log "MISSING: ${path}"
      missing=$((missing + 1))
      continue
    fi
    if [[ ! -s "${path}" ]]; then
      log "EMPTY: ${path}"
      empty=$((empty + 1))
      continue
    fi
  done
  if [[ "${missing}" -eq 0 && "${empty}" -eq 0 ]]; then
    log "verify 通过：四张证据 PNG 均已就位"
    log "下一步: git add FHD/docs/evidence/mod/*.png"
    log "         并事实更新 docs/CLAIMED_VS_ACTUAL.md Mod 商店分成行"
    return 0
  fi
  fail "verify 未通过（缺 ${missing}，空文件 ${empty}）— 见 ${PILOT_DOC}"
}

main() {
  case "${1:-}" in
    -h|--help)
      usage
      ;;
    --paths)
      print_paths
      ;;
    --check-only)
      check_only
      ;;
    --verify)
      verify_evidence
      ;;
    ""|--steps)
      print_steps
      print_paths
      ;;
    *)
      usage >&2
      fail "未知选项: $1"
      ;;
  esac
}

main "$@"
