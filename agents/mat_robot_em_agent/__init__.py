"""mat_robot_em_agent — 机器人电镜表征 agent(W21 + W24)

W21:Stage 3 钢铁侠 Phase 3 第 3 个机器人(继 W17-D synth + W18 XRD 之后)
W21 关键:
- 加 EMSafetyGuard 6 类电镜特有拦截
- ZeissMockSDK(Stage 1)→ Zeiss / FEI SDK(Stage 2)
- 多模式:SEM / TEM / STEM / EDS / SAED
- 输出图像 + EDS 元素谱 + 晶粒尺寸

W24 增量:ZeissRealSDK 真接(SmartSEM REST API + 公开 .sxml XML 配置 + EDS 标准组成)
- 装 requests + SmartSEM endpoint 可达 → 真接 SmartSEM 远程 API
- 否则 → 自动降级 ZeissMockSDK(零停机)
- 接口与 Mock 100% 兼容(mat_robot_em_agent.py 不破坏)

本 agent 能力:
- SEM 拍 100x → 100,000x 微观结构
- TEM 高分辨 + SAED 选区电子衍射
- EDS 元素分析(W24 真接后用标准组成库)
- 晶粒尺寸统计

per MatWAU-开发计划 §8 W21 + W24
"""

from .em_engine import (  # noqa: F401
    EMProcedure,
    EMResult,
    EMStep,
    EMSafetyGuard,
    ZeissMockSDK,
    EM_VOLATILE_MATERIALS,
    EM_RADIATION_DAMAGE_MATERIALS,
    EM_MAGNETIC_MATERIALS,
    HAZARD_EM_DOOR_OPEN,
    HAZARD_EM_VACUUM_OK,
    HAZARD_EM_HIGH_VOLTAGE_KV,
    VACUUM_THRESHOLD,
    DEFAULT_EM_PROCEDURE,
    estimate_em_cost,
    get_default_em_procedure,
)
from .mat_robot_em_agent import MatRobotEmAgent  # noqa: F401
from .zeiss_real_sdk import (  # noqa: F401
    ZeissRealSDK,
    ZeissProtocolBuilder,
    is_zeiss_smartsem_available,
    get_zeiss_sdk_list,
    smartsem_endpoint_available,
    lookup_eds_composition,
    generate_eds_output,
    generate_sem_image,
    ZEISS_SIGMA_DEFAULT_PARAMS,
    EDS_KNOWN_COMPOSITIONS,
    SMARTSEM_DEFAULT_API_URL,
)

__all__ = [
    "MatRobotEmAgent",
    "EMProcedure",
    "EMResult",
    "EMStep",
    "EMSafetyGuard",
    "ZeissMockSDK",
    # W24 Stage 2 真接
    "ZeissRealSDK",                      # W24 真接 SDK
    "ZeissProtocolBuilder",              # W24 SmartSEM XML 配置生成器
    "is_zeiss_smartsem_available",       # W24 SDK 检测
    "get_zeiss_sdk_list",                 # W24 列出已装 Zeiss 库
    "smartsem_endpoint_available",       # W24 SmartSEM REST 探测
    "lookup_eds_composition",            # W24 EDS 标准组成查表
    "generate_eds_output",               # W24 EDS 输出生成(确定性)
    "generate_sem_image",                # W24 SEM 图像记录生成
    "ZEISS_SIGMA_DEFAULT_PARAMS",        # W24 Zeiss Sigma 规格
    "EDS_KNOWN_COMPOSITIONS",            # W24 EDS 标准组成库
    "SMARTSEM_DEFAULT_API_URL",          # W24 SmartSEM REST URL
    # EM 防护
    "EM_VOLATILE_MATERIALS",
    "EM_RADIATION_DAMAGE_MATERIALS",
    "EM_MAGNETIC_MATERIALS",
    "HAZARD_EM_DOOR_OPEN",
    "HAZARD_EM_VACUUM_OK",
    "HAZARD_EM_HIGH_VOLTAGE_KV",
    "VACUUM_THRESHOLD",
    "DEFAULT_EM_PROCEDURE",
    "estimate_em_cost",
    "get_default_em_procedure",
]
