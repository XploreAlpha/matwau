"""W4_critic_L1L4.py — 课堂演示(mat-critic-agent)

教学目标:
  - 理解 critic 的"4 路打分"模型:L1 物理 / L2 合成 / L3 安全 / L4 跨机器人
  - 看 verdict 是怎么由规则打分产生的
  - 故意制造 1 个 fail 场景

用法:
  cd /path/to/matwau
  python3 docs/teaching_manual/03_demo_scripts/W4_critic_L1L4.py

预期输出:
  === 测试 1: pass 候选 ===
  verdict: pass, overall = 0.85
  L1 物理: 0.90 | L2 合成: 0.80 | L3 安全: 0.90 | L4 跨机器人: 0.70

  === 测试 2: 含 Co 候选(故意失败)===
  verdict: fail, overall = 0.45
  ...
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


def _run_critic(label: str, candidates, message: str = "评估候选"):
    print(f"\n=== {label} ===")
    print(f"📝 {message}\n")

    try:
        from agents.mat_critic_agent import MatCriticAgent
        from matwau.core.agent_base import AgentRequest
    except ImportError as e:
        print(f"❌ ImportError: {e}")
        return

    agent = MatCriticAgent()  # 默认 enable_llm_review=False
    req = AgentRequest(
        run_id=f"w4-{label}",
        message=message,
        artifacts={"candidates": candidates},
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
            print(f"   └ L4 跨机器人:    {verdict.l4_cross_robot:.2f}")


def main():
    print("🚀 MatWAU 学院版 — W4 课堂演示(mat-critic-agent)\n")
    print("📐 Critic 4 路打分:")
    print("   L1 物理一致性(Lattice + Energy + Bragg)")
    print("   L2 实验可行性(成本 + 设备可达)")
    print("   L3 安全规则(Co / Be / 放射性限制)")
    print("   L4 跨机器人一致性(同一材料不同表征结果不矛盾)")
    print()

    # 测试 1 — pass 候选(无 Co,稳定)
    _run_critic(
        "测试 1: pass 候选(LiFePO4,稳定 + 无毒)",
        candidates=[
            _make_candidate("LiFePO4", -3.4, "stable", 0.9),
        ],
        message="评估 LiFePO4 候选",
    )

    # 测试 2 — 含 Co 候选(安全规则应 fail)
    _run_critic(
        "测试 2: 含 Co 候选(故意触发 L3 安全 fail)",
        candidates=[
            _make_candidate("LiCoO2", -3.5, "stable", 0.9),
        ],
        message='用户约束: no Co。请评估 LiCoO2。',
    )

    # 测试 3 — L4 跨机器人不一致(2 个结构,声称是同材料)
    _run_critic(
        "测试 3: L4 跨机器人不一致(故意触发)",
        candidates=[
            _make_candidate("Inconel_718_phase_A", -3.2, "stable", 0.9),
            _make_candidate("Inconel_718_phase_B", -3.5, "stable", 0.9),
        ],
        message="评估 Inconel 718 跨机器人一致性",
    )

    print("\n✅ W4 demo 跑完。")
    print("💡 进阶:把 MatCriticAgent() 改成 MatCriticAgent(enable_llm_review=True),")
    print("   看 LLM 复核建议(需配 MATWAU_LLM_API_KEY)。")


if __name__ == "__main__":
    main()