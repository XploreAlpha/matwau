"""mat_jarvis_agent / mat_jarvis_agent.py — JARVIS wrapper(继承 MatWAUAgentBase)

业务逻辑(per mat_oqmd_agent / mat_cod_agent 同模式):
1. 解析 user_intent → 化学式
2. 调 JarvClient.search 拉 records
3. 转 AgentResponse(records + canonical_key + sources + 2D/3D 标记)
4. confidence 启发(同 oqmd / cod)
5. is_jarvis_tools_available 检测 → reply 里标注 "jarvis-tools 包状态"

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2 第 7-8 项
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

from agents.jarvis_client import (  # noqa: E402
    JarvClient,
    JarvReference,
    is_jarvis_available,
    is_jarvis_tools_available,
    search_jarvis,
)


# ============================================================================
# 配置
# ============================================================================


@dataclass
class JarvConfig:
    """JARVIS 查询配置(per AgentRequest.context)"""

    n_results: int = 5
    include_canonical: bool = True
    include_2d_only: bool = False  # True = 只返回 2D 材料

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "JarvConfig":
        if not d:
            return cls()
        return cls(
            n_results=d.get("n_results", 5),
            include_canonical=d.get("include_canonical", True),
            include_2d_only=d.get("include_2d_only", False),
        )


# ============================================================================
# helper: results → AgentResponse
# ============================================================================


def _results_to_response(
    refs: List[JarvReference],
    is_real: bool,
    config: JarvConfig,
    user_intent: str,
    jarvis_tools_available: bool,
) -> AgentResponse:
    """JARVIS 查询结果 → AgentResponse"""
    from agents.data_canonical import CanonicalKey

    # 1. 过滤 2D-only(若启用)
    if config.include_2d_only:
        refs = [r for r in refs if r.is_2d]

    # 2. 转 canonical_key
    canonical_keys: List[CanonicalKey] = []
    if config.include_canonical and refs:
        for r in refs:
            try:
                canonical_keys.append(
                    CanonicalKey.from_formula_spacegroup(
                        r.formula, r.spacegroup_symbol,
                    )
                )
            except Exception:
                canonical_keys.append(CanonicalKey(reduced_formula=""))

    # 3. 自然语言 reply
    source_tag = "🌐 JARVIS 实时" if is_real else "🧪 JARVIS mock(fallback)"
    lines = [
        f"🔬 {source_tag} 查询结果: {user_intent}",
        f"   命中 {len(refs)} 条 JARVIS entry",
    ]
    if refs:
        lines.append("\n📊 Top entry:")
        for r in refs[:3]:
            dim_marker = "🧊 2D" if r.is_2d else "🧱 3D"
            gap_str = f"Eg={r.band_gap_eV:.2f} eV" if r.band_gap_eV else "Eg=?"
            xc = f"({r.xc_functional})" if r.xc_functional else ""
            lines.append(
                f"   [{dim_marker}] [{r.jid}] {r.formula} | {r.spacegroup_symbol or '?'} | "
                f"{gap_str} {xc}"
            )
    if canonical_keys:
        unique_canonical = set(str(k) for k in canonical_keys if k.reduced_formula)
        lines.append(f"\n🔑 Canonical key 归一化: {len(unique_canonical)} 个唯一物相")

    # jarvis-tools 包状态
    pkg_status = "✓ jarvis-tools 已装" if jarvis_tools_available else "△ jarvis-tools 未装(纯 REST 模式)"
    lines.append(f"\n📦 {pkg_status}")

    reply = "\n".join(lines)

    # 4. confidence 启发
    if not refs:
        confidence = 0.3
    elif len(refs) <= 2:
        confidence = 0.6
    else:
        confidence = 0.8

    cost = 0.05 if is_real else 0.001

    return AgentResponse(
        reply=reply,
        artifacts={
            "records": [r.to_dict() for r in refs],
            "canonical_keys": [k.to_dict() for k in canonical_keys],
            "n_results": len(refs),
            "is_real_query": is_real,
            "source_platform": "JARVIS",
            "source_doi": "10.1038/s41597-020-00673-3",
            "citation": "Choudhary et al., Sci. Data 2020, 1408",
            "user_intent": user_intent,
            "jarvis_tools_available": jarvis_tools_available,
            "n_2d_records": sum(1 for r in refs if r.is_2d),
            "n_3d_records": sum(1 for r in refs if not r.is_2d),
        },
        confidence=confidence,
        cost=cost,
    )


# ============================================================================
# MatJarvAgent
# ============================================================================


class MatJarvAgent(MatWAUAgentBase):
    """mat-jarvis-agent — JARVIS 综合材料性质查询助手(2D + 3D)

    业务流程:
    1. 解析 user_intent → 化学式
    2. 调 JarvClient.search 拉 records
    3. 可选 filter 2D only
    4. 转 AgentResponse(含 canonical_key + 2D/3D 标记)
    """

    name = "mat-jarvis-agent"

    def __init__(
        self,
        *,
        default_n_results: int = 5,
        cost_per_query: float = 0.05,
        use_real_jarvis: bool = True,
        client: Optional[JarvClient] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.default_n_results = default_n_results
        self.cost_per_query = cost_per_query
        self.use_real_jarvis = use_real_jarvis
        self._client = client or JarvClient(max_results=default_n_results)

        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return """你是材料科学 JARVIS(Joint Automated Reverse Engineering & Scoring
Materials Database)综合性质查询助手(mat-jarvis-agent)。

能力:
1. 解析 user_intent → 化学式
2. 调 JARVIS REST API(/jarvisdb/3dmat endpoint)查询综合材料性质
3. jarvis-tools Python 包作为 optional(若未装则仅走 REST,降级不阻塞)
4. 返回的字段包括:jid / formula / elements / spacegroup_symbol /
   spacegroup_number / 晶格常数 / formation_energy_per_atom_eV / band_gap_eV /
   bulk_modulus_GPa / magmom / dimensionality / is_2d / xc_functional
5. 计算 CanonicalKey 供 M3 mat_critic 跨源规则使用
6. 区分 2D 材料(MoS2 / graphene / etc.)和 3D 材料(常规晶体)
7. cite JARVIS 数据来源(Choudhary et al., Sci. Data 2020, 1408)

适用场景:
- "查 MoS2 带隙(2D 半导体)"
- "GaN 的 bulk modulus(VASP PBE)"
- "LiCoO2 在 JARVIS 中的 Eg"
- 任何已知化学式的综合性质查询,特别是 2D 材料

约束:
- 单次返回最多 5 条,降级 mock 时仍给有效 reply
- jarvis-tools 包缺失时不报错,降级到 REST 模式
- 学院方 IT 配 Bearer token 用 MATWAU_JARVIS_TOKEN 环境变量
- 0 行 UI 代码
"""

    def act(self, ctx: Dict[str, Any], tools: List[str]) -> AgentResponse:
        user_message = ctx.get("user_message") or ctx.get("message") or ""
        config: JarvConfig = ctx.get("_input_config") or JarvConfig()

        if not user_message:
            return self._empty_response("用户 query 为空")

        jarvis_tools_available = is_jarvis_tools_available()

        try:
            if self.use_real_jarvis and self._client.enable_fallback:
                refs, is_real = self._client.search(
                    user_message, max_results=config.n_results
                )
            else:
                refs, is_real = _mock_search_safe(user_message, config.n_results)
        except Exception as e:
            return self._error_response(f"JARVIS 查询失败: {e}")

        response = _results_to_response(refs, is_real, config, user_message, jarvis_tools_available)

        if self.safety_guard:
            try:
                if not self.safety_guard.check(response):
                    response.reply = f"[BLOCKED by SafetyGuard] {response.reply}"
            except Exception:
                pass

        return response

    def perceive(self, req: AgentRequest) -> Dict[str, Any]:
        ctx = super().perceive(req)
        ctx["user_message"] = req.message
        ctx["_input_config"] = JarvConfig.from_dict(req.context)
        ctx["_input_artifacts"] = req.artifacts or {}
        return ctx

    def _empty_response(self, reason: str) -> AgentResponse:
        return AgentResponse(
            reply=f"⚠️ mat-jarvis: {reason}",
            artifacts={"records": [], "n_results": 0, "source_platform": "JARVIS"},
            confidence=0.3,
        )

    def _error_response(self, error: str) -> AgentResponse:
        return AgentResponse(
            reply=f"❌ mat-jarvis 错误: {error}",
            artifacts={"records": [], "n_results": 0, "source_platform": "JARVIS"},
            confidence=0.0,
            error=error,
        )


# ============================================================================
# 内部 helper
# ============================================================================


def _mock_search_safe(user_intent: str, n: int) -> tuple:
    """mock 模式快捷调用"""
    from agents.jarvis_client.client import _mock_jarvis_response, _build_jarvis_query
    formula = _build_jarvis_query(user_intent)
    refs = _mock_jarvis_response(formula, n=n)
    return refs, False


# ============================================================================
# 工厂 + CLI
# ============================================================================


def create_default_agent() -> MatJarvAgent:
    return MatJarvAgent(default_n_results=5)


if __name__ == "__main__":
    print("🚀 MatJarvAgent Demo")
    print("=" * 60)

    agent = create_default_agent()
    print(f"   {agent}")

    print("\n🔬 Demo 1: MoS2 2D 材料查询")
    req1 = AgentRequest(
        run_id="jarvis-demo-1",
        message="查 MoS2 2D 材料带隙",
    )
    r1 = agent.run(req1)
    print(r1.reply)

    print("\n\n🔬 Demo 2: 仅 2D 材料")
    req2 = AgentRequest(
        run_id="jarvis-demo-2",
        message="MoS2 综合性质",
        context={"include_2d_only": True},
    )
    r2 = agent.run(req2)
    print(r2.reply)

    print("\n\n🔬 Demo 3: 离线 mock 模式")
    agent3 = MatJarvAgent(use_real_jarvis=False)
    req3 = AgentRequest(
        run_id="jarvis-demo-3",
        message="GaN bulk modulus",
    )
    r3 = agent3.run(req3)
    print(r3.reply)


__all__ = [
    "MatJarvAgent",
    "JarvConfig",
    "create_default_agent",
]