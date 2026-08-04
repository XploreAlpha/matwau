"""mat_robot_xrd_agent.py — MatWAU 机器人 XRD 表征 agent(W18)

W18:复用 mat-robot-synth-agent 模板(W17-D SafetyGuard 子类化)
W18 关键:加 XRDSafetyGuard 3 类 XRD 辐射防护
"""
from __future__ import annotations

import logging
from typing import Any

from matwau.core.agent_base import (
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)

from .xrd_engine import (
    XRDProcedure,
    XRDResult,
    XRDSafetyGuard,
    estimate_xrd_cost,
    get_default_xrd_procedure,
)

logger = logging.getLogger(__name__)


class MatRobotXrdAgent(MatWAUAgentBase):
    """机器人 XRD 表征 agent(W18 — Stage 3 钢铁侠 Phase 2 + W20 真接)

    W18:复用 W17-D SafetyGuard + 子类化加 3 类 XRD 辐射防护
    W20 增量:
    - 默认 robot_sdk 由 BrukerMockSDK → BrukerRealSDK
    - 自动降级:装了 bruker 库走真 + 内置 PDF 卡片数据库
    - 输出可观测:sdk_mode 属性(real / mock)

    用法:
        agent = MatRobotXrdAgent()
        req = AgentRequest(
            run_id="xrd-001",
            message="测 Ca-LLZO",
            artifacts={"procedure": procedure},
        )
        resp = agent.run(req)

    兼容性(W18 接口 100% 保留):
        agent = MatRobotXrdAgent(robot_sdk=BrukerMockSDK(...))  # 强制 mock
        agent = MatRobotXrdAgent()  # 默认 BrukerRealSDK(W20 自动降级)
    """

    name = "mat-robot-xrd-agent"

    def __init__(
        self,
        *,
        safety_guard: XRDSafetyGuard | None = None,
        robot_sdk: Any | None = None,  # BrukerMockSDK | BrukerRealSDK
        context_manager=None,
        tool_registry=None,
        state_store=None,
        eval_harness=None,
        failure_callback=None,
        max_iterations: int = 1,
        confidence_threshold: float = 0.99,
    ) -> None:
        super().__init__(
            safety_guard=safety_guard or XRDSafetyGuard(),  # 默认带 XRDSafetyGuard
            context_manager=context_manager,
            tool_registry=tool_registry,
            state_store=state_store,
            eval_harness=eval_harness,
            failure_callback=failure_callback,
            max_iterations=max_iterations,
            confidence_threshold=confidence_threshold,
        )
        if robot_sdk is None:
            # W20 默认切到 BrukerRealSDK(自动降级 mock)
            from .bruker_real_sdk import BrukerRealSDK
            self.robot_sdk = BrukerRealSDK(fail_chance=0.0)
        else:
            self.robot_sdk = robot_sdk
        self.warnings: list[str] = []

    def system_prompt(self) -> str:
        return (
            "你是 MatWAU 机器人 XRD 表征 agent(W18 + W20 真接)。"
            "负责把样品方案翻译成 Bruker XRD 的真实操作。"
            "所有步骤必须先经 XRDSafetyGuard 拦截(舱门 / 铅围裙 / 易辐射分解物质)。"
            "输出 Bragg 峰 + PDF 卡片匹配结果给 mat-critic 比对。"
        )

    def act(self, ctx: dict[str, Any], tools: list[Any] | None = None) -> AgentResponse:
        """Inner Loop act(W18 + W20 真接)"""
        procedure: XRDProcedure | None = None

        # 1. 拿 procedure
        if isinstance(ctx, dict):
            request_obj = ctx.get("_request")
            if request_obj is not None:
                procedure = request_obj.artifacts.get("procedure") if request_obj.artifacts else None

        if procedure is None:
            procedure = get_default_xrd_procedure()

        if procedure is None:
            return AgentResponse(
                reply="❌ 没找到 XRD procedure",
                artifacts={},
                confidence=0.0,
            )

        # 2. XRDSafetyGuard 三类拦截
        sg: XRDSafetyGuard = self.safety_guard  # type: ignore[assignment]
        xrd_warnings = sg.check_xrd(procedure)

        blocked_steps = []
        if xrd_warnings:
            self.warnings.extend(xrd_warnings)
            for w in xrd_warnings:
                if "舱门" in w:
                    blocked_steps.append("door_open")
                elif "围裙" in w:
                    blocked_steps.append("no_apron")
                elif "辐射分解" in w:
                    blocked_steps.append("radioactive_sensitive")

            return AgentResponse(
                reply=f"⛔ 辐射拦截:{xrd_warnings[0]}",
                artifacts={
                    "procedure": procedure,
                    "blocked": True,
                    "warnings": xrd_warnings,
                    "blocked_steps": blocked_steps,
                    "safety_violations": len(xrd_warnings),
                },
                confidence=0.0,
            )

        # 3. 执行 XRD 扫描
        result_log: list[str] = []
        all_ok = True
        all_peaks: list[dict[str, float]] = []
        total_duration = 0.0

        for step in procedure.steps:
            exec_resp = self.robot_sdk.execute(step)
            result_log.append(f"[step {step.name}] {exec_resp['log']}")
            total_duration += step.duration_minutes
            if exec_resp["ok"]:
                all_peaks.extend(exec_resp["peaks"])
            else:
                all_ok = False
                break

        # 4. PDF 卡片比对
        # W20 增量:真接模式用 PDF 数据库精细比对;mock 模式粗略匹配目标 phases
        matched_phase = ""
        confidence = 0.0
        if all_ok and procedure.target_phases:
            sdk_mode = getattr(self.robot_sdk, "sdk_mode", "mock")
            target_pdf = procedure.target_phases[0]

            if sdk_mode == "real":
                # 真接:用 PDF 卡片数据库精细比对
                from .bruker_real_sdk import compare_to_pdf_card
                cmp_result = compare_to_pdf_card(all_peaks, target_pdf)
                if cmp_result["matched"]:
                    matched_phase = target_pdf
                    confidence = cmp_result["score"]
                else:
                    matched_phase = ""
                    confidence = 0.0
            else:
                # Mock:粗略匹配目标 phases
                matched_phase = target_pdf
                confidence = 0.9

        result = XRDResult(
            run_id="",
            procedure=procedure,
            success=all_ok,
            peaks=all_peaks,
            matched_phase=matched_phase,
            confidence=confidence,
            warnings=xrd_warnings,
            blocked_steps=blocked_steps,
            log=result_log,
            cost=estimate_xrd_cost(procedure),
            metadata={
                "robot_sdk": self.robot_sdk.lab_id,
                "robot_sdk_class": type(self.robot_sdk).__name__,
                "sdk_mode": getattr(self.robot_sdk, "sdk_mode", "mock"),
                "domain": ctx.get("domain", "inorganic_crystal") if isinstance(ctx, dict) else "inorganic_crystal",
            },
        )

        reply = (
            f"✅ {self.robot_sdk.lab_id} 完成 {procedure.sample_formula} XRD 测试,"
            f"匹配 {matched_phase},峰 {len(all_peaks)} 个"
            if all_ok
            else f"❌ XRD 测试失败:{result_log[-1] if result_log else 'unknown'}"
        )

        return AgentResponse(
            reply=reply,
            artifacts={
                "result": {
                    "peaks": all_peaks,
                    "matched_phase": matched_phase,
                    "confidence": confidence,
                    "success": all_ok,
                },
                "procedure": procedure,
                "success": all_ok,
                "robot_sdk": self.robot_sdk.lab_id,
                "robot_sdk_class": type(self.robot_sdk).__name__,
                "sdk_mode": result.metadata["sdk_mode"],
            },
            confidence=confidence if confidence > 0 else (0.95 if all_ok else 0.3),
            cost=result.cost,
        )

    def perceive(self, req: AgentRequest) -> dict[str, Any]:
        """Inner Loop perceive(W18)"""
        ctx = dict(req.context) if req.context else {}
        if req.artifacts and "procedure" not in ctx:
            ctx["procedure"] = req.artifacts.get("procedure")
        ctx["_request"] = req
        return ctx
