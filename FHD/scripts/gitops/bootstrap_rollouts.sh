#!/usr/bin/env bash
# Install the Argo Rollouts controller + CRDs on the current-kubeconfig cluster (the
# non-GitOps path; GitOps installs it declaratively via FHD/gitops/apps/rollouts.yaml).
# Idempotent. Optionally installs the kubectl-argo-rollouts plugin hint.
#
#   bash FHD/scripts/gitops/bootstrap_rollouts.sh
#   ROLLOUTS_VERSION=v1.7.2 bash FHD/scripts/gitops/bootstrap_rollouts.sh
set -euo pipefail

ROLLOUTS_NAMESPACE="${ROLLOUTS_NAMESPACE:-argo-rollouts}"
ROLLOUTS_VERSION="${ROLLOUTS_VERSION:-stable}"  # e.g. v1.7.2 or 'stable'

log() { printf '\033[35m[rollouts]\033[0m %s\n' "$*"; }

command -v kubectl >/dev/null 2>&1 || { echo "kubectl not found" >&2; exit 1; }
kubectl cluster-info >/dev/null 2>&1 || { echo "no reachable cluster (check KUBE_CONFIG)" >&2; exit 1; }

log "Ensuring namespace ${ROLLOUTS_NAMESPACE}"
kubectl create namespace "${ROLLOUTS_NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

log "Installing Argo Rollouts (${ROLLOUTS_VERSION})"
kubectl apply -n "${ROLLOUTS_NAMESPACE}" \
  -f "https://github.com/argoproj/argo-rollouts/releases/${ROLLOUTS_VERSION}/download/install.yaml"

log "Waiting for the controller"
kubectl -n "${ROLLOUTS_NAMESPACE}" rollout status deploy/argo-rollouts --timeout=300s || true

log "CRDs:"
kubectl get crd rollouts.argoproj.io analysistemplates.argoproj.io 2>/dev/null || \
  log "(CRDs not visible yet — give the controller a moment)"

cat <<'EOF'
[rollouts] Done. Optional CLI plugin (local inspection / manual promote-abort):
  brew install argoproj/tap/kubectl-argo-rollouts   # macOS
  kubectl argo rollouts get rollout xcagi -n xcagi-staging --watch
  kubectl argo rollouts promote xcagi -n xcagi-staging      # manual promote
  kubectl argo rollouts abort   xcagi -n xcagi-staging      # manual abort/rollback
EOF
