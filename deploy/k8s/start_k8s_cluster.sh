#!/usr/bin/env bash
# start_k8s_cluster.sh — MatWAU k8s 部署启动脚本(W29 远程部署)
#
# 用法:
#   ./deploy/k8s/start_k8s_cluster.sh apply      # 应用所有 manifest
#   ./deploy/k8s/start_k8s_cluster.sh status     # 看状态
#   ./deploy/k8s/start_k8s_cluster.sh delete     # 删除全部
#   ./deploy/k8s/start_k8s_cluster.sh logs       # 看日志
#
# 依赖:kubectl + k8s cluster(minikube/kind/k3s 都行)

set -e
SCRIPT_DIR="$(dirname "$0")"
K8S_DIR="${SCRIPT_DIR}"

cmd="${1:-apply}"

case "$cmd" in
  apply)
    echo "🚀 部署 MatWAU k8s 集群"
    # 1. 部署 Secrets(per feedback-redis-password-leak 占位)
    kubectl apply -f "${K8S_DIR}/matwau-deployment.yml"
    # 2. 部署 Postgres multi-node
    kubectl apply -f "${K8S_DIR}/postgres-multi-node.yml"
    echo ""
    echo "✅ 部署完成"
    echo ""
    echo "📋 等 PG 就绪..."
    kubectl wait --for=condition=ready pod -l component=postgres-primary --timeout=120s
    echo ""
    echo "📋 看 Pod 状态:"
    kubectl get pods -l app=matwau
    ;;
  status)
    echo "📋 MatWAU 集群状态:"
    kubectl get all -l app=matwau
    echo ""
    echo "📋 Pod 详情:"
    kubectl get pods -l app=matwau -o wide
    ;;
  delete)
    echo "⏹️ 删除 MatWAU 集群"
    kubectl delete -f "${K8S_DIR}/postgres-multi-node.yml" 2>/dev/null || true
    kubectl delete -f "${K8S_DIR}/matwau-deployment.yml" 2>/dev/null || true
    ;;
  logs)
    kubectl logs -l app=matwau --tail=50 -f
    ;;
  *)
    echo "用法: $0 {apply|status|delete|logs}"
    exit 1
    ;;
esac