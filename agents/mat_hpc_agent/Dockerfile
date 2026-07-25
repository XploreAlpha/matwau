# mat-hpc-agent Dockerfile
# Stage 1 mock 版本,Stage 2 切真 Slurm + VASP + 超算对接
#
# 构建:docker build -t mat-hpc:0.1.0 -f Dockerfile .
# 运行:docker run -p 18804:18804 mat-hpc:0.1.0

FROM python:3.11-slim

WORKDIR /app

# 系统依赖(Stage 2 需要 ssh client + VASP module)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# 复制 agent 代码 + 上游依赖(mat-gen + mat-sim)
COPY . /app/agents/mat-hpc-agent/
COPY ../mat_gen_agent /app/agents/mat_gen_agent/
COPY ../mat_sim_agent /app/agents/mat_sim_agent/
COPY ../../matwau /app/matwau/

# 装依赖(mock 版本不需 torch / ase / chgnet)
# Stage 2 切真版本时加:ase==3.22.0 + pymatgen==2024.3.1 + ssh 配置
RUN pip install --no-cache-dir \
    pyyaml \
    pytest \
    pydantic

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import sys; sys.path.insert(0, '/app'); \
                    from agents.mat_hpc_agent.mat_hpc_agent import MatHpcAgent; \
                    a = MatHpcAgent(); assert a.name == 'mat-hpc-agent'" \
    || exit 1

# 默认启动 mock agent CLI(Stage 2 接 wau-python-sdk 的 WauClient 启动)
CMD ["python3", "-m", "agents.mat_hpc_agent.mat_hpc_agent"]

LABEL org.opencontainers.image.title="mat-hpc-agent" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.description="MatWAU mat-hpc agent — VASP HPC submission via Slurm (mock stage)"