"""synth_engine.py — MatWAU 机器人合成实验核心引擎(W17-D)

职责:
1. SynthProcedure:1 个合成配方(Ca-LLZO 等)
2. SynthStep:1 个合成步骤(称量 / 球磨 / 烧结 / 等)
3. SynthResult:1 个合成结果(产物 + 失败原因)
4. OpentronsMockSDK:Opentrons OT-2 mock(Stage 1,Stage 2 真接 SDK)
5. SafetyGuard:实装 matwau.core 的 SafetyGuard ABC(W17-D 关键价值)

per MatWAU-Harness-Loop-工程心法实践 §5.4
"""
from __future__ import annotations

import logging
import random
import uuid
from dataclasses import dataclass, field
from typing import Any

from matwau.core.agent_base import AgentResponse
from matwau.core.agent_base import SafetyGuard as BaseSafetyGuard

logger = logging.getLogger(__name__)

# 高温告警上限(W17-D 铁律)
HAZARD_TEMP_CELSIUS_LIMIT = 800.0


# ============================================================================
# 数据类
# ============================================================================


@dataclass
class SynthStep:
    """1 个合成步骤"""

    step_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""                                # 称量 / 球磨 / 烧结 / 等
    duration_minutes: float = 0.0
    temperature_celsius: float = 25.0             # 该步骤温度(室温默认)
    chemicals: list[str] = field(default_factory=list)  # 用到的化学试剂
    params: dict[str, Any] = field(default_factory=dict)  # 其他参数

    def is_high_temperature(self) -> bool:
        return self.temperature_celsius > HAZARD_TEMP_CELSIUS_LIMIT


@dataclass
class SynthProcedure:
    """1 个合成配方(用户提交)"""

    target_formula: str = ""                       # 目标化学式(Ca-LLZO 等)
    steps: list[SynthStep] = field(default_factory=list)
    target_yield_grams: float = 1.0                # 期望产物质量(g)
    method: str = "Pechini"                        # Pechini / sol-gel / 共沉淀 / 等

    def total_duration_minutes(self) -> float:
        return sum(s.duration_minutes for s in self.steps)

    def max_temperature(self) -> float:
        if not self.steps:
            return 25.0
        return max(s.temperature_celsius for s in self.steps)


@dataclass
class SynthResult:
    """1 次合成结果"""

    run_id: str = ""
    procedure: SynthProcedure | None = None
    success: bool = True
    product_formula: str = ""                      # 实际产物(可能不是目标)
    yield_grams: float = 0.0
    synthesis_duration_minutes: float = 0.0
    warnings: list[str] = field(default_factory=list)   # SafetyGuard 报警
    blocked_steps: list[str] = field(default_factory=list)  # 被拦截的步骤
    log: list[str] = field(default_factory=list)     # 实验日志
    cost: float = 0.0
    cost_estimate: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "target_formula": self.procedure.target_formula if self.procedure else "",
            "success": self.success,
            "product_formula": self.product_formula,
            "yield_grams": self.yield_grams,
            "synthesis_duration_minutes": self.synthesis_duration_minutes,
            "warnings": self.warnings,
            "blocked_steps": self.blocked_steps,
            "cost": self.cost,
            "metadata": self.metadata,
        }


# ============================================================================
# OpentronsMockSDK(Stage 1 mock,Stage 2 真接 OT-2 API)
# ============================================================================


class OpentronsMockSDK:
    """Opentrons OT-2 机械臂 mock(Stage 1,W17-D)

    Stage 2 真接(per Stage 3 钢铁侠 doc):
    - 替换内部 random/seed 为 opentrons 库真实调用
    - robot.perform_command(...) → 真实 API
    - 保持一致接口(Stage 1 → Stage 2 零改 mat_robot_synth_agent)
    """

    def __init__(self, *, lab_id: str = "matwau-lab-01", fail_chance: float = 0.05) -> None:
        self.lab_id = lab_id
        self.fail_chance = fail_chance  # 模拟机械臂 5% 失败率
        self.commands_executed: list[str] = []
        self.connected = True

    def execute(self, step: SynthStep) -> dict[str, Any]:
        """执行 1 个 SynthStep(真接就是 robot.transfer / robot.aspirate / robot.dispense)

        Returns:
            {"ok": bool, "log": str, "yield": float}
        """
        self.commands_executed.append(step.name)
        # mock 真实调用:在真 SDK 下会变 `opentrons.simulate(...)`
        if not self.connected:
            return {"ok": False, "log": f"机械臂 {self.lab_id} 未连接", "yield": 0.0}
        if random.random() < self.fail_chance:
            return {"ok": False, "log": f"步骤 {step.name} 失败(模拟随机失败)", "yield": 0.0}
        # mock yield:温度 × 时长 经验比例
        yield_grams = step.duration_minutes * 0.05 * (step.temperature_celsius / 100.0)
        return {
            "ok": True,
            "log": f"执行 {step.name} OK @ {step.temperature_celsius}°C × {step.duration_minutes}min",
            "yield": min(yield_grams, 10.0),
        }

    def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected


# ============================================================================
# SafetyGuard(W17-D:实装 agent_base.SafetyGuard ABC)
# ============================================================================


class SafetyGuard(BaseSafetyGuard):
    """W17-D SafetyGuard 模板

    拦截 3 类危险操作:
    1. 高温(> 800°C) → block,给用户报警
    2. 危险化学品(定义一个简单的黑名单)
    3. 试剂超量(单次 > 100g)

    这是 W17-D 给 W18 XRD 的模板:W18 复用同 SafetyGuard,加辐射检查
    """

    DANGEROUS_CHEMICALS = [
        "HNO3",         # 浓硝酸
        "H2SO4",        # 浓硫酸
        "HF",           # 氢氟酸(特危)
        "HClO4",        # 高氯酸
        "CrO3",         # 铬酐
        "KClO3",        # 氯酸钾(易爆)
    ]
    MAX_REAGENT_GRAMS = 100.0

    def __init__(self, temp_limit: float = HAZARD_TEMP_CELSIUS_LIMIT) -> None:
        self.temp_limit = temp_limit
        self.warnings_count = 0

    def check(self, response: AgentResponse) -> bool:
        """W17-D 默认实现:从 response.artifacts 找 SynthProcedure,检查所有步骤

        True = 通过(可以继续)
        False = 拦截(危险)
        """
        procedure: SynthProcedure | None = response.artifacts.get("procedure") if response.artifacts else None
        if procedure is None:
            return True  # 没 procedure → 默认放行

        # 1. 高温检查
        if procedure.max_temperature() > self.temp_limit:
            self.warnings_count += 1
            return False

        # 2. 化学品黑名单
        for step in procedure.steps:
            for chem in step.chemicals:
                if chem in self.DANGEROUS_CHEMICALS:
                    self.warnings_count += 1
                    return False

        # 3. 试剂超量
        if procedure.target_yield_grams > self.MAX_REAGENT_GRAMS:
            self.warnings_count += 1
            return False

        return True

    def check_procedure(self, procedure: SynthProcedure) -> list[str]:
        """额外接口:返回报警列表(诊断用)"""
        warnings = []
        if procedure.max_temperature() > self.temp_limit:
            warnings.append(
                f"⚠️ 高温报警:最高温度 {procedure.max_temperature()}°C > {self.temp_limit}°C"
            )
        for step in procedure.steps:
            for chem in step.chemicals:
                if chem in self.DANGEROUS_CHEMICALS:
                    warnings.append(f"⚠️ 危险化学品: {chem} (步骤 {step.name})")
        if procedure.target_yield_grams > self.MAX_REAGENT_GRAMS:
            warnings.append(
                f"⚠️ 试剂超量:{procedure.target_yield_grams}g > {self.MAX_REAGENT_GRAMS}g"
            )
        return warnings


# ============================================================================
# 高层入口 — Per W4 Goldens "用 Pechini 法合成 Ca-LLZO"
# ============================================================================


# 一些常见合成的默认步骤(Stage 1 模板,Stage 2 可用户自配)
DEFAULT_PROCEDURES = {
    "Pechini_Ca_LLZO": SynthProcedure(
        target_formula="Ca0.25Li6.5La3Zr1.75O12",
        method="Pechini",
        steps=[
            SynthStep(name="称量硝酸盐", duration_minutes=10, temperature_celsius=25.0,
                     chemicals=["LiNO3", "La(NO3)3", "ZrO(NO3)2", "Ca(NO3)2"]),
            SynthStep(name="配乙二醇溶液", duration_minutes=15, temperature_celsius=25.0,
                     chemicals=["ethylene glycol", "citric acid"]),
            SynthStep(name="球磨混合", duration_minutes=120, temperature_celsius=25.0),
            SynthStep(name="500°C 预烧", duration_minutes=240, temperature_celsius=500.0),
            SynthStep(name="900°C 主烧结", duration_minutes=720, temperature_celsius=900.0),  # > 800°C
            SynthStep(name="XRD 表征交付", duration_minutes=30, temperature_celsius=25.0),
        ],
        target_yield_grams=2.0,
    ),
    "sol_gel_PMMA": SynthProcedure(
        target_formula="PMMA",
        method="sol-gel",
        steps=[
            SynthStep(name="MMA 单体蒸馏", duration_minutes=60, temperature_celsius=80.0),
            SynthStep(name="聚合反应", duration_minutes=240, temperature_celsius=65.0,
                     chemicals=["AIBN"]),
            SynthStep(name="后处理沉淀", duration_minutes=120, temperature_celsius=25.0,
                     chemicals=["methanol"]),
            SynthStep(name="干燥", duration_minutes=600, temperature_celsius=60.0),
        ],
        target_yield_grams=5.0,
    ),
}


def get_default_procedure(name: str) -> SynthProcedure | None:
    """获取 1 个默认 procedure"""
    return DEFAULT_PROCEDURES.get(name)


def estimate_synth_cost(procedure: SynthProcedure) -> float:
    """估算 1 次合成成本(¥)— W17-D 单价约定:
    - 称量 / 配液:¥5/次
    - 球磨:¥20/小时
    - 烧结(< 500°C):¥30/小时
    - 烧结(> 500°C,高温):¥80/小时
    - 干燥 / 蒸馏:¥10/小时
    """
    if not procedure.steps:
        return 0.0
    cost = 0.0
    for step in procedure.steps:
        hours = step.duration_minutes / 60.0
        if step.temperature_celsius > 500:
            cost += 80.0 * hours  # 高温烧结贵
        elif step.temperature_celsius > 100:
            cost += 30.0 * hours  # 中温
        else:
            cost += 10.0 * hours  # 室温/干燥
        cost += 5.0  # 基础费
    return round(cost, 2)
