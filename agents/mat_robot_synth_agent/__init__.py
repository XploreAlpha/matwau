"""mat_robot_synth_agent — Stage 3 钢铁侠起步(W17-D + W19 真接)

W17: MatWAU 新品类 — 物理世界机器人 agent(从数字跨到物理)
W19 增量:OpentronsRealSDK 真接 OT-2(装 opentrons 真协议生成 / 降级 mock)

设计原则(per Stage 3 钢铁侠愿景 doc):
1. 继承 MatWAU-AgentBase(共用 Inner Loop 基类,保持 11+1 agent 独立)
2. SafetyGuard 是必备(机械臂操作危险:高温 / 化学品 / 电力)
3. Opentrons OT-2 SDK 接入(W19 Stage 2 真接 + 降级 mock)

本 agent 能力:
- 真接 / 模拟 OT-2 协议(per W19 OpentronsRealSDK)
- SafetyGuard 实时拦截高温 > 800°C / 化学品超量 / 危险操作
- 输出结构化实验报告(给 mat-critic 喂数据)

per MatWAU-开发计划 §8 W17-D + W19 真接
"""

from .mat_robot_synth_agent import MatRobotSynthAgent  # noqa: F401
from .opentrons_real_sdk import (  # noqa: F401
    OpentronsProtocolBuilder,
    OpentronsRealSDK,
    is_opentrons_available,
    get_opentrons_version,
    simulate_protocol,
)
from .synth_engine import (  # noqa: F401
    SynthProcedure,
    SynthStep,
    SynthResult,
    OpentronsMockSDK,
    SafetyGuard,
    HAZARD_TEMP_CELSIUS_LIMIT,
    get_default_procedure,
    estimate_synth_cost,
)

__all__ = [
    "MatRobotSynthAgent",
    "SynthProcedure",
    "SynthStep",
    "SynthResult",
    "OpentronsMockSDK",
    "OpentronsRealSDK",          # W19 Stage 2 真接
    "OpentronsProtocolBuilder",  # W19 协议生成器
    "is_opentrons_available",    # W19 SDK 检测
    "get_opentrons_version",     # W19 版本查询
    "simulate_protocol",         # W19 opentrons.simulate()
    "SafetyGuard",
    "HAZARD_TEMP_CELSIUS_LIMIT",
    "get_default_procedure",
    "estimate_synth_cost",
]
