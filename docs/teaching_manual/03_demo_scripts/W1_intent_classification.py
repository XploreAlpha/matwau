"""W1_intent_classification.py — 课堂演示(mat-intent-agent)

教学目标:
  - 理解 MatWAU agent 的"输入 → 输出"模型
  - 看 mat-intent-agent 怎么把 1 句话拆成 MatIntent
  - 跑 3 类意图:design_new_material / optimize_existing / literature_review

用法:
  cd /path/to/matwau
  python3 docs/teaching_manual/03_demo_scripts/W1_intent_classification.py

预期输出:
  === 测试 1: design_new_material ===
  reply: 用户想做 ... (子类: design_new_material, 系统: li_ion_cathode, ...)
  artifacts.mat_intent.subclass: design_new_material
  ...
"""
from __future__ import annotations

import sys
from pathlib import Path

# 让脚本能 import matwau 顶层模块
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT))


def _print_intent(label: str, message: str):
    print(f"\n=== {label} ===")
    print(f"📝 用户输入: {message}\n")

    # 延迟 import(让错误更友好)
    try:
        from agents.mat_intent_agent import MatIntentAgent
        from matwau.core.agent_base import AgentRequest
    except ImportError as e:
        print(f"❌ ImportError: {e}")
        print("   请确保已 pip install -r requirements.txt")
        return

    agent = MatIntentAgent()
    req = AgentRequest(run_id=f"w1-{label}", message=message, artifacts={}, context={})
    resp = agent.run(req)

    print(f"🤖 回复: {resp.reply[:200]}...")
    print(f"📦 artifacts keys: {list(resp.artifacts.keys())}")
    if "mat_intent" in resp.artifacts:
        mi = resp.artifacts["mat_intent"]
        print(f"   ├ subclass:      {getattr(mi, 'subclass', 'N/A')}")
        print(f"   ├ material_system: {getattr(mi, 'material_system', 'N/A')}")
        print(f"   ├ target_props:   {getattr(mi, 'target_props', 'N/A')}")
        print(f"   └ constraints:    {getattr(mi, 'constraints', {})}")
    print(f"💰 cost: ¥{resp.cost}")


def main():
    print("🚀 MatWAU 学院版 — W1 课堂演示(mat-intent-agent)\n")

    _print_intent(
        "测试 1: design_new_material(设计新材料)",
        "设计新型无钴锂电池正极材料,能量密度 > 500 Wh/kg",
    )

    _print_intent(
        "测试 2: optimize_existing(优化现有材料)",
        "把 Inconel 718 的高温强度再提升 20%",
    )

    _print_intent(
        "测试 3: literature_review(文献综述)",
        "帮我查近 3 年钙钛矿太阳能电池的论文",
    )

    print("\n✅ W1 demo 跑完。试试改 prompt(mat_intent_agent.py §87),看输出变化。")


if __name__ == "__main__":
    main()