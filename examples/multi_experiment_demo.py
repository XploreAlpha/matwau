"""multi_experiment_demo.py — W31 Stage 3 JARVIS 雏形演示

跑 3 个实验并行:
  - Inconel 718(metal, 4 步 synth+xrd+em+dsc)
  - PMMA(polymer, 2 步 synth+dsc)
  - TiO2(ceramic, 3 步 synth+xrd+dsc,W31 NEW)

每个实验跑完接 mat-critic-agent(L4 cross-validation per W30),
聚合 BatchWorkflowResult。

用法:
    cd /home/inamoto888/project/matwau
    python3 examples/multi_experiment_demo.py

输出:
    3 实验并行 → 每个 verdict → overall verdict → L4 详情
"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许直接 python3 examples/multi_experiment_demo.py
_EXAMPLE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _EXAMPLE_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_orchestrator import (
    MatOrchestrator,
    get_multi_experiment_default_batch,
)


def main():
    """跑 W31 多实验并行 demo"""
    print("🚀 MatWAU W31 Stage 3 JARVIS Demo — 3 实验并行\n")
    print("=" * 60)

    # 1. 创建 orchestrator
    orch = MatOrchestrator()

    # 2. 准备默认批次(Inconel 718 + PMMA + TiO2)
    experiments = get_multi_experiment_default_batch()

    print("\n📋 默认批次(覆盖 3 个 material domain):")
    for i, t in enumerate(experiments, 1):
        print(f"   {i}. {t.target_sample}({t.domain},{len(t.robot_steps)} robot steps)")

    print("\n⚙️  并行模式:ThreadPoolExecutor max_workers=3")
    print("\n⏳ 跑 3 个实验并行 + critic L4 复核...")

    # 3. 跑 run_batch
    batch = orch.run_batch(experiments, parallel=True, max_workers=3)

    # 4. 打印结果
    print(f"\n{'=' * 60}")
    print("📊 BatchWorkflowResult")
    print(f"{'=' * 60}")
    print(f"  N total : {batch.n_total}")
    print(f"  N passed: {batch.n_passed}")
    print(f"  N warned: {batch.n_warned}")
    print(f"  N failed: {batch.n_failed}")
    print(f"  N blocked: {batch.n_blocked}")
    print(f"  Overall verdict: {batch.overall_verdict.upper()}")
    print(f"  Total cost: ¥{batch.total_cost_cny:.0f}")
    print(f"  Total duration: {batch.total_duration_seconds:.2f}s")
    print(f"  Parallel: {batch.parallel}, max_workers={batch.max_workers}")

    print("\n📦 Per-experiment 详情:")
    for r in batch.experiment_results:
        print(f"\n  - {r.target_sample}:")
        print(f"    verdict: {r.verdict.upper()}")
        print(f"    cost: ¥{r.cost_cny:.0f}")
        print(f"    duration: {r.duration_seconds:.2f}s")
        print(f"    experiment_id: {r.experiment_id}")
        if r.error:
            print(f"    error: {r.error}")

        # Critic L4 详情(per W30)
        if r.critic_verdict:
            cv = r.critic_verdict
            cross = cv.cross_robot
            print(f"    critic L1={cv.l1.score:.2f} L2={cv.l2.score:.2f} L3={cv.l3.score:.2f} L4={cross.score:.2f}")
            print(f"    L4 consistent: {cross.consistent}")
            if cross.rules_passed:
                print(f"    L4 rules passed: {cross.rules_passed}")
            if cross.rules_failed:
                print(f"    L4 rules failed: {cross.rules_failed}")
            if cv.failures:
                codes = [f.code for f in cv.failures]
                print(f"    failures: {codes[:3]}")

    # 5. 最终判定
    print(f"\n{'=' * 60}")
    if batch.all_passed():
        print(f"🎉 All {batch.n_total} experiments PASSED!")
    elif batch.overall_verdict == "warn":
        print(f"⚠️ {batch.n_warned} experiment WARNED — 需复核")
    else:
        print(f"❌ {batch.n_failed} experiment FAILED — {batch.failed_samples()}")

    return batch


if __name__ == "__main__":
    main()