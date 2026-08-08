"""mat_cod_agent / mat_cod_agent.py — COD wrapper(继承 MatWAUAgentBase)

业务逻辑(per mat_oqmd_agent 同模式):
1. 解析 user_intent → 化学式
2. 调 CodClient.search 拉 records + CodClient.fetch_cif 拉 CIF
3. 转 AgentResponse(records + canonical_key + sources)
4. confidence 启发(同 oqmd)

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M1 第 7-8 项
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.cod_client import (
    CodClient,
    CodReference,
    fetch_cif,
)
from agents.widget_helpers import (
    assert_spoken_text_safe,
    attach_widget_protocol,
    make_property_table_widget,
    summarize_for_voice,
)
from matwau.core.agent_base import (
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)
from matwau.harness.context_manager import ContextManager
from matwau.harness.safety_guard import SafetyGuard

# ============================================================================
# 配置
# ============================================================================


@dataclass
class CodConfig:
    """COD 查询配置(per AgentRequest.context)"""

    n_results: int = 5
    include_canonical: bool = True
    fetch_cif_inline: bool = False  # 是否在 response 里附 CIF 全文(默认 False,大)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> CodConfig:
        if not d:
            return cls()
        return cls(
            n_results=d.get("n_results", 5),
            include_canonical=d.get("include_canonical", True),
            fetch_cif_inline=d.get("fetch_cif_inline", False),
        )


# ============================================================================
# helper: results → AgentResponse
# ============================================================================


def _results_to_response(
    refs: list[CodReference],
    is_real: bool,
    config: CodConfig,
    user_intent: str,
) -> AgentResponse:
    """COD 查询结果 → AgentResponse

    Args:
        refs: List[CodReference]
        is_real: True = 真查 COD;False = mock fallback
        config: CodConfig
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
                # COD 用自己的 _canonical_fields(因为 spacegroup_number 是 direct field)
                rf, ps, sgn = CodClient._canonical_fields(r)
                canonical_keys.append(
                    CanonicalKey(reduced_formula=rf, pearson_symbol=ps, spacegroup_number=sgn)
                )
            except Exception:
                canonical_keys.append(CanonicalKey(reduced_formula=""))

    # 2. 自然语言 reply
    source_tag = "🌐 COD 实时" if is_real else "🧪 COD mock(fallback)"
    lines = [
        f"🔬 {source_tag} 查询结果: {user_intent}",
        f"   命中 {len(refs)} 条实验晶体结构",
    ]
    if refs:
        lines.append("\n📊 Top 结构:")
        for r in refs[:3]:
            lines.append(
                f"   [{r.cod_id}] {r.formula} | {r.spacegroup_h_m or '?'} | "
                f"a={r.a:.3f} Å | V={r.volume:.1f} Å³"
            )
    if canonical_keys:
        unique_canonical = {str(k) for k in canonical_keys if k.reduced_formula}
        lines.append(f"\n🔑 Canonical key 归一化: {len(unique_canonical)} 个唯一物相")

    reply = "\n".join(lines)

    # 3. confidence 启发(同 oqmd)
    if not refs:
        confidence = 0.3
    elif len(refs) <= 2:
        confidence = 0.6
    else:
        confidence = 0.8

    cost = 0.02 if is_real else 0.001  # 真查 > mock

    # artifacts
    artifacts = {
        "records": [r.to_dict() for r in refs],
        "canonical_keys": [k.to_dict() for k in canonical_keys],
        "n_results": len(refs),
        "is_real_query": is_real,
        "source_platform": "COD",
        "source_doi": "10.1107/S0108768111046701",
        "citation": "Gražulis et al., Nucleic Acids Res. 2012, D13",
        "user_intent": user_intent,
    }

    # 可选:fetch_cif_inline
    if config.fetch_cif_inline and refs:
        # 拉首条 CIF
        first = refs[0]
        cif_text = fetch_cif(first.cod_id)
        if cif_text:
            artifacts["cif_text"] = cif_text[:4000]  # 限 4 KB
            artifacts["cif_cod_id"] = first.cod_id

    response = AgentResponse(
        reply=reply,
        artifacts=artifacts,
        confidence=confidence,
        cost=cost,
    )

    # v1.4-Academic M3 — attach matwau_property_table widget(取首条 record 作 formula + 晶格常数 properties)
    if refs:
        primary = refs[0]
        properties = [
            {"name": "a", "label": "a 晶格",
             "value": round(primary.a, 4), "unit": "Å", "source": "COD"},
            {"name": "b", "label": "b 晶格",
             "value": round(primary.b, 4), "unit": "Å", "source": "COD"},
            {"name": "c", "label": "c 晶格",
             "value": round(primary.c, 4), "unit": "Å", "source": "COD"},
            {"name": "alpha", "label": "α 角",
             "value": round(primary.alpha, 2), "unit": "°", "source": "COD"},
            {"name": "beta", "label": "β 角",
             "value": round(primary.beta, 2), "unit": "°", "source": "COD"},
            {"name": "gamma", "label": "γ 角",
             "value": round(primary.gamma, 2), "unit": "°", "source": "COD"},
            {"name": "volume", "label": "体积",
             "value": round(primary.volume, 3), "unit": "Å³", "source": "COD"},
            {"name": "spacegroup", "label": "空间群",
             "value": primary.spacegroup_h_m or "?", "unit": "", "source": "COD"},
        ]
        widget = make_property_table_widget(
            formula=primary.formula,
            properties=properties,
            source_platform="COD",
        )
        spoken = summarize_for_voice(properties, user_intent, locale="zh", kind="properties")
        response.artifacts["source_platform"] = "COD"
        attach_widget_protocol(
            response,
            widgets=[widget],
            spoken_text=spoken,
            structured_data={"records": [r.to_dict() for r in refs], "n_results": len(refs),
                             "source_platform": "COD", "formula": primary.formula},
        )
        assert_spoken_text_safe(spoken)

    return response


# ============================================================================
# MatCodAgent
# ============================================================================


class MatCodAgent(MatWAUAgentBase):
    """mat-cod-agent — COD 实验晶体结构查询助手

    业务流程:
    1. 解析 user_intent
    2. 调 CodClient.search 拉 records
    3. 可选 fetch_cif 拉首条 CIF
    4. 转 AgentResponse(含 canonical_key + source attribution)
    """

    name = "mat-cod-agent"

    def __init__(
        self,
        *,
        default_n_results: int = 5,
        cost_per_query: float = 0.02,
        use_real_cod: bool = True,
        client: CodClient | None = None,
        **kwargs,
    ) -> None:
        """构造

        Args:
            default_n_results: 默认返回几条
            cost_per_query: 单次查询估算成本 ¥
            use_real_cod: True = 真查 COD,False = mock
            client: 可选注入 CodClient(测试用)
        """
        super().__init__(**kwargs)
        self.default_n_results = default_n_results
        self.cost_per_query = cost_per_query
        self.use_real_cod = use_real_cod
        self._client = client or CodClient(max_results=default_n_results)

        # 默认 harness
        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return """你是材料科学 COD(Crystallography Open Database)实验晶体结构查询助手(mat-cod-agent)。

能力:
1. 解析 user_intent → 化学式
2. 调 COD REST API(/cod/cgi-bin/cif-get.py)查询实验晶体结构
3. 返回的字段包括:cod_id / formula / spacegroup_h_m / spacegroup_number /
   a/b/c 晶格常数 / alpha/beta/gamma 晶格角 / volume / cod_cif_url / citation
4. 可选拉 CIF 全文(供下游 mat_exp / mat_robot_synth 等解析)
5. 计算 CanonicalKey 供 M3 mat_critic 跨源规则使用
6. cite COD 数据来源(Gražulis et al., Nucleic Acids Res. 2012, D13)

适用场景:
- "查 Si 已知实验结构"
- "TiO2 在 COD 里的标准结构"
- "LiCoO2 实验测得晶格常数"
- 任何已知化学式的实验晶体结构查询

约束:
- 不接付费库(ICSD / MPDS 等) — 学院版预算不允许
- M1 简化:仅依赖已知 mock 字典 + cif-get.py 直接拉 CIF
- 0 行 UI 代码
"""

    def act(self, ctx: dict[str, Any], tools: list[str]) -> AgentResponse:
        """Inner Loop 第 3 步:COD 查询"""
        user_message = ctx.get("user_message") or ctx.get("message") or ""
        config: CodConfig = ctx.get("_input_config") or CodConfig()

        if not user_message:
            return self._empty_response("用户 query 为空")

        # 调 COD client
        try:
            if self.use_real_cod and self._client.enable_fallback:
                refs, is_real = self._client.search(
                    user_message, max_results=config.n_results
                )
            else:
                refs, is_real = _mock_search_safe(user_message, config.n_results)
        except Exception as e:
            return self._error_response(f"COD 查询失败: {e}")

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

    def perceive(self, req: AgentRequest) -> dict[str, Any]:
        """步骤 1 重写:抽取 user_message + config"""
        ctx = super().perceive(req)
        ctx["user_message"] = req.message
        ctx["_input_config"] = CodConfig.from_dict(req.context)
        ctx["_input_artifacts"] = req.artifacts or {}
        return ctx

    # ===== helpers =====

    def _empty_response(self, reason: str) -> AgentResponse:
        return AgentResponse(
            reply=f"⚠️ mat-cod: {reason}",
            artifacts={"records": [], "n_results": 0, "source_platform": "COD"},
            confidence=0.3,
        )

    def _error_response(self, error: str) -> AgentResponse:
        return AgentResponse(
            reply=f"❌ mat-cod 错误: {error}",
            artifacts={"records": [], "n_results": 0, "source_platform": "COD"},
            confidence=0.0,
            error=error,
        )


# ============================================================================
# 内部 helper
# ============================================================================


def _mock_search_safe(user_intent: str, n: int) -> tuple:
    """mock 模式快捷调用"""
    from agents.cod_client.client import _build_cod_query, _mock_cod_response
    formula = _build_cod_query(user_intent)
    refs = _mock_cod_response(formula, n=n)
    return refs, False


# ============================================================================
# 工厂 + CLI
# ============================================================================


def create_default_agent() -> MatCodAgent:
    """便利函数"""
    return MatCodAgent(default_n_results=5)


if __name__ == "__main__":
    print("🚀 MatCodAgent Demo")
    print("=" * 60)

    agent = create_default_agent()
    print(f"   {agent}")

    print("\n🔬 Demo 1: Si 已知结构查询")
    req1 = AgentRequest(
        run_id="cod-demo-1",
        message="查 Si 已知实验结构",
    )
    r1 = agent.run(req1)
    print(r1.reply)

    print("\n\n🔬 Demo 2: TiO2 标准结构(rutile)")
    req2 = AgentRequest(
        run_id="cod-demo-2",
        message="TiO2 标准结构",
        context={"fetch_cif_inline": True},
    )
    r2 = agent.run(req2)
    print(r2.reply)
    if "cif_text" in r2.artifacts:
        print(f"\n📄 CIF 前 200 字符: {r2.artifacts['cif_text'][:200]}")

    print("\n\n🔬 Demo 3: 离线 mock 模式")
    agent3 = MatCodAgent(use_real_cod=False)
    req3 = AgentRequest(
        run_id="cod-demo-3",
        message="Inconel 718 实验结构",
    )
    r3 = agent3.run(req3)
    print(r3.reply)


__all__ = [
    "CodConfig",
    "MatCodAgent",
    "create_default_agent",
]