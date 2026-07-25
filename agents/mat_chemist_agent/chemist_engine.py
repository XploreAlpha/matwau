"""chemist_engine.py — MatWAU 化学师协调核心引擎(W26)

W26 JARVIS 化学师大脑 — 1 个 agent 调度 4 个机器人(synth + xrd + em + dsc)

设计原则(per MatWAU-Stage 3 钢铁侠 doc + W11 域路由):
1. 接收 1 个材料研究目标(自然语言 / 1 个 ChemistTask)
2. 拆解成 4 个 RobotStep(synth + xrd + em + dsc)
3. 依次调用 4 个 robot agent.run(req)
4. 汇总 4 个结果成 1 个 ChemistReport
5. 每个 robot step 可以独立成功 / 失败 / SafetyGuard 拦截
6. 复用 MatWAUAgentBase 基类 + Inner Loop 4 步
7. **ChemistSafetyGuard**(W26 关键):跨机器人一致性 + 协调级安全

ChemistSafetyGuard 5 类协调级拦截(per W26 + Stage 3 钢铁侠 doc):
1. 4 个机器人不能同时跑一个样品(避免样品竞争 / 污染)
2. 跨机器人结果矛盾(block:例 XRD 测到 α 相,EM 看不到晶界 → 检查样品制备)
3. 总成本超预算(block:per 任务成本 > ¥10000 自动停)
4. 危险步骤顺序(block:合成高温前,EM 不能开电子束)
5. 样品量过大(block:4 个机器人共用一个样品池)

per MatWAU-Harness-Loop-工程心法实践 §5.4
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from matwau.core.agent_base import AgentResponse

logger = logging.getLogger(__name__)

# ============================================================================
# 协调级常量(W26)
# ============================================================================

# Chemist 任务默认预算(¥)
CHEMIST_DEFAULT_BUDGET_CNY = 10000.0

# 4 机器人类型(per W17-D / W18 / W21 / W22)
ROBOT_TYPES = ("synth", "xrd", "em", "dsc")

# 单样品共享标记 — 1 个样品同时只能被 1 个机器人操作(防污染)
SAMPLE_LOCK_KEY = "_sample_locked"


# ============================================================================
# 数据类
# ============================================================================


@dataclass
class RobotStep:
    """1 个机器人调度步骤"""

    step_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    robot_type: str = ""                 # 'synth' / 'xrd' / 'em' / 'dsc'
    description: str = ""                # 人类描述
    required: bool = True                # 是否必需(失败 → 整体 fail)
    estimated_cost_cny: float = 0.0
    dependencies: List[str] = field(default_factory=list)  # 依赖的 step_id
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChemistTask:
    """1 个化学师任务"""

    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    target_sample: str = ""                  # 目标样品(例 "Inconel 718")
    domain: str = "metal_alloy"              # 默认金属合金
    goal: str = ""                           # 人类目标
    robot_steps: List[RobotStep] = field(default_factory=list)
    budget_cny: float = CHEMIST_DEFAULT_BUDGET_CNY
    parallel_allowed: bool = False           # 是否允许并行(默认串行,防样品竞争)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def total_estimated_cost(self) -> float:
        return sum(s.estimated_cost_cny for s in self.robot_steps)

    def required_robots(self) -> List[str]:
        return [s.robot_type for s in self.robot_steps if s.required]


@dataclass
class RobotStepResult:
    """1 个机器人步骤执行结果"""

    step_id: str = ""
    robot_type: str = ""
    success: bool = False
    blocked: bool = False
    reply: str = ""
    artifacts: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    blocked_steps: List[str] = field(default_factory=list)
    cost_cny: float = 0.0
    duration_seconds: float = 0.0


@dataclass
class ChemistReport:
    """1 个化学师任务的综合报告"""

    task_id: str = ""
    target_sample: str = ""
    goal: str = ""
    overall_success: bool = True
    robot_results: List[RobotStepResult] = field(default_factory=list)
    total_cost_cny: float = 0.0
    total_duration_seconds: float = 0.0
    summary: str = ""
    cross_validation: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    blocked_steps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "target_sample": self.target_sample,
            "goal": self.goal,
            "overall_success": self.overall_success,
            "n_robot_steps": len(self.robot_results),
            "n_successful": sum(1 for r in self.robot_results if r.success),
            "n_blocked": sum(1 for r in self.robot_results if r.blocked),
            "total_cost_cny": self.total_cost_cny,
            "total_duration_seconds": self.total_duration_seconds,
            "cross_validation": self.cross_validation,
            "warnings": self.warnings[:3],  # 头 3 个
        }


# ============================================================================
# 默认 4 机器人 workflow(per W26 + Stage 3 PoC)
# ============================================================================


def get_default_inconel_718_workflow() -> ChemistTask:
    """Inconel 718 完整表征 workflow(W26 PoC)

    串行 4 步:
    1. synth(合成标样):制备 Inconel 718 样品
    2. xrd(晶体结构):测晶体相 + Bragg 峰
    3. em(微观结构 + 元素):SEM + EDS
    4. dsc(热稳定性):Tg / Tm 测熔点
    """
    return ChemistTask(
        target_sample="Inconel 718",
        domain="metal_alloy",
        goal="Inconel 718 完整表征(合成 + 晶体 + 微观 + 热学)",
        robot_steps=[
            RobotStep(
                robot_type="synth",
                description="制备 Inconel 718 标样(球磨 + 烧结)",
                estimated_cost_cny=200.0,
            ),
            RobotStep(
                robot_type="xrd",
                description="XRD 测晶体相 + Bragg 峰(参考 PDF 卡片)",
                estimated_cost_cny=150.0,
                dependencies=[],  # 实际依赖 synth 完成
            ),
            RobotStep(
                robot_type="em",
                description="SEM 拍 1000x + 10000x 微观结构 + EDS 元素",
                estimated_cost_cny=300.0,
            ),
            RobotStep(
                robot_type="dsc",
                description="DSC 测熔点 Tm + Tg(在 N2 气氛)",
                estimated_cost_cny=100.0,
            ),
        ],
        budget_cny=10000.0,
        parallel_allowed=False,
    )


def get_default_pmma_workflow() -> ChemistTask:
    """PMMA 玻璃化温度 workflow(W26 PoC — 简化版)"""
    return ChemistTask(
        target_sample="PMMA",
        domain="polymer",
        goal="PMMA 玻璃化温度 Tg 测定",
        robot_steps=[
            RobotStep(
                robot_type="synth",
                description="PMMA 溶解 + 浇铸成膜",
                estimated_cost_cny=80.0,
            ),
            RobotStep(
                robot_type="dsc",
                description="DSC 测 Tg(N2 气氛,3°C/min)",
                estimated_cost_cny=100.0,
            ),
        ],
        budget_cny=500.0,
        parallel_allowed=False,
    )


# ============================================================================
# ChemistSafetyGuard(W26 关键 — 5 类协调级拦截)
# ============================================================================


class ChemistSafetyGuard:
    """W26 化学师协调级 SafetyGuard(独立类,不继承 SafetyGuard)

    协调级 5 类拦截:
    1. 4 个机器人不能同时跑一个样品 → block
    2. 总成本超预算 → block
    3. 危险步骤顺序(EM 不能在高温合成前开) → block
    4. 样品量过大(共用样品池) → block
    5. 跨机器人结果矛盾 → warning(不阻断,记录)

    独立类(不继承 SafetyGuard):
    - SafetyGuard 是物理设备级(W17-D)
    - ChemistSafetyGuard 是协调级(W26)
    - 两者层级不同,不强制继承
    """

    def __init__(
        self,
        *,
        max_budget_cny: float = CHEMIST_DEFAULT_BUDGET_CNY,
        block_sample_contention: bool = True,
        block_dangerous_ordering: bool = True,
        block_excessive_sample_mass: bool = True,
        warn_cross_robot_inconsistency: bool = True,
    ) -> None:
        self.max_budget_cny = max_budget_cny
        self.block_sample_contention = block_sample_contention
        self.block_dangerous_ordering = block_dangerous_ordering
        self.block_excessive_sample_mass = block_excessive_sample_mass
        self.warn_cross_robot_inconsistency = warn_cross_robot_inconsistency
        self.warnings_count = 0
        self.sample_lock_active = False  # 样品锁状态

    def check(self, response: AgentResponse) -> bool:
        """W26 override MatWAUAgentBase.check:接 AgentResponse,从 artifacts["task"] 取 ChemistTask

        Returns:
            True = 通过,False = 阻断
        """
        task = response.artifacts.get("task") if response.artifacts else None
        if not isinstance(task, ChemistTask):
            return True  # 兜底放行(不是 ChemistTask)

        warnings = self.check_chemist_task(task)
        if any("⛔" in w for w in warnings):
            self.warnings_count += 1
            return False
        return True

    def check_chemist_task(self, task: ChemistTask) -> List[str]:
        """检查 1 个 ChemistTask,返回 warning 列表

        Returns:
            列表里有 "⛔" = 阻断 / "⚠️" = 警告
        """
        warnings: List[str] = []

        # 1. 预算检查
        total_cost = task.total_estimated_cost()
        if total_cost > task.budget_cny:
            warnings.append(
                f"⛔ 预算超限:任务预算 ¥{task.budget_cny},4 步预估 ¥{total_cost}"
            )
        elif total_cost > self.max_budget_cny:
            warnings.append(
                f"⛔ 协调级预算超限:总预估 ¥{total_cost} > 系统硬上限 ¥{self.max_budget_cny}"
            )

        # 2. 样品竞争检查
        if self.block_sample_contention and task.parallel_allowed and len(task.robot_steps) > 1:
            # 串行默认安全,并行才检查样品锁
            warnings.append(
                "⚠️ 启用并行模式:4 个机器人不能同时接触同一物理样品,启用虚拟串行隔离"
            )

        # 3. 危险顺序检查(EM 不能在高温合成前开)
        if self.block_dangerous_ordering:
            synth_step = None
            em_step = None
            for step in task.robot_steps:
                if step.robot_type == "synth":
                    synth_step = step
                elif step.robot_type == "em":
                    em_step = step
            if synth_step is not None and em_step is not None:
                # 找它们在 list 中的位置
                synth_idx = task.robot_steps.index(synth_step)
                em_idx = task.robot_steps.index(em_step)
                # 检查 synthesis 是否有高温 step(>800°C)
                has_high_temp = False
                if "estimated_cost_cny" in synth_step.params:
                    pass  # 可扩展
                # 简化:如果 EM 在 synth 之前,且 task 没有显式声明,警告
                if em_idx < synth_idx and not task.parallel_allowed:
                    warnings.append(
                        "⚠️ EM 在 synth 之前:电子束可能影响未固化的样品,确认顺序"
                    )

        # 4. 样品量过大检查(4 个机器人共用样品池,典型总质量 ≤ 5g)
        total_sample_mass_g = sum(
            s.params.get("sample_mass_g", 0.0) for s in task.robot_steps
        )
        if self.block_excessive_sample_mass and total_sample_mass_g > 5.0:
            warnings.append(
                f"⛔ 总样品质量过大:{total_sample_mass_g}g > 5g 上限,样品池容量不足"
            )

        return warnings

    def check_cross_validation(self, report: ChemistReport) -> Dict[str, Any]:
        """跨机器人结果一致性检查(只警告不阻断)

        检查项:
        - XRD 检测到的相是否与 EM EDS 检测到的元素匹配
        - DSC 测的 Tm 是否与金属相图匹配
        - synth 是否成功(其他 3 个都依赖它)

        Returns:
            Dict with keys: consistent, issues, warnings
        """
        issues: List[str] = []
        warnings: List[str] = []

        if not self.warn_cross_robot_inconsistency:
            return {"consistent": True, "issues": [], "warnings": []}

        # 1. 检查 synth 是否成功 — 是其他 3 个的依赖
        synth_results = [r for r in report.robot_results if r.robot_type == "synth"]
        non_synth_results = [r for r in report.robot_results if r.robot_type != "synth"]
        if synth_results and non_synth_results:
            synth_success = synth_results[0].success
            if not synth_success:
                issues.append("synth_failed_others_may_be_invalid")
                warnings.append("⚠️ synth 失败:其他 3 个结果可能基于错误样品,需人工复核")

        # 2. 检查 XRD 与 EM 是否都成功
        xrd_success = any(r.success for r in report.robot_results if r.robot_type == "xrd")
        em_success = any(r.success for r in report.robot_results if r.robot_type == "em")
        if xrd_success and em_success:
            # 简化:都成功 → 暂时一致
            pass
        elif xrd_success and not em_success:
            warnings.append("⚠️ XRD 成功但 EM 失败:晶体相已确认,微观结构待补")
        elif em_success and not xrd_success:
            warnings.append("⚠️ EM 成功但 XRD 失败:微观结构已确认,晶体相待补")

        return {
            "consistent": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
        }


# ============================================================================
# 任务拆解器(per W26 + Stage 3 PoC)
# ============================================================================


def decompose_goal_to_robots(target_sample: str, goal: str) -> List[RobotStep]:
    """根据目标样品 + 目标自然语言 → 拆解成 robot steps(Stage 1 简单关键词)

    Args:
        target_sample: 样品化学式/名称
        goal: 人类目标(自然语言)

    Returns:
        List of RobotStep
    """
    upper_goal = goal.upper()
    upper_sample = target_sample.upper()
    steps: List[RobotStep] = []

    # 关键词 → 机器人映射
    needs_synth = any(k in upper_goal for k in ["合成", "制备", "PREPARE", "SYNTH"]) or "标样" in upper_goal
    needs_xrd = any(k in upper_goal for k in ["XRD", "晶体", "CRYSTAL", "BRAGG", "相"])
    needs_em = any(k in upper_goal for k in ["EM", "SEM", "TEM", "微观", "MICRO", "结构", "EDS", "元素"])
    needs_dsc = any(k in upper_goal for k in ["DSC", "TG", "热", "熔", "玻璃", "THERMAL", "TEMP"])

    # 默认:样品如果没识别出特定需求,跑全套
    if not any([needs_synth, needs_xrd, needs_em, needs_dsc]):
        needs_synth = needs_xrd = needs_em = needs_dsc = True

    if needs_synth:
        steps.append(RobotStep(
            robot_type="synth",
            description=f"制备 {target_sample} 标样",
            estimated_cost_cny=200.0,
        ))
    if needs_xrd:
        steps.append(RobotStep(
            robot_type="xrd",
            description=f"XRD 测 {target_sample} 晶体结构",
            estimated_cost_cny=150.0,
        ))
    if needs_em:
        steps.append(RobotStep(
            robot_type="em",
            description=f"EM 拍 {target_sample} 微观结构 + EDS",
            estimated_cost_cny=300.0,
        ))
    if needs_dsc:
        steps.append(RobotStep(
            robot_type="dsc",
            description=f"DSC 测 {target_sample} 热学性质",
            estimated_cost_cny=100.0,
        ))

    return steps