"""mat-data-lineage-agent — 材料科学数据血缘追踪员(per dev plan §七 W14)

Stage 1 / Phase 1:纯 in-memory 存储
Stage 2(WAU v1.0.0 GA 后):接 wau-store SDK(wau-lineage 仓 Go 服务)

业务流程(per act() 实现):
1. 从 req.artifacts 抽 input/output + run_id
2. 加 1 条 LineageRecord 到 store
3. 可选查询 ancestors/descendants(per query)
4. 返回 LineageRecord + 血缘树

用法:
    from agents.mat_data_lineage_agent.mat_data_lineage_agent import MatDataLineageAgent
    from matwau.core.agent_base import AgentRequest

    agent = MatDataLineageAgent()

    # 记录 1 次 run
    req1 = AgentRequest(
        run_id="gen-001",
        message="记录 mat-gen 跑 run-001",
        artifacts={
            "input_artifacts": {"message": "design new"},
            "output_artifacts": {"candidates": [...]},
            "agent_name": "mat-gen-agent",
        },
    )
    r1 = agent.run(req1)

    # 查询血缘树
    req2 = AgentRequest(
        run_id="query-001",
        message="查 run-001 的血缘",
        artifacts={"query_type": "ancestors", "target_run_id": "run-001"},
    )
    r2 = agent.run(req2)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 允许直接 python3 -m 运行本文件
_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import (
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)
from matwau.harness.context_manager import ContextManager
from matwau.harness.safety_guard import SafetyGuard

from .lineage_engine import (
    LineageStore,
    build_lineage_tree,
    get_global_store,
    reset_global_store,
)

# ============================================================================
# 配置 + 辅助
# ============================================================================


@dataclass
class LineageConfig:
    """用户配置(per AgentRequest.context)"""

    use_global_store: bool = True       # True = 用全局 store(Stage 1)
    query_type: str = "record"          # record / ancestors / descendants / tree

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> LineageConfig:
        if not d:
            return cls()
        return cls(
            use_global_store=d.get("use_global_store", True),
            query_type=d.get("query_type", "record"),
        )


# ============================================================================
# MatDataLineageAgent 主体
# ============================================================================


class MatDataLineageAgent(MatWAUAgentBase):
    """mat-data-lineage-agent — 数据血缘追踪员

    业务流程:
    1. 2 种模式:
       a. 记录模式(artifacts 里有 input/output/agent_name):加 1 条 record
       b. 查询模式(artifacts 里有 query_type + target_run_id):查 store
    2. 返回 LineageRecord / 血缘树
    """

    name = "mat-data-lineage-agent"

    def __init__(
        self,
        *,
        store: LineageStore | None = None,
        cost_per_call: float = 0.001,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.store = store
        self.cost_per_call = cost_per_call

        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return """你是材料科学数据血缘追踪员 agent(mat-data-lineage-agent),记录 + 查询实验数据血缘。

能力:
1. 记录模式:从 artifacts 抽 input/output/agent_name → 加 1 条 LineageRecord
2. 查询模式:从 artifacts 抽 query_type(target_run_id) → 查 store
3. 4 种 query_type:record(单条)/ ancestors(上游)/ descendants(下游)/ tree(完整树)
4. Stage 1:纯 in-memory dict;Stage 2:接 wau-store SDK

数据结构:
- LineageRecord:lineage_id + run_id + parent_run_id + agent_name + input/output_hash + timestamp
- LineageStore:records dict + by_run index + by_parent index
- LineageTree:root + ancestors_tree + descendants_tree + depth

适用场景:
- 1 个 mat-gen 跑出 5 候选 → 记 1 条 record
- mat-sim 用这 5 候选 → 记 1 条 record + parent_run_id 指向 gen
- 1 周后查:这 5 候选的完整血缘(gen → sim → hpc → exp → critic)

约束:
- 0 行 UI 代码
- 1 次调用 = 1 次 Goldens 跑分(mat-data-lineage.yaml,pass-rate > 50% Stage 1)
"""

    def act(self, ctx: dict[str, Any], tools: list[str]) -> AgentResponse:
        artifacts = ctx.get("_input_artifacts") or {}
        config: LineageConfig = ctx.get("_input_config") or LineageConfig()

        # 1. 选 store
        if config.use_global_store:
            store = self.store or get_global_store()
        else:
            if self.store is None:
                self.store = LineageStore()
            store = self.store

        # 2. 选模式
        query_type = artifacts.get("query_type", "record")

        if query_type == "record":
            return self._record_mode(store, artifacts, config)
        elif query_type in ("ancestors", "descendants", "tree"):
            return self._query_mode(store, artifacts, query_type, config)
        else:
            return self._error_response(f"未知 query_type: {query_type}")

    def perceive(self, req: AgentRequest) -> dict[str, Any]:
        ctx = super().perceive(req)
        ctx["user_message"] = req.message
        ctx["_input_config"] = LineageConfig.from_dict(req.context)
        ctx["_input_artifacts"] = req.artifacts or {}
        return ctx

    # ========================================================================
    # 内部 helper
    # ========================================================================

    def _record_mode(
        self,
        store: LineageStore,
        artifacts: dict[str, Any],
        config: LineageConfig,
    ) -> AgentResponse:
        """记录模式:加 1 条 record"""
        run_id = artifacts.get("run_id") or f"auto-{store.size() + 1}"
        agent_name = artifacts.get("agent_name", "unknown")
        input_artifacts = artifacts.get("input_artifacts", {})
        output_artifacts = artifacts.get("output_artifacts", {})
        parent_run_id = artifacts.get("parent_run_id")
        duration = artifacts.get("duration_seconds", 0.0)
        cost = artifacts.get("cost", 0.0)
        metadata = artifacts.get("metadata", {})

        try:
            record = store.add(
                run_id=run_id,
                agent_name=agent_name,
                input_artifacts=input_artifacts,
                output_artifacts=output_artifacts,
                parent_run_id=parent_run_id,
                duration_seconds=duration,
                cost=cost,
                metadata=metadata,
            )
        except Exception as e:
            return self._error_response(f"记录失败: {e}")

        return AgentResponse(
            reply=f"✅ 已记录 lineage: {run_id} ({agent_name})\n   lineage_id: {record.lineage_id[:8]}...\n   store size: {store.size()}",
            artifacts={
                "record": record,
                "record_dict": record.to_dict(),
                "lineage_id": record.lineage_id,
                "run_id": run_id,
                "store_size": store.size(),
            },
            confidence=0.9,
            cost=self.cost_per_call,
        )

    def _query_mode(
        self,
        store: LineageStore,
        artifacts: dict[str, Any],
        query_type: str,
        config: LineageConfig,
    ) -> AgentResponse:
        """查询模式:ancestors / descendants / tree"""
        target_run_id = artifacts.get("target_run_id") or artifacts.get("run_id")
        if not target_run_id:
            return self._error_response("query 模式需要 target_run_id")

        if query_type == "ancestors":
            records = store.ancestors(target_run_id)
            data = {
                "target_run_id": target_run_id,
                "ancestors": [r.to_dict() for r in records],
                "count": len(records),
            }
            reply = f"📜 ancestors of {target_run_id}: {len(records)} 条"
        elif query_type == "descendants":
            records = store.descendants(target_run_id)
            data = {
                "target_run_id": target_run_id,
                "descendants": [r.to_dict() for r in records],
                "count": len(records),
            }
            reply = f"📜 descendants of {target_run_id}: {len(records)} 条"
        elif query_type == "tree":
            tree = build_lineage_tree(store, target_run_id)
            data = tree.to_dict()
            reply = f"🌳 lineage tree of {target_run_id}: depth={tree.depth}, total={tree.total_nodes}"
        else:
            return self._error_response(f"未知 query_type: {query_type}")

        return AgentResponse(
            reply=reply,
            artifacts={
                "query_type": query_type,
                **data,
            },
            confidence=0.85,
            cost=self.cost_per_call,
        )

    def _empty_response(self, reason: str) -> AgentResponse:
        return AgentResponse(
            reply=f"⚠️ mat-data-lineage: {reason}",
            artifacts={},
            confidence=0.3,
        )

    def _error_response(self, error: str) -> AgentResponse:
        return AgentResponse(
            reply=f"❌ mat-data-lineage 错误: {error}",
            artifacts={},
            confidence=0.1,        # 用 0.1 而非 0.0(避开 agent_base 默认 0.5 覆盖)
            error=error,
        )


def create_default_agent() -> MatDataLineageAgent:
    return MatDataLineageAgent(
        store=get_global_store(),
        cost_per_call=0.001,
    )


# ============================================================================
# CLI 入口
# ============================================================================


if __name__ == "__main__":
    print("🚀 MatDataLineageAgent Demo")
    print("=" * 60)

    # 1. 重置全局 store
    reset_global_store()

    agent = create_default_agent()
    print(f"   {agent}")

    # 2. 记录 3 条(gen → sim → critic)
    print("\n📝 Step 1: 记录 3 条 lineage")
    req1 = AgentRequest(
        run_id="gen-001",
        message="记录 mat-gen",
        artifacts={
            "run_id": "run-001",
            "agent_name": "mat-gen-agent",
            "input_artifacts": {"message": "design new"},
            "output_artifacts": {"candidates": [{"formula": "LiCoO2"}]},
        },
    )
    r1 = agent.run(req1)
    print(r1.reply)

    req2 = AgentRequest(
        run_id="sim-001",
        message="记录 mat-sim",
        artifacts={
            "run_id": "run-002",
            "agent_name": "mat-sim-agent",
            "input_artifacts": {"candidates": [{"formula": "LiCoO2"}]},
            "output_artifacts": {"simulated": [{"formula": "LiCoO2", "relaxed_energy": -3.5}]},
            "parent_run_id": "run-001",
        },
    )
    r2 = agent.run(req2)
    print(r2.reply)

    req3 = AgentRequest(
        run_id="critic-001",
        message="记录 mat-critic",
        artifacts={
            "run_id": "run-003",
            "agent_name": "mat-critic-agent",
            "input_artifacts": {"candidates": [{"formula": "LiCoO2"}]},
            "output_artifacts": {"verdict": "pass"},
            "parent_run_id": "run-002",
        },
    )
    r3 = agent.run(req3)
    print(r3.reply)

    # 3. 查询血缘
    print("\n\n🔍 Step 2: 查 run-003 的 ancestors")
    req4 = AgentRequest(
        run_id="query-001",
        message="查 run-003 的 ancestors",
        artifacts={"query_type": "ancestors", "target_run_id": "run-003"},
    )
    r4 = agent.run(req4)
    print(r4.reply)

    # 4. 查询 tree
    print("\n\n🔍 Step 3: 查 run-002 的 tree")
    req5 = AgentRequest(
        run_id="query-002",
        message="查 run-002 的 tree",
        artifacts={"query_type": "tree", "target_run_id": "run-002"},
    )
    r5 = agent.run(req5)
    print(r5.reply)
    print(f"   artifacts keys: {list(r5.artifacts.keys())}")


__all__ = [
    "LineageConfig",
    "MatDataLineageAgent",
    "create_default_agent",
]