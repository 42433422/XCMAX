#!/usr/bin/env bash
# Sync SSOT k6_7d_contract.js → K8s ConfigMap manifest (k6-7day-contract).
# Usage:
#   bash scripts/observability/sync_k6_configmap.sh
#   bash scripts/observability/sync_k6_configmap.sh --apply
#   bash scripts/observability/sync_k6_configmap.sh --namespace xcagi-staging --apply
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SSOT="${ROOT}/scripts/observability/k6_7d_contract.js"
OUT="${ROOT}/k8s/monitoring/k6-configmap.yaml"
NAMESPACE="${K6_NAMESPACE:-xcagi-staging}"
CM_NAME="k6-7day-contract"
APPLY=0
KUBECTL="${KUBECTL:-kubectl}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --output) OUT="$2"; shift 2 ;;
    --kubectl) KUBECTL="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: sync_k6_configmap.sh [--apply] [--namespace NS] [--output PATH]"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ ! -f "$SSOT" ]]; then
  echo "SSOT not found: $SSOT" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT")"

"$KUBECTL" create configmap "$CM_NAME" \
  --namespace="$NAMESPACE" \
  --from-file=k6_7d_contract.js="$SSOT" \
  --dry-run=client -o yaml > "$OUT"

# Header for repo traceability
{
  echo "# Generated from FHD/scripts/observability/k6_7d_contract.js — do not hand-edit."
  echo "# Regenerate: bash FHD/scripts/observability/sync_k6_configmap.sh"
  cat "$OUT"
} > "${OUT}.tmp" && mv "${OUT}.tmp" "$OUT"

echo "[sync_k6_configmap] wrote $OUT ($(wc -l < "$SSOT") lines from SSOT)"

if [[ "$APPLY" -eq 1 ]]; then
  "$KUBECTL" apply -f "$OUT"
  echo "[sync_k6_configmap] applied ConfigMap $CM_NAME in $NAMESPACE"
fi
