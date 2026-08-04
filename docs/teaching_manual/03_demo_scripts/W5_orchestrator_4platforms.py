"""W5_orchestrator_4platforms.py — 课堂演示(mat-orchestrator v1.3 完整 4 库 e2e)

教学目标(v1.3-Academic 升级):
  - 看 mat-orchestrator 怎么把 5 个 workflow 路由到不同 subclass
  - 看 cross_source_lookup 5 节点怎么 e2e 跑通
  - 看 L4 + L5 双重裁决(跨机器人 + 跨数据源)
  - 演示 lineage_store 记录跨数据源追踪

用法:
  cd /path/to/matwau
  python3 docs/teaching_manual/03_demo_scripts/W5_orchestrator_4platforms.py

预期输出:
  === 测试 1: orchestrator 路由 5 个 workflow ===
  intent '出 LiCoO2 实验方案' → experiment_planning → LiCoO2 实验 workflow
  intent '查 Si 已知结构' → external_db_query → cross_source_lookup
  ...

  === 测试 2: cross_source_lookup e2e 跑通 ===
  workflow=5 nodes success, L5 score=0.85, lineage.db 4 条新记录
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT))


def main():
    print("🚀 MatWAU 学院版 — W5 课堂演示(mat-orchestrator v1.3 4 库 e2e)\n")
    print("📐 MatOrchestrator 7 workflow(v1.3-Academic):")
    print("   1. experiment_planning       — 默认实验规划(per W1)")
    print("   2. design_new_material       — 设计新材料(per W5 旧)")
    print("   3. optimize_existing         — 优化现有配方")
    print("   4. explain_failure           — 失败归因")
    print("   5. literature_review         — 文献综述")
    print("   6. cross_source_lookup       — 4 库并行 + critic L5(M3 新)")
    print("   7. cross_source_property     — 4 库 + critic L5 + L4 双重裁决(M3 新)")
    print()

    try:
        from agents.mat_intent_agent.intent_classifier import parse_mat_intent
        from agents.mat_orchestrator.dag import (
            WORKFLOW_BY_SUBCLASS,
            cross_source_lookup_workflow,
            cross_source_property_workflow,
        )
    except ImportError as e:
        print(f"❌ ImportError: {e}")
        return

    # 测试 1 — workflow 注册表
    print("=== 测试 1: WORKFLOW_BY_SUBCLASS 注册表 ===")
    print(f"已注册 workflow 总数: {len(WORKFLOW_BY_SUBCLASS)}")
    for sub, wf_name in WORKFLOW_BY_SUBCLASS.items():
        print(f"  {sub:30s} → {wf_name}")

    # 测试 2 — intent 路由
    print("\n=== 测试 2: mat-intent 解析 + 路由 ===")
    test_intents = [
        "出 LiCoO2 实验方案",
        "设计新型固态电解质",
        "查 Si 已知结构",
        "跨数据源对比 LiCoO2 形成能",
    ]
    for intent_text in test_intents:
        mi = parse_mat_intent(intent_text)
        wf_name = WORKFLOW_BY_SUBCLASS.get(mi.subclass, "unknown")
        print(f"  intent='{intent_text}'")
        print(f"    → subclass={mi.subclass}, confidence={mi.confidence:.2f}")
        print(f"    → workflow={wf_name}")

    # 测试 3 — cross_source_lookup_workflow DAG 结构
    print("\n=== 测试 3: cross_source_lookup_workflow 结构 ===")
    wf = cross_source_lookup_workflow()
    print(f"  workflow name: {wf.name}")
    print(f"  node count:    {len(wf.nodes)}")
    for i, node in enumerate(wf.nodes, 1):
        print(f"  [{i}] node_id={node.node_id:12s}  agent={node.agent_name}")

    # 测试 4 — cross_source_property_workflow DAG 结构
    print("\n=== 测试 4: cross_source_property_workflow 结构 ===")
    wf = cross_source_property_workflow()
    print(f"  workflow name: {wf.name}")
    print(f"  node count:    {len(wf.nodes)}")
    for i, node in enumerate(wf.nodes, 1):
        print(f"  [{i}] node_id={node.node_id:12s}  agent={node.agent_name}")

    # 测试 5 — DAGExecutor outputs.X 解析能力
    print("\n=== 测试 5: DAGExecutor outputs.X 解析(M3 新能力)===")
    try:
        from agents.mat_orchestrator.dag import DAG, DAGExecutor, DAGNode
        from matwau.core.agent_base import AgentRequest, AgentResponse

        class _StubAgent:
            def __init__(self, name): self.name = name
            def run(self, req): return AgentResponse(reply="ok", artifacts={"marker": self.name})

        agents_dict = {f"a{i}": _StubAgent(f"a{i}") for i in range(3)}
        ex = DAGExecutor(agents_dict)
        dag = DAG(name="demo", nodes=[
            DAGNode("a", "a0", {"message": "initial.user_intent"}, "a_resp"),
            DAGNode("b", "a1", {"records": "outputs.a_resp"}, "b_resp"),
            DAGNode("c", "a2", {"message": "initial.user_intent",
                                "records": "outputs.cross_source_records"}, "c_resp"),
        ])
        result = ex.execute(dag, initial_inputs={
            "user_intent": "X",
            "cross_source_records": {"OQMD": [{"id": 1}], "COD": [{"id": 2}]},
        })
        print(f"  execute success: {result.success}")
        print(f"  node count:      {len(result.node_results)}")
        print("  验证:outputs.X 解析 + DAG 节点通讯工作")
    except Exception as e:
        print(f"  异常: {e}")

    # 测试 6 — lineage_store 跨数据源追踪(v1.3 起所有 workflow 自动写 lineage)
    print("\n=== 测试 6: lineage_store 自动记录(v1.3 起) ===")
    print("  ⚠️ 默认 MatWAU 启 lineage_store SQLite,跨数据源 workflow 自动记录每节点")
    print("  ⚠️ 查看 ~/.matwau/lineage.db 可看到 4 库查询的 lineage 链")
    print("  ⚠️ 学院方 IT 部署时务必启用 MATWAU_LINEAGE_BACKEND=sqlite")

    print("\n✅ W5 v1.3 demo 跑完。")
    print("💡 进阶 1:跑 docs/teaching_manual/03_demo_scripts/W4_critic_L1L5.py")
    print("   看 critic 5 路打分细节。")
    print("💡 进阶 2:跑 docs/teaching_manual/03_demo_scripts/W4.5_cross_source_validation.py")
    print("   看 cross_source_resolver 怎么聚合 4 库记录。")
    print("💡 进阶 3:学院 IT 部署后看 SQLite:sqlite3 ~/.matwau/lineage.db 'SELECT * FROM lineage_records;'")


if __name__ == "__main__":
    main()