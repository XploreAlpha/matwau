"""mat-data-lineage-agent — 材料科学数据血缘追踪员

Stage 1: 纯 in-memory dict(LineageStore)
Stage 2: 接 wau-store SDK(wau-lineage 仓 Go 服务)

能力:
1. 记录 1 条 LineageRecord(run_id + parent + agent + hash + timestamp)
2. 查询 ancestors / descendants / tree
3. 导出 JSON(给 wau-store 持久化)

per MatWAU-开发计划 §七 W14
"""
from .lineage_engine import (
    LineageRecord,
    LineageStore,
    LineageTree,
    build_lineage_tree,
    get_global_store,
    hash_data,
    reset_global_store,
    summarize_artifacts,
)
from .mat_data_lineage_agent import (
    LineageConfig,
    MatDataLineageAgent,
    create_default_agent,
)

__all__ = [
    "MatDataLineageAgent",
    "LineageConfig",
    "LineageRecord",
    "LineageStore",
    "LineageTree",
    "create_default_agent",
    "build_lineage_tree",
    "get_global_store",
    "hash_data",
    "reset_global_store",
    "summarize_artifacts",
]