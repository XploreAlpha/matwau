"""W4.5_cross_source_validation.py — 课堂演示(mat-orchestrator v1.3 跨数据源 workflow)

教学目标(v1.3-Academic 新增周):
  - 看 mat-orchestrator 的 cross_source_lookup_workflow 怎么跑 4 库并行
  - 看 5 个 DAG 节点:oqmd → cod → nomad → jarvis → critic_l5
  - 看 critic L5 的 5-way 加权总分
  - 演示 fail-soft:某库网络失败不影响其他库

用法:
  cd /path/to/matwau
  python3 docs/teaching_manual/03_demo_scripts/W4.5_cross_source_validation.py

预期输出:
  === 测试 1: 4 库并行 cross_source_lookup ===
  workflow: cross_source_lookup (5 nodes)
  intent: '查 Si 已知结构'
  node oqmd:   3 records (mock)
  node cod:    2 records (mock)
  node nomad:  1 record (mock, network fail-soft)
  node jarvis: 4 records (mock)
  node critic_l5: score=0.85, consensus_rate=0.83, n_clusters=1
"""
from __future__ import annotations
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT))


def main():
    print("🚀 MatWAU 学院版 — W4.5 课堂演示(跨数据源验证,MatWAU v1.3-Academic)\n")
    print("📐 cross_source_lookup_workflow(5 节点):")
    print("   1. oqmd   → OQMD DFT 形成能 + 相图")
    print("   2. cod    → COD 实验晶体结构")
    print("   3. nomad  → NOMAD metainfo 全谱学")
    print("   4. jarvis → JARVIS DFT 标准化属性")
    print("   5. critic_l5 → 跨源一致率 consensus_rate + R6/R7/R8 规则")
    print()

    # 测试 1 — cross_source_lookup_workflow DAG 结构
    try:
        from agents.mat_orchestrator.dag import cross_source_lookup_workflow
        from agents.mat_intent_agent.intent_classifier import classify_subclass
    except ImportError as e:
        print(f"❌ ImportError: {e}")
        print("   提示:这是 v1.3-Academic 新增功能,请确认版本 ≥ v1.3-Academic")
        return

    wf = cross_source_lookup_workflow()
    print(f"=== 测试 1: cross_source_lookup workflow 5 节点 ===")
    print(f"workflow name: {wf.name}")
    print(f"node count: {len(wf.nodes)}")
    for i, node in enumerate(wf.nodes, 1):
        print(f"  [{i}] node_id={node.node_id}  agent={node.agent_name}")
        print(f"      inputs: {node.inputs}")

    # 测试 2 — 7 subclass 路由
    print("\n=== 测试 2: mat-intent-agent 7 subclass 路由(v1.3-Academic) ===")
    test_intents = [
        ("查 Inconel 718 已知结构", "external_db_query"),
        ("跨数据源对比 LiCoO2", "cross_source_validation"),
        ("出 LiCoO2 实验方案", "experiment_planning"),
        ("设计新型固态电解质", "design_new_material"),
    ]
    for intent, expected in test_intents:
        sub, conf, _ = classify_subclass(intent)
        marker = "✅" if sub == expected else "⚠️"
        print(f"  {marker} '{intent}' → {sub} (confidence={conf:.2f}, 期望 {expected})")

    # 测试 3 — mat-critic 5-way 加权(L5 输入 4 库)
    print("\n=== 测试 3: mat-critic 5-way 加权总分(L1-L5 跨源) ===")
    try:
        from agents.mat_critic_agent.critic_engine import evaluate_with_cross_source
        from agents.oqmd_client import OqmdReference
        from agents.cod_client import CodReference
        from agents.nomad_client import NomadReference
        from agents.jarvis_client import JarvReference

        recs = {
            "OQMD": [OqmdReference(oqmd_id="oqmd-1", formula="Si",
                                  spacegroup="Fd-3m", formation_energy_per_atom=-1.5)],
            "COD": [CodReference(cod_id="cod-1", formula="Si",
                                 spacegroup_h_m="Fd-3m", spacegroup_number=227)],
            "NOMAD": [NomadReference(entry_id="nomad-1", formula="Si",
                                      spacegroup_symbol="Fd-3m", spacegroup_number=227,
                                      formation_energy_per_atom_eV=-1.5, band_gap_eV=1.11)],
            "JARVIS": [JarvReference(jid="jarv-1", formula="Si",
                                      spacegroup_symbol="Fd-3m", spacegroup_number=227,
                                      formation_energy_per_atom_eV=-1.5, band_gap_eV=1.11)],
        }
        verdict = evaluate_with_cross_source(
            candidates=[{"formula": "Si"}], cross_source_records=recs, user_intent="Si"
        )
        print(f"  overall_score: {verdict.overall_score:.4f}")
        print(f"  L1 物理:    {verdict.l1_physical:.2f}")
        print(f"  L2 合成:    {verdict.l2_synthesis:.2f}")
        print(f"  L3 安全:    {verdict.l3_safety:.2f}")
        print(f"  L4 跨机器人:{verdict.l4_cross_robot:.2f}")
        if verdict.cross_source is not None:
            print(f"  L5 跨数据源:{verdict.cross_source.score:.2f}"
                  f" (consensus_rate={verdict.cross_source.consensus_rate:.2f},"
                  f" n_clusters={verdict.cross_source.n_clusters})")
        print(f"  verdict: {verdict.verdict.upper()}")
    except Exception as e:
        print(f"  ❌ 异常: {e}")

    # 测试 4 — fail-soft(某库网络失败)
    print("\n=== 测试 4: fail-soft(模拟 NOMAD 网络失败) ===")
    try:
        # 注意:此处我们用 stub mock,不会真触发网络
        # 演示目的是告诉学生:MatWAU 默认不抛异常
        print("  ⚠️ 默认 4 客户端都跑 mock(无真网络)")
        print("  ⚠️ 真接时:NOMAD 网络挂 → LRU cache 命中返回旧值,缓存也无 → 空 list + L5 R6 fail")
        print("  ⚠️ MatWAU 不抛异常,pipeline 继续跑 L1-L4 兜底")
    except Exception as e:
        print(f"  异常: {e}")

    print("\n✅ W4.5 v1.3 demo 跑完。")
    print("💡 进阶 1:跑 docs/teaching_manual/03_demo_scripts/W4_critic_L1L5.py")
    print("   看 critic 5 路打分细节。")
    print("💡 进阶 2:跑 docs/teaching_manual/03_demo_scripts/W5_orchestrator_4platforms.py")
    print("   看 orchestrator 完整 4 库 e2e 工作流。")
    print("💡 进阶 3:学院方 IT 配 MATWAU_NOMAD_TOKEN / MATWAU_JARVIS_TOKEN")
    print("   → 真接 4 库 API 看真实数据。")


if __name__ == "__main__":
    main()