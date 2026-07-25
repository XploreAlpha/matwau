#!/usr/bin/env bash
# start_ot2_gateway.sh — OT-2 网关启动脚本(W28 真接)
#
# 用法:
#   ./deploy/ot2_gateway/start_ot2_gateway.sh            # 默认 up -d
#   ./deploy/ot2_gateway/start_ot2_gateway.sh status     # 看状态
#   ./deploy/ot2_gateway/start_ot2_gateway.sh stop       # 停
#   ./deploy/ot2_gateway/start_ot2_gateway.sh logs       # 看日志
#   ./deploy/ot2_gateway/start_ot2_gateway.sh reset      # 删数据重启
#   ./deploy/ot2_gateway/start_ot2_gateway.sh demo       # 跑端到端 demo
#
# 依赖:docker + docker compose + opentrons pip(降级用)

set -e
SCRIPT_DIR="$(dirname "$0")"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"

cmd="${1:-up}"

case "$cmd" in
  up)
    echo "🚀 启动 MatWAU OT-2 网关"
    docker compose -f "$COMPOSE_FILE" up -d
    echo ""
    echo "✅ 启动完毕"
    echo ""
    echo "📋 端口:31950 (OT-2 RPC)"
    echo "📋 协议目录:${SCRIPT_DIR}/protocols"
    echo "📋 输出目录:${SCRIPT_DIR}/output"
    ;;
  status)
    docker compose -f "$COMPOSE_FILE" ps
    ;;
  stop)
    echo "⏹️ 停止 OT-2 网关"
    docker compose -f "$COMPOSE_FILE" stop
    ;;
  logs)
    docker compose -f "$COMPOSE_FILE" logs -f ot2-simulator
    ;;
  reset)
    echo "🔄 删除 volumes 重启"
    docker compose -f "$COMPOSE_FILE" down -v
    docker compose -f "$COMPOSE_FILE" up -d
    ;;
  demo)
    echo "🎯 跑 W28 端到端 demo"
    cd "$(dirname "$0")/../.."
    python3 examples/ot2_hardware_demo.py
    ;;
  *)
    echo "用法: $0 {up|status|stop|logs|reset|demo}"
    exit 1
    ;;
esac