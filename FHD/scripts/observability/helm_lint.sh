#!/usr/bin/env bash
# Helm chart lint + template render gate (⑤-P1)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHART="${ROOT}/helm/xcagi"

if ! command -v helm >/dev/null 2>&1; then
  echo "[helm_lint] helm CLI not installed; skip" >&2
  exit 0
fi

helm lint "$CHART" -f "${CHART}/values-staging.yaml"
helm template xcagi-staging "$CHART" -f "${CHART}/values-staging.yaml" >/dev/null
echo "[helm_lint] ok: ${CHART}"
