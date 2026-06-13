#!/bin/bash
# 回滚脚本 - 一键回滚到上一版本（Deployment break-glass 或 GitOps Rollout）

set -e

NAMESPACE="${NAMESPACE:-default}"
DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-xcagi}"
# 默认回滚到“上一个”版本（CI 自动回滚用）。传入数字则回滚到指定 revision。
REVISION="${1:-previous}"

_use_rollout() {
  kubectl get "rollout/${DEPLOYMENT_NAME}" -n "$NAMESPACE" >/dev/null 2>&1
}

_rollout_cli() {
  if command -v kubectl-argo-rollouts >/dev/null 2>&1; then
    kubectl-argo-rollouts "$@"
    return $?
  fi
  if kubectl argo rollouts version >/dev/null 2>&1; then
    kubectl argo rollouts "$@"
    return $?
  fi
  return 1
}

if _use_rollout && _rollout_cli version >/dev/null 2>&1; then
  echo "检测到 Rollout/${DEPLOYMENT_NAME} — 使用 Argo Rollouts undo"
  echo "可用历史版本:"
  _rollout_cli history "rollout/${DEPLOYMENT_NAME}" -n "$NAMESPACE" || true
  echo "执行回滚 (rollout/${DEPLOYMENT_NAME}, revision=${REVISION})..."
  if [ "$REVISION" = "previous" ] || [ "$REVISION" = "0" ]; then
    _rollout_cli undo "rollout/${DEPLOYMENT_NAME}" -n "$NAMESPACE"
  else
    _rollout_cli undo "rollout/${DEPLOYMENT_NAME}" -n "$NAMESPACE" --to-revision="$REVISION"
  fi
  echo "等待回滚完成..."
  _rollout_cli status "rollout/${DEPLOYMENT_NAME}" -n "$NAMESPACE" --timeout=300s
else
  echo "使用 Deployment/${DEPLOYMENT_NAME}（break-glass 或未安装 Rollouts CLI）"
  echo "可用历史版本:"
  kubectl rollout history "deployment/${DEPLOYMENT_NAME}" -n "$NAMESPACE" || true
  echo "执行回滚 (deployment/${DEPLOYMENT_NAME}, revision=${REVISION})..."
  if [ "$REVISION" = "previous" ] || [ "$REVISION" = "0" ]; then
    kubectl rollout undo "deployment/${DEPLOYMENT_NAME}" -n "$NAMESPACE"
  else
    kubectl rollout undo "deployment/${DEPLOYMENT_NAME}" -n "$NAMESPACE" --to-revision="$REVISION"
  fi
  echo "等待回滚完成..."
  kubectl rollout status "deployment/${DEPLOYMENT_NAME}" -n "$NAMESPACE" --timeout=300s
fi

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
kubectl get pods -n "$NAMESPACE" -l app="$DEPLOYMENT_NAME"
