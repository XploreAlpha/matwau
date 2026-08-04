"""mat_robot_dsc_agent.py — MatWAU 机器人 DSC 热分析 agent(W22)

W22 第 4 个物理世界机器人 agent(继 W17-D synth + W18 XRD + W21 EM 之后)
W22 关键:
- 加 DSCSafetyGuard 5 类 DSC 特有拦截(高温氧化 / 坩埚密封 / 超量 / 升温速率 / 爆炸物)
- TAMockSDK(Stage 1)→ TA Trios API / Perkin Elmer(Stage 2)
- 多气氛:空气 / N2 / Ar / O2 / 真空
- 输出:Tg / Tm / Tc + DSC 曲线
"""
from __future__ import annotations

import logging
from typing import Any

from matwau.core.agent_base import (
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)

from .dsc_engine import (
    DSCProcedure,
    DSCResult,
    DSCSafetyGuard,
    TAMockSDK,
    estimate_dsc_cost,
    get_default_dsc_procedure,
)
from .ta_trios_real_sdk import TATriosRealSDK  # W25 Stage 2 真接

logger = logging.getLogger(__name__)


class MatRobotDscAgent(MatWAUAgentBase):
    """机器人 DSC 热分析 agent(W22 — Stage 3 钢铁侠 Phase 3 第 4 个机器人)

    W22:复用 mat-robot-xrd-agent 模板(W18 模式)
    W22 价值点:
    - 物理世界表征(DSC 热流 vs 温度)
    - 多气氛 + 多升温速率(per TA Trios / Perkin Elmer)
    - 输出 Tg / Tm / Tc → mat-critic 比对材料数据库

    用法:
        agent = MatRobotDscAgent()
        req = AgentRequest(
            run_id="dsc-001",
            message="测 PMMA 玻璃化转变温度",
            artifacts={"procedure": procedure},
        )
        resp = agent.run(req)
    """

    name = "mat-robot-dsc-agent"

    def __init__(
        self,
        *,
        safety_guard: DSCSafetyGuard | None = None,
        robot_sdk=None,  # W25: 接受 TATriosRealSDK 或 TAMockSDK
        context_manager=None,
        tool_registry=None,
        state_store=None,
        eval_harness=None,
        failure_callback=None,
        max_iterations: int = 1,
        confidence_threshold: float = 0.99,
        use_real_sdk: bool = True,  # W25: 默认用 RealSDK(降级自动)
        trios_api_url: str = "http://localhost:49160/triosautopilot/v1",
    ) -> None:
        super().__init__(
            safety_guard=safety_guard or DSCSafetyGuard(),  # 默认带 DSCSafetyGuard
            context_manager=context_manager,
            tool_registry=tool_registry,
            state_store=state_store,
            eval_harness=eval_harness,
            failure_callback=failure_callback,
            max_iterations=max_iterations,
            confidence_threshold=confidence_threshold,
        )
        # W25 默认 TATriosRealSDK(双形态:装 requests + endpoint 可达→真接;否则降级 mock)
        if robot_sdk is not None:
            self.robot_sdk = robot_sdk
        elif use_real_sdk:
            self.robot_sdk = TATriosRealSDK(
                lab_id="matwau-dsc-01",
                trios_api_url=trios_api_url,
                skip_endpoint_check=True,  # 默认不查 endpoint,直接当虚拟连接
            )
        else:
            self.robot_sdk = TAMockSDK(fail_chance=0.0)
        self.warnings: list[str] = []

    def system_prompt(self) -> str:
        return (
            "你是 MatWAU 机器人 DSC 热分析 agent(W22)。"
            "负责把样品方案翻译成 TA Instruments DSC 的真实操作。"
            "所有步骤必须先经 DSCSafetyGuard 拦截"
            "(高温氧化 / 坩埚密封 / 样品超量 / 升温速率 / 爆炸物)。"
            "输出 Tg / Tm / Tc + DSC 曲线给 mat-critic 比对材料数据库。"
        )

    def act(self, ctx: dict[str, Any], tools: list[Any] | None = None) -> AgentResponse:
        """Inner Loop act(W22)"""
        procedure: DSCProcedure | None = None

        # 1. 拿 procedure
        if isinstance(ctx, dict):
            request_obj = ctx.get("_request")
            if request_obj is not None:
                procedure = request_obj.artifacts.get("procedure") if request_obj.artifacts else None

        if procedure is None:
            procedure = get_default_dsc_procedure()

        if procedure is None:
            return AgentResponse(
                reply="❌ 没找到 DSC procedure",
                artifacts={},
                confidence=0.0,
            )

        # 2. DSCSafetyGuard 5 类拦截
        sg: DSCSafetyGuard = self.safety_guard  # type: ignore[assignment]
        dsc_warnings = sg.check_dsc(procedure)

        blocked_steps = []
        hard_blocks = [w for w in dsc_warnings if "⛔" in w]
        if hard_blocks:
            self.warnings.extend(dsc_warnings)
            for w in hard_blocks:
                if "高温氧化" in w or "空气" in w:
                    blocked_steps.append("high_temp_oxidizing")
                elif "坩埚" in w:
                    blocked_steps.append("unsealed_high_temp")
                elif "样品超量" in w:
                    blocked_steps.append("over_mass")
                elif "升温速率" in w:
                    blocked_steps.append("overheating_rate")
                elif "爆炸" in w or "剧毒" in w:
                    blocked_steps.append("explosive_sample")

            return AgentResponse(
                reply=f"⛔ DSC 拦截:{hard_blocks[0]}",
                artifacts={
                    "procedure": procedure,
                    "blocked": True,
                    "warnings": dsc_warnings,
                    "blocked_steps": blocked_steps,
                    "safety_violations": len(hard_blocks),
                },
                confidence=0.0,
            )

        # 3. 执行 DSC 温度程序
        result_log: list[str] = []
        all_ok = True
        all_x: list[float] = []
        all_y: list[float] = []

        # W25: 让 RealSDK 知道当前样品的化学式(查标准材料库用)
        if hasattr(self.robot_sdk, "set_sample_formula"):
            self.robot_sdk.set_sample_formula(procedure.sample_formula)

        for step in procedure.steps:
            exec_resp = self.robot_sdk.execute(step)
            result_log.append(f"[step {step.name}] {exec_resp['log']}")
            if exec_resp["ok"]:
                for x, y in exec_resp["curve"]:
                    all_x.append(x)
                    all_y.append(y)
            else:
                all_ok = False
                break

        # 4. 解析 DSC 曲线 → Tg / Tm / Tc / ΔH(mock)
        tg = tm = tc = None
        enthalpy = None
        if all_ok and all_x and all_y:
            # 找最大热流峰 → 假定是 Tm
            max_idx = max(range(len(all_y)), key=lambda i: all_y[i])
            tm = round(all_x[max_idx], 2)
            # Tg 大概在升温段 60% 处
            tg = round(all_x[len(all_x) // 4] + 50, 2)
            # Tc 在 Tg 之后(冷却段)
            if len(all_x) > len(all_x) // 2:
                tc = round(all_x[3 * len(all_x) // 4], 2)
            # ΔH = 峰面积(简化: |sum(y)| / 峰宽)
            enthalpy = round(abs(sum(all_y)) / max(len(all_y), 1), 3)

        result = DSCResult(
            run_id="",
            procedure=procedure,
            success=all_ok,
            glass_transition_temp_c=tg,
            melting_temp_c=tm,
            crystallization_temp_c=tc,
            enthalpy_change_j_per_g=enthalpy,
            dsc_curve_x=all_x,
            dsc_curve_y=all_y,
            warnings=dsc_warnings,
            blocked_steps=blocked_steps,
            log=result_log,
            cost=estimate_dsc_cost(procedure),
            metadata={
                "robot_sdk": self.robot_sdk.lab_id,
                "atmosphere": procedure.atmosphere,
                "domain": procedure.domain,
            },
        )

        reply = (
            f"✅ {self.robot_sdk.lab_id} 完成 {procedure.sample_formula} DSC 测试,"
            f"Tg={tg}°C Tm={tm}°C Tc={tc}°C ΔH={enthalpy}J/g"
            if all_ok
            else f"❌ DSC 测试失败:{result_log[-1] if result_log else 'unknown'}"
        )

        return AgentResponse(
            reply=reply,
            artifacts={
                "result": {
                    "Tg_c": tg,
                    "Tm_c": tm,
                    "Tc_c": tc,
                    "enthalpy_j_per_g": enthalpy,
                    "curve_points": len(all_x),
                    "success": all_ok,
                },
                "procedure": procedure,
                "success": all_ok,
                "robot_sdk": self.robot_sdk.lab_id,
                "atmosphere": procedure.atmosphere,
                "sdk_mode": getattr(self.robot_sdk, "sdk_mode", "mock"),  # W25 标记
            },
            confidence=0.95 if all_ok else 0.3,
            cost=result.cost,
        )

    def perceive(self, req: AgentRequest) -> dict[str, Any]:
        """Inner Loop perceive(W22)"""
        ctx = dict(req.context) if req.context else {}
        if req.artifacts and "procedure" not in ctx:
            ctx["procedure"] = req.artifacts.get("procedure")
        ctx["_request"] = req
        return ctx
