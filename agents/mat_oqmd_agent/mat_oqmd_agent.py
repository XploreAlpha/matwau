"""mat_oqmd_agent / mat_oqmd_agent.py — OQMD wrapper(继承 MatWAUAgentBase)

业务逻辑:
1. 解析 user_intent → 化学式
2. 调 OqmdClient.search 拉 records
3. 转 AgentResponse(records + canonical_key + sources + is_real flag)
4. 默认 confidence 由 n_results 启发:
   - 0 records → 0.3(可能查不到)
   - 1-2 → 0.6
   - ≥3 → 0.8

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M1 第 5-6 项
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

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

from agents.oqmd_client import (  # noqa: E402
    OqmdClient,
    OqmdReference,
    is_oqmd_available,
    search_oqmd,
)


# ============================================================================
# 配置
# ============================================================================


@dataclass
class OqmdConfig:
    """OQMD 查询配置(per AgentRequest.context)"""

    n_results: int = 5
    include_canonical: bool = True

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "OqmdConfig":
        if not d:
            return cls()
        return cls(
            n_results=d.get("n_results", 5),
            include_canonical=d.get("include_canonical", True),
        )


# ============================================================================
# helper: results → AgentResponse
# ============================================================================


def _results_to_response(
    refs: List[OqmdReference],
    is_real: bool,
    config: OqmdConfig,
    user_intent: str,
) -> AgentResponse:
    """OQMD 查询结果 → AgentResponse

    Args:
        refs: List[OqmdReference]
        is_real: True = 真查 OQMD;False = mock fallback
        config: OqmdConfig
        user_intent: 原始 user_intent(用于 reply)

    Returns:
        AgentResponse 实例
    """
    from agents.data_canonical import CanonicalKey

    # 1. 转 canonical_key(若启用)
    canonical_keys = []
    if config.include_canonical and refs:
        for r in refs:
            try:
                canonical_keys.append(CanonicalKey.from_record(r))
            except Exception:
                canonical_keys.append(CanonicalKey(reduced_formula=""))

    # 2. 自然语言 reply
    source_tag = "🌐 OQMD 实时" if is_real else "🧪 OQMD mock(fallback)"
    lines = [
        f"🔬 {source_tag} 查询结果: {user_intent}",
        f"   命中 {len(refs)} 条记录",
    ]
    if refs:
        lines.append("\n📊 Top 记录:")
        for r in refs[:3]:
            tag = "✓ 稳定" if r.is_stable else "△ 亚稳"
            lines.append(
                f"   [{tag}] {r.formula} | {r.spacegroup or '?'} | "
                f"Ef={r.formation_energy_per_atom:.3f} eV/atom | "
                f"V={r.volume:.1f} Å³ | n={r.n_atoms}"
            )
    if canonical_keys:
        unique_canonical = set(str(k) for k in canonical_keys if k.reduced_formula)
        lines.append(f"\n🔑 Canonical key 归一化: {len(unique_canonical)} 个唯一物相")

    reply = "\n".join(lines)

    # 3. confidence 启发
    if not refs:
        confidence = 0.3
    elif len(refs) <= 2:
        confidence = 0.6
    else:
        confidence = 0.8

    cost = 0.05 if is_real else 0.001  # 真查 > mock

    return AgentResponse(
        reply=reply,
        artifacts={
            "records": [r.to_dict() for r in refs],
            "canonical_keys": [k.to_dict() for k in canonical_keys],
            "n_results": len(refs),
            "is_real_query": is_real,
            "source_platform": "OQMD",
            "source_doi": "10.1038/sdata.2013.1",
            "citation": "Kirklin et al., Sci. Data 2013, 1405",
            "user_intent": user_intent,
        },
        confidence=confidence,
        cost=cost,
    )


# ============================================================================
# MatOqmdAgent
# ============================================================================


class MatOqmdAgent(MatWAUAgentBase):
    """mat-oqmd-agent — OQMD DFT 数据查询助手

    业务流程:
    1. 解析 user_intent
    2. 调 OqmdClient.search
    3. 转 AgentResponse(含 canonical_key + source attribution)
    """

    name = "mat-oqmd-agent"

    def __init__(
        self,
        *,
        default_n_results: int = 5,
        cost_per_query: float = 0.05,
        use_real_oqmd: bool = True,
        client: Optional[OqmdClient] = None,
        **kwargs,
    ) -> None:
        """构造

        Args:
            default_n_results: 默认返回几条
            cost_per_query: 单次查询估算成本 ¥
            use_real_oqmd: True = 真查 OQMD API,False = mock
            client: 可选注入 OqmdClient(测试用)
        """
        super().__init__(**kwargs)
        self.default_n_results = default_n_results
        self.cost_per_query = cost_per_query
        self.use_real_oqmd = use_real_oqmd
        self._client = client or OqmdClient(max_results=default_n_results)

        # 默认 harness
        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return """你是材料科学 OQMD(Open Quantum Materials Database)DFT 数据查询助手(mat-oqmd-agent)。

能力:
1. 解析 user_intent → 化学式(Ni3Cr2Fe2Mo / LiCoO2 / LLZO 等)
2. 调 OQMD REST API(/formationenergy endpoint)查询 DFT 计算数据
3. 返回的字段包括:oqmd_id / formula / spacegroup / formation_energy_per_atom /
   energy_above_hull / volume / n_atoms / is_stable / band_gap
4. 计算 CanonicalKey(归一化化学式 + Pearson 符号 + 空间群编号)供 M3 mat_critic 跨源规则使用
5. cite OQMD 数据来源(Kirklin et al., Sci. Data 2013, 1405)

适用场景:
- "查 Inconel 718 的形成焓"
- "LiCoO2 在 OQMD 里的 stability 数据"
- "对比 LLZO 跟 LGPS 的形成焓"
- 任何已知化学式的 DFT 形成焓 / 凸包距离查询

约束:
- 不接付费库(MPDS / ICSD 等) — 学院版预算不允许
- 单次返回最多 5 条,降级 mock 时仍给有效 reply
- 0 行 UI 代码
"""

    def act(self, ctx: Dict[str, Any], tools: List[str]) -> AgentResponse:
        """Inner Loop 第 3 步:OQMD 查询"""
        user_message = ctx.get("user_message") or ctx.get("message") or ""
        config: OqmdConfig = ctx.get("_input_config") or OqmdConfig()

        if not user_message:
            return self._empty_response("用户 query 为空")

        # 调 OQMD client
        try:
            if self.use_real_oqmd and self._client.enable_fallback:
                refs, is_real = self._client.search(
                    user_message, max_results=config.n_results
                )
            else:
                # mock 模式
                refs, is_real = _mock_search_safe(user_message, config.n_results)
        except Exception as e:
            return self._error_response(f"OQMD 查询失败: {e}")

        # 转 response
        response = _results_to_response(refs, is_real, config, user_message)

        # SafetyGuard
        if self.safety_guard:
            try:
                if not self.safety_guard.check(response):
                    response.reply = f"[BLOCKED by SafetyGuard] {response.reply}"
            except Exception:
                pass

        return response

    def perceive(self, req: AgentRequest) -> Dict[str, Any]:
        """步骤 1 重写:抽取 user_message + config"""
        ctx = super().perceive(req)
        ctx["user_message"] = req.message
        ctx["_input_config"] = OqmdConfig.from_dict(req.context)
        ctx["_input_artifacts"] = req.artifacts or {}
        return ctx

    # ===== helpers =====

    def _empty_response(self, reason: str) -> AgentResponse:
        return AgentResponse(
            reply=f"⚠️ mat-oqmd: {reason}",
            artifacts={"records": [], "n_results": 0, "source_platform": "OQMD"},
            confidence=0.3,
        )

    def _error_response(self, error: str) -> AgentResponse:
        return AgentResponse(
            reply=f"❌ mat-oqmd 错误: {error}",
            artifacts={"records": [], "n_results": 0, "source_platform": "OQMD"},
            confidence=0.0,
            error=error,
        )


# ============================================================================
# 内部 helper
# ============================================================================


def _mock_search_safe(user_intent: str, n: int) -> tuple:
    """mock 模式快捷调用"""
    from agents.oqmd_client.client import _mock_oqmd_response, _build_oqmd_query
    formula = _build_oqmd_query(user_intent)
    refs = _mock_oqmd_response(formula, n=n)
    return refs, False


# ============================================================================
# 工厂 + CLI
# ============================================================================


def create_default_agent() -> MatOqmdAgent:
    """便利函数"""
    return MatOqmdAgent(default_n_results=5)


if __name__ == "__main__":
    print("🚀 MatOqmdAgent Demo")
    print("=" * 60)

    agent = create_default_agent()
    print(f"   {agent}")

    print("\n🔬 Demo 1: Inconel 718 形成焓查询")
    req1 = AgentRequest(
        run_id="oqmd-demo-1",
        message="查 Inconel 718 的形成焓",
    )
    r1 = agent.run(req1)
    print(r1.reply)

    print("\n\n🔬 Demo 2: LiCoO2 stability 查询")
    req2 = AgentRequest(
        run_id="oqmd-demo-2",
        message="LiCoO2 stability",
    )
    r2 = agent.run(req2)
    print(r2.reply)

    print("\n\n🔬 Demo 3: 离线 mock 模式")
    agent3 = MatOqmdAgent(use_real_oqmd=False)
    req3 = AgentRequest(
        run_id="oqmd-demo-3",
        message="LLZO 形成焓",
    )
    r3 = agent3.run(req3)
    print(r3.reply)


__all__ = [
    "MatOqmdAgent",
    "OqmdConfig",
    "create_default_agent",
]