# mat-gen-agent Dockerfile
# Stage 1 mock 版本,Stage 2 切真 MatterGen 加 torch + CUDA + model weights
#
# 构建:docker build -t mat-gen:0.1.0 -f Dockerfile .
# 运行:docker run -p 18802:18802 mat-gen:0.1.0

FROM python:3.11-slim

WORKDIR /app

# 系统依赖(Stage 2 真 MatterGen 需要 CUDA,这里只装 mock 依赖)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# 复制 agent 代码
COPY . /app/agents/mat-gen-agent/
COPY matwau/ /app/matwau/

# 装依赖(mock 版本不需 torch / mattergen)
# Stage 2 切真版本时加:torch==2.5.0 --index-url https://download.pytorch.org/whl/cu121
RUN pip install --no-cache-dir \
    pyyaml \
    pytest \
    pydantic

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import sys; sys.path.insert(0, '/app'); \
                    from agents.mat_gen_agent.mat_gen_agent import MatGenAgent; \
                    a = MatGenAgent(); assert a.name == 'mat-gen-agent'" \
    || exit 1

# 默认启动 mock agent CLI(Stage 2 接 wau-python-sdk 的 WauClient 启动)
CMD ["python3", "-m", "agents.mat_gen_agent.mat_gen_agent"]

LABEL org.opencontainers.image.title="mat-gen-agent" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.description="MatWAU mat-gen agent — crystal structure generation (mock stage)"