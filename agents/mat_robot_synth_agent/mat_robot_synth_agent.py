"""mat_robot_synth_agent.py — MatWAU 机器人合成实验 agent(W17-D + W19 真接)

W19 增量:
- 默认 robot_sdk 由 OpentronsMockSDK → OpentronsRealSDK
- 自动降级:装了 opentrons 走真协议生成,没装降级 mock
- W17-D 接口 100% 不变(MatRobotSynthAgent.__init__/act/perceive/system_prompt)

继承 MatWAU-AgentBase(Inner Loop 4 步 + Harness 5 职责)。
特别:必带 SafetyGuard(机械臂操作危险)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from matwau.core.agent_base import (
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)

from .synth_engine import (
    OpentronsMockSDK,
    SafetyGuard,
    SynthProcedure,
    SynthResult,
    estimate_synth_cost,
)

logger = logging.getLogger(__name__)


class MatRobotSynthAgent(MatWAUAgentBase):
    """机器人合成实验 agent(Stage 3 钢铁侠起步 — W17-D + W19 真接)

    新品类:
    - 跨入物理世界(其他 15 agent 全是数字世界)
    - 必须带 SafetyGuard(高温 / 化学品 / 超量拦截)
    - **W19 真接 SDK**:默认 OpentronsRealSDK(装了 opentrons 走真协议生成,否则降级 Mock)

    用法:
        agent = MatRobotSynthAgent()
        req = AgentRequest(
            run_id="synth-001",
            message="用 Pechini 法合成 Ca-LLZO",
            artifacts={"procedure": procedure},
            context={"domain": "inorganic_crystal"},
        )
        resp = agent.run(req)

    兼容性(W17-D 接口 100% 保留):
        agent = MatRobotSynthAgent(robot_sdk=OpentronsMockSDK(...))  # 强制 mock
        agent = MatRobotSynthAgent()  # 默认 OpentronsRealSDK(W19 自动检测)
    """

    name = "mat-robot-synth-agent"

    def __init__(
        self,
        *,
        safety_guard: Optional[SafetyGuard] = None,
        robot_sdk: Optional[Any] = None,  # OpentronsMockSDK | OpentronsRealSDK(W19 兼容两种)
        context_manager=None,
        tool_registry=None,
        state_store=None,
        eval_harness=None,
        failure_callback=None,
        max_iterations: int = 1,    # 物理合成不需要多轮(每轮 1 次真实验)
        confidence_threshold: float = 0.99,
    ) -> None:
        super().__init__(
            safety_guard=safety_guard or SafetyGuard(),  # 默认带 SafetyGuard
            context_manager=context_manager,
            tool_registry=tool_registry,
            state_store=state_store,
            eval_harness=eval_harness,
            failure_callback=failure_callback,
            max_iterations=max_iterations,
            confidence_threshold=confidence_threshold,
        )
        if robot_sdk is None:
            # W19 默认切到 OpentronsRealSDK(自动降级 mock)
            from .opentrons_real_sdk import OpentronsRealSDK
            self.robot_sdk = OpentronsRealSDK(fail_chance=0.0)
        else:
            self.robot_sdk = robot_sdk
        self.warnings: List[str] = []

    def system_prompt(self) -> str:
        return (
            "你是 MatWAU 机器人合成实验 agent。"
            "负责把材料配方(化学式 + 步骤)翻译成实验室机械臂(OT-2)的真实操作。"
            "所有步骤必须经 SafetyGuard 拦截后再执行。"
            "输出结构化 SynthResult 给 mat-critic 评估。"
        )

    def act(self, ctx: Dict[str, Any], tools: Optional[List[Any]] = None) -> AgentResponse:
        """Inner Loop 第 3 步:真接(per SafetyGuard 输出)

        Args:
            ctx: perceive 输出(dom = req.context + state 合并)
            tools: tool_registry 暴露的可调用工具(本 agent 不使用)
        """
        # 1. 从 ctx 拿 procedure(可以从 upstream mat-gen 传来)
        procedure: Optional[SynthProcedure] = None

        # 显式 artifacts 路径(per DAG 编排,mat-gen → mat-robot-synth)
        if isinstance(ctx, dict):
            request_obj = ctx.get("_request")
            if request_obj is not None:
                procedure = request_obj.artifacts.get("procedure") if request_obj.artifacts else None

        # 兜底:兜底 procedure 可硬编码 Ca-LLZO(W17-D 默认 PoC)
        if procedure is None:
            from .synth_engine import get_default_procedure
            procedure = get_default_procedure("Pechini_Ca_LLZO")

        if procedure is None:
            return AgentResponse(
                reply="❌ 没找到 synthesis procedure",
                artifacts={},
                confidence=0.0,
            )

        # 2. SafetyGuard 拦截检查(高危)
        sg: SafetyGuard = self.safety_guard  # type: ignore[assignment]
        synth_result_warnings = sg.check_procedure(procedure)

        # 3. 仿真执行
        blocked_steps: List[str] = []
        if synth_result_warnings:
            # 有报警 → block 整个实验
            self.warnings.extend(synth_result_warnings)
            for w in synth_result_warnings:
                if "高温" in w:
                    blocked_steps.append("high_temperature_steps")
                elif "危险化学品" in w:
                    blocked_steps.append("dangerous_chemical_steps")
                elif "试剂超量" in w:
                    blocked_steps.append("over_yield_steps")

            return AgentResponse(
                reply=(
                    f"⛔ 安全拦截:共 {len(synth_result_warnings)} 条报警 — {synth_result_warnings[:2]}"
                ),
                artifacts={
                    "procedure": procedure,
                    "blocked": True,
                    "warnings": synth_result_warnings,
                    "blocked_steps": blocked_steps,
                    "safety_violations": len(synth_result_warnings),
                },
                confidence=0.0,
            )

        # 4. 真接 SDK 执行(per Opentrons OT-2 real API 在 Stage 2)
        result_log: List[str] = []
        all_ok = True
        total_yield = 0.0
        total_duration = 0.0
        for step in procedure.steps:
            exec_resp = self.robot_sdk.execute(step)
            result_log.append(f"[step {step.name}] {exec_resp['log']}")
            total_duration += step.duration_minutes
            if exec_resp["ok"]:
                total_yield += exec_resp["yield"]
            else:
                all_ok = False
                break

        result = SynthResult(
            run_id="",
            procedure=procedure,
            success=all_ok,
            product_formula=procedure.target_formula if all_ok else "",
            yield_grams=round(total_yield, 3),
            synthesis_duration_minutes=total_duration,
            warnings=synth_result_warnings,
            blocked_steps=blocked_steps,
            log=result_log,
            cost=estimate_synth_cost(procedure),
            cost_estimate={"method": "w17_d_estimate"},
            metadata={
                "domain": ctx.get("domain", "inorganic_crystal") if isinstance(ctx, dict) else "inorganic_crystal",
                "method": procedure.method,
                "robot_sdk": type(self.robot_sdk).__name__,
                # W19 增量:sdk_mode 可观测(real / mock)
                "sdk_mode": getattr(self.robot_sdk, "sdk_mode", "mock"),
            },
        )

        confidence = 0.95 if all_ok else 0.3
        reply = (
            f"✅ 机械臂 {self.robot_sdk.lab_id} 完成 {procedure.target_formula} 合成 "
            f"({procedure.method}),产 {result.yield_grams:.2f}g"
            if all_ok
            else f"❌ 合成失败:{result_log[-1] if result_log else 'unknown'}"
        )

        return AgentResponse(
            reply=reply,
            artifacts={
                "result": result.to_dict(),
                "procedure": procedure,
                "success": all_ok,
                "robot_sdk": self.robot_sdk.lab_id,
                "robot_sdk_class": type(self.robot_sdk).__name__,
                "sdk_mode": result.metadata["sdk_mode"],
                "domain": result.metadata["domain"],
            },
            confidence=confidence,
            cost=result.cost,
        )

    def perceive(self, req: AgentRequest) -> Dict[str, Any]:
        """Inner Loop 第 1 步

        本 agent 不需要复杂 context 组装(直接拿 procedure),
        override 基类 default 简化逻辑
        """
        ctx = dict(req.context) if req.context else {}
        if req.artifacts and "procedure" not in ctx:
            ctx["procedure"] = req.artifacts.get("procedure")
        ctx["_request"] = req
        return ctx
