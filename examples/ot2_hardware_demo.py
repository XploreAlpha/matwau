"""ot2_hardware_demo.py — W28 真 OT-2 硬件接入演示

端到端:
1. SynthProcedure(LLZO 合成)
2. 化学品供应清单(查 REAGENT_CATALOG)
3. OT-2 协议生成(per W19 OpentronsProtocolBuilder)
4. 写到文件
5. opentrons.simulate() 真跑协议

用法:
    cd /home/inamoto888/project/matwau
    python3 examples/ot2_hardware_demo.py

前置:
    pip install opentrons(已装 9.1.1)
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_robot_synth_agent import (
    get_opentrons_version,
    is_opentrons_available,
)
from agents.mat_robot_synth_agent.ot2_hardware_gateway import (
    build_reagent_manifest,
    estimate_reagent_cost,
    hardware_full_workflow,
)
from agents.mat_robot_synth_agent.synth_engine import DEFAULT_PROCEDURES


def print_header(title: str) -> None:
    print()
    print("=" * 70)
    print(f" {title}")
    print("=" * 70)


def main() -> None:
    print_header("MatWAU W28 真 OT-2 硬件接入 Demo")

    # 1. 检测 opentrons 安装
    print("\n🔌 opentrons 安装检测:")
    print(f"  - is_opentrons_available: {is_opentrons_available()}")
    print(f"  - version: {get_opentrons_version()}")

    # 2. 选默认 procedure(LLZO Pechini 法合成)
    proc = DEFAULT_PROCEDURES.get("Pechini_Ca_LLZO")
    if proc is None:
        print("❌ 没找到 LLZO 默认 procedure")
        return
    print(f"\n📋 选 procedure: {proc.target_formula} ({proc.method})")
    print(f"  步骤数: {len(proc.steps)}")
    print(f"  总时长: {proc.total_duration_minutes():.0f} min")

    # 3. 化学品供应清单
    orders = build_reagent_manifest(proc)
    cost = estimate_reagent_cost(orders)
    print("\n💊 化学品供应清单:")
    for o in orders[:5]:
        print(f"  - {o.chemical_formula}:{o.amount}{o.unit} ¥{o.price_cny:.2f} ({o.supplier})")
    if len(orders) > 5:
        print(f"  ...({len(orders) - 5} 更多)")
    print(f"  总成本:¥{cost:.2f}")

    # 4. 端到端 workflow
    print_header("W28 端到端:procedure → 化学品 → 协议 → simulate")
    result = hardware_full_workflow(proc, run_id="w28-demo-001")

    print("\n📋 化学品供应:")
    print(f"  - {len(result['reagent_orders'])} 个化学品")
    print(f"  - 总成本:¥{result['total_reagent_cost_cny']:.2f}")

    print("\n📝 OT-2 协议:")
    print(f"  - 路径:{result['protocol_path']}")
    print(f"  - 大小:{Path(result['protocol_path']).stat().st_size} bytes")

    sim = result["simulate_result"]
    if sim is not None:
        print("\n🎬 simulate 结果:")
        print(f"  - 状态:{'✅' if sim['ok'] else '❌'} {sim['log']}")
        print(f"  - 来源:{sim.get('source', 'unknown')}")
        if sim.get("commands_count") is not None:
            print(f"  - 命令数:{sim['commands_count']}")
        if sim.get("runtime_seconds") is not None:
            print(f"  - 运行时长:{sim['runtime_seconds']:.3f}s")
    else:
        print("\n❌ simulate 完全失败(opentrons 未装?)")

    # 5. 总结
    print_header("W28 收口")
    print("✅ 真接 SDK 链路:")
    print("   - SynthProcedure → REAGENT_CATALOG 化学品供应")
    print("   - → OpentronsProtocolBuilder 生成 OT-2 协议")
    print("   - → 写到 .py 文件")
    print("   - → opentrons.simulate() 真跑模拟")
    print("   - → 反馈 commands_count + runtime_seconds")
    print()
    print("🚀 Stage 4 enterprise:")
    print("   - Docker compose 部署(ot2-simulator + gateway)")
    print("   - 化学品费用清单 → 实验室 LIMS 对接")
    print("   - 协议版本控制(per LineageStore / Postgres)")


if __name__ == "__main__":
    main()