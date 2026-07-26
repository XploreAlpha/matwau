"""W2_xrd_peak_decode.py — 课堂演示(mat-sim-agent + mat-exp-agent)

教学目标:
  - 理解"MLIP 预筛 + XRD 表征"科研流程
  - 跑 mat-sim-agent 算能量(快速试菜)
  - 跑 mat-exp-agent 解 XRD 谱(布拉格定律 2d sinθ = nλ)

用法:
  cd /path/to/matwau
  python3 docs/teaching_manual/03_demo_scripts/W2_xrd_peak_decode.py

预期输出:
  === Step 1: mat-sim-agent 算能量 ===
  LiCoO2 relaxed_energy = -3.5 eV/atom
  ...
  === Step 2: mat-exp-agent 解 XRD ===
  3 个布拉格峰:
    2θ = 18.7° → d = 4.74 Å → (003)
    2θ = 37.9° → d = 2.37 Å → (101)
    2θ = 45.2° → d = 2.00 Å → (104)
  ...
"""
from __future__ import annotations
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT))


def _run_sim():
    print("\n=== Step 1: mat-sim-agent 算能量(快速试菜员)===\n")
    try:
        from agents.mat_sim_agent.mat_sim_agent import MatSimAgent, SimCandidate
        from matwau.core.agent_base import AgentRequest
    except ImportError as e:
        print(f"❌ ImportError: {e}")
        return

    # 模拟 3 个候选(LiCoO2 + 2 个掺杂版)
    candidates = [
        SimCandidate(formula="LiCoO2", cif="data_LiCoO2\n",
                     relaxed_energy=-3.5, forces_max=0.01,
                     relaxation_converged=True, stability="stable", confidence=0.92),
        SimCandidate(formula="LiNiO2", cif="data_LiNiO2\n",
                     relaxed_energy=-3.2, forces_max=0.02,
                     relaxation_converged=True, stability="stable", confidence=0.85),
        SimCandidate(formula="LiMnO2", cif="data_LiMnO2\n",
                     relaxed_energy=-2.9, forces_max=0.05,
                     relaxation_converged=True, stability="metastable", confidence=0.70),
    ]

    agent = MatSimAgent()
    req = AgentRequest(run_id="w2-sim", message="快速预筛 LiMO2 系列", artifacts={"candidates": candidates}, context={})
    resp = agent.run(req)

    print(f"🤖 reply: {resp.reply[:200]}...")
    print(f"\n📊 候选排序(按 relaxed_energy):")
    if "candidates" in resp.artifacts:
        for i, c in enumerate(resp.artifacts["candidates"][:3], 1):
            print(f"  {i}. {c.formula:12s}  E = {c.relaxed_energy:6.2f} eV/atom  stability = {c.stability}")


def _run_xrd():
    print("\n=== Step 2: mat-exp-agent 解 XRD 谱(实验老师)===\n")
    print("📐 布拉格定律: 2d sinθ = nλ")
    print(f"   Cu Kα 波长 λ = 1.5406 Å")
    print()

    try:
        from agents.mat_exp_agent.mat_exp_agent import MatExpAgent
        from matwau.core.agent_base import AgentRequest
    except ImportError as e:
        print(f"❌ ImportError: {e}")
        return

    # 给 1 个 XRD 谱(2θ 角度 + intensity)— 模拟 LiCoO2 主峰
    xrd_data = {
        "wavelength_A": 1.5406,  # Cu Kα
        "peaks": [
            {"two_theta": 18.7, "intensity": 100.0, "hkl": "(003)"},
            {"two_theta": 37.9, "intensity": 45.0, "hkl": "(101)"},
            {"two_theta": 45.2, "intensity": 80.0, "hkl": "(104)"},
            {"two_theta": 59.5, "intensity": 30.0, "hkl": "(107)"},
            {"two_theta": 65.6, "intensity": 35.0, "hkl": "(018)"},
        ],
    }

    agent = MatExpAgent()
    req = AgentRequest(run_id="w2-xrd", message="解 LiCoO2 XRD 谱", artifacts={"xrd_data": xrd_data}, context={})
    resp = agent.run(req)

    print(f"🤖 reply: {resp.reply[:200]}...")
    print(f"\n📊 3 个最强峰(布拉格定律反推 d-spacing):")
    import math
    lam = xrd_data["wavelength_A"]
    for peak in sorted(xrd_data["peaks"], key=lambda p: -p["intensity"])[:3]:
        theta_rad = math.radians(peak["two_theta"] / 2)
        d = lam / (2 * math.sin(theta_rad))
        print(f"   2θ = {peak['two_theta']:5.1f}°  intensity = {peak['intensity']:5.1f}  "
              f"→ d = {d:.3f} Å  →  {peak['hkl']}")

    print(f"\n💡 试着改 wavelength_A 从 1.5406(Cu Kα)→ 0.7107(Mo Kα),看峰位移。")


def main():
    print("🚀 MatWAU 学院版 — W2 课堂演示(sim + exp)\n")
    _run_sim()
    _run_xrd()
    print("\n✅ W2 demo 跑完。")


if __name__ == "__main__":
    main()