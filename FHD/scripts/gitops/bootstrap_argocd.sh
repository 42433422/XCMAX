#!/usr/bin/env bash
# Bootstrap ArgoCD + the FHD App-of-Apps on the cluster pointed at by the current
# kubeconfig (CI exports KUBE_CONFIG → kubeconfig). Idempotent: safe to re-run.
#
#   bash FHD/scripts/gitops/bootstrap_argocd.sh            # install + apply app-of-apps
#   ARGOCD_VERSION=v2.12.4 bash FHD/scripts/gitops/bootstrap_argocd.sh
#
# Requires: kubectl (with a working context). No private keys; repo is public.
set -euo pipefail

ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
ARGOCD_VERSION="${ARGOCD_VERSION:-stable}"  # e.g. v2.12.4 or 'stable'
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
APP_OF_APPS="${REPO_ROOT}/FHD/gitops/app-of-apps.yaml"

log() { printf '\033[36m[gitops]\033[0m %s\n' "$*"; }

command -v kubectl >/dev/null 2>&1 || { echo "kubectl not found" >&2; exit 1; }
kubectl cluster-info >/dev/null 2>&1 || { echo "no reachable cluster (check KUBE_CONFIG)" >&2; exit 1; }

log "Ensuring namespace ${ARGOCD_NAMESPACE}"
kubectl create namespace "${ARGOCD_NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

log "Installing ArgoCD (${ARGOCD_VERSION})"
kubectl apply -n "${ARGOCD_NAMESPACE}" \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"

# Overlays reference the parent base dir (resources: ../..), which kustomize blocks under
# the default LoadRestrictionsStrict. Allow it cluster-wide for ArgoCD's kustomize build.
log "Patching argocd-cm: kustomize.buildOptions=--load-restrictor LoadRestrictionsNone"
kubectl -n "${ARGOCD_NAMESPACE}" patch configmap argocd-cm --type merge \
  -p '{"data":{"kustomize.buildOptions":"--load-restrictor LoadRestrictionsNone"}}'

log "Waiting for argocd-server rollout"
kubectl -n "${ARGOCD_NAMESPACE}" rollout status deploy/argocd-server --timeout=300s || true
# Repo-server reads kustomize.buildOptions; restart so the patch takes effect.
kubectl -n "${ARGOCD_NAMESPACE}" rollout restart deploy/argocd-repo-server >/dev/null 2>&1 || true

log "Applying App-of-Apps: ${APP_OF_APPS}"
kubectl apply -f "${APP_OF_APPS}"

log "Done. ArgoCD now manages FHD/gitops/apps/* declaratively."
log "Admin password: kubectl -n ${ARGOCD_NAMESPACE} get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
