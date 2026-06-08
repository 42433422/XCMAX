#!/usr/bin/env bash
# M0 证据链门禁：能自动跑的跑完；staging / Mod 真验收需外部前置
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${ROOT}"

log() { printf '[m0-gate] %s\n' "$*"; }
fail=0

log "=== 1/3 本地 SLO（Docker + FastAPI :5000）==="
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  log "SKIP 本地 Grafana：Docker 未就绪"
  fail=1
elif ! curl -sf http://127.0.0.1:5000/api/health >/dev/null 2>&1; then
  log "SKIP 本地 Grafana：FastAPI :5000 未就绪"
  log "  → cd FHD/XCAGI && ../.venv/bin/python run_fastapi.py --desktop --host 127.0.0.1 --port 5000"
  fail=1
else
  bash scripts/observability/local_stack_up.sh || fail=1
fi

log "=== 2/3 staging SLO（T36–T37 · 7d 验收）==="
if [[ -z "${KUBECONFIG:-}" ]] || ! kubectl config current-context >/dev/null 2>&1; then
  log "BLOCKED staging：未设置 KUBECONFIG / kubectl context"
  log "  → export KUBECONFIG=/path/to/staging.kubeconfig"
  log "  → 见 FHD/docs/staging-m0-preflight.md · specs/BLOCKERS.md T36–T37"
  fail=1
else
  export NS="${NS:-xcagi-staging}"
  if kubectl get ns "${NS}" >/dev/null 2>&1; then
    kubectl -n "${NS}" port-forward svc/grafana 3000:3000 >/tmp/m0-grafana-pf.log 2>&1 &
    pf_pid=$!
    sleep 2
    export GRAFANA_URL=http://127.0.0.1:3000
    export TIME_RANGE=now-7d
    if bash scripts/observability/export_m0_panels.sh --prefix staging; then
      log "staging PNG 已导出（须人工确认 7d 流量 + acceptance yaml）"
    else
      log "staging 导出失败"
      fail=1
    fi
    kill "${pf_pid}" 2>/dev/null || true
  else
    log "BLOCKED staging：命名空间 ${NS} 不存在"
    fail=1
  fi
fi

log "=== 3/3 Mod 商家试点四图 ===="
export MODSTORE_DEPLOY_ROOT="${MODSTORE_DEPLOY_ROOT:-${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy}"
if bash MODstore/scripts/mod-pilot-checklist.sh --verify 2>/dev/null; then
  log "Mod 四图验收通过"
else
  log "BLOCKED Mod：四张真实 PNG 未就位"
  log "  → 跑通 mod-merchant-pilot.md 四步后：bash MODstore/scripts/mod-pilot-checklist.sh --verify"
  fail=1
fi

python3 scripts/observability/sync_m0_evidence_manifest.py

if [[ "${fail}" -eq 0 ]]; then
  log "M0 证据链门禁：全部通过"
  exit 0
fi
log "M0 证据链门禁：仍有阻塞项（见上方 BLOCKED）"
exit 1
