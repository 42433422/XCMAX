#!/usr/bin/env bash
# Declarative image bump for GitOps: rewrite the newTag in a kustomize overlay so ArgoCD
# syncs the new image. The caller (CI / run_modstore_daily_local.sh) then commits + pushes;
# this script only edits the file (and optionally commits with --commit).
#
#   bash FHD/scripts/gitops/bump_image.sh <env> <tag> [--commit]
#     <env>  staging | production
#     <tag>  e.g. sha-1a2b3c4   (the image tag CI pushed to GHCR)
#
# v10 lock: artifact identity is git_sha + sha256 + cosign digest — this never bumps the
# product version (anchor stays 10.0.0).
set -euo pipefail

ENV_NAME="${1:-}"
NEW_TAG="${2:-}"
DO_COMMIT="${3:-}"

usage() { echo "usage: $0 <staging|production> <image-tag> [--commit]" >&2; exit 2; }
[ -n "${ENV_NAME}" ] && [ -n "${NEW_TAG}" ] || usage

case "${ENV_NAME}" in
  staging|production) ;;
  *) echo "unknown env: ${ENV_NAME}" >&2; usage ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
OVERLAY="${REPO_ROOT}/FHD/k8s/overlays/${ENV_NAME}/kustomization.yaml"
[ -f "${OVERLAY}" ] || { echo "overlay not found: ${OVERLAY}" >&2; exit 1; }

if ! grep -qE '^[[:space:]]*newTag:' "${OVERLAY}"; then
  echo "no 'newTag:' line in ${OVERLAY} — is the images: block present?" >&2
  exit 1
fi

# In-place rewrite of the single newTag value (portable BSD/GNU sed).
tmp="$(mktemp)"
sed -E "s|^([[:space:]]*newTag:[[:space:]]*).*|\1${NEW_TAG}|" "${OVERLAY}" > "${tmp}"
mv "${tmp}" "${OVERLAY}"

echo "[gitops] ${ENV_NAME} image tag -> ${NEW_TAG}"
grep -nE '^[[:space:]]*(newName|newTag):' "${OVERLAY}" || true

# Validate the overlay still builds (parent-base reference needs LoadRestrictionsNone).
if command -v kubectl >/dev/null 2>&1; then
  if kubectl kustomize --load-restrictor LoadRestrictionsNone "${REPO_ROOT}/FHD/k8s/overlays/${ENV_NAME}" \
      >/dev/null 2>"${REPO_ROOT}/.gitops-kustomize-err.log"; then
    echo "[gitops] kustomize build OK"
    rm -f "${REPO_ROOT}/.gitops-kustomize-err.log"
  else
    echo "::warning::kustomize build failed after bump — see .gitops-kustomize-err.log" >&2
  fi
fi

if [ "${DO_COMMIT}" = "--commit" ]; then
  cd "${REPO_ROOT}"
  git add "FHD/k8s/overlays/${ENV_NAME}/kustomization.yaml"
  # [skip ci]: GitOps tag bumps touch only overlay YAML — ArgoCD syncs them, no need to
  # re-run the full app pipeline (also prevents commit→CI→commit loops for PAT pushers).
  git commit -m "gitops(${ENV_NAME}): image -> ${NEW_TAG} [skip ci] [v10 线内迭代]" \
    -m "Declarative image bump; ArgoCD will sync. Artifact id git_sha+digest; anchor 10.0.0." \
    || echo "[gitops] nothing to commit"
fi
