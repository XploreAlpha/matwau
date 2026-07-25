"""mat_chemist_agent.py — MatWAU 化学师协调 agent(W26)

W26 第 5 个物理世界 agent 角色(不是机器人,而是协调员)
W26 关键:
- 接收 1 个材料研究目标 → 拆解成 4 个 robot step
- 依次调用 4 个 robot agent(synth + xrd + em + dsc)
- 汇总 4 个结果成 1 个 ChemistReport
- ChemistSafetyGuard 5 类协调级拦截

继承 MatWAUAgentBase(per Harness & Loop 心法):
- 11 agent 全部独立 Harness + 共用 Inner Loop 基类
- ChemistSafetyGuard 是协调级(W26),不继承 SafetyGuard(物理设备级)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from matwau.core.agent_base import (
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)

from .chemist_engine import (
    ChemistReport,
    ChemistSafetyGuard,
    ChemistTask,
    RobotStep,
    RobotStepResult,
    decompose_goal_to_robots,
    get_default_inconel_718_workflow,
    get_default_pmma_workflow,
)

logger = logging.getLogger(__name__)


class MatChemistAgent(MatWAUAgentBase):
    """化学师协调 agent(W26 — Stage 3 钢铁侠 Phase 4 第 5 件)

    W26 角色:JARVIS 化学师大脑(协调 4 个机器人)
    W26 价值点:
    - 1 个 agent 调度 4 个 robot agent(Stage 3 Phase 4 入口)
    - 拆解自然语言目标 → robot steps
    - ChemistSafetyGuard 协调级 5 类拦截
    - 跨机器人结果一致性 cross_validation

    用法:
        agent = MatChemistAgent()
        req = AgentRequest(
            run_id="chem-001",
            message="测 Inconel 718 完整表征",
            artifacts={"task": task},
        )
        resp = agent.run(req)
    """

    name = "mat-chemist-agent"

    def __init__(
        self,
        *,
        safety_guard: Optional[ChemistSafetyGuard] = None,
        synth_agent=None,
        xrd_agent=None,
        em_agent=None,
        dsc_agent=None,
        context_manager=None,
        tool_registry=None,
        state_store=None,
        eval_harness=None,
        failure_callback=None,
        max_iterations: int = 1,
        confidence_threshold: float = 0.95,
    ) -> None:
        super().__init__(
            safety_guard=safety_guard or ChemistSafetyGuard(),
            context_manager=context_manager,
            tool_registry=tool_registry,
            state_store=state_store,
            eval_harness=eval_harness,
            failure_callback=failure_callback,
            max_iterations=max_iterations,
            confidence_threshold=confidence_threshold,
        )
        # 懒加载 4 个 robot agent
        self.synth_agent = synth_agent
        self.xrd_agent = xrd_agent
        self.em_agent = em_agent
        self.dsc_agent = dsc_agent
        self.warnings: List[str] = []

    def _get_robot_agent(self, robot_type: str):
        """懒加载 robot agent(W26)"""
        if robot_type == "synth" and self.synth_agent is None:
            from agents.mat_robot_synth_agent.mat_robot_synth_agent import MatRobotSynthAgent
            self.synth_agent = MatRobotSynthAgent()
        elif robot_type == "xrd" and self.xrd_agent is None:
            from agents.mat_robot_xrd_agent.mat_robot_xrd_agent import MatRobotXrdAgent
            self.xrd_agent = MatRobotXrdAgent()
        elif robot_type == "em" and self.em_agent is None:
            from agents.mat_robot_em_agent.mat_robot_em_agent import MatRobotEmAgent
            self.em_agent = MatRobotEmAgent()
        elif robot_type == "dsc" and self.dsc_agent is None:
            from agents.mat_robot_dsc_agent.mat_robot_dsc_agent import MatRobotDscAgent
            self.dsc_agent = MatRobotDscAgent()
        return {
            "synth": self.synth_agent,
            "xrd": self.xrd_agent,
            "em": self.em_agent,
            "dsc": self.dsc_agent,
        }.get(robot_type)

    def system_prompt(self) -> str:
        return (
            "你是 MatWAU 化学师协调 agent(W26)。"
            "负责把材料研究目标拆解成 robot steps,串行调用 4 个机器人"
            "(synth 合成 + xrd 晶体 + em 微观 + dsc 热学),"
            "汇总结果给 mat-critic 评估 / mat-orchestrator 调度。"
            "所有任务必须先经 ChemistSafetyGuard 协调级拦截"
            "(预算 / 样品竞争 / 危险顺序 / 样品量过大)。"
        )

    def act(self, ctx: Dict[str, Any], tools: Optional[List[Any]] = None) -> AgentResponse:
        """Inner Loop act(W26)"""
        task: Optional[ChemistTask] = None

        # 1. 拿 task(从 artifacts 或默认)
        if isinstance(ctx, dict):
            request_obj = ctx.get("_request")
            if request_obj is not None and request_obj.artifacts:
                task = request_obj.artifacts.get("task")

        if task is None:
            # 默认:Inconel 718 完整表征
            task = get_default_inconel_718_workflow()

        # 2. ChemistSafetyGuard 5 类协调级拦截
        sg: ChemistSafetyGuard = self.safety_guard  # type: ignore[assignment]
        chemist_warnings = sg.check_chemist_task(task)
        hard_blocks = [w for w in chemist_warnings if "⛔" in w]
        if hard_blocks:
            self.warnings.extend(chemist_warnings)
            return AgentResponse(
                reply=f"⛔ Chemist 拦截:{hard_blocks[0]}",
                artifacts={
                    "task": task,
                    "blocked": True,
                    "warnings": chemist_warnings,
                    "blocked_steps": [w[:50] for w in hard_blocks],
                    "safety_violations": len(hard_blocks),
                },
                confidence=0.0,
            )

        # 3. 串行执行 4 个 robot step
        robot_results: List[RobotStepResult] = []
        all_success = True
        result_log: List[str] = []
        total_cost = 0.0
        total_duration = 0.0

        # 样品锁:1 个样品同时只能 1 个机器人接触
        sg.sample_lock_active = True

        for step in task.robot_steps:
            agent = self._get_robot_agent(step.robot_type)
            if agent is None:
                rr = RobotStepResult(
                    step_id=step.step_id,
                    robot_type=step.robot_type,
                    success=False,
                    reply=f"未找到 {step.robot_type} agent",
                )
                robot_results.append(rr)
                if step.required:
                    all_success = False
                continue

            # 调用 robot agent
            start_time = time.time()
            robot_req = AgentRequest(
                run_id=f"{task.task_id}-{step.step_id}",
                message=step.description,
                artifacts={"task_id": task.task_id, "sample": task.target_sample, **step.params},
            )
            try:
                robot_resp = agent.run(robot_req)
                duration = time.time() - start_time
                blocked = robot_resp.artifacts.get("blocked", False) if robot_resp.artifacts else False
                success = robot_resp.confidence > 0.5 and not blocked
                rr = RobotStepResult(
                    step_id=step.step_id,
                    robot_type=step.robot_type,
                    success=success,
                    blocked=blocked,
                    reply=robot_resp.reply,
                    artifacts=robot_resp.artifacts or {},
                    warnings=robot_resp.artifacts.get("warnings", []) if robot_resp.artifacts else [],
                    blocked_steps=robot_resp.artifacts.get("blocked_steps", []) if robot_resp.artifacts else [],
                    cost_cny=robot_resp.cost or step.estimated_cost_cny,
                    duration_seconds=duration,
                )
                result_log.append(f"[{step.robot_type}] {rr.reply[:80]}")
                robot_results.append(rr)
                total_cost += rr.cost_cny
                total_duration += rr.duration_seconds
                # 检查 budget
                if total_cost > task.budget_cny:
                    rr.reply += f" (⚠️ 累计成本超预算)"
                if step.required and not success:
                    all_success = False
            except Exception as e:  # noqa: BLE001
                rr = RobotStepResult(
                    step_id=step.step_id,
                    robot_type=step.robot_type,
                    success=False,
                    reply=f"机器人 {step.robot_type} 调用异常:{e}",
                )
                robot_results.append(rr)
                if step.required:
                    all_success = False

        sg.sample_lock_active = False

        # 4. cross-validation(协调级)
        report = ChemistReport(
            task_id=task.task_id,
            target_sample=task.target_sample,
            goal=task.goal,
            overall_success=all_success,
            robot_results=robot_results,
            total_cost_cny=total_cost,
            total_duration_seconds=total_duration,
            summary=f"4 机器人执行:{sum(1 for r in robot_results if r.success)}/{len(robot_results)} 成功,¥{total_cost}",
            cross_validation={},
            warnings=chemist_warnings,
            blocked_steps=[],
        )
        cross_val = sg.check_cross_validation(report)
        report.cross_validation = cross_val
        if cross_val.get("warnings"):
            report.warnings.extend(cross_val["warnings"])

        # 5. 总回复
        n_success = sum(1 for r in robot_results if r.success)
        n_blocked = sum(1 for r in robot_results if r.blocked)
        reply = (
            f"✅ Chemist 完成 {task.target_sample} 任务:"
            f"{n_success}/{len(robot_results)} 机器人成功"
            + (f",{n_blocked} 被拦截" if n_blocked else "")
            + f",总成本 ¥{total_cost:.2f}"
            if all_success
            else f"❌ Chemist 任务失败:{n_success}/{len(robot_results)} 成功"
        )

        return AgentResponse(
            reply=reply,
            artifacts={
                "task_id": task.task_id,
                "target_sample": task.target_sample,
                "goal": task.goal,
                "overall_success": all_success,
                "n_successful": n_success,
                "n_blocked": n_blocked,
                "n_robot_steps": len(robot_results),
                "robot_results": [
                    {
                        "robot_type": r.robot_type,
                        "success": r.success,
                        "blocked": r.blocked,
                        "reply": r.reply[:120],
                        "cost": r.cost_cny,
                    }
                    for r in robot_results
                ],
                "total_cost_cny": total_cost,
                "total_duration_seconds": total_duration,
                "cross_validation": cross_val,
                "summary": report.summary,
                "warnings": report.warnings[:5],
            },
            confidence=0.95 if all_success else 0.5,
            cost=total_cost,
        )

    def perceive(self, req: AgentRequest) -> Dict[str, Any]:
        """Inner Loop perceive(W26)"""
        ctx = dict(req.context) if req.context else {}
        if req.artifacts and "task" not in ctx:
            ctx["task"] = req.artifacts.get("task")
        ctx["_request"] = req
        return ctx