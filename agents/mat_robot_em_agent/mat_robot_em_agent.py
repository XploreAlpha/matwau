"""mat_robot_em_agent.py — MatWAU 机器人电镜表征 agent(W21)

W21 第 3 个物理世界机器人 agent(继 W17-D 合成 + W18 XRD 之后)
W21 关键:
- 加 EMSafetyGuard 6 类电镜特有拦截(真空 / 舱门 / 喷金 / 易挥发 / 易辐照损伤 / 磁性)
- ZeissMockSDK(Stage 1)→ Zeiss SDK / FEI SDK(Stage 2 真接)
- 支持多模式:SEM / TEM / STEM / EDS / SAED
- 输出:image + EDS 元素谱 + 晶粒尺寸
"""
from __future__ import annotations

import logging
from typing import Any

from matwau.core.agent_base import (
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)

from .em_engine import (
    EMProcedure,
    EMResult,
    EMSafetyGuard,
    ZeissMockSDK,
    estimate_em_cost,
    get_default_em_procedure,
)
from .zeiss_real_sdk import ZeissRealSDK  # W24 Stage 2 真接

logger = logging.getLogger(__name__)


class MatRobotEmAgent(MatWAUAgentBase):
    """机器人电镜表征 agent(W21 — Stage 3 钢铁侠 Phase 3 第 3 个机器人)

    W21:复用 mat-robot-xrd-agent 模板(W18 模式)
    W21 价值点:
    - 物理世界表征(SEM + EDS)
    - 电子束辐射防护(6 类 EM 特有检查)
    - 输出 SEM/TEM 图像 + EDS 元素谱 → mat-critic 比对 / mat-orchestrator 调度

    用法:
        agent = MatRobotEmAgent()
        req = AgentRequest(
            run_id="em-001",
            message="拍 Inconel 718 微观结构 + 元素分析",
            artifacts={"procedure": procedure},
        )
        resp = agent.run(req)
    """

    name = "mat-robot-em-agent"

    def __init__(
        self,
        *,
        safety_guard: EMSafetyGuard | None = None,
        robot_sdk=None,  # W24: 接受 ZeissRealSDK 或 ZeissMockSDK
        context_manager=None,
        tool_registry=None,
        state_store=None,
        eval_harness=None,
        failure_callback=None,
        max_iterations: int = 1,
        confidence_threshold: float = 0.99,
        use_real_sdk: bool = True,  # W24: 默认用 RealSDK(降级自动)
        smartsem_api_url: str = "http://localhost:49150/smartsem/v1",
    ) -> None:
        super().__init__(
            safety_guard=safety_guard or EMSafetyGuard(),  # 默认带 EMSafetyGuard
            context_manager=context_manager,
            tool_registry=tool_registry,
            state_store=state_store,
            eval_harness=eval_harness,
            failure_callback=failure_callback,
            max_iterations=max_iterations,
            confidence_threshold=confidence_threshold,
        )
        # W24 默认 ZeissRealSDK(双形态:装 requests + endpoint 可达→真接;否则降级 mock)
        if robot_sdk is not None:
            self.robot_sdk = robot_sdk
        elif use_real_sdk:
            self.robot_sdk = ZeissRealSDK(
                lab_id="matwau-em-01",
                smartsem_api_url=smartsem_api_url,
                skip_endpoint_check=True,  # 默认不查 endpoint,直接当虚拟连接
            )
        else:
            self.robot_sdk = ZeissMockSDK(fail_chance=0.0)
        self.warnings: list[str] = []

    def system_prompt(self) -> str:
        return (
            "你是 MatWAU 机器人电镜表征 agent(W21)。"
            "负责把样品方案翻译成 Zeiss SEM/TEM 的真实操作。"
            "所有步骤必须先经 EMSafetyGuard 拦截"
            "(真空 / 舱门 / 喷金 / 易挥发 / 易辐照损伤 / 磁性样品)。"
            "输出 SEM/TEM 图像 + EDS 元素谱 + 晶粒尺寸给 mat-critic 比对。"
        )

    def act(self, ctx: dict[str, Any], tools: list[Any] | None = None) -> AgentResponse:
        """Inner Loop act(W21)"""
        procedure: EMProcedure | None = None

        # 1. 拿 procedure
        if isinstance(ctx, dict):
            request_obj = ctx.get("_request")
            if request_obj is not None:
                procedure = request_obj.artifacts.get("procedure") if request_obj.artifacts else None

        if procedure is None:
            procedure = get_default_em_procedure()

        if procedure is None:
            return AgentResponse(
                reply="❌ 没找到 EM procedure",
                artifacts={},
                confidence=0.0,
            )

        # 2. EMSafetyGuard 6 类拦截
        sg: EMSafetyGuard = self.safety_guard  # type: ignore[assignment]
        em_warnings = sg.check_em(procedure)

        blocked_steps = []
        hard_blocks = [w for w in em_warnings if "⛔" in w]
        if hard_blocks:
            self.warnings.extend(em_warnings)
            for w in hard_blocks:
                if "真空" in w:
                    blocked_steps.append("vacuum_insufficient")
                elif "舱门" in w:
                    blocked_steps.append("door_open")
                elif "喷金" in w:
                    blocked_steps.append("no_conductive_coating")
                elif "易挥发" in w:
                    blocked_steps.append("volatile_sample")
                elif "辐照损伤" in w:
                    blocked_steps.append("radiation_damage_sensitive")

            return AgentResponse(
                reply=f"⛔ 电镜拦截:{hard_blocks[0]}",
                artifacts={
                    "procedure": procedure,
                    "blocked": True,
                    "warnings": em_warnings,
                    "blocked_steps": blocked_steps,
                    "safety_violations": len(hard_blocks),
                },
                confidence=0.0,
            )

        # 3. 执行电镜操作
        result_log: list[str] = []
        all_ok = True
        all_images: list[dict[str, Any]] = []
        all_elements: list[dict[str, Any]] = []

        for step in procedure.steps:
            exec_resp = self.robot_sdk.execute(step)
            result_log.append(f"[step {step.name}] {exec_resp['log']}")
            if exec_resp["ok"]:
                all_images.extend(exec_resp["images"])
                all_elements.extend(exec_resp["elements"])
            else:
                all_ok = False
                break

        # 4. 计算晶粒尺寸(mock:基于 EDS 元素 weight % + mag)
        grain_size_um = None
        if all_ok and all_images:
            # mock: SEM 10000x 平均晶粒 = 5μm
            grain_size_um = round(5.0 + 0.1 * len(all_images), 2)

        result = EMResult(
            run_id="",
            procedure=procedure,
            success=all_ok,
            images=all_images,
            elements_detected=all_elements,
            diffraction_peaks=[],
            grain_size_um=grain_size_um,
            warnings=em_warnings,
            blocked_steps=blocked_steps,
            log=result_log,
            cost=estimate_em_cost(procedure),
            metadata={
                "robot_sdk": self.robot_sdk.lab_id,
                "imaging_modes": procedure.target_imaging_modes,
                "domain": procedure.domain,
            },
        )

        reply = (
            f"✅ {self.robot_sdk.lab_id} 完成 {procedure.sample_formula} 电镜测试,"
            f"成像 {len(all_images)} 张,EDS 元素 {len(all_elements)} 个"
            if all_ok
            else f"❌ 电镜测试失败:{result_log[-1] if result_log else 'unknown'}"
        )

        return AgentResponse(
            reply=reply,
            artifacts={
                "result": {
                    "images": all_images,
                    "elements": all_elements,
                    "grain_size_um": grain_size_um,
                    "success": all_ok,
                },
                "procedure": procedure,
                "success": all_ok,
                "robot_sdk": self.robot_sdk.lab_id,
                "imaging_modes": procedure.target_imaging_modes,
                "sdk_mode": getattr(self.robot_sdk, "sdk_mode", "mock"),  # W24 标记
            },
            confidence=0.95 if all_ok else 0.3,
            cost=result.cost,
        )

    def perceive(self, req: AgentRequest) -> dict[str, Any]:
        """Inner Loop perceive(W21)"""
        ctx = dict(req.context) if req.context else {}
        if req.artifacts and "procedure" not in ctx:
            ctx["procedure"] = req.artifacts.get("procedure")
        ctx["_request"] = req
        return ctx
