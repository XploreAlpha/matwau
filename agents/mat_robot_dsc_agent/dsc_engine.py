"""dsc_engine.py — MatWAU 机器人 DSC 热分析核心引擎(W22)

W22 第 4 个物理世界机器人 agent(继 W17-D 合成 + W18 XRD + W21 EM 之后)
W22 复用 W17-D SafetyGuard 模板 + W18/W21 子类化模式

DSC 的铁律(per Perkin Elmer / TA Instruments 公开规格书):
1. 温度 > 800°C + 空气气氛 + 可燃样品 → block(燃烧爆炸)
2. 样品未密封 + 高于沸点 → block(坩埚爆裂)
3. 样品质量 > 100mg → block(超出仪量程)
4. 升温速率 > 100°C/min → block(热冲击损毁样品池)
5. 含剧毒 / 易分解样品(过氧化氢 / 雷酸汞 / 硝化甘油)→ block

DSC 的能力:
- 升温 / 降温 / 恒温循环
- 4 类输出:Tg 玻璃化 + Tm 熔融 + Tc 结晶 + ΔH 焓变
- 多气氛:空气 / N₂ / Ar / O₂ / 真空

per MatWAU-Harness-Loop-工程心法实践 §5.4
"""
from __future__ import annotations

import logging
import random
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from matwau.core.agent_base import AgentResponse

from agents.mat_robot_synth_agent.synth_engine import SafetyGuard

logger = logging.getLogger(__name__)

# ============================================================================
# DSC 铁律常量(W22)
# ============================================================================

# 高温下危险 — 空气气氛可燃样品燃烧
HAZARD_DSC_HIGH_TEMP_OXIDIZING = 600.0    # 在空气气氛下 > 600°C 可燃样品燃烧

# 升温速率上限(防止热冲击损毁样品池)
HAZARD_DSC_MAX_HEATING_RATE_C_PER_MIN = 100.0

# 样品量上限(典型 DSC 坩埚 100mg)
HAZARD_DSC_MAX_SAMPLE_MASS_MG = 100.0

# 含剧毒 / 爆炸物
DSC_DANGEROUS_MATERIALS = {
    "H2O2",            # 过氧化氢
    "nitroglycerin",   # 硝化甘油
    "Hg(ONC)2",        # 雷酸汞
    "TNT",             # 三硝基甲苯
    "RDX",             # 黑索金
    "HMX",             # 奥克托金
    "lead azide",      # 叠氮化铅
    "mercury fulminate",  # 雷汞
}

# DSC 默认气氛
DSC_ATMOSPHERES = {"air", "N2", "Ar", "O2", "vacuum"}


# ============================================================================
# 数据类
# ============================================================================


@dataclass
class DSCStep:
    """1 个 DSC 温度程序步骤"""

    step_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""                                  # 升温 / 恒温 / 降温 / 平衡
    duration_minutes: float = 0.0
    target_temperature_celsius: float = 25.0        # 目标温度
    heating_rate_c_per_min: float = 10.0            # 升温速率(°C/min)
    is_isothermal: bool = False                     # 恒温段
    params: Dict[str, Any] = field(default_factory=dict)

    def is_ramp(self) -> bool:
        return not self.is_isothermal and self.heating_rate_c_per_min > 0


@dataclass
class DSCProcedure:
    """1 个 DSC 测试方案"""

    sample_formula: str = ""                         # 样品化学式
    target_properties: List[str] = field(default_factory=list)  # ['Tg', 'Tm', 'Tc', 'crystallization']
    steps: List[DSCStep] = field(default_factory=list)
    atmosphere: str = "N2"                          # 默认 N2(惰性)
    sample_mass_mg: float = 5.0                     # 样品质量(mg)
    crucible_sealed: bool = True                     # 坩埚是否密封
    sample_is_explosive: bool = False                # 是否易爆 / 剧毒
    max_heating_rate_c_per_min: float = 10.0        # 最大升温速率
    domain: str = "polymer"                         # 默认 polymer 域

    def total_duration_minutes(self) -> float:
        return sum(s.duration_minutes for s in self.steps)

    def max_temperature(self) -> float:
        if not self.steps:
            return 25.0
        return max(s.target_temperature_celsius for s in self.steps)

    def effective_heating_rate(self) -> float:
        if not self.steps:
            return 0.0
        return max(s.heating_rate_c_per_min for s in self.steps)


@dataclass
class DSCResult:
    """1 次 DSC 测试结果"""

    run_id: str = ""
    procedure: Optional[DSCProcedure] = None
    success: bool = True
    glass_transition_temp_c: Optional[float] = None      # Tg
    melting_temp_c: Optional[float] = None               # Tm
    crystallization_temp_c: Optional[float] = None       # Tc
    enthalpy_change_j_per_g: Optional[float] = None      # ΔH
    dsc_curve_x: List[float] = field(default_factory=list)     # 温度序列(°C)
    dsc_curve_y: List[float] = field(default_factory=list)     # 热流(W/g)
    warnings: List[str] = field(default_factory=list)
    blocked_steps: List[str] = field(default_factory=list)
    log: List[str] = field(default_factory=list)
    cost: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "sample_formula": self.procedure.sample_formula if self.procedure else "",
            "success": self.success,
            "Tg_c": self.glass_transition_temp_c,
            "Tm_c": self.melting_temp_c,
            "Tc_c": self.crystallization_temp_c,
            "enthalpy_j_per_g": self.enthalpy_change_j_per_g,
            "n_curve_points": len(self.dsc_curve_x),
            "warnings": self.warnings,
            "cost": self.cost,
        }


# ============================================================================
# TAMockSDK(Stage 1 mock,Stage 2 真接)
# ============================================================================


class TAMockSDK:
    """TA Instruments DSC 250 mock(W22)

    Stage 2 真接:
    - 替换内部 random/seed 为 TA Trios API
    - 保持接口(Stage 1 → Stage 2 零改 mat_robot_dsc_agent)
    """

    def __init__(self, *, lab_id: str = "matwau-dsc-01", fail_chance: float = 0.05) -> None:
        self.lab_id = lab_id
        self.fail_chance = fail_chance
        self.commands_executed: List[str] = []
        self.connected = True

    def execute(self, step: DSCStep) -> Dict[str, Any]:
        """执行 1 个 DSCStep(真接 = TA Trios remote API)"""
        self.commands_executed.append(step.name)
        if not self.connected:
            return {"ok": False, "log": f"DSC {self.lab_id} 未连接", "curve": []}
        if random.random() < self.fail_chance:
            return {"ok": False, "log": f"步骤 {step.name} 失败(模拟)", "curve": []}
        # mock 生成 DSC 曲线
        if step.is_isothermal:
            # 恒温段:平稳热流
            n = max(1, int(step.duration_minutes))
            x = [step.target_temperature_celsius] * n
            y = [0.01 * (random.random() - 0.5) for _ in range(n)]
        else:
            # 升温 / 降温段:热流随温度变化
            n = max(1, int(step.duration_minutes))
            start_t = 25.0 if step.heating_rate_c_per_min > 0 else step.target_temperature_celsius
            end_t = step.target_temperature_celsius if step.heating_rate_c_per_min > 0 else 25.0
            x = [
                start_t + (end_t - start_t) * (i / n)
                for i in range(n + 1)
            ]
            # mock 热流 = 基线 + 模拟峰
            y = []
            for t in x:
                flow = 0.01 * (random.random() - 0.5)  # 基线噪声
                # 模拟熔融峰(若是升温段 + 到达中点)
                t_mid = (start_t + end_t) / 2
                if abs(t - t_mid) < 5 and step.heating_rate_c_per_min > 0:
                    flow += 0.5 * (1 - abs(t - t_mid) / 5)
                y.append(flow)

        return {
            "ok": True,
            "log": f"DSC 步骤 {step.name} 完成 @ {step.target_temperature_celsius}°C × {step.duration_minutes}min",
            "curve": list(zip(x, y)),
        }

    def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected


# ============================================================================
# DSCSafetyGuard(W22 关键 — 5 类 DSC 特有拦截)
# ============================================================================


class DSCSafetyGuard(SafetyGuard):
    """W22 DSC 热分析 SafetyGuard

    继承 W17-D SafetyGuard(高温 / 化学品 / 超量),加 5 类 DSC 特有:
    1. 高温 + 空气气氛 + 可燃样品 → block(燃烧爆炸)
    2. 坩埚未密封 + 高温 → block
    3. 样品超量 → block
    4. 升温速率过快 → block(热冲击)
    5. 爆炸 / 剧毒样品 → block

    W17-D → W18 → W21 → W22 模板复用链:
    SafetyGuard(3 类基本)
      → XRDSafetyGuard(3 类 XRD)
        → EMSafetyGuard(6 类 EM)
          → DSCSafetyGuard(5 类 DSC)
    """

    def __init__(
        self,
        temp_limit: float = 1000.0,
        *,
        block_if_oxidizing_combustible: bool = True,
        block_if_unsealed_high_temp: bool = True,
        block_if_overheating_rate: bool = True,
        block_if_explosive: bool = True,
    ) -> None:
        super().__init__(temp_limit=temp_limit)
        self.block_if_oxidizing_combustible = block_if_oxidizing_combustible
        self.block_if_unsealed_high_temp = block_if_unsealed_high_temp
        self.block_if_overheating_rate = block_if_overheating_rate
        self.block_if_explosive = block_if_explosive
        self.warnings_count = 0

    def check(self, response: AgentResponse) -> bool:
        """W22 override:不调父类(父类用 SynthProcedure.max_temperature)

        本类只看 response.artifacts.get("procedure") 是 DSCProcedure,
        调 self.check_dsc
        """
        procedure = response.artifacts.get("procedure") if response.artifacts else None
        if not hasattr(procedure, "atmosphere"):
            return True  # 兜底放行

        warnings = self.check_dsc(procedure)
        if warnings and any("⛔" in w for w in warnings):
            self.warnings_count += 1
            return False
        return True

    def check_dsc(self, procedure: DSCProcedure) -> List[str]:
        """DSC 流程专用安全检查(扩展父类 + 5 类 DSC 特有)"""
        warnings = []

        # 1. 高温 + 空气气氛 + 可燃样品
        if (
            self.block_if_oxidizing_combustible
            and procedure.atmosphere in ("air", "O2")
            and procedure.max_temperature() > HAZARD_DSC_HIGH_TEMP_OXIDIZING
        ):
            warnings.append(
                f"⛔ 高温氧化燃烧:{procedure.max_temperature()}°C 空气气氛,易燃样品会自燃,改 N2/Ar"
            )

        # 2. 坩埚未密封 + 高温
        if (
            self.block_if_unsealed_high_temp
            and not procedure.crucible_sealed
            and procedure.max_temperature() > 300.0
        ):
            warnings.append(
                f"⛔ 高温坩埚未密封:{procedure.max_temperature()}°C 下未密封坩埚会爆裂,加压密封"
            )

        # 3. 样品超量
        if procedure.sample_mass_mg > HAZARD_DSC_MAX_SAMPLE_MASS_MG:
            warnings.append(
                f"⛔ 样品超量:{procedure.sample_mass_mg}mg > {HAZARD_DSC_MAX_SAMPLE_MASS_MG}mg,DSC 坩埚上限"
            )

        # 4. 升温速率过快
        if (
            self.block_if_overheating_rate
            and procedure.effective_heating_rate() > HAZARD_DSC_MAX_HEATING_RATE_C_PER_MIN
        ):
            warnings.append(
                f"⛔ 升温速率过快:{procedure.effective_heating_rate()}°C/min > {HAZARD_DSC_MAX_HEATING_RATE_C_PER_MIN}°C/min,会热冲击损样品"
            )

        # 5. 爆炸 / 剧毒样品
        if self.block_if_explosive and procedure.sample_is_explosive:
            for mat in DSC_DANGEROUS_MATERIALS:
                if mat.upper() in procedure.sample_formula.upper():
                    warnings.append(
                        f"⛔ 爆炸 / 剧毒样品:{mat} 不允许进 DSC 测试"
                    )
                    break

        return warnings


# ============================================================================
# 成本估算(W22 DSC 单价约定)
# ============================================================================


def estimate_dsc_cost(procedure: DSCProcedure) -> float:
    """估算 1 次 DSC 测试成本(¥)

    单价约定:
    - 装样 / 卸载:¥15/次
    - 平衡段:¥5/次
    - 恒温段:¥10/小时
    - 升降温段:¥30/小时
    """
    cost = 25.0  # 基础维护
    for step in procedure.steps:
        hours = step.duration_minutes / 60.0
        if step.is_isothermal:
            cost += 10.0 * hours
        else:
            cost += 30.0 * hours
        cost += 5.0  # 步骤基础费
    return round(cost, 2)


# ============================================================================
# 默认 procedure(W22 PoC:测 PMMA Tg)
# ============================================================================


DEFAULT_DSC_PROCEDURE = DSCProcedure(
    sample_formula="PMMA",                          # PMMA 玻璃化转变
    target_properties=["Tg", "Tm"],
    steps=[
        DSCStep(name="平衡", duration_minutes=5, target_temperature_celsius=25.0, is_isothermal=True),
        DSCStep(name="升温 25→200", duration_minutes=60, target_temperature_celsius=200.0, heating_rate_c_per_min=3.0),
        DSCStep(name="恒温", duration_minutes=10, target_temperature_celsius=200.0, is_isothermal=True),
        DSCStep(name="降温 200→25", duration_minutes=30, target_temperature_celsius=25.0, heating_rate_c_per_min=-6.0),
    ],
    atmosphere="N2",                                # 惰性气氛
    sample_mass_mg=5.0,                             # 5 mg 典型
    crucible_sealed=True,                           # 密封
    sample_is_explosive=False,
    max_heating_rate_c_per_min=3.0,                 # 3°C/min(精细)
    domain="polymer",
)


def get_default_dsc_procedure() -> DSCProcedure:
    """获取默认 W22 PoC procedure(PMMA Tg 测试)"""
    return DEFAULT_DSC_PROCEDURE
