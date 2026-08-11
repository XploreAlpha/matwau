#!/usr/bin/env bash
# MatWAU 学院版 — 一键部署脚本(per W37.4)
#
# 学院 IT 在 Linux 服务器上跑这 1 个脚本即可:
#   bash deploy_academic.sh
#
# 流程:
#   1. 校验 docker / docker compose 可用
#   2. 创建 .env(如未存在)
#   3. 构建并启动容器
#   4. 校验健康检查端点
#   5. 跑 demo 验证(可选)
#
# 维护:XploreAlpha(Apache 2.0)
# 部署对象:学院 IT(无 IT 经验也能跑)

set -euo pipefail

# ======== 颜色 + 日志 ========
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[matwau-academic]${NC} $*"; }
ok()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err() { echo -e "${RED}[✗]${NC} $*" >&2; }

# ======== 元数据 ========
MATWAU_VERSION="v1.4.2-Academic"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$DEPLOY_DIR/../.." && pwd)"

echo "==============================================="
echo "  MatWAU 学院版 一键部署脚本"
echo "  版本:$MATWAU_VERSION"
echo "  维护:XploreAlpha(Apache 2.0)"
echo "==============================================="
echo ""

# ======== 1. 校验 Docker ========
log "校验 Docker 环境..."
if ! command -v docker >/dev/null 2>&1; then
    err "Docker 未安装。请先装 Docker:"
    err "  Ubuntu: sudo apt install docker.io docker-compose-plugin"
    err "  CentOS: sudo yum install docker docker-compose-plugin"
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    err "Docker daemon 未运行。请启动 Docker:"
    err "  sudo systemctl start docker"
    exit 1
fi

if docker compose version >/dev/null 2>&1; then
    ok "Docker Compose 可用:$(docker compose version --short 2>/dev/null || echo 'plugin-based')"
else
    err "Docker Compose 未安装(需 v2+):"
    err "  https://docs.docker.com/compose/install/"
    exit 1
fi

# ======== 2. 校验 .env ========
log "校验环境变量文件..."
cd "$DEPLOY_DIR"

if [[ ! -f ".env" ]]; then
    if [[ -f ".env.example" ]]; then
        cp .env.example .env
        warn ".env 不存在,从 .env.example 复制。"
        warn "请编辑 .env 改 POSTGRES_PASSWORD 与(可选)MATWAU_LLM_API_KEY"
        warn "现在先按默认值启动,跑通后再编辑。"
    else
        err ".env 和 .env.example 都不存在。脚本异常退出。"
        exit 1
    fi
else
    ok ".env 存在"
fi

# ======== 3. 校验数据目录 ========
log "校验数据目录..."
# docker volume 名称(matwau-data / matwau-db)由 docker compose 自动管理
# 这里只是提示学院 IT 备份策略
ok "数据将存在 docker volumes: matwau-data(血缘 + 用户数据)+ matwau-db(Postgres)"
warn "学院 IT 备份策略:每周 cron 备份这两个 volume。"

# ======== 4. 构建 + 启动 ========
log "构建并启动容器(首次约 3-5 分钟)..."
docker compose build --no-cache
docker compose up -d

# ======== 5. 等待健康 ========
log "等待服务健康(最多 60 秒)..."
for i in {1..12}; do
    sleep 5
    if curl -fsS http://localhost:8080/health >/dev/null 2>&1; then
        ok "MatWAU 学院版 API 健康!"
        break
    fi
    if [[ $i -eq 12 ]]; then
        err "60 秒后仍未就绪。查日志:docker compose logs matwau-app"
        exit 1
    fi
    log "  还在等...($((i * 5))s)"
done

# ======== 6. 打印摘要 ========
echo ""
echo "==============================================="
echo "  部署成功!"
echo "==============================================="
echo ""
echo "  服务地址:"
echo "    - HTTP API:    http://localhost:8080"
echo "    - 健康检查:    http://localhost:8080/health"
echo "    - 版本:        http://localhost:8080/version"
echo ""
echo "  快速测试:"
echo "    curl http://localhost:8080/health"
echo "    curl -X POST http://localhost:8080/intent \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"message\": \"设计无钴锂电池正极材料\"}'"
echo "    curl -X POST http://localhost:8080/multi-exp \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"n_experiments\": 1}'"
echo ""
echo "  跑 demo(可选,容器外):"
echo "    docker compose exec matwau-app python3 examples/multi_experiment_demo.py"
echo ""
echo "  查看日志:"
echo "    docker compose logs -f"
echo ""
echo "  停止 / 重启 / 删除:"
echo "    docker compose stop        # 停止(数据保留)"
echo "    docker compose restart     # 重启"
echo "    docker compose down        # 删除容器(数据卷保留)"
echo "    docker compose down -v     # 删除容器 + 数据卷(危险!学院 IT 慎用)"
echo ""
echo "  数据备份(每周 cron 跑 1 次):"
echo "    docker run --rm -v matwau-data:/data -v \$(pwd):/backup \\"
echo "      alpine tar czf /backup/matwau-data-\$(date +%Y%m%d).tar.gz /data"
echo "    docker run --rm -v matwau-db:/db -v \$(pwd):/backup \\"
echo "      alpine tar czf /backup/matwau-db-\$(date +%Y%m%d).tar.gz /db"
echo ""
echo "  维护:XploreAlpha(support@xplorealpha.example)"
echo "  License:Apache 2.0"
echo "  数据归属:学校"
echo ""