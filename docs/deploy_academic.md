# MatWAU 学院版 — 部署文档(deploy_academic)

> **目标读者**: 学院 IT 工程师(不要求 Docker 经验)
> **难度**: 入门(跟着步骤 1 个小时能跑通)
> **配套版本**: MatWAU v1.0-Academic
> **License**: Apache 2.0(同 MatWAU 主 license)

---

## 一、准备(10 分钟)

### 1.1 服务器要求

| 项 | 最低 | 推荐 |
|---|---|---|
| **CPU** | 4 核 | 8 核 |
| **内存** | 8 GB | 16 GB |
| **磁盘** | 20 GB | 100 GB(含数据备份)|
| **系统** | Ubuntu 22.04+ / CentOS Stream 9+ | Ubuntu 24.04 LTS |
| **网络** | 学院内网可达 | + 可选外网(LLM 复核)|
| **权限** | sudo(安装 Docker)| sudo 或 root |

### 1.2 安装 Docker

```bash
# Ubuntu
sudo apt update
sudo apt install -y docker.io docker-compose-plugin

# CentOS
sudo yum install -y docker docker-compose-plugin

# 启动 Docker daemon
sudo systemctl start docker
sudo systemctl enable docker  # 开机自启

# 把当前用户加入 docker 组(避免每次 sudo)
sudo usermod -aG docker $USER
newgrp docker  # 立即生效

# 验证
docker run hello-world
# 看到 "Hello from Docker!" = 成功
```

---

## 二、一键部署(15 分钟)

### 2.1 拉代码 + 进 deploy/academic/

```bash
# 拉 MatWAU 学院版代码
git clone https://github.com/XploreAlpha/matwau.git
cd matwau

# 切换到学院版稳定版 tag
git checkout v1.0-Academic

# 进学院版 Docker 包目录
cd deploy/academic
```

### 2.2 配置 .env(可选,2 分钟)

```bash
# 复制模板
cp .env.example .env

# 编辑(改密码 / LLM key)
vi .env
```

`.env` 关键 4 项:

| 项 | 默认 | 何时改 |
|---|---|---|
| `POSTGRES_PASSWORD` | `changeme_in_env_file_2026` | **必须改!**改成你自己的强密码 |
| `MATWAU_LLM_ENABLED` | `0`(关闭 LLM)| 想用 LLM 复核时改 `1` |
| `MATWAU_LLM_API_KEY` | 空 | 想用 LLM 复核时填 DeepSeek key |
| `MATWAU_PORT` | `8080` | 端口被占用时改 |

⚠️ **API key 走 env,绝不入对话**(per LICENSE 规定 + 学院 IT 安全合规)。

### 2.3 一键启动

```bash
bash deploy_academic.sh
```

脚本会做:

```
1. 校验 Docker / docker compose 可用
2. 创建 .env(如未存在)
3. 构建镜像(首次 3-5 分钟)
4. 启动容器(matwau-app + lineage-db)
5. 等待健康检查通过(最多 60 秒)
6. 打印测试命令
```

### 2.4 验证部署成功

```bash
# 健康检查
curl http://localhost:8080/health
# 期望:{"status": "ok", "service": "matwau-academic", "version": "v1.0-Academic", ...}

# 版本
curl http://localhost:8080/version
# 期望:{"version": "v1.0-Academic", "license": "Apache-2.0", ...}

# 试 1 个意图解析
curl -X POST http://localhost:8080/intent \
  -H 'Content-Type: application/json' \
  -d '{"message": "设计无钴锂电池正极材料,能量密度 > 500 Wh/kg"}'
# 期望:200 + {"reply": "...", "mat_intent": "...", ...}

# 试 1 个多实验并行
curl -X POST http://localhost:8080/multi-exp \
  -H 'Content-Type: application/json' \
  -d '{"n_experiments": 1}'
# 期望:200 + {"n_total": 1, "overall_verdict": "pass", ...}
```

---

## 三、日常运维

### 3.1 启停 / 重启

```bash
# 在 deploy/academic/ 目录下

docker compose stop         # 停止(数据保留)
docker compose start        # 启动
docker compose restart      # 重启

# 跑全量 demo(从容器内)
docker compose exec matwau-app python3 examples/multi_experiment_demo.py

# 看实时日志
docker compose logs -f

# 看某 service 的最近 100 行日志
docker compose logs --tail=100 matwau-app
```

### 3.2 数据备份(学院 IT 每周 cron 1 次)

```bash
# 备份 lineage + 用户数据
docker run --rm \
  -v matwau-data:/data:ro \
  -v $(pwd):/backup \
  alpine tar czf /backup/matwau-data-$(date +%Y%m%d).tar.gz -C / data

# 备份 Postgres 数据
docker run --rm \
  -v matwau-db:/db:ro \
  -v $(pwd):/backup \
  alpine tar czf /backup/matwau-db-$(date +%Y%m%d).tar.gz -C / db
```

自动化(可选,加到 `/etc/cron.weekly/matwau-backup`):

```bash
#!/bin/bash
# /etc/cron.weekly/matwau-backup
cd /opt/matwau/deploy/academic
docker run --rm -v matwau-data:/data:ro -v /backup:/backup \
    alpine tar czf /backup/matwau-data-$(date +%Y%m%d).tar.gz -C / data
docker run --rm -v matwau-db:/db:ro -v /backup:/backup \
    alpine tar czf /backup/matwau-db-$(date +%Y%m%d).tar.gz -C / db
# 保留最近 4 周
find /backup -name "matwau-*.tar.gz" -mtime +28 -delete
```

### 3.3 升级到 v1.1-Academic(未来)

```bash
cd /opt/matwau  # 你的代码目录
git fetch origin
git checkout v1.1-Academic  # 或 main
cd deploy/academic
docker compose build         # 重建镜像
docker compose up -d         # 重启容器
docker compose exec matwau-app python3 -m pytest tests/ -q   # 跑回归
```

### 3.4 监控(学院 IT 自建时)

docker-compose.yml 第 3 个 service `prometheus` 默认注释。如启用:

```yaml
# 取消注释 + 写 prometheus.yml
prometheus:
  image: prom/prometheus:latest
  ports:
    - "9090:9090"
  volumes:
    - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
```

学院 IT 用 Grafana 接 Prometheus 即可可视化。

---

## 四、故障排查

### 4.1 端口 8080 被占用

修改 `.env`:

```
MATWAU_PORT=8888  # 或别的空闲端口
docker compose restart
```

### 4.2 docker compose build 慢 / 失败

```bash
# 清缓存重试
docker system prune -a
docker compose build --no-cache

# 拉基础镜像慢?配学院 Docker 镜像加速器
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<EOF
{
  "registry-mirrors": ["https://<your-academy-mirror>/"]
}
EOF
sudo systemctl restart docker
```

### 4.3 数据库连接失败

```bash
# 看 lineage-db 健康
docker compose ps lineage-db
# 期望:Up (healthy)

# 重启 lineage-db
docker compose restart lineage-db
sleep 10  # 等 Postgres 起来
docker compose restart matwau-app
```

### 4.4 LLM 复核开启后不工作

```bash
# 1. 验证 .env
grep MATWAU_LLM .env
# 应该看到 MATWAU_LLM_ENABLED=1 + MATWAU_LLM_API_KEY=sk-...

# 2. 从容器内测试 API key
docker compose exec matwau-app python3 -c "
import os
print('LLM_ENABLED:', os.environ.get('MATWAU_LLM_ENABLED'))
print('API_KEY set:', bool(os.environ.get('MATWAU_LLM_API_KEY')))
"

# 3. 学院 IT 自查:从 docker host 测试 DeepSeek API 是否可达
curl -fsS -o /dev/null -w '%{http_code}' \
  https://api.deepseek.com
# 期望:200 / 405(GET 不允许但服务在)
```

### 4.5 容器日志查问题

```bash
docker compose logs --tail=200 matwau-app
docker compose logs --tail=50 lineage-db
```

---

## 五、安全合规

### 5.1 学院 IT 自查清单

- [ ] `.env` 文件已加入 `.gitignore`(默认 ✅)
- [ ] `.env` 中 `POSTGRES_PASSWORD` 已改成强密码(默认示例已含提醒)
- [ ] 如配 LLM,`MATWAU_LLM_API_KEY` 只在学院内网可达的 docker host 上设置
- [ ] 学院防火墙已开放 8080(API)+ 5432(只内网)
- [ ] 数据卷 `matwau-data` 和 `matwau-db` 在学院 IT 备份策略内
- [ ] 学院 IT 已订阅 XploreAlpha GitHub Releases(等 v1.1-Academic)

### 5.2 数据归属声明

```
学院 IT 部署完成后:
  - 所有 lineage 数据 → 写入学院 IT 指定的 volume(matwau-data / matwau-db)
  - MatWAU 服务本身 → 只读代码 + 配置,不收集任何使用数据
  - 可选 LLM 复核 → 学院 IT 配的 API key,直接调 DeepSeek,XploreAlpha 不中转
  - 数据所有权 → 学院(详见 LICENSE §"DATA OWNERSHIP")
```

---

## 六、卸载(完整删除)

```bash
cd deploy/academic
docker compose down -v    # ⚠️ -v 会删除数据卷,学院 IT 慎用

# 如要保留数据:
docker compose down       # 只删除容器,数据卷保留
```

---

## 七、附录:完整部署命令清单

```bash
# === 一次性安装 ===
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER
newgrp docker

# === 部署 MatWAU 学院版 ===
git clone https://github.com/XploreAlpha/matwau.git /opt/matwau
cd /opt/matwau
git checkout v1.0-Academic
cd deploy/academic
cp .env.example .env
# vi .env  # 编辑(改密码 / LLM key)
bash deploy_academic.sh

# === 验证 ===
curl http://localhost:8080/health
curl -X POST http://localhost:8080/intent \
  -H 'Content-Type: application/json' \
  -d '{"message": "设计无钴锂电池正极材料"}'

# === 跑 demo ===
docker compose exec matwau-app python3 examples/multi_experiment_demo.py

# === 每周 cron 备份 ===
# (见 §3.2)

# === 升级 ===
cd /opt/matwau
git fetch origin
git checkout v1.1-Academic
cd deploy/academic
docker compose build && docker compose up -d
```

---

**end of docs/deploy_academic.md**

> 编写日期:2026-07-26
> 配套版本:MatWAU v1.0-Academic
> License:Apache 2.0
> 维护:XploreAlpha 团队
> 反馈:GitHub Issues https://github.com/XploreAlpha/matwau/issues