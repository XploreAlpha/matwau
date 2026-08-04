"""em_engine.py — MatWAU 机器人电镜表征核心引擎(W21)

W21 第 3 个物理世界机器人 agent(SEM / TEM / STEM)
W21 复用 W17-D SafetyGuard 模板 + W18 XRDSafetyGuard 子类化模式

电镜的铁律(Stage 3 钢铁侠 doc):
1. 真空度不足 → block(防镜筒崩裂)
2. 电子束电压 > 30 kV 且舱门开 → block
3. 样品不导电 & 没喷金 → block(SEM 模式)
4. 高能电子束直接照生物样品 → block(辐照损伤)
5. 样品含易挥发/含水未脱水 → block(真空污染)
6. 磁敏感样品不抗磁化 → 警告(TEM)

电镜的能力:
- 拍照:100x → 100,000x 多档成像
- 元素分析:EDS / EDX(扫描能谱)
- 衍射:SAED(选区电子衍射,TEM 模式)
- 数据:image.tif + elements.json + grain_size.json

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

# ============================================================================
# 电镜铁律常量(W21)
# ============================================================================

HAZARD_EM_DOOR_OPEN = True             # 舱门状态(默认违规)
HAZARD_EM_VACUUM_OK = True             # 真空度是否达标(默认 OK)
HAZARD_EM_NO_CONDUCTIVE_COATING = False  # 喷金是否做了(SEM 样品)
HAZARD_EM_HIGH_VOLTAGE_KV = 30.0       # 高压电子束阈值

# 真空度阈值(粗糙模拟 — 真实仪器用 Pa,W21 用 0-1 标准值,>0.95 算 ok)
VACUUM_THRESHOLD = 0.95

# 易挥发 / 含水物质 — 不进电镜真空样品室
EM_VOLATILE_MATERIALS = {
    "H2O",            # 水
    "ethanol",        # 乙醇
    "methanol",       # 甲醇
    "acetone",        # 丙酮
    "NH4Cl",          # 氯化铵(易分解)
    "Mg(OH)2",        # 氢氧化镁(真空失水)
}

# 易辐射分解 / 不耐电子束物质
EM_RADIATION_DAMAGE_MATERIALS = {
    "TBP",            # 磷酸三丁酯
    "BaP",            # 苯并芘
    "PMMA",           # PMMA 电子束下易解聚
    "polystyrene",    # 聚苯乙烯
    "biological",     # 生物样品缩写
}

# 磁敏感样品
EM_MAGNETIC_MATERIALS = {
    "Fe",             # 纯铁
    "Co",             # 钴
    "Ni",             # 镍
    "NdFeB",          # 钕铁硼磁铁
    "permalloy",      # 坡莫合金
    "ferrite",        # 铁氧体
}


# ============================================================================
# 数据类
# ============================================================================


@dataclass
class EMStep:
    """1 个电镜步骤"""

    step_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""                              # 装样 / 抽真空 / 拍照 / 元素分析 / 卸载
    duration_minutes: float = 0.0
    magnification: int = 1000                   # 放大倍数(100 / 1000 / 10000 / 100000)
    beam_voltage_kv: float = 15.0               # 电子束电压
    beam_current_na: float = 1.0                # 电子束电流(nA)
    imaging_mode: str = "SEM"                   # SEM / TEM / STEM / EDS
    params: dict[str, Any] = field(default_factory=dict)

    def is_high_voltage(self) -> bool:
        return self.beam_voltage_kv > HAZARD_EM_HIGH_VOLTAGE_KV


@dataclass
class EMProcedure:
    """1 个电镜测试方案"""

    sample_formula: str = ""                     # 样品化学式
    target_imaging_modes: list[str] = field(default_factory=list)  # ['SEM', 'EDS']
    steps: list[EMStep] = field(default_factory=list)
    door_open: bool = HAZARD_EM_DOOR_OPEN       # 默认违规
    vacuum_ok: bool = HAZARD_EM_VACUUM_OK        # 默认 OK
    sample_conductive_coated: bool = HAZARD_EM_NO_CONDUCTIVE_COATING  # 默认没喷金
    sample_is_magnetic: bool = False            # 默认非磁性
    sample_is_biological: bool = False          # 默认非生物
    sample_is_volatile: bool = False            # 默认非易挥发
    sample_is_radiation_sensitive: bool = False  # 默认非易辐照损伤
    domain: str = "inorganic_crystal"           # 域标识(inorganic_crystal / nano / metal_alloy / polymer)

    def total_duration_minutes(self) -> float:
        return sum(s.duration_minutes for s in self.steps)

    def max_voltage(self) -> float:
        if not self.steps:
            return 0.0
        return max(s.beam_voltage_kv for s in self.steps)


@dataclass
class EMResult:
    """1 次电镜测试结果"""

    run_id: str = ""
    procedure: EMProcedure | None = None
    success: bool = True
    images: list[dict[str, Any]] = field(default_factory=list)        # [{"path": "...", "mag": 1000, "mode": "SEM"}]
    elements_detected: list[dict[str, Any]] = field(default_factory=list)  # EDS 输出 [{"element": "Fe", "wt_pct": 65.2}]
    diffraction_peaks: list[dict[str, float]] = field(default_factory=list)  # SAED 输出(TEM 模式)
    grain_size_um: float | None = None
    warnings: list[str] = field(default_factory=list)
    blocked_steps: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    cost: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "sample_formula": self.procedure.sample_formula if self.procedure else "",
            "success": self.success,
            "n_images": len(self.images),
            "n_elements_detected": len(self.elements_detected),
            "grain_size_um": self.grain_size_um,
            "warnings": self.warnings,
            "blocked_steps": self.blocked_steps,
            "cost": self.cost,
        }


# ============================================================================
# ZeissMockSDK / TescanMockSDK(Stage 1 mock,Stage 2 真接)
# ============================================================================


class ZeissMockSDK:
    """Zeiss Sigma FE-SEM mock(W21)

    Stage 2 真接:
    - 替换内部 random/seed 为 Zeiss SmartSEM API
    - 保持接口(Stage 1 → Stage 2 零改 mat_robot_em_agent)
    """

    def __init__(self, *, lab_id: str = "matwau-em-01", fail_chance: float = 0.05) -> None:
        self.lab_id = lab_id
        self.fail_chance = fail_chance
        self.commands_executed: list[str] = []
        self.connected = True

    def execute(self, step: EMStep) -> dict[str, Any]:
        """执行 1 个 EMStep(真接 = Zeiss SmartSEM remote API)"""
        self.commands_executed.append(step.name)
        if not self.connected:
            return {
                "ok": False,
                "log": f"电镜 {self.lab_id} 未连接",
                "images": [],
                "elements": [],
            }
        if random.random() < self.fail_chance:
            return {
                "ok": False,
                "log": f"步骤 {step.name} 失败(模拟)",
                "images": [],
                "elements": [],
            }
        # mock 输出
        if "EDS" in step.imaging_mode or "元素" in step.name:
            # 元素分析
            elements = [
                {"element": "Fe", "wt_pct": 65.0 + random.randint(-3, 3)},
                {"element": "Cr", "wt_pct": 18.5 + random.randint(-2, 2)},
                {"element": "Ni", "wt_pct": 9.5 + random.randint(-1, 1)},
                {"element": "Mo", "wt_pct": 2.8 + random.randint(0, 1)},
            ]
            return {
                "ok": True,
                "log": f"EDS 分析完成,{len(elements)} 元素检出",
                "images": [],
                "elements": elements,
            }
        elif "TEM" in step.imaging_mode or "SAED" in step.name:
            # TEM 衍射
            return {
                "ok": True,
                "log": f"TEM/SAED 完成,mag {step.magnification}x",
                "images": [{"path": f"mock:SAED_{step.step_id}.tif", "mag": step.magnification, "mode": "SAED"}],
                "elements": [],
            }
        else:
            # SEM 成像
            mag = step.magnification
            n = max(1, mag // 1000)  # mag 越大图越多
            images = [
                {
                    "path": f"mock:SEM_{step.step_id}_{i}.tif",
                    "mag": mag,
                    "mode": step.imaging_mode,
                    "size_pixel": 1024,
                }
                for i in range(n)
            ]
            return {
                "ok": True,
                "log": f"SEM 拍照完成 {n} 张,mag {mag}x",
                "images": images,
                "elements": [],
            }

    def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected


# ============================================================================
# EMSafetyGuard(W21 关键 — 6 类电镜特有拦截)
# ============================================================================


class EMSafetyGuard(SafetyGuard):
    """W21 电镜辐射防护 SafetyGuard

    继承 W17-D SafetyGuard(高温 / 化学品 / 超量),加 6 类电镜特有检查:
    1. 真空度不足 → block
    2. 舱门开 → block
    3. SEM 样品没喷金 → block
    4. 易挥发物质 → block
    5. 易辐照损伤物质 → block
    6. 磁性样品 → warnings(不能 hard block,只警告)

    这是 W17-D → W18 → W21 模板复用链:
    W17-D SafetyGuard(3 类) → W18 XRDSafetyGuard(3 类 XRD) → W21 EMSafetyGuard(6 类 EM)
    """

    def __init__(
        self,
        temp_limit: float = 1000.0,
        *,
        block_if_door_open: bool = True,
        block_if_not_vacuum: bool = True,
        block_if_no_coating: bool = True,
        block_if_volatile: bool = True,
        block_if_radiation_damage: bool = True,
        warn_if_magnetic: bool = True,
    ) -> None:
        super().__init__(temp_limit=temp_limit)
        self.block_if_door_open = block_if_door_open
        self.block_if_not_vacuum = block_if_not_vacuum
        self.block_if_no_coating = block_if_no_coating
        self.block_if_volatile = block_if_volatile
        self.block_if_radiation_damage = block_if_radiation_damage
        self.warn_if_magnetic = warn_if_magnetic
        self.warnings_count = 0

    def check(self, response: AgentResponse) -> bool:
        """W21 override:不调父类(父类用 SynthProcedure.max_temperature)

        本类只看 response.artifacts.get("procedure") 是 EMProcedure,
        调 self.check_em
        """
        # local import 防循环
        # (EMProcedure 在同模块,本类也在同模块)
        procedure = response.artifacts.get("procedure") if response.artifacts else None
        if not hasattr(procedure, "door_open"):
            return True  # 兜底放行(不是 EMProcedure)

        warnings = self.check_em(procedure)
        if warnings and any("block" in w.lower() or "⛔" in w for w in warnings):
            self.warnings_count += 1
            return False
        return True

    def check_em(self, procedure: EMProcedure) -> list[str]:
        """电镜流程专用安全检查(扩展父类 + 6 类 EM 特有)"""
        warnings = []

        # 1. 真空度检查(W21 铁律)
        if self.block_if_not_vacuum and not procedure.vacuum_ok:
            warnings.append(
                "⛔ 镜筒真空度不足:必须 < 1e-3 Pa 才能开电子束(SEM/TEM 镜筒会崩裂)"
            )

        # 2. 舱门检查
        if self.block_if_door_open and procedure.door_open:
            warnings.append(
                "⛔ 电镜舱门开着:电子束辐射危险,关舱门再启动电子枪"
            )

        # 3. SEM 喷金检查
        if (
            self.block_if_no_coating
            and "SEM" in procedure.target_imaging_modes
            and not procedure.sample_conductive_coated
        ):
            warnings.append(
                "⛔ SEM 样品没喷金:不导电样品必须做 Au/Pt 涂层,否则图像充电失真"
            )

        # 4. 易挥发物质
        if self.block_if_volatile and procedure.sample_is_volatile:
            for mat in EM_VOLATILE_MATERIALS:
                if mat.upper() in procedure.sample_formula.upper():
                    warnings.append(
                        f"⛔ 样品含易挥发物质 {mat}:污染真空样品室,先脱水/冻干"
                    )
                    break

        # 5. 易辐照损伤
        if self.block_if_radiation_damage and procedure.sample_is_radiation_sensitive:
            for mat in EM_RADIATION_DAMAGE_MATERIALS:
                if mat.upper() in procedure.sample_formula.upper():
                    warnings.append(
                        f"⛔ 样品 {mat} 在电子束下易辐照损伤:用低剂量 + 低温样品台"
                    )
                    break

        # 6. 磁性样品(只警告不阻断 — TEM 特殊模式可观察)
        if self.warn_if_magnetic and procedure.sample_is_magnetic:
            for mat in EM_MAGNETIC_MATERIALS:
                if mat.upper() in procedure.sample_formula.upper():
                    warnings.append(
                        f"⚠️ 磁性样品 {mat}:会干扰电子束,降束流 + 短曝光"
                    )
                    break

        return warnings


# ============================================================================
# 成本估算(W21 单价约定)
# ============================================================================


def estimate_em_cost(procedure: EMProcedure) -> float:
    """估算 1 次电镜测试成本(¥)

    单价约定:
    - 装样 / 卸载:¥20/次(电镜装样品要放真空)
    - 抽真空:¥30/次
    - SEM 拍照:¥40/小时
    - TEM 高分辨率拍照:¥80/小时
    - EDS 元素分析:¥60/次
    - SAED 衍射:¥50/次
    """
    cost = 40.0  # 基础维护
    for step in procedure.steps:
        hours = step.duration_minutes / 60.0
        if "抽真空" in step.name or "pump" in step.name.lower():
            cost += 30.0
        elif "装样" in step.name or "卸载" in step.name:
            cost += 20.0
        elif "EDS" in step.imaging_mode or "元素" in step.name:
            cost += 60.0
        elif "TEM" in step.imaging_mode or "SAED" in step.name:
            cost += 50.0 + 80.0 * hours
        elif "SEM" in step.imaging_mode:
            cost += 40.0 * hours
        else:
            # 未知模式按 SEM 计
            cost += 40.0 * hours
    return round(cost, 2)


# ============================================================================
# 默认 procedure + 默认电镜(per W21 钢铁侠 PoC)
# ============================================================================


DEFAULT_EM_PROCEDURE = EMProcedure(
    sample_formula="Inconel 718",          # 默认测金属合金(W17-A 域扩展)
    target_imaging_modes=["SEM", "EDS"],
    steps=[
        EMStep(name="装样", duration_minutes=10),
        EMStep(name="抽真空", duration_minutes=20),
        EMStep(name="SEM 1000x 拍照", duration_minutes=15, magnification=1000, imaging_mode="SEM", beam_voltage_kv=15.0),
        EMStep(name="SEM 10000x 拍照", duration_minutes=20, magnification=10000, imaging_mode="SEM", beam_voltage_kv=15.0),
        EMStep(
            name="EDS 元素分析", duration_minutes=30, imaging_mode="EDS", beam_voltage_kv=20.0,
            params={"sample_formula": "Inconel 718"},  # W24: 让 RealSDK 拿到样品名查标准组成
        ),
        EMStep(name="卸载", duration_minutes=10),
    ],
    door_open=False,                          # 默认安全
    vacuum_ok=True,                           # 默认安全
    sample_conductive_coated=True,            # 喷金已做
    sample_is_magnetic=True,                  # Inconel 718 是 Ni-Fe 基,含磁性
    domain="metal_alloy",
)


def get_default_em_procedure() -> EMProcedure:
    """获取默认 W21 PoC procedure(Inconel 718 SEM + EDS)"""
    return DEFAULT_EM_PROCEDURE
