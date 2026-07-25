# mat-sim-agent Dockerfile
# Stage 1 mock 版本,Stage 2 切真 CHGNet 加 torch + CUDA + model weights
#
# 构建:docker build -t mat-sim:0.1.0 -f Dockerfile .
# 运行:docker run -p 18803:18803 mat-sim:0.1.0

FROM python:3.11-slim

WORKDIR /app

# 系统依赖(Stage 2 真 CHGNet 需要 CUDA,这里只装 mock 依赖)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# 复制 agent 代码 + mat-gen(上游依赖)
COPY . /app/agents/mat-sim-agent/
COPY ../mat_gen_agent /app/agents/mat_gen_agent/
COPY ../../matwau /app/matwau/

# 装依赖(mock 版本不需 torch / chgnet)
# Stage 2 切真版本时加:torch==2.5.0 --index-url https://download.pytorch.org/whl/cu121
# + chgnet==0.3.0 + ase==3.22.0
RUN pip install --no-cache-dir \
    pyyaml \
    pytest \
    pydantic

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import sys; sys.path.insert(0, '/app'); \
                    from agents.mat_sim_agent.mat_sim_agent import MatSimAgent; \
                    a = MatSimAgent(); assert a.name == 'mat-sim-agent'" \
    || exit 1

# 默认启动 mock agent CLI(Stage 2 接 wau-python-sdk 的 WauClient 启动)
CMD ["python3", "-m", "agents.mat_sim_agent.mat_sim_agent"]

LABEL org.opencontainers.image.title="mat-sim-agent" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.description="MatWAU mat-sim agent — CHGNet MLIP structure relaxation (mock stage)"