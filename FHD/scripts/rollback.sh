#!/bin/bash
# 回滚脚本 - 一键回滚到上一版本

set -e

NAMESPACE="${NAMESPACE:-default}"
DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-xcagi}"
# 默认回滚到“上一个”版本（CI 自动回滚用）。传入数字则回滚到指定 revision。
REVISION="${1:-previous}"

echo "可用历史版本:"
kubectl rollout history "deployment/${DEPLOYMENT_NAME}" -n "$NAMESPACE" || true

echo "执行回滚 ($DEPLOYMENT_NAME, revision=${REVISION})..."
if [ "$REVISION" = "previous" ] || [ "$REVISION" = "0" ]; then
    kubectl rollout undo "deployment/${DEPLOYMENT_NAME}" -n "$NAMESPACE"
else
    kubectl rollout undo "deployment/${DEPLOYMENT_NAME}" -n "$NAMESPACE" --to-revision="$REVISION"
fi

echo "等待回滚完成..."
kubectl rollout status "deployment/${DEPLOYMENT_NAME}" -n "$NAMESPACE" --timeout=300s

# 健康验证：CI/集群外环境设 ROLLBACK_SKIP_HEALTH=1 跳过（runner 无法直连集群内 :5000）。
if [ "${ROLLBACK_SKIP_HEALTH:-0}" != "1" ]; then
    echo "验证服务健康状态..."
    HEALTH_URL="${HEALTH_URL:-http://localhost:5000/health/liveness}"
    if command -v curl &> /dev/null; then
        curl -sf "$HEALTH_URL" || {
            echo "健康检查失败!"
            exit 1
        }
    fi
fi

echo "回滚完成!"
kubectl get pods -n $NAMESPACE -l app=$DEPLOYMENT_NAME