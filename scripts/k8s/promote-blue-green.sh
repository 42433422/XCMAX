#!/usr/bin/env bash
# Promote blue-green traffic to green (canary track) after rollout is ready.
set -euo pipefail

NS="${K8S_NAMESPACE:-xcagi-blue-green}"
SERVICE="${BG_SERVICE_NAME:-xcagi-blue-service}"
TIMEOUT="${BG_ROLLOUT_TIMEOUT:-300s}"

echo "[info] namespace=${NS} service=${SERVICE}"
kubectl -n "${NS}" rollout status deployment/xcagi-green --timeout="${TIMEOUT}"

echo "[info] patching ${SERVICE} selector track=canary"
kubectl patch svc "${SERVICE}" -n "${NS}" -p '{"spec":{"selector":{"track":"canary"}}}'

echo "[ok] traffic promoted to green (canary track)"
