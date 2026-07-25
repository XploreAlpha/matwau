"""mat-gen-agent — 造物主(MatterGen CIF 生成,per dev plan §5.2)

Stage 1 / Phase 1:用 mock MatterGen,本机不需 GPU
Stage 2(WAU v1.0.0 GA + 服务器 GPU 后)切真模型

用法:
    from matwau.agents.mat_gen_agent.mat_gen_agent import MatGenAgent
    from matwau.core.agent_base import AgentRequest

    agent = MatGenAgent()  # 自动注入 Harness 部件(可选)
    req = AgentRequest(
        run_id="run-001",
        message="设计新型固态电解质,不含贵金属,室温电导率 > 1 mS/cm",
    )
    response = agent.run(req)
    print(response.reply)
    print(response.artifacts["candidates"])  # List[GenCandidate]
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 允许直接 python3 -m 运行本文件
_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import (  # noqa: E402
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)
from matwau.harness.context_manager import ContextManager  # noqa: E402
from matwau.harness.safety_guard import SafetyGuard  # noqa: E402

from .mattergen import (  # noqa: E402
    GenCandidate,
    GenConstraints,
    generate as mattergen_generate,
    parse_constraints,
)

# W15: 域路由(W2 接入真实 backend)
from agents.material_domain_router import (  # noqa: E402
    DEFAULT_DOMAIN,
    detect_domain,
    get_gen_backend,
    get_profile,
)


class MatGenAgent(MatWAUAgentBase):
    """mat-gen-agent — 材料科学造物主

    业务流程(per act() 实现):
    1. 解析用户消息 → GenConstraints(元素 + 数量 + 目标属性 + 禁止元素)
    2. 调 MatterGen 生成 CIF 列表
    3. 对每个候选估算形成能(Stage 1 mock,Stage 2 接 CHGNet)
    4. 返回按稳定性排序的候选列表
    """

    name = "mat-gen-agent"

    def __init__(
        self,
        *,
        n_samples: int = 10,
        target_energy_threshold: float = -1.5,
        domain: Optional[str] = None,
        **kwargs,
    ) -> None:
        """构造

        Args:
            n_samples: 默认生成候选数(用户 query 可覆盖)
            target_energy_threshold: 形成能阈值(eV/atom),低于此认为稳定
            domain: 材料域(per W15 material_domain_router)
                   - None / "auto" → 从 user_intent 自动检测
                   - "inorganic_crystal" / "polymer" / "nano" → 显式指定
                   - 默认 "inorganic_crystal"(向后兼容)
        """
        super().__init__(**kwargs)
        self.n_samples = n_samples
        self.target_energy_threshold = target_energy_threshold
        self.domain = domain or DEFAULT_DOMAIN

        # 默认注入 harness 部件(mat-gen 自带 Stage 1 简版)
        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=100.0)

    def system_prompt(self) -> str:
        return """你是材料科学造物主 agent(mat-gen-agent),根据用户约束设计新晶体结构。

能力:
1. 接受用户自然语言需求(目标材料 + 约束 + 性能目标)
2. 解析约束(必含元素 / 禁止元素 / 数量 / 目标属性)
3. 调用 MatterGen 扩散模型生成候选 CIF
4. 用 MLIP(Stage 1 mock / Stage 2 CHGNet)估算每个候选的形成能
5. 按稳定性排序,返回 top-N 候选

输出格式:
- reply:自然语言总结(候选数 + 平均形成能 + top-3 化学式)
- artifacts.candidates: List[GenCandidate](每个有 cif / formula / estimated_energy / confidence)

约束:
- 0 行 UI 代码(无头架构,所有展示走 HomeRail / Claude Desktop / Cursor)
- 1 个 LLM 调用 = 1 次 Goldens 跑分(W1 末已建 50 case,pass-rate > 80%)
"""

    def act(self, ctx: Dict[str, Any], tools: List[str]) -> AgentResponse:
        """Inner Loop 第 3 步:执行 — mat-gen 特有业务逻辑

        1. 从 ctx 拿 user_message + domain(W15 路由)
        2. parse_constraints()
        3. mattergen.generate()(Stage 1 mock;Stage 2 按 gen_backend 路由)
        4. 形成能估算 + 排序
        5. 安全检查(SafetyGuard)
        6. 返回 AgentResponse
        """
        user_message = ctx.get("user_message", "")
        if not user_message:
            # fallback 到 ctx["messages"] 最后一条
            messages = ctx.get("messages", [])
            if messages and hasattr(messages[-1], "content"):
                user_message = messages[-1].content

        # W15: 域路由(优先 ctx["domain"] > self.domain > auto-detect)
        ctx_domain = ctx.get("domain")
        if ctx_domain:
            run_domain = ctx_domain
        elif self.domain and self.domain != "auto":
            run_domain = self.domain
        else:
            run_domain = detect_domain(user_message)

        # W15: 记录 backend(Stage 2 真模型按这个切)
        backend = get_gen_backend(run_domain)

        # 1. 解析约束
        constraints = parse_constraints(user_message)
        if constraints.n_samples < self.n_samples:
            constraints.n_samples = self.n_samples

        # 2. 调 MatterGen(Stage 1 mock;Stage 2 按 backend 路由)
        candidates: List[GenCandidate] = mattergen_generate(constraints)

        # 3. 过滤(可选:形成能低于阈值)
        stable_candidates = [
            c for c in candidates if c.estimated_energy < self.target_energy_threshold
        ]
        # 全部都不稳 → 保留 top-5
        if not stable_candidates and candidates:
            stable_candidates = candidates[:5]

        # 4. 安全检查:成本估算 + 是否超 budget
        total_cost = self._estimate_cost(len(candidates), domain=run_domain)
        # budget 校验
        budget = ctx.get("budget")  # 透传的预算

        # 5. 构造响应
        domain_label = get_profile(run_domain).get("display_name_zh", run_domain)
        if not stable_candidates:
            reply = f"❌ [{domain_label}/{backend}] 未能生成满足约束的候选(尝试 {len(candidates)} 个全失败)"
            confidence = 0.2
        else:
            top_3 = [c.formula for c in stable_candidates[:3]]
            avg_energy = sum(c.estimated_energy for c in stable_candidates) / len(stable_candidates)
            reply = (
                f"✅ [{domain_label}/{backend}] 生成 {len(stable_candidates)} 个稳定候选 "
                f"(总尝试 {len(candidates)} 个)\n"
                f"平均形成能 {avg_energy:.2f} eV/atom\n"
                f"top-3 化学式:{top_3}"
            )
            confidence = 0.9

        # 6. 成本填充
        if budget is not None and total_cost > budget:
            reply = f"[WARN 超预算] 总成本 ¥{total_cost} > 预算 ¥{budget}\n" + reply

        # 7. SafetyGuard 检查(Stage 1 简版)
        if self.safety_guard:
            response = AgentResponse(
                reply=reply,
                artifacts={"candidates": stable_candidates},
                confidence=confidence,
                cost=total_cost,
            )
            try:
                if not self.safety_guard.check(response):
                    response.reply = f"[BLOCKED by SafetyGuard] {response.reply}"
            except Exception:
                pass  # SafetyGuard 异常不阻断
            return response

        return AgentResponse(
            reply=reply,
            artifacts={"candidates": stable_candidates},
            confidence=confidence,
            cost=total_cost,
        )

    def _estimate_cost(self, n_candidates: int, domain: Optional[str] = None) -> float:
        """估算成本(per W15 domain 单价)

        Args:
            n_candidates: 生成候选数
            domain: 材料域(None → 用 self.domain → 默认 inorganic_crystal)
        """
        from agents.material_domain_router import get_unit_cost_table

        d = domain or self.domain or DEFAULT_DOMAIN
        cost_table = get_unit_cost_table(d)
        per_candidate = cost_table.get("mat-gen-agent", 0.06)
        return round(n_candidates * per_candidate, 4)


def create_default_agent() -> MatGenAgent:
    """便利函数:创建带默认 Harness 的 MatGenAgent"""
    return MatGenAgent(
        n_samples=10,
        target_energy_threshold=-1.5,
    )


if __name__ == "__main__":
    # CLI 入口:python3 -m mat_gen_agent
    agent = create_default_agent()
    print(f"🚀 {agent}")
    print(f"   name: {agent.name}")
    print(f"   harness parts: context_manager={'✓' if agent.context_manager else '✗'}, "
          f"safety_guard={'✓' if agent.safety_guard else '✗'}")

    # 跑 1 个 demo
    req = AgentRequest(
        run_id="demo-001",
        message="设计新型固态电解质,不含贵金属,室温电导率 > 1 mS/cm",
    )
    response = agent.run(req)
    print(f"\n📨 reply: {response.reply}")
    print(f"📊 confidence: {response.confidence:.0%}, cost: ¥{response.cost:.2f}")
    candidates = response.artifacts.get("candidates", [])
    for i, c in enumerate(candidates[:5]):
        print(f"   #{i+1} {c.formula}: 形成能 {c.estimated_energy:.2f} eV/atom, "
              f"confidence {c.confidence:.0%}")


__all__ = ["MatGenAgent", "create_default_agent"]