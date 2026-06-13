#!/usr/bin/env bash
# Rollout metrics-fix backend on staging + scale to 2 replicas (does not restart k6 Job).
# Usage: bash FHD/scripts/observability/staging_rollout_metrics.sh
set -euo pipefail

REMOTE="${XCMAX_REMOTE_HOST:-119.27.178.147}"
FHD_SRC="${FHD_SRC:-/opt/fhd-full}"
SSH="ssh -o BatchMode=yes -o ConnectTimeout=15 root@${REMOTE}"
NS=xcagi-staging
KUB="/usr/local/bin/k3s kubectl"

log() { printf '[staging-rollout] %s\n' "$*"; }

$SSH bash -s <<EOF
set -euo pipefail
NS=${NS}
KUB='${KUB}'
FHD_SRC='${FHD_SRC}'

if [ ! -d "\$FHD_SRC" ]; then
  echo "FHD_SRC \$FHD_SRC missing" >&2
  exit 1
fi

cd "\$FHD_SRC"
if [ ! -d xcagi_common ]; then
  for CAND in ../packages/xcagi_common/xcagi_common /opt/XCMAX/packages/xcagi_common/xcagi_common; do
    [ -d "\$CAND" ] && cp -r "\$CAND" xcagi_common && break
  done
fi

docker build \
  --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
  --build-arg PIP_TRUSTED_HOST=mirrors.aliyun.com \
  -f docker/Dockerfile.fhd-api \
  -t xcagi-fhd-api:staging .

\$KUB -n \$NS patch configmap xcagi-config --type merge -p '{"data":{"XCAGI_GUNICORN_WORKERS":"2"}}' 2>/dev/null || true

\$KUB -n \$NS scale deployment xcagi --replicas=2
\$KUB -n \$NS rollout restart deployment/xcagi
\$KUB -n \$NS rollout status deployment/xcagi --timeout=300s
\$KUB -n \$NS get pods -l app=xcagi -o wide
EOF

log "rollout complete on ${REMOTE}"
