"""mat_robot_xrd_agent — 机器人 XRD 表征 agent(W18 + W20 真接)

W18: 复用 W17-D mat-robot-synth-agent 模板,加 X 射线辐射防护层
- 复用 SafetyGuard 父类(metaclass safety 机制 + 高温已经够用)
- 加 XRDSafetyGuard 子类:3 类额外拦截
  1. 仪器舱门开着 → 阻断 X 射线
  2. 用户不在 lead apron → block
  3. 测样品包含易辐射分解物质(过氧化氢 / 苯并[a]芘)→ block

W20 增量:
- 默认 robot_sdk 由 BrukerMockSDK → BrukerRealSDK
- 装了 brukerraw / pydcdi 等走真 PDF 卡片比对
- 未装降级 mock + 走粗略 matched_phase

本 agent 能力:
- 真接 / 模拟 XRD 扫描(cu 靶 / Bragg-Brentano 几何)— W20
- 输出峰列表 / d-spacing / 晶系 — 给 mat-critic 喂 PDF 卡片比对

per MatWAU-开发计划 §8 W18 + W20 真接
"""
from .bruker_real_sdk import (
    PDF_CARDS_DB,
    BrukerProtocolBuilder,
    BrukerRealSDK,
    compare_to_pdf_card,
    get_bruker_sdk_list,
    is_bruker_raw_available,
    lookup_pdf_card,
    scan_to_peaks,
)
from .mat_robot_xrd_agent import MatRobotXrdAgent
from .xrd_engine import (
    HAZARD_XRD_DOOR_OPEN,
    HAZARD_XRD_NO_APRON,
    RADIATION_DECOMPOSE_MATERIALS,
    BrukerMockSDK,
    XRDProcedure,
    XRDResult,
    XRDSafetyGuard,
    XRDStep,
    estimate_xrd_cost,
    get_default_xrd_procedure,
)

__all__ = [
    "HAZARD_XRD_DOOR_OPEN",
    "HAZARD_XRD_NO_APRON",
    "PDF_CARDS_DB",               # W20 内置 PDF 卡片数据库
    "RADIATION_DECOMPOSE_MATERIALS",
    "BrukerMockSDK",
    "BrukerProtocolBuilder",      # W20 .brml XML 生成
    "BrukerRealSDK",              # W20 Stage 2 真接
    "MatRobotXrdAgent",
    "XRDProcedure",
    "XRDResult",
    "XRDSafetyGuard",
    "XRDStep",
    "compare_to_pdf_card",        # W20 峰比对
    "estimate_xrd_cost",
    "get_bruker_sdk_list",        # W20 Bruker 库列表
    "get_default_xrd_procedure",
    "is_bruker_raw_available",    # W20 SDK 检测
    "lookup_pdf_card",            # W20 PDF 卡片查询
    "scan_to_peaks",              # W20 扫描 → Bragg 峰
]
