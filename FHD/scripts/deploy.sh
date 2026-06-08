#!/bin/bash
# 部署脚本 - 蓝绿/金丝雀部署支持

set -e

set -a
source .env 2>/dev/null || true
set +a

NAMESPACE="${NAMESPACE:-default}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-xcagi}"
STRATEGY="${STRATEGY:-rolling}"  # rolling, blue-green, canary

echo "XCAGI 部署脚本"
echo "===================="
echo "策略: $STRATEGY"
echo "镜像标签: $IMAGE_TAG"
echo ""

case "$STRATEGY" in
    rolling)
        echo "执行滚动更新..."
        kubectl set image deployment/$DEPLOYMENT_NAME xcagi=xcagi:$IMAGE_TAG -n $NAMESPACE
        kubectl rollout status deployment/$DEPLOYMENT_NAME -n $NAMESPACE --timeout=600s
        ;;
    blue-green)
        echo "执行蓝绿部署（双 Deployment 切换，无 scale-to-zero 中断）..."
        kubectl apply -f k8s/blue-green-deployment.yaml -n "$NAMESPACE"
        kubectl set image deployment/xcagi-green xcagi=xcagi:"$IMAGE_TAG" -n "$NAMESPACE"
        kubectl rollout status deployment/xcagi-green -n "$NAMESPACE" --timeout=600s
        kubectl patch service xcagi -n "$NAMESPACE" -p '{"spec":{"selector":{"track":"green"}}}'
        ;;
    canary)
        echo "执行金丝雀部署（Ingress 权重）..."
        kubectl apply -f k8s/canary.yaml -n "$NAMESPACE"
        kubectl set image deployment/xcagi-canary xcagi=xcagi:"$IMAGE_TAG" -n "$NAMESPACE"
        kubectl rollout status deployment/xcagi-canary -n "$NAMESPACE" --timeout=600s
        echo "金丝雀流量: 见 k8s/canary.yaml Ingress annotation canary-weight"
        ;;
esac

echo ""
echo "运行健康检查..."
./scripts/health-check.sh

echo ""
echo "部署完成!"
kubectl get pods -n $NAMESPACE -l app=$DEPLOYMENT_NAME