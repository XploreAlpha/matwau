#!/usr/bin/env bash
# start_postgres.sh — Postgres 一键启动(W23 真接)
#
# 用法:
#   ./deploy/postgres/start_postgres.sh           # 默认 up -d
#   ./deploy/postgres/start_postgres.sh status    # 看状态
#   ./deploy/postgres/start_postgres.sh stop      # 停
#   ./deploy/postgres/start_postgres.sh logs      # 看日志
#   ./deploy/postgres/start_postgres.sh reset     # 删数据重启
#
# 依赖:docker + docker compose
#
# 设置 DSN 给 MatWAU:
#   export MATWAU_PG_DSN="postgresql://matwau:matwau_dev_pw@localhost:5432/matwau"

set -e
COMPOSE_FILE="$(dirname "$0")/docker-compose.yml"

cmd="${1:-up}"

case "$cmd" in
  up)
    echo "🚀 启动 MatWAU Postgres"
    docker compose -f "$COMPOSE_FILE" up -d
    echo ""
    echo "✅ 启动完毕"
    echo ""
    echo "📋 DSN(postgres://):"
    echo "  export MATWAU_PG_DSN='postgresql://matwau:matwau_dev_pw@localhost:5432/matwau'"
    echo ""
    echo "📋 进 PG 客户端:"
    echo "  docker exec -it matwau-postgres psql -U matwau -d matwau"
    ;;
  status)
    docker compose -f "$COMPOSE_FILE" ps
    echo ""
    docker inspect --format '{{.State.Health.Status}}' matwau-postgres 2>/dev/null || echo "(容器未运行)"
    ;;
  stop)
    echo "⏹️ 停止 Postgres"
    docker compose -f "$COMPOSE_FILE" stop
    ;;
  logs)
    docker compose -f "$COMPOSE_FILE" logs -f postgres
    ;;
  reset)
    echo "🔄 删除 volume 重启(数据全清)"
    docker compose -f "$COMPOSE_FILE" down -v
    docker compose -f "$COMPOSE_FILE" up -d
    ;;
  *)
    echo "用法: $0 {up|status|stop|logs|reset}"
    exit 1
    ;;
esac
