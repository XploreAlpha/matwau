"""mat_robot_dsc_agent — 机器人 DSC 热分析 agent(W22 + W25)

W22:Stage 3 钢铁侠 Phase 3 第 4 个机器人(继 W17-D synth + W18 XRD + W21 EM)
W22 关键:
- 加 DSCSafetyGuard 5 类 DSC 特有拦截(高温氧化 / 坩埚密封 / 超量 / 升温速率 / 爆炸物)
- TAMockSDK(Stage 1)→ TA Trios API / Perkin Elmer(Stage 2)
- 多气氛 + 多升温速率
- 输出 Tg / Tm / Tc / ΔH + DSC 曲线

W25 增量:TATriosRealSDK 真接(TA Trios AutoPilot REST API + 公开 .csv 温度程序
+ 内置标准材料 DSC 属性库)
- 装 requests + Trios endpoint 可达 → 真接 AutoPilot 远程 API
- 否则 → 自动降级 TAMockSDK(零停机)
- 接口与 Mock 100% 兼容(mat_robot_dsc_agent.py 不破坏)

本 agent 能力:
- 测 Tg 玻璃化 / Tm 熔融 / Tc 结晶 / ΔH 焓变
- 多气氛:空气 / N2 / Ar / O2 / 真空
- 标准材料库查 Tg / Tm(per W25)

per MatWAU-开发计划 §8 W22 + W25
"""

from .dsc_engine import (  # noqa: F401
    DSCProcedure,
    DSCResult,
    DSCStep,
    DSCSafetyGuard,
    TAMockSDK,
    DSC_DANGEROUS_MATERIALS,
    HAZARD_DSC_HIGH_TEMP_OXIDIZING,
    HAZARD_DSC_MAX_HEATING_RATE_C_PER_MIN,
    HAZARD_DSC_MAX_SAMPLE_MASS_MG,
    DSC_ATMOSPHERES,
    DEFAULT_DSC_PROCEDURE,
    estimate_dsc_cost,
    get_default_dsc_procedure,
)
from .mat_robot_dsc_agent import MatRobotDscAgent  # noqa: F401
from .ta_trios_real_sdk import (  # noqa: F401
    TATriosRealSDK,
    TATriosProtocolBuilder,
    is_ta_trios_available,
    get_ta_sdk_list,
    trios_endpoint_available,
    lookup_material_dsc,
    compute_tg_tm,
    generate_dsc_curve,
    TA_DSC_250_DEFAULT_PARAMS,
    MATERIAL_DSC_LIBRARY,
    TA_TRIOS_DEFAULT_API_URL,
)

__all__ = [
    "MatRobotDscAgent",
    "DSCProcedure",
    "DSCResult",
    "DSCStep",
    "DSCSafetyGuard",
    "TAMockSDK",
    # W25 Stage 2 真接
    "TATriosRealSDK",                 # W25 真接 SDK
    "TATriosProtocolBuilder",         # W25 Trios CSV 程序生成器
    "is_ta_trios_available",          # W25 SDK 检测
    "get_ta_sdk_list",                # W25 列出已装 TA 库
    "trios_endpoint_available",       # W25 Trios AutoPilot 探测
    "lookup_material_dsc",            # W25 标准材料 DSC 属性查表
    "compute_tg_tm",                  # W25 Tg / Tm / Tc 估算
    "generate_dsc_curve",             # W25 DSC 曲线生成(确定性)
    "TA_DSC_250_DEFAULT_PARAMS",      # W25 TA DSC 250 规格
    "MATERIAL_DSC_LIBRARY",           # W25 内置材料 DSC 库
    "TA_TRIOS_DEFAULT_API_URL",       # W25 Trios AutoPilot REST URL
    # DSC 防护
    "DSC_DANGEROUS_MATERIALS",
    "HAZARD_DSC_HIGH_TEMP_OXIDIZING",
    "HAZARD_DSC_MAX_HEATING_RATE_C_PER_MIN",
    "HAZARD_DSC_MAX_SAMPLE_MASS_MG",
    "DSC_ATMOSPHERES",
    "DEFAULT_DSC_PROCEDURE",
    "estimate_dsc_cost",
    "get_default_dsc_procedure",
]