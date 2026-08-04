"""xrd_engine.py — MatWAU 机器人 XRD 表征核心引擎(W18)

W18 复用 W17-D synth_engine 的设计原则,但加 3 个新拦截:
1. 仪器舱门开着 → block(防 X 射线辐射)
2. 用户不在 lead apron → block
3. 易辐射分解物质 → block

per MatWAU-Harness-Loop-工程心法实践 §5.4
"""
from __future__ import annotations

import logging
import random
import uuid
from dataclasses import dataclass, field
from typing import Any

from agents.mat_robot_synth_agent.synth_engine import SafetyGuard
from matwau.core.agent_base import AgentResponse

logger = logging.getLogger(__name__)

# W18 XRD 辐射防护铁律
HAZARD_XRD_DOOR_OPEN = True     # 仪器舱门状态
HAZARD_XRD_NO_APRON = False     # 用户是否穿铅围裙
RADIATION_DECOMPOSE_MATERIALS = {  # 易辐射分解物质
    "H2O2",        # 过氧化氢
    "BaP",         # 苯并[a]芘
    "U",           # 铀
    "Th",          # 钍
    "TBP",         # 磷酸三丁酯
}


# ============================================================================
# 数据类(reuse W17-D 模式)
# ============================================================================


@dataclass
class XRDStep:
    """1 个 XRD 步骤"""

    step_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""                                # 装样 / 对光 / 扫描 / 卸载
    duration_minutes: float = 0.0
    tube_voltage_kv: float = 40.0                 # X 射线管电压(kV)
    tube_current_ma: float = 30.0                 # X 射线管电流(mA)
    two_theta_range: tuple = (5.0, 90.0)         # 扫描 2θ 范围
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class XRDProcedure:
    """1 个 XRD 测试方案"""

    sample_formula: str = ""                      # 样品化学式
    target_phases: list[str] = field(default_factory=list)  # 期望匹配的 PDF 卡片
    steps: list[XRDStep] = field(default_factory=list)
    door_open: bool = HAZARD_XRD_DOOR_OPEN        # 仪器舱门(默认安全)
    user_in_apron: bool = HAZARD_XRD_NO_APRON     # 用户着铅围裙(默认违规)
    sample_is_radioactive_sensitive: bool = False  # 易辐射分解样品

    def total_duration_minutes(self) -> float:
        return sum(s.duration_minutes for s in self.steps)


@dataclass
class XRDResult:
    """1 次 XRD 测试结果"""

    run_id: str = ""
    procedure: XRDProcedure | None = None
    success: bool = True
    peaks: list[dict[str, float]] = field(default_factory=list)  # [(2θ, d, intensity)]
    matched_phase: str = ""                       # 匹配的 PDF 卡片
    confidence: float = 0.0                       # 匹配确信度
    warnings: list[str] = field(default_factory=list)
    blocked_steps: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    cost: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# BrukerMockSDK(Stage 1 mock,真接 Bruker XRD SDK 在 Stage 2)
# ============================================================================


class BrukerMockSDK:
    """Bruker D8 Advance XRD mock(W18)

    Stage 2 真接:
    - 替换内部 random/seed 为 Bruker XRD Bridge API
    - 保持接口(Stage 1 → Stage 2 零改 mat_robot_xrd_agent)
    """

    def __init__(self, *, lab_id: str = "matwau-xrd-01", fail_chance: float = 0.05) -> None:
        self.lab_id = lab_id
        self.fail_chance = fail_chance
        self.scans_completed: list[str] = []
        self.connected = True

    def execute(self, step: XRDStep) -> dict[str, Any]:
        """执行 1 个 XRDStep(真接就是 Bruker XRD Bridge API)"""
        self.scans_completed.append(step.name)
        if not self.connected:
            return {"ok": False, "log": f"XRD {self.lab_id} 未连接", "peaks": []}
        if random.random() < self.fail_chance:
            return {"ok": False, "log": f"步骤 {step.name} 失败(模拟)", "peaks": []}
        # mock 峰值生成(2θ 5-90 度区间,fake Bragg 峰)
        n_peaks = 3
        peaks = [
            {
                "two_theta": 18.5 + i * 12.3,    # 18.5 / 30.8 / 43.1 度
                "d_spacing_angstrom": round(4.8 - i * 1.5, 3),
                "intensity": 100 - i * 20,
            }
            for i in range(n_peaks)
        ]
        return {
            "ok": True,
            "log": f"XRD 扫描 {step.two_theta_range} 完成,峰 {n_peaks} 个",
            "peaks": peaks,
        }

    def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected


# ============================================================================
# XRDSafetyGuard(W18 关键 — 复用 W17-D + 加 3 类 XRD 特有拦截)
# ============================================================================


class XRDSafetyGuard(SafetyGuard):
    """W18 XRD 辐射防护 SafetyGuard

    继承 W17-D SafetyGuard,加 3 类 XRD 特有:
    1. 仪器舱门开着 → block
    2. 用户不在铅围裙 → block
    3. 易辐射分解物质 → block

    这是 W17-D 给 W18 的模板价值的兑现:继承即可,XRD 特有 5 行代码即可加 3 类拦截
    """

    def __init__(
        self,
        temp_limit: float = 1000.0,                # XRD 室温,提高一点
        *,
        block_if_door_open: bool = True,
        block_if_no_apron: bool = True,
    ) -> None:
        super().__init__(temp_limit=temp_limit)
        self.block_if_door_open = block_if_door_open
        self.block_if_apron_no = block_if_no_apron
        self.warnings_count = 0

    def check(self, response: AgentResponse) -> bool:
        """W18 override:不调父类(父类用 SynthProcedure.max_temperature)

        本类只看 response.artifacts.get(\"procedure\") 是 XRDProcedure,
        调 self.check_xrd
        """
        from agents.mat_robot_xrd_agent.xrd_engine import XRDProcedure  # local
        procedure = response.artifacts.get("procedure") if response.artifacts else None
        if not isinstance(procedure, XRDProcedure):
            return True  # 兜底放行
        warns = self.check_xrd(procedure)
        if warns:
            self.warnings_count += 1
            return False
        return True

    def check_xrd(self, procedure: XRDProcedure) -> list[str]:
        """XRD 流程专用安全检查(扩展父类)"""
        warnings = []

        # 1. 舱门检查(W18 铁律)
        if self.block_if_door_open and procedure.door_open:
            warnings.append(
                "⛔ 辐射危险:XRD 仪器舱门开着,先关舱门再启动 X 射线管"
            )

        # 2. 铅围裙检查
        if self.block_if_apron_no and not procedure.user_in_apron:
            warnings.append(
                "⛔ 辐射危险:操作员未穿铅围裙,需穿戴 ≥0.25mm Pb 等效围裙"
            )

        # 3. 易辐射分解物质检查
        if procedure.sample_is_radioactive_sensitive:
            for mat in RADIATION_DECOMPOSE_MATERIALS:
                if mat in procedure.sample_formula.upper():
                    warnings.append(
                        f"⛔ 辐射危险:样品包含易辐射分解物质 {mat}"
                    )
                    break

        return warnings


# ============================================================================
# 成本估算(W18 单价约定)
# ============================================================================


def estimate_xrd_cost(procedure: XRDProcedure) -> float:
    """估算 1 次 XRD 测试成本(¥)

    单价约定:
    - 装样 / 卸载:¥10/次
    - 对光:¥5/次
    - 扫描:¥30/小时
    - 维护 / 校准:¥20/次
    """
    cost = 30.0  # 基础维护
    for step in procedure.steps:
        hours = step.duration_minutes / 60.0
        if "扫描" in step.name:
            cost += 30.0 * hours
        elif "对光" in step.name:
            cost += 5.0
        elif "装样" in step.name or "卸载" in step.name:
            cost += 10.0
    return round(cost, 2)


# 默认 procedure:Ca-LLZO 表征(per W17-D 衔接)
DEFAULT_XRD_PROCEDURE = XRDProcedure(
    sample_formula="Ca0.25Li6.5La3Zr1.75O12",
    target_phases=["PDF 45-1090 LLZO cubic"],
    steps=[
        XRDStep(name="装样", duration_minutes=10),
        XRDStep(name="对光", duration_minutes=5),
        XRDStep(name="扫描 5-90°", duration_minutes=30, two_theta_range=(5.0, 90.0)),
        XRDStep(name="卸载", duration_minutes=5),
    ],
    door_open=False,
    user_in_apron=True,
    sample_is_radioactive_sensitive=False,
)


def get_default_xrd_procedure() -> XRDProcedure:
    """获取默认 Ca-LLZO XRD procedure"""
    return DEFAULT_XRD_PROCEDURE
