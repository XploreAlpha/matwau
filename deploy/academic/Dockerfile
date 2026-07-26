# MatWAU 学院版 — Docker 镜像
# 单机包 Dockerfile(per W37.4)
#
# 镜像用途:学院 IT 一键部署 MatWAU 学院版
# - 基础镜像:python:3.11-slim(学院服务器常见 Python 版本)
# - 工作目录:/app
# - 端口:8080(HTTP API)+ 22(可选 SSH)
# - 用户:非 root(学院安全合规)

FROM python:3.11-slim AS base

# 元数据(LICENSE 要求的双署名)
LABEL maintainer="XploreAlpha <support@xplorealpha.example>"
LABEL org.opencontainers.image.title="MatWAU Academic"
LABEL org.opencontainers.image.description="Material Science AI Universal — Academic Edition (Apache 2.0)"
LABEL org.opencontainers.image.source="https://github.com/XploreAlpha/matwau"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.vendor="XploreAlpha"

# 系统依赖(学院版默认 mock 模式,无需 GPU / 真仪器 SDK)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        git \
        ca-certificates \
        libpq-dev \
        gcc \
        && rm -rf /var/lib/apt/lists/*

# 非 root 用户(学院安全合规)
RUN groupadd -r matwau && useradd -r -g matwau -d /app -s /bin/bash matwau

WORKDIR /app

# 先装 Python 依赖(利用 Docker 层缓存)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码(学院版完整代码)
COPY --chown=matwau:matwau . /app/

# 学院 IT 健康检查端点
RUN echo '#!/bin/bash\n\
curl -fsS http://localhost:8080/health || exit 1' > /app/healthcheck.sh \
    && chmod +x /app/healthcheck.sh

USER matwau

# 学院版默认端口
EXPOSE 8080

# 入口脚本(启动 MatWAU 学院版 API)
CMD ["python3", "deploy/academic/serve.py"]