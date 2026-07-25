"""test_mat_chemist_agent.py — W26 化学师协调 agent 测试

目标(per W26 规划):
1. 验证 ChemistTask 数据类结构
2. 验证 ChemistSafetyGuard 5 类协调级拦截
3. 验证 decompose_goal_to_robots 自然语言拆解
4. 验证默认 workflow(Inconel 718 / PMMA)
5. 验证 MatChemistAgent 串行调用 4 个 robot agent
6. 验证 lazy load 4 个 robot agent
7. 验证 cross_validation 跨机器人一致性
8. 验证预算超限拦截
9. 验证协调级样品量过大拦截

per MatWAU-Stage 3 钢铁侠 doc §3.5 Phase 4
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_chemist_agent import (  # noqa: E402
    CHEMIST_DEFAULT_BUDGET_CNY,
    ROBOT_TYPES,
    ChemistReport,
    ChemistSafetyGuard,
    ChemistTask,
    MatChemistAgent,
    RobotStep,
    RobotStepResult,
    decompose_goal_to_robots,
    get_default_inconel_718_workflow,
    get_default_pmma_workflow,
)
from matwau.core.agent_base import (  # noqa: E402
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)


# ============================================================================
# 测试 1: 数据类结构
# ============================================================================


class TestChemistDataClasses:
    """数据类结构(per W26)"""

    def test_robot_step_creation(self):
        step = RobotStep(
            robot_type="synth",
            description="test",
            estimated_cost_cny=100.0,
        )
        assert step.robot_type == "synth"
        assert step.estimated_cost_cny == 100.0
        assert step.required is True  # 默认 True
        assert step.step_id  # 自动生成

    def test_chemist_task_creation(self):
        task = ChemistTask(
            target_sample="Inconel 718",
            goal="test",
            robot_steps=[RobotStep(robot_type="synth", description="x")],
        )
        assert task.target_sample == "Inconel 718"
        assert task.task_id  # 自动生成
        assert task.budget_cny == CHEMIST_DEFAULT_BUDGET_CNY

    def test_chemist_task_total_cost(self):
        task = ChemistTask(
            target_sample="X",
            goal="g",
            robot_steps=[
                RobotStep(robot_type="synth", description="a", estimated_cost_cny=100.0),
                RobotStep(robot_type="xrd", description="b", estimated_cost_cny=200.0),
                RobotStep(robot_type="em", description="c", estimated_cost_cny=300.0),
            ],
        )
        assert task.total_estimated_cost() == 600.0

    def test_chemist_task_required_robots(self):
        task = ChemistTask(
            target_sample="X",
            goal="g",
            robot_steps=[
                RobotStep(robot_type="synth", description="a", required=True),
                RobotStep(robot_type="xrd", description="b", required=False),
                RobotStep(robot_type="em", description="c", required=True),
            ],
        )
        robots = task.required_robots()
        assert "synth" in robots
        assert "xrd" not in robots  # required=False
        assert "em" in robots

    def test_robot_step_result_creation(self):
        result = RobotStepResult(
            step_id="r1",
            robot_type="xrd",
            success=True,
        )
        assert result.success is True
        assert result.cost_cny == 0.0

    def test_chemist_report_to_dict(self):
        report = ChemistReport(
            task_id="t1",
            target_sample="X",
            overall_success=True,
            robot_results=[
                RobotStepResult(step_id="r1", robot_type="synth", success=True),
                RobotStepResult(step_id="r2", robot_type="xrd", success=False, blocked=True),
            ],
            total_cost_cny=300.0,
        )
        d = report.to_dict()
        assert d["task_id"] == "t1"
        assert d["n_successful"] == 1
        assert d["n_blocked"] == 1
        assert d["total_cost_cny"] == 300.0


# ============================================================================
# 测试 2: 默认 workflows
# ============================================================================


class TestDefaultWorkflows:
    """默认 workflow(per W26 PoC)"""

    def test_inconel_718_workflow_has_4_steps(self):
        """Inconel 718 workflow 4 步(synth/xrd/em/dsc)"""
        task = get_default_inconel_718_workflow()
        assert task.target_sample == "Inconel 718"
        assert task.domain == "metal_alloy"
        assert len(task.robot_steps) == 4
        robots = [s.robot_type for s in task.robot_steps]
        assert robots == ["synth", "xrd", "em", "dsc"]

    def test_inconel_718_workflow_budget(self):
        task = get_default_inconel_718_workflow()
        assert task.budget_cny == 10000.0
        # 总成本应在预算内
        assert task.total_estimated_cost() < task.budget_cny

    def test_pmma_workflow_has_2_steps(self):
        """PMMA workflow 2 步(synth + dsc)"""
        task = get_default_pmma_workflow()
        assert task.target_sample == "PMMA"
        assert task.domain == "polymer"
        assert len(task.robot_steps) == 2
        robots = [s.robot_type for s in task.robot_steps]
        assert robots == ["synth", "dsc"]

    def test_pmma_workflow_budget(self):
        task = get_default_pmma_workflow()
        # PMMA 测试便宜
        assert task.budget_cny <= 1000.0

    def test_robot_types_constant(self):
        """ROBOT_TYPES 包含 4 机器人"""
        assert "synth" in ROBOT_TYPES
        assert "xrd" in ROBOT_TYPES
        assert "em" in ROBOT_TYPES
        assert "dsc" in ROBOT_TYPES
        assert len(ROBOT_TYPES) == 4


# ============================================================================
# 测试 3: decompose_goal_to_robots 自然语言拆解
# ============================================================================


class TestDecomposeGoalToRobots:
    """decompose_goal_to_robots(W26 关键 — 自然语言拆解)"""

    def test_full_keywords_decompose(self):
        """'制备 XRD EM DSC 完整表征' → 4 步"""
        steps = decompose_goal_to_robots("Inconel 718", "制备 XRD 测相 EM 拍微观 DSC 测热")
        robots = [s.robot_type for s in steps]
        assert "synth" in robots
        assert "xrd" in robots
        assert "em" in robots
        assert "dsc" in robots

    def test_only_xrd_em(self):
        """'XRD + EM 表征' → 2 步"""
        steps = decompose_goal_to_robots("X", "XRD 测相 EM 微观")
        robots = [s.robot_type for s in steps]
        assert robots == ["xrd", "em"]
        assert "synth" not in robots
        assert "dsc" not in robots

    def test_only_dsc(self):
        """'测 Tg' → 1 步 dsc"""
        steps = decompose_goal_to_robots("PMMA", "测 Tg 玻璃化")
        robots = [s.robot_type for s in steps]
        assert robots == ["dsc"]

    def test_no_keywords_full_workflow(self):
        """没关键词 → 全套 4 步"""
        steps = decompose_goal_to_robots("X", "测试 X")
        assert len(steps) == 4

    def test_english_keywords(self):
        """英文关键词 'crystal micro thermal'"""
        steps = decompose_goal_to_robots("X", "Crystal micro structure thermal analysis")
        robots = [s.robot_type for s in steps]
        assert "xrd" in robots
        assert "em" in robots
        assert "dsc" in robots


# ============================================================================
# 测试 4: ChemistSafetyGuard 5 类协调级拦截
# ============================================================================


class TestChemistSafetyGuard:
    """ChemistSafetyGuard 5 类协调级拦截(W26)"""

    def test_default_construct(self):
        sg = ChemistSafetyGuard()
        assert sg.max_budget_cny == CHEMIST_DEFAULT_BUDGET_CNY
        assert sg.block_sample_contention is True

    def test_check_safe_task_returns_no_blocks(self):
        """安全 task → 没 ⛔"""
        sg = ChemistSafetyGuard()
        task = get_default_inconel_718_workflow()
        warnings = sg.check_chemist_task(task)
        # 默认 workflow 应该是安全的
        hard_blocks = [w for w in warnings if "⛔" in w]
        assert len(hard_blocks) == 0

    def test_check_over_budget(self):
        """超预算 → block"""
        sg = ChemistSafetyGuard()
        task = ChemistTask(
            target_sample="X",
            goal="test",
            robot_steps=[
                RobotStep(robot_type="synth", description="a", estimated_cost_cny=20000.0),
            ],
            budget_cny=1000.0,
        )
        warnings = sg.check_chemist_task(task)
        hard_blocks = [w for w in warnings if "⛔" in w]
        assert len(hard_blocks) >= 1
        assert any("预算" in w for w in hard_blocks)

    def test_check_excessive_sample_mass(self):
        """样品量过大 → block"""
        sg = ChemistSafetyGuard()
        task = ChemistTask(
            target_sample="X",
            goal="test",
            robot_steps=[
                RobotStep(robot_type="synth", description="a",
                          params={"sample_mass_g": 10.0}),  # 10g 过大
                RobotStep(robot_type="xrd", description="b",
                          params={"sample_mass_g": 5.0}),
            ],
            budget_cny=10000.0,
        )
        warnings = sg.check_chemist_task(task)
        # 总样品质量 15g > 5g 上限 → block
        hard_blocks = [w for w in warnings if "⛔" in w]
        assert any("样品质量" in w or "样品" in w for w in hard_blocks)

    def test_check_parallel_warning(self):
        """并行模式 → 警告"""
        sg = ChemistSafetyGuard(block_sample_contention=True)
        task = ChemistTask(
            target_sample="X",
            goal="test",
            robot_steps=[
                RobotStep(robot_type="synth", description="a"),
                RobotStep(robot_type="xrd", description="b"),
            ],
            parallel_allowed=True,
        )
        warnings = sg.check_chemist_task(task)
        # 警告(不阻断)
        soft_warnings = [w for w in warnings if "⚠️" in w]
        assert any("并行" in w or "隔离" in w for w in soft_warnings)

    def test_check_base_class_check_method(self):
        """W26 override MatWAUAgentBase.check 接 AgentResponse"""
        sg = ChemistSafetyGuard()
        # 不是 ChemistTask → 兜底放行
        resp = AgentResponse(reply="ok", artifacts={"task": None}, confidence=1.0)
        assert sg.check(resp) is True
        # 是 ChemistTask → 正常检查
        task = get_default_inconel_718_workflow()
        resp2 = AgentResponse(reply="ok", artifacts={"task": task}, confidence=1.0)
        assert sg.check(resp2) is True

    def test_cross_validation(self):
        """跨机器人一致性检查"""
        sg = ChemistSafetyGuard()
        # synth 失败,其他成功
        report = ChemistReport(
            task_id="t1",
            target_sample="X",
            overall_success=False,
            robot_results=[
                RobotStepResult(step_id="r1", robot_type="synth", success=False, blocked=True),
                RobotStepResult(step_id="r2", robot_type="xrd", success=True),
                RobotStepResult(step_id="r3", robot_type="em", success=True),
            ],
        )
        cv = sg.check_cross_validation(report)
        # synth 失败 → 不一致 + 警告
        assert cv["consistent"] is False
        assert "synth_failed_others_may_be_invalid" in cv["issues"]
        assert any("synth" in w.lower() for w in cv["warnings"])

    def test_cross_validation_xrd_em_consistent(self):
        """XRD + EM 都成功 → 一致"""
        sg = ChemistSafetyGuard()
        report = ChemistReport(
            task_id="t1",
            target_sample="X",
            overall_success=True,
            robot_results=[
                RobotStepResult(step_id="r1", robot_type="synth", success=True),
                RobotStepResult(step_id="r2", robot_type="xrd", success=True),
                RobotStepResult(step_id="r3", robot_type="em", success=True),
            ],
        )
        cv = sg.check_cross_validation(report)
        assert cv["consistent"] is True

    def test_cross_validation_partial_results_warning(self):
        """XRD 成功 EM 失败 → warning"""
        sg = ChemistSafetyGuard()
        report = ChemistReport(
            task_id="t1",
            target_sample="X",
            overall_success=False,
            robot_results=[
                RobotStepResult(step_id="r1", robot_type="synth", success=True),
                RobotStepResult(step_id="r2", robot_type="xrd", success=True),
                RobotStepResult(step_id="r3", robot_type="em", success=False, blocked=True),
            ],
        )
        cv = sg.check_cross_validation(report)
        # XRD 成功 + EM 失败 → 警告(晶体已确认,微观待补)
        assert any("EM" in w or "微观" in w for w in cv["warnings"])


# ============================================================================
# 测试 5: MatChemistAgent 默认行为
# ============================================================================


class TestMatChemistAgentBasics:
    """MatChemistAgent 基本行为"""

    def test_agent_inherits_base(self):
        """MatChemistAgent 继承 MatWAUAgentBase"""
        agent = MatChemistAgent()
        assert isinstance(agent, MatWAUAgentBase)

    def test_agent_name(self):
        agent = MatChemistAgent()
        assert agent.name == "mat-chemist-agent"

    def test_default_safety_guard_is_chemist_safety_guard(self):
        """默认 safety_guard 是 ChemistSafetyGuard"""
        agent = MatChemistAgent()
        assert isinstance(agent.safety_guard, ChemistSafetyGuard)

    def test_system_prompt_describes_coordinator_role(self):
        agent = MatChemistAgent()
        prompt = agent.system_prompt()
        assert "协调" in prompt or "chemist" in prompt.lower() or "化学师" in prompt


# ============================================================================
# 测试 6: MatChemistAgent 串行调用 4 robot
# ============================================================================


class TestMatChemistAgentRun:
    """MatChemistAgent.run 串行 4 机器人"""

    def test_run_with_inconel_718_default(self):
        """跑 Inconel 718 默认 workflow"""
        agent = MatChemistAgent()
        req = AgentRequest(
            run_id="w26-inconel-001",
            message="测 Inconel 718 完整表征",
            artifacts={"task": get_default_inconel_718_workflow()},
        )
        resp = agent.run(req)
        # 4 个 robot step 都被调用
        assert resp.artifacts["n_robot_steps"] == 4
        # 所有 4 个 robot type 都执行了
        robot_types = [r["robot_type"] for r in resp.artifacts["robot_results"]]
        assert "synth" in robot_types
        assert "xrd" in robot_types
        assert "em" in robot_types
        assert "dsc" in robot_types

    def test_run_with_pmma_workflow(self):
        """跑 PMMA workflow"""
        agent = MatChemistAgent()
        req = AgentRequest(
            run_id="w26-pmma-001",
            message="测 PMMA Tg",
            artifacts={"task": get_default_pmma_workflow()},
        )
        resp = agent.run(req)
        assert resp.artifacts["n_robot_steps"] == 2
        robots = [r["robot_type"] for r in resp.artifacts["robot_results"]]
        assert robots == ["synth", "dsc"]

    def test_run_with_no_task_uses_default(self):
        """没传 task → 默认 Inconel 718 workflow"""
        agent = MatChemistAgent()
        req = AgentRequest(
            run_id="w26-default-001",
            message="测 Inconel 718",
        )
        resp = agent.run(req)
        # 默认 task 是 Inconel 718 workflow
        assert resp.artifacts["target_sample"] == "Inconel 718"
        assert resp.artifacts["n_robot_steps"] == 4

    def test_run_returns_valid_response(self):
        """run 返回有效 AgentResponse"""
        agent = MatChemistAgent()
        req = AgentRequest(
            run_id="w26-001",
            message="test",
            artifacts={"task": get_default_pmma_workflow()},
        )
        resp = agent.run(req)
        assert isinstance(resp, AgentResponse)
        assert resp.confidence >= 0.0
        assert "n_successful" in resp.artifacts
        assert "robot_results" in resp.artifacts


# ============================================================================
# 测试 7: 跨机器人结果一致性
# ============================================================================


class TestCrossValidation:
    """跨机器人结果一致性(W26 关键 — JARVIS 终极特性)"""

    def test_cross_validation_in_artifacts(self):
        """artifacts 包含 cross_validation"""
        agent = MatChemistAgent()
        req = AgentRequest(
            run_id="w26-cv-001",
            message="test",
            artifacts={"task": get_default_pmma_workflow()},
        )
        resp = agent.run(req)
        assert "cross_validation" in resp.artifacts
        cv = resp.artifacts["cross_validation"]
        assert "consistent" in cv
        assert "warnings" in cv


# ============================================================================
# 测试 8: MatChemistAgent lazy load 4 robot
# ============================================================================


class TestLazyLoadRobots:
    """MatChemistAgent 懒加载 4 robot agent"""

    def test_lazy_load_synth(self):
        agent = MatChemistAgent()
        assert agent.synth_agent is None  # 还没 load
        a = agent._get_robot_agent("synth")
        assert a is not None
        assert agent.synth_agent is not None

    def test_lazy_load_xrd(self):
        agent = MatChemistAgent()
        a = agent._get_robot_agent("xrd")
        assert a is not None
        assert agent.xrd_agent is not None

    def test_lazy_load_em(self):
        agent = MatChemistAgent()
        a = agent._get_robot_agent("em")
        assert a is not None
        assert agent.em_agent is not None

    def test_lazy_load_dsc(self):
        agent = MatChemistAgent()
        a = agent._get_robot_agent("dsc")
        assert a is not None
        assert agent.dsc_agent is not None

    def test_unknown_robot_returns_none(self):
        agent = MatChemistAgent()
        a = agent._get_robot_agent("unknown")
        assert a is None

    def test_pass_explicit_robot_agents(self):
        """显式传 4 个 robot agent"""
        mock_synth = MagicMock()
        mock_xrd = MagicMock()
        mock_em = MagicMock()
        mock_dsc = MagicMock()
        agent = MatChemistAgent(
            synth_agent=mock_synth,
            xrd_agent=mock_xrd,
            em_agent=mock_em,
            dsc_agent=mock_dsc,
        )
        assert agent.synth_agent is mock_synth
        assert agent.xrd_agent is mock_xrd
        assert agent.em_agent is mock_em
        assert agent.dsc_agent is mock_dsc


# ============================================================================
# 测试 9: 协调级阻断
# ============================================================================


class TestChemistBlocking:
    """ChemistSafetyGuard 阻断 + Chemist 处理阻断"""

    def test_over_budget_blocks_chemist(self):
        """超预算任务被 chemist 阻断"""
        agent = MatChemistAgent()
        task = ChemistTask(
            target_sample="X",
            goal="test",
            robot_steps=[
                RobotStep(robot_type="synth", description="a", estimated_cost_cny=50000.0),
            ],
            budget_cny=100.0,
        )
        req = AgentRequest(
            run_id="w26-budget-001",
            message="test",
            artifacts={"task": task},
        )
        resp = agent.run(req)
        # 应被阻断
        assert resp.artifacts.get("blocked") is True
        assert resp.confidence == 0.0

    def test_excessive_sample_mass_blocks_chemist(self):
        """样品量过大被 chemist 阻断"""
        agent = MatChemistAgent()
        task = ChemistTask(
            target_sample="X",
            goal="test",
            robot_steps=[
                RobotStep(robot_type="synth", description="a",
                          params={"sample_mass_g": 10.0}),
                RobotStep(robot_type="xrd", description="b",
                          params={"sample_mass_g": 5.0}),
            ],
            budget_cny=10000.0,
        )
        req = AgentRequest(
            run_id="w26-mass-001",
            message="test",
            artifacts={"task": task},
        )
        resp = agent.run(req)
        assert resp.artifacts.get("blocked") is True


# ============================================================================
# 测试 10: 总览 + Stage 3 钢铁侠
# ============================================================================


class TestW26Overview:
    """W26 总览 — JARVIS 化学师雏形"""

    def test_5_agent_ecosystem_complete(self):
        """5 件生态完成(4 机器人 + 1 化学师)"""
        from agents.mat_robot_synth_agent import MatRobotSynthAgent
        from agents.mat_robot_xrd_agent import MatRobotXrdAgent
        from agents.mat_robot_em_agent import MatRobotEmAgent
        from agents.mat_robot_dsc_agent import MatRobotDscAgent

        synth = MatRobotSynthAgent()
        xrd = MatRobotXrdAgent()
        em = MatRobotEmAgent()
        dsc = MatRobotDscAgent()
        chemist = MatChemistAgent(
            synth_agent=synth,
            xrd_agent=xrd,
            em_agent=em,
            dsc_agent=dsc,
        )

        task = get_default_inconel_718_workflow()
        req = AgentRequest(
            run_id="w26-overview-001",
            message="测 Inconel 718",
            artifacts={"task": task},
        )
        resp = chemist.run(req)
        # 5 件都参与了
        assert resp.artifacts["n_robot_steps"] == 4
        # 协调器汇总
        assert "summary" in resp.artifacts
        # cross-validation
        assert "cross_validation" in resp.artifacts