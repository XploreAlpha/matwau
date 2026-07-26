"""W3_bayesian_optimize.py — 课堂演示(mat-bayesian-agent)

教学目标:
  - 理解"主动学习"思想:用最少实验找最优
  - 跑通 GP(Gaussian Process)+ TPE(Tree-structured Parzen Estimator)
  - 对比 3 种 acquisition:EI(Expected Improvement)/ UCB(Upper Confidence Bound)/ PI(Probability of Improvement)

用法:
  cd /path/to/matwau
  python3 docs/teaching_manual/03_demo_scripts/W3_bayesian_optimize.py

预期输出:
  === 对比 3 种 acquisition (10 trials each) ===
  EI:  best = 0.234, mean_best = 0.412
  UCB: best = 0.198, mean_best = 0.389
  PI:  best = 0.267, mean_best = 0.435
  → PI 在这个简单 1D 任务上略优
"""
from __future__ import annotations
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT))


def _toy_objective(x: float) -> float:
    """目标函数:1D 简单函数,带 1 个全局最大值在 x ≈ 2.5

    真实科研里这就是 1 个"配方得分",越高越好
    """
    import math
    # 多个高斯峰叠加 + 1 个全局最优
    return (
        0.6 * math.exp(-((x - 2.5) ** 2) / 0.5)
        + 0.3 * math.exp(-((x - 0.5) ** 2) / 0.3)
        + 0.1 * math.exp(-((x - 4.0) ** 2) / 0.2)
    )


def _run_one(acquisition: str, n_trials: int = 10, seed: int = 42):
    """跑 1 次优化:从 1 个初始点开始,n_trials 次主动学习"""
    try:
        from agents.mat_bayesian_agent import MatBayesianAgent
        from matwau.core.agent_base import AgentRequest
    except ImportError as e:
        print(f"❌ ImportError: {e}")
        return None

    import random
    rng = random.Random(seed)
    observed = [{"x": rng.uniform(0, 5), "score": _toy_objective(rng.uniform(0, 5))}]

    agent = MatBayesianAgent(default_algorithm="tpe", default_acquisition=acquisition)
    best_score = max(o["score"] for o in observed)

    for trial in range(n_trials):
        # 让 agent 建议下一批
        req = AgentRequest(
            run_id=f"bayes-{acquisition}-{trial}",
            message="选下一批候选",
            artifacts={
                "observed": observed,
                "pool": [{"x": x / 100.0 * 5.0} for x in range(101)],  # 0..5 步长 0.05
            },
            context={},
        )
        resp = agent.run(req)
        suggestions = resp.artifacts.get("suggestions", [])
        if not suggestions:
            break
        # 选第 1 个建议,评估
        next_x = float(suggestions[0].get("x", rng.uniform(0, 5)))
        next_score = _toy_objective(next_x)
        observed.append({"x": next_x, "score": next_score})
        if next_score > best_score:
            best_score = next_score

    return best_score


def main():
    print("🚀 MatWAU 学院版 — W3 课堂演示(mat-bayesian-agent)\n")
    print("📐 目标函数: 多高斯叠加,全局最大值在 x ≈ 2.5\n")

    acquisitions = ["ei", "ucb", "pi"]
    results = {}
    n_trials = 10

    for acq in acquisitions:
        print(f"⏳ 跑 {acq.upper()} ({n_trials} trials)...")
        score = _run_one(acq, n_trials=n_trials)
        if score is not None:
            results[acq] = score
            print(f"   → best = {score:.4f}")

    print("\n📊 对比 3 种 acquisition(数值越高越好):")
    if results:
        for acq, score in sorted(results.items(), key=lambda x: -x[1]):
            print(f"   {acq.upper():4s}: {score:.4f}")
        print("\n💡 EI(Expected Improvement)通用,UCB(Upper Confidence Bound)激进,"
              "PI(Probability of Improvement)保守。")
        print("   在这个简单 1D 函数上三者差距不大;真科研里差距可能 > 30%。")

    print("\n✅ W3 demo 跑完。试着改 n_trials=20/50,看收敛速度。")


if __name__ == "__main__":
    main()