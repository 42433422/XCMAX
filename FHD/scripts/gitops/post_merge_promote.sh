#!/usr/bin/env bash
# Post-merge GitOps promote: wait for fhd-ci-cd on main → bump staging overlay image tag.
# Respects MODSTORE_SLO_HALT_AUTO_MERGE / SLO readings before promoting.
#
#   bash FHD/scripts/gitops/post_merge_promote.sh [git-sha]
#   MODSTORE_SLO_HALT_AUTO_MERGE=1 bash FHD/scripts/gitops/post_merge_promote.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GIT_SHA="${1:-${GITHUB_SHA:-}}"
WAIT_MINS="${GITOPS_WAIT_CI_MINS:-45}"
REPO="${GITHUB_REPOSITORY:-42433422/XCMAX}"

log() { printf '\033[36m[post-merge]\033[0m %s\n' "$*"; }

_slo_halt() {
  if [[ "${MODSTORE_SLO_HALT_AUTO_MERGE:-0}" != "1" && "${MODSTORE_RELEASE_SLO_HALT:-0}" != "1" ]]; then
    return 1
  fi
  local latest
  latest="$(ls -t "${REPO_ROOT}/metrics"/slo-measured-*.json 2>/dev/null | head -1 || true)"
  [[ -n "${latest}" ]] || return 1
  python3 - <<'PY' "${latest}"
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text())
readings = data.get("readings") or {}
for rid, row in readings.items():
    if row.get("meets_target") is False:
        print(f"SLO halt: {rid} fails target")
        sys.exit(0)
sys.exit(1)
PY
}

if _slo_halt; then
  log "SLO 熔断 — 跳过 GitOps promote（MODSTORE_SLO_HALT_*）"
  exit 1
fi

if [[ -z "${GIT_SHA}" ]]; then
  log "ERROR: 需要 git sha（参数或 GITHUB_SHA）"
  exit 2
fi

TAG="sha-${GIT_SHA:0:7}"

if command -v gh >/dev/null 2>&1 && [[ -n "${GITHUB_TOKEN:-${GH_TOKEN:-}}" ]]; then
  log "等待 fhd-ci-cd 在 main@${GIT_SHA:0:7} 上成功（最多 ${WAIT_MINS}m）…"
  deadline=$(( $(date +%s) + WAIT_MINS * 60 ))
  while [[ $(date +%s) -lt ${deadline} ]]; do
    if gh run list --repo "${REPO}" --workflow fhd-ci-cd.yml --branch main --limit 20 \
        --json conclusion,headSha,status \
        -q ".[] | select(.headSha|startswith(\"${GIT_SHA:0:7}\")) | .conclusion" 2>/dev/null \
        | grep -qx success; then
      log "fhd-ci-cd 已成功"
      break
    fi
    sleep 30
  done
fi

log "GitOps bump staging → ${TAG}"
bash "${REPO_ROOT}/scripts/gitops/bump_image.sh" staging "${TAG}" --commit

if [[ "${GITOPS_POST_MERGE_PUSH:-1}" == "1" ]]; then
  cd "${REPO_ROOT}"
  git push origin HEAD || log "WARN: push 失败（branch protection?）— 可改用 GITOPS_BUMP_ENABLE=1"
fi

log "Done — ArgoCD 将 sync staging overlay"
