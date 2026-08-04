"""W4_critic_L1L5.py — 课堂演示(mat-critic-agent v1.3)

教学目标(v1.3-Academic 升级):
  - 理解 critic 的"5 路打分"模型:L1 物理 / L2 合成 / L3 安全 / L4 跨机器人 / L5 跨数据源
  - 看 5-way 加权总分:0.27/0.27/0.18/0.18/0.10
  - 故意制造 1 个 L5 fail 场景(consensus_rate 低)

用法:
  cd /path/to/matwau
  python3 docs/teaching_manual/03_demo_scripts/W4_critic_L1L5.py

预期输出:
  === 测试 1: pass 候选 ===
  verdict: pass, overall = 0.85
  L1 物理: 0.90 | L2 合成: 0.80 | L3 安全: 0.90 | L4 跨机器人: 0.70 | L5 跨源: 0.75

  === 测试 2: 含 Co 候选(L3 安全 fail)===
  verdict: fail, overall = 0.45
  ...

  === 测试 3: L5 跨源 fail(4 库不一致)===
  verdict: fail, overall = 0.40
  L5 cross_source_consensus_rate < 0.5
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT))


def _make_candidate(formula: str, energy: float, stable: str, conf: float):
    """造 1 个 mat-sim-agent 候选"""
    from agents.mat_sim_agent.mat_sim_agent import SimCandidate
    return SimCandidate(
        formula=formula, cif=f"data_{formula}\n",
        relaxed_energy=energy, forces_max=0.02,
        relaxation_converged=True, stability=stable, confidence=conf,
    )


def _make_cross_source_records(formula: str, consistent: bool):
    """造 4 库 cross_source_records(consensus 一致/不一致)"""
    from agents.cod_client import CodReference
    from agents.jarvis_client import JarvReference
    from agents.nomad_client import NomadReference
    from agents.oqmd_client import OqmdReference

    if consistent:
        # 4 库一致:Si, Fd-3m, -1.5 eV/atom, 1.11 eV gap
        return {
            "OQMD": [OqmdReference(oqmd_id=f"oqmd-{formula}", formula=formula, spacegroup="Fd-3m",
                                   formation_energy_per_atom=-1.5)],
            "COD": [CodReference(cod_id=f"cod-{formula}", formula=formula,
                                 spacegroup_h_m="Fd-3m", spacegroup_number=227)],
            "NOMAD": [NomadReference(entry_id=f"nomad-{formula}", formula=formula,
                                      spacegroup_symbol="Fd-3m", spacegroup_number=227,
                                      formation_energy_per_atom_eV=-1.5, band_gap_eV=1.11)],
            "JARVIS": [JarvReference(jid=f"jarv-{formula}", formula=formula,
                                      spacegroup_symbol="Fd-3m", spacegroup_number=227,
                                      formation_energy_per_atom_eV=-1.5, band_gap_eV=1.11)],
        }
    else:
        # 4 库严重不一致:形成能偏差 5 eV
        return {
            "OQMD": [OqmdReference(oqmd_id=f"oqmd-{formula}", formula=formula, spacegroup="Fd-3m",
                                   formation_energy_per_atom=-1.0)],
            "COD": [],  # COD 缺失
            "NOMAD": [NomadReference(entry_id=f"nomad-{formula}", formula=formula,
                                      spacegroup_symbol="P6_3/mmc",  # 不同晶系!
                                      spacegroup_number=194,
                                      formation_energy_per_atom_eV=-5.0, band_gap_eV=0.0)],
            "JARVIS": [JarvReference(jid=f"jarv-{formula}", formula=formula,
                                      spacegroup_symbol="Fd-3m", spacegroup_number=227,
                                      formation_energy_per_atom_eV=-1.5, band_gap_eV=1.11)],
        }


def _run_critic(label: str, candidates, message: str, cross_source=None):
    print(f"\n=== {label} ===")
    print(f"📝 {message}\n")

    try:
        from agents.mat_critic_agent import MatCriticAgent
        from matwau.core.agent_base import AgentRequest
    except ImportError as e:
        print(f"❌ ImportError: {e}")
        return

    agent = MatCriticAgent()  # 默认 enable_llm_review=False
    artifacts = {"candidates": candidates}
    if cross_source is not None:
        artifacts["cross_source_records"] = cross_source
    req = AgentRequest(
        run_id=f"w4-{label}",
        message=message,
        artifacts=artifacts,
        context={},
    )
    resp = agent.run(req)

    print(f"🤖 reply:\n{resp.reply}\n")

    verdict = resp.artifacts.get("verdict")
    if verdict is not None:
        print(f"📊 verdict: {verdict.verdict.upper()}")
        print(f"   ├ overall_score: {verdict.overall_score:.4f}")
        if hasattr(verdict, "l1_physical"):
            print(f"   ├ L1 物理:        {verdict.l1_physical:.2f}")
            print(f"   ├ L2 合成:        {verdict.l2_synthesis:.2f}")
            print(f"   ├ L3 安全:        {verdict.l3_safety:.2f}")
        if hasattr(verdict, "l4_cross_robot"):
            print(f"   ├ L4 跨机器人:    {verdict.l4_cross_robot:.2f}")
        if hasattr(verdict, "l5_cross_source_score"):
            print(f"   └ L5 跨数据源:    {verdict.l5_cross_source_score:.2f}"
                  f"  (consensus_rate={verdict.l5_cross_source_consensus_rate:.2f})")


def main():
    print("🚀 MatWAU 学院版 — W4 课堂演示(mat-critic-agent v1.3,5 路打分)\n")
    print("📐 Critic 5 路打分(per MatWAU v1.3-Academic):")
    print("   L1 物理一致性(Lattice + Energy + Bragg)        权重 0.27")
    print("   L2 实验可行性(成本 + 设备可达)                  权重 0.27")
    print("   L3 安全规则(Co / Be / 放射性限制)               权重 0.18")
    print("   L4 跨机器人一致性(同一材料不同表征结果不矛盾)    权重 0.18")
    print("   L5 跨数据源一致性(OQMD/COD/NOMAD/JARVIS)        权重 0.10")
    print()

    # 测试 1 — pass 候选(无 Co + 4 库一致)
    _run_critic(
        "测试 1: pass 候选(LiFePO4,稳定 + 无毒 + 4 库一致)",
        candidates=[_make_candidate("LiFePO4", -3.4, "stable", 0.9)],
        message="评估 LiFePO4 候选",
        cross_source=_make_cross_source_records("LiFePO4", consistent=True),
    )

    # 测试 2 — 含 Co 候选(安全规则应 fail)
    _run_critic(
        "测试 2: 含 Co 候选(故意触发 L3 安全 fail)",
        candidates=[_make_candidate("LiCoO2", -3.5, "stable", 0.9)],
        message='用户约束: no Co。请评估 LiCoO2。',
    )

    # 测试 3 — L5 跨源不一致
    _run_critic(
        "测试 3: L5 跨源 fail(故意制造 4 库不一致:晶系 + 形成能 + 带隙偏差)",
        candidates=[_make_candidate("Si_unknown", -2.0, "stable", 0.9)],
        message="评估 Si 候选(4 库不一致)",
        cross_source=_make_cross_source_records("Si_unknown", consistent=False),
    )

    # 测试 4 — L4 跨机器人不一致(回归测试,L4 行为不变)
    _run_critic(
        "测试 4: L4 跨机器人不一致(回归测试,与 v1.1 行为一致)",
        candidates=[
            _make_candidate("Inconel_718_phase_A", -3.2, "stable", 0.9),
            _make_candidate("Inconel_718_phase_B", -3.5, "stable", 0.9),
        ],
        message="评估 Inconel 718 跨机器人一致性",
    )

    print("\n✅ W4 v1.3 demo 跑完。")
    print("💡 进阶 1:把 MatCriticAgent() 改成 MatCriticAgent(enable_llm_review=True),")
    print("   看 LLM 复核建议(需配 MATWAU_LLM_API_KEY)。")
    print("💡 进阶 2:把 cross_source 改成 4 库全一致 → 看 L5 score 升到 1.0。")
    print("💡 进阶 3:跑 docs/teaching_manual/03_demo_scripts/W4.5_cross_source_validation.py")
    print("   演示 4 库并行 orchestrator workflow。")


if __name__ == "__main__":
    main()