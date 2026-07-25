# mat-exp-agent Dockerfile
# Stage 1 mock 版本,Stage 2 切真 XRD 仪器 + 烧结炉
#
# 构建:docker build -t mat-exp:0.1.0 -f Dockerfile .
# 运行:docker run -p 18805:18805 mat-exp:0.1.0

FROM python:3.11-slim

WORKDIR /app

# 系统依赖(Stage 2 需要 XRD 仪器 SDK + 串口)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# 复制 agent 代码 + 上游依赖(mat-gen + mat-sim + mat-hpc)
COPY . /app/agents/mat-exp-agent/
COPY ../mat_gen_agent /app/agents/mat_gen_agent/
COPY ../mat_sim_agent /app/agents/mat_sim_agent/
COPY ../mat_hpc_agent /app/agents/mat_hpc_agent/
COPY ../../matwau /app/matwau/

# 装依赖(mock 版本不需 pymatgen / XRD SDK)
# Stage 2 切真版本时加:pymatgen==2024.3.1 + XRD 仪器 SDK
RUN pip install --no-cache-dir \
    pyyaml \
    pytest \
    pydantic

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import sys; sys.path.insert(0, '/app'); \
                    from agents.mat_exp_agent.mat_exp_agent import MatExpAgent; \
                    a = MatExpAgent(); assert a.name == 'mat-exp-agent'" \
    || exit 1

# 默认启动 mock agent CLI(Stage 2 接 wau-python-sdk 的 WauClient 启动)
CMD ["python3", "-m", "agents.mat_exp_agent.mat_exp_agent"]

LABEL org.opencontainers.image.title="mat-exp-agent" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.description="MatWAU mat-exp agent — XRD + sintering recipe planner (mock stage)"