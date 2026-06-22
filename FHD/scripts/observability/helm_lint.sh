#!/usr/bin/env bash
# Helm chart lint + template render gate (⑤-P1)
#
# When helm is absent the gate skips (CI runners without helm stay green).
# When helm is present it now does a real check:
#   - lint default values AND values-staging.yaml
#   - render both value sets
#   - assert the rendered output actually contains the FHD API Deployment
#     (kind: Deployment / name: xcagi) and its Service, so a regression back to
#     a "monitoring-only" chart fails the gate instead of passing silently.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHART="${ROOT}/helm/xcagi"

if ! command -v helm >/dev/null 2>&1; then
  echo "[helm_lint] helm CLI not installed; skip" >&2
  exit 0
fi

# --- lint (default + staging) ---
helm lint "$CHART"
helm lint "$CHART" -f "${CHART}/values-staging.yaml"

# --- render + assert key objects exist ---
assert_render() {
  local label="$1"; shift
  local out
  out="$(helm template xcagi-staging "$CHART" "$@")"

  # API Deployment must be present and named "xcagi".
  echo "$out" | awk '
    /^kind: Deployment$/ { d=1; next }
    d && /^  name: xcagi$/ { found=1 }
    /^---/ { d=0 }
    END { exit(found?0:1) }
  ' || { echo "[helm_lint] FAIL (${label}): API Deployment (name: xcagi) not rendered" >&2; exit 1; }

  # API Service must be present.
  echo "$out" | grep -qE '^\s+name: xcagi-service$' \
    || { echo "[helm_lint] FAIL (${label}): Service xcagi-service not rendered" >&2; exit 1; }

  # Redis must be present.
  echo "$out" | grep -qE '^\s+name: redis-service$' \
    || { echo "[helm_lint] FAIL (${label}): Redis service not rendered" >&2; exit 1; }

  echo "[helm_lint] ${label}: rendered $(echo "$out" | grep -c '^kind:') manifests incl. API Deployment/Service + Redis"
}

assert_render "default"
assert_render "staging" -f "${CHART}/values-staging.yaml"

# Staging enables k6 — its ConfigMap must be present (no dangling mount).
helm template xcagi-staging "$CHART" -f "${CHART}/values-staging.yaml" \
  | grep -qE '^\s+name: k6-7day-contract$' \
  || { echo "[helm_lint] FAIL (staging): k6-7day-contract ConfigMap not rendered" >&2; exit 1; }
echo "[helm_lint] staging: k6 ConfigMap k6-7day-contract present (mount satisfied)"

echo "[helm_lint] ok: ${CHART}"
