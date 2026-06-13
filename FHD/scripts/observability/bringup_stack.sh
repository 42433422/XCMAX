#!/usr/bin/env bash
# One-click observability stack on the current kubeconfig (GitOps path or manual).
# Applies the full monitoring overlay (Prometheus + Grafana + Loki + Alertmanager).
#
#   bash FHD/scripts/observability/bringup_stack.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OVERLAY="${REPO_ROOT}/k8s/monitoring/overlays/full"

log() { printf '\033[36m[observability]\033[0m %s\n' "$*"; }

command -v kubectl >/dev/null 2>&1 || { echo "kubectl not found" >&2; exit 1; }
kubectl cluster-info >/dev/null 2>&1 || { echo "no reachable cluster (check KUBE_CONFIG)" >&2; exit 1; }

log "Applying monitoring full stack: ${OVERLAY}"
kubectl apply -k "${OVERLAY}" --load-restrictor LoadRestrictionsNone

log "Waiting for prometheus + grafana in namespace monitoring"
kubectl -n monitoring rollout status deploy/prometheus --timeout=300s || true
kubectl -n monitoring rollout status deploy/grafana --timeout=300s || true

log "Done. Port-forward examples:"
log "  kubectl -n monitoring port-forward svc/prometheus 9090:9090"
log "  kubectl -n monitoring port-forward svc/grafana 3000:3000"
