"""coordination_demo.py — W27 化学师协调 4 机器人完整演示

Stage 3 钢铁侠 Phase 4 入口 — JARVIS 雏形

用法:
    cd /home/inamoto888/project/matwau
    python3 examples/coordination_demo.py

输出:
    - Inconel 718 完整表征报告
    - 4 机器人结果明细
    - cross_validation 跨机器人一致性
    - 总成本 + 总时长
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_chemist_agent import (  # noqa: E402
    MatChemistAgent,
    decompose_goal_to_robots,
    get_default_inconel_718_workflow,
    get_default_pmma_workflow,
)
from agents.mat_robot_dsc_agent import MatRobotDscAgent  # noqa: E402
from agents.mat_robot_em_agent import MatRobotEmAgent  # noqa: E402
from agents.mat_robot_synth_agent import MatRobotSynthAgent  # noqa: E402
from agents.mat_robot_xrd_agent import MatRobotXrdAgent  # noqa: E402
from matwau.core.agent_base import AgentRequest  # noqa: E402


def print_header(title: str) -> None:
    print()
    print("=" * 70)
    print(f" {title}")
    print("=" * 70)


def print_section(title: str) -> None:
    print()
    print(f"--- {title} ---")


def main() -> None:
    # 1. 初始化 4 个机器人 + 1 个化学师
    print_header("MatWAU Stage 3 钢铁侠 — 化学师协调 4 机器人 Demo")

    print("🔧 初始化 4 机器人:")
    synth = MatRobotSynthAgent()
    print(f"  - synth agent: {synth.name} (robot_sdk={synth.robot_sdk.sdk_mode})")
    xrd = MatRobotXrdAgent()
    print(f"  - xrd agent:   {xrd.name} (robot_sdk={xrd.robot_sdk.sdk_mode})")
    em = MatRobotEmAgent()
    print(f"  - em agent:    {em.name} (robot_sdk={em.robot_sdk.sdk_mode})")
    dsc = MatRobotDscAgent()
    print(f"  - dsc agent:   {dsc.name} (robot_sdk={dsc.robot_sdk.sdk_mode})")

    chemist = MatChemistAgent(
        synth_agent=synth,
        xrd_agent=xrd,
        em_agent=em,
        dsc_agent=dsc,
    )
    print(f"  - chemist agent: {chemist.name} (协调器)")

    # 2. 示例 1:Inconel 718 完整表征
    print_header("示例 1:Inconel 718 完整表征(synth + xrd + em + dsc)")
    task = get_default_inconel_718_workflow()
    print(f"目标样品:{task.target_sample}")
    print(f"研究目标:{task.goal}")
    print(f"机器人步骤:")
    for step in task.robot_steps:
        print(f"  - {step.robot_type}:{step.description} (¥{step.estimated_cost_cny})")
    print(f"预算:¥{task.budget_cny}")

    req = AgentRequest(
        run_id="demo-inconel-001",
        message="测 Inconel 718 完整表征",
        artifacts={"task": task},
    )
    resp = chemist.run(req)

    print_section("执行结果")
    print(f"Reply: {resp.reply}")
    print(f"Overall Success: {resp.artifacts['overall_success']}")
    print(f"Successful: {resp.artifacts['n_successful']}/{resp.artifacts['n_robot_steps']}")
    print(f"Blocked: {resp.artifacts['n_blocked']}")
    print(f"Total Cost: ¥{resp.artifacts['total_cost_cny']:.2f}")
    print(f"Total Duration: {resp.artifacts['total_duration_seconds']:.3f}s")

    print_section("每机器人详情")
    for r in resp.artifacts["robot_results"]:
        status = "✅" if r["success"] else ("⛔" if r["blocked"] else "❌")
        print(f"  {status} {r['robot_type']:6s}: {r['reply'][:80]} (¥{r['cost']:.2f})")

    print_section("跨机器人一致性 (cross_validation)")
    cv = resp.artifacts["cross_validation"]
    print(f"  Consistent: {cv['consistent']}")
    if cv.get("warnings"):
        for w in cv["warnings"]:
            print(f"  - {w}")

    # W31 NEW — Section 1.5:接 mat-critic-agent 跑 L4 跨机器人一致性
    print_section("mat-critic L4 跨机器人一致性(W30 + W31)")
    try:
        from agents.mat_critic_agent import MatCriticAgent
        critic = MatCriticAgent()
        critic_req = AgentRequest(
            run_id="demo-inconel-critic",
            message="Inconel 718 表征复核",
            artifacts={"report": resp.artifacts.get("report")},
        )
        critic_resp = critic.run(critic_req)
        critic_verdict = critic_resp.artifacts.get("critic_verdict")
        if critic_verdict:
            cross = critic_verdict.cross_robot
            print(f"  critic verdict: {critic_verdict.verdict.upper()}")
            print(f"  L4 score: {cross.score:.2f} (consistent: {cross.consistent})")
            if cross.rules_passed:
                print(f"  L4 rules passed: {cross.rules_passed}")
            if cross.rules_failed:
                print(f"  L4 rules failed: {cross.rules_failed}")
        else:
            print(f"  critic verdict unavailable")
    except Exception as e:
        print(f"  critic 跳过:{e}")

    # 3. 示例 2:自然语言拆解
    print_header("示例 2:自然语言目标自动拆解")
    print('输入:"测 PMMA 玻璃化温度 Tg"')
    steps = decompose_goal_to_robots("PMMA", "测 PMMA 玻璃化温度 Tg")
    print(f"自动拆解成 {len(steps)} 个 robot step:")
    for step in steps:
        print(f"  - {step.robot_type}:{step.description}")

    # 4. 示例 3:PMMA 简化 workflow
    print_header("示例 3:PMMA 玻璃化温度(简化 2 步)")
    task_pmma = get_default_pmma_workflow()
    print(f"目标样品:{task_pmma.target_sample}")
    print(f"机器人步骤:")
    for step in task_pmma.robot_steps:
        print(f"  - {step.robot_type}:{step.description}")
    print(f"预算:¥{task_pmma.budget_cny}")

    req_pmma = AgentRequest(
        run_id="demo-pmma-001",
        message="测 PMMA Tg",
        artifacts={"task": task_pmma},
    )
    resp_pmma = chemist.run(req)

    print(f"\nReply: {resp_pmma.reply}")
    print(f"Successful: {resp_pmma.artifacts['n_successful']}/{resp_pmma.artifacts['n_robot_steps']}")
    print(f"Total Cost: ¥{resp_pmma.artifacts['total_cost_cny']:.2f}")

    # 5. 总结
    print_header("Stage 3 钢铁侠 — JARVIS 雏形完整")
    print("✅ 5 件 agent 全部就绪:")
    print("   - 4 个机器人(synth / xrd / em / dsc)")
    print("   - 1 个化学师(mat-chemist-agent,协调)")
    print()
    print("🎯 Stage 4 入口(企业部署):")
    print("   - mat-critic 拿汇总报告做 3 路交叉验证")
    print("   - mat-orchestrator DAG 调度多个化学师")
    print("   - LineageStore / PostgresBackend 数据持久化")

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()