"""mat_nomad_agent / mat_nomad_agent.py — NOMAD wrapper(继承 MatWAUAgentBase)

业务逻辑(per mat_oqmd_agent / mat_cod_agent 同模式):
1. 解析 user_intent → 化学式
2. 调 NomadClient.search 拉 records
3. 转 AgentResponse(records + canonical_key + sources + metainfo_unmapped)
4. confidence 启发(同 oqmd)
5. metainfo_unmapped 字段填到 artifacts,供 M3 mat_critic L4 规则使用

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2 第 5-6 项
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.nomad_client import (
    NomadClient,
    NomadReference,
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
class NomadConfig:
    """NOMAD 查询配置(per AgentRequest.context)"""

    n_results: int = 5
    include_canonical: bool = True
    include_metainfo_unmapped: bool = True  # 是否导出 metainfo_unmapped 到 artifacts

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> NomadConfig:
        if not d:
            return cls()
        return cls(
            n_results=d.get("n_results", 5),
            include_canonical=d.get("include_canonical", True),
            include_metainfo_unmapped=d.get("include_metainfo_unmapped", True),
        )


# ============================================================================
# helper: results → AgentResponse
# ============================================================================


def _results_to_response(
    refs: list[NomadReference],
    is_real: bool,
    config: NomadConfig,
    user_intent: str,
) -> AgentResponse:
    """NOMAD 查询结果 → AgentResponse"""
    from agents.data_canonical import CanonicalKey

    # 1. 转 canonical_key
    canonical_keys: list[CanonicalKey] = []
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

    # 2. 自然语言 reply
    source_tag = "🌐 NOMAD 实时" if is_real else "🧪 NOMAD mock(fallback)"
    lines = [
        f"🔬 {source_tag} 查询结果: {user_intent}",
        f"   命中 {len(refs)} 条 entry",
    ]
    if refs:
        lines.append("\n📊 Top entry:")
        for r in refs[:3]:
            dim_tag = ""
            if r.available_properties:
                props = ", ".join(r.available_properties[:3])
                dim_tag = f" | props=[{props}]"
            gap_str = f"Eg={r.band_gap_eV:.2f} eV" if r.band_gap_eV else "Eg=?"
            lines.append(
                f"   [{r.entry_id}] {r.formula} | {r.spacegroup_symbol or '?'} | "
                f"{gap_str}{dim_tag}"
            )

    # metainfo_unmapped 聚合
    all_unmapped: list[str] = []
    if config.include_metainfo_unmapped:
        for r in refs:
            all_unmapped.extend(r.metainfo_unmapped)
    unique_unmapped = sorted(set(all_unmapped))

    if unique_unmapped:
        lines.append(
            f"\n🔬 未映射 metainfo 字段({len(unique_unmapped)} 个,供 M3 mat_critic 用):"
        )
        for p in unique_unmapped[:5]:
            lines.append(f"   - {p}")
        if len(unique_unmapped) > 5:
            lines.append(f"   ... +{len(unique_unmapped) - 5} more")

    if canonical_keys:
        unique_canonical = {str(k) for k in canonical_keys if k.reduced_formula}
        lines.append(f"\n🔑 Canonical key 归一化: {len(unique_canonical)} 个唯一物相")

    reply = "\n".join(lines)

    # 3. confidence 启发(同 oqmd / cod)
    if not refs:
        confidence = 0.3
    elif len(refs) <= 2:
        confidence = 0.6
    else:
        confidence = 0.8

    cost = 0.05 if is_real else 0.001

    response = AgentResponse(
        reply=reply,
        artifacts={
            "records": [r.to_dict() for r in refs],
            "canonical_keys": [k.to_dict() for k in canonical_keys],
            "n_results": len(refs),
            "is_real_query": is_real,
            "source_platform": "NOMAD",
            "source_doi": "10.1088/2515-7655/ab002a",
            "citation": "Draxl & Scheffler, J. Phys. Mater. 2019, 2",
            "user_intent": user_intent,
            "metainfo_unmapped": unique_unmapped,
        },
        confidence=confidence,
        cost=cost,
    )

    # v1.4-Academic M3 — attach matwau_property_table widget(NOMAD 综合物性)
    if refs:
        primary = refs[0]
        properties = []
        if primary.band_gap_eV is not None:
            properties.append({"name": "band_gap_eV", "label": "带隙",
                               "value": round(primary.band_gap_eV, 3),
                               "unit": "eV", "source": "NOMAD"})
        if primary.formation_energy_per_atom_eV is not None:
            properties.append({"name": "formation_energy_per_atom_eV", "label": "形成能",
                               "value": round(primary.formation_energy_per_atom_eV, 3),
                               "unit": "eV/atom", "source": "NOMAD"})
        if primary.bulk_modulus_GPa is not None:
            properties.append({"name": "bulk_modulus_GPa", "label": "体积模量",
                               "value": round(primary.bulk_modulus_GPa, 2),
                               "unit": "GPa", "source": "NOMAD"})
        if primary.energy_above_hull_eV is not None:
            properties.append({"name": "energy_above_hull_eV", "label": "凸包距",
                               "value": round(primary.energy_above_hull_eV, 3),
                               "unit": "eV/atom", "source": "NOMAD"})
        if primary.spacegroup_symbol:
            properties.append({"name": "spacegroup_symbol", "label": "空间群",
                               "value": primary.spacegroup_symbol,
                               "unit": "", "source": "NOMAD"})
        if primary.xc_functional:
            properties.append({"name": "xc_functional", "label": "XC 泛函",
                               "value": primary.xc_functional,
                               "unit": "", "source": "NOMAD"})

        if properties:
            widget = make_property_table_widget(
                formula=primary.formula,
                properties=properties,
                source_platform="NOMAD",
            )
            spoken = summarize_for_voice(properties, user_intent, locale="zh", kind="properties")
            attach_widget_protocol(
                response,
                widgets=[widget],
                spoken_text=spoken,
                structured_data={"records": [r.to_dict() for r in refs], "n_results": len(refs),
                                 "source_platform": "NOMAD", "formula": primary.formula},
            )
            assert_spoken_text_safe(spoken)

    return response


# ============================================================================
# MatNomadAgent
# ============================================================================


class MatNomadAgent(MatWAUAgentBase):
    """mat-nomad-agent — NOMAD archive 综合数据查询助手

    业务流程:
    1. 解析 user_intent → 化学式
    2. 调 NomadClient.search 拉 records(metainfo 标准化)
    3. 转 AgentResponse(含 canonical_key + metainfo_unmapped)
    """

    name = "mat-nomad-agent"

    def __init__(
        self,
        *,
        default_n_results: int = 5,
        cost_per_query: float = 0.05,
        use_real_nomad: bool = True,
        client: NomadClient | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.default_n_results = default_n_results
        self.cost_per_query = cost_per_query
        self.use_real_nomad = use_real_nomad
        self._client = client or NomadClient(max_results=default_n_results)

        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return """你是材料科学 NOMAD(Novel Materials Discovery)archive 综合数据查询助手(mat-nomad-agent)。

能力:
1. 解析 user_intent → 化学式(Ni3Cr2Fe2Mo / LiCoO2 / LLZO 等)
2. 调 NOMAD REST API(/entries endpoint)查询 archive entry
3. 标准化 NOMAD metainfo(per metainfo_mapping.py,~30 关键字段)
4. 返回的字段包括:entry_id / formula / elements / spacegroup_symbol /
   spacegroup_number / 晶格常数 / band_gap_eV / formation_energy_per_atom_eV /
   energy_above_hull_eV / bulk_modulus_GPa / xc_functional / program_name /
   available_properties
5. 计算 CanonicalKey(归一化化学式 + Pearson 符号 + 空间群编号)供 M3 mat_critic 跨源规则使用
6. 导出未映射 metainfo 路径(metainfo_unmapped)供 M3 扩展规则参考
7. cite NOMAD 数据来源(Draxl & Scheffler, J. Phys. Mater. 2019, 2)

适用场景:
- "查 LiCoO2 在 NOMAD 里的 formation energy / bulk modulus"
- "LLZO 的 electronic properties"
- "Ni3Cr2Fe2Mo 是否在 NOMAD archive 中"
- 任何已知化学式的综合材料性质查询

约束:
- 单次返回最多 5 条,降级 mock 时仍给有效 reply
- metainfo_unmapped 字段供 M3 调试,不阻塞当前返回
- 学院方 IT 配 Bearer token 用 MATWAU_NOMAD_TOKEN 环境变量
- 0 行 UI 代码
"""

    def act(self, ctx: dict[str, Any], tools: list[str]) -> AgentResponse:
        user_message = ctx.get("user_message") or ctx.get("message") or ""
        config: NomadConfig = ctx.get("_input_config") or NomadConfig()

        if not user_message:
            return self._empty_response("用户 query 为空")

        try:
            if self.use_real_nomad and self._client.enable_fallback:
                refs, is_real = self._client.search(
                    user_message, max_results=config.n_results
                )
            else:
                refs, is_real = _mock_search_safe(user_message, config.n_results)
        except Exception as e:
            return self._error_response(f"NOMAD 查询失败: {e}")

        response = _results_to_response(refs, is_real, config, user_message)

        if self.safety_guard:
            try:
                if not self.safety_guard.check(response):
                    response.reply = f"[BLOCKED by SafetyGuard] {response.reply}"
            except Exception:
                pass

        return response

    def perceive(self, req: AgentRequest) -> dict[str, Any]:
        ctx = super().perceive(req)
        ctx["user_message"] = req.message
        ctx["_input_config"] = NomadConfig.from_dict(req.context)
        ctx["_input_artifacts"] = req.artifacts or {}
        return ctx

    def _empty_response(self, reason: str) -> AgentResponse:
        return AgentResponse(
            reply=f"⚠️ mat-nomad: {reason}",
            artifacts={"records": [], "n_results": 0, "source_platform": "NOMAD"},
            confidence=0.3,
        )

    def _error_response(self, error: str) -> AgentResponse:
        return AgentResponse(
            reply=f"❌ mat-nomad 错误: {error}",
            artifacts={"records": [], "n_results": 0, "source_platform": "NOMAD"},
            confidence=0.0,
            error=error,
        )


# ============================================================================
# 内部 helper
# ============================================================================


def _mock_search_safe(user_intent: str, n: int) -> tuple:
    """mock 模式快捷调用"""
    from agents.nomad_client.client import _build_nomad_query, _mock_nomad_response
    formula = _build_nomad_query(user_intent)
    refs = _mock_nomad_response(formula, n=n)
    return refs, False


# ============================================================================
# 工厂 + CLI
# ============================================================================


def create_default_agent() -> MatNomadAgent:
    return MatNomadAgent(default_n_results=5)


if __name__ == "__main__":
    print("🚀 MatNomadAgent Demo")
    print("=" * 60)

    agent = create_default_agent()
    print(f"   {agent}")

    print("\n🔬 Demo 1: LiCoO2 在 NOMAD 中的 formation energy")
    req1 = AgentRequest(
        run_id="nomad-demo-1",
        message="查 LiCoO2 在 NOMAD 里的形成能",
    )
    r1 = agent.run(req1)
    print(r1.reply)

    print("\n\n🔬 Demo 2: LLZO 综合性质")
    req2 = AgentRequest(
        run_id="nomad-demo-2",
        message="LLZO bulk modulus",
    )
    r2 = agent.run(req2)
    print(r2.reply)

    print("\n\n🔬 Demo 3: 离线 mock 模式")
    agent3 = MatNomadAgent(use_real_nomad=False)
    req3 = AgentRequest(
        run_id="nomad-demo-3",
        message="TiO2 综合性质",
    )
    r3 = agent3.run(req3)
    print(r3.reply)


__all__ = [
    "MatNomadAgent",
    "NomadConfig",
    "create_default_agent",
]