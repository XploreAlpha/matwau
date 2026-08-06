"""mat_pubchem_agent / mat_pubchem_agent.py — PubChem wrapper(继承 MatWAUAgentBase)

业务逻辑:
1. 解析 user_intent → 化学式 / 名字
2. 调 PubChemClient.search 拉 records(自动 LRU cache 复用)
3. 转 AgentResponse(records + is_real_query + confidence + cost)
4. 默认 confidence 启发:
   - 0 records → 0.3(可能查不到)
   - 1 record → 0.6
   - ≥2 records → 0.8

per MatWAU-v1.3.3-Academic-dev-plan-20260806.md §三 M1
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.pubchem_client import PubChemClient, PubChemReference
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
class PubChemAgentConfig:
    """PubChem 查询配置(per AgentRequest.context)"""

    n_results: int = 5
    max_results_hard_cap: int = 20
    enable_cache: bool = True
    cache_size: int = 128

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> PubChemAgentConfig:
        if not d:
            return cls()
        n_results = int(d.get("n_results", 5))
        if n_results > cls.max_results_hard_cap:
            n_results = cls.max_results_hard_cap
        return cls(
            n_results=n_results,
            enable_cache=d.get("enable_cache", True),
            cache_size=int(d.get("cache_size", 128)),
        )


# ============================================================================
# helper: results → AgentResponse
# ============================================================================


def _results_to_response(
    refs: list[PubChemReference],
    is_real: bool,
    config: PubChemAgentConfig,
    user_intent: str,
) -> AgentResponse:
    """PubChem 查询结果 → AgentResponse"""
    records = [r.to_dict() for r in refs]

    n = len(records)
    if n == 0:
        confidence = 0.3
    elif n == 1:
        confidence = 0.6
    else:
        confidence = 0.8

    source_tag = "🌐 PubChem 实时" if is_real else "🧪 PubChem mock(fallback)"
    lines = [
        f"💊 {source_tag} 化合物查询: {user_intent}",
        f"   命中 {n} 个化合物",
    ]
    if refs:
        lines.append("\n📋 Top 化合物:")
        for r in refs[:3]:
            mw_str = f"MW={r.molecular_weight:.2f}" if r.molecular_weight else "MW=?"
            smi = r.canonical_smiles[:50] + ("..." if len(r.canonical_smiles) > 50 else "")
            lines.append(
                f"   CID {r.cid} | {r.molecular_formula} | {mw_str} | SMILES={smi}"
            )
    if not is_real:
        lines.append("\n⚠️ 真 PubChem 不可达,使用本地 mock 数据(向后兼容 W14)")

    reply = "\n".join(lines)
    cost = 0.01 if is_real else 0.001

    return AgentResponse(
        reply=reply,
        artifacts={
            "records": records,
            "canonical_key": None,
            "sources": ["pubchem"],
            "is_real_query": is_real,
            "n_results": n,
            "source_platform": "PubChem",
            "source_doi": "",
            "citation": "Kim et al., Nucleic Acids Res. 2025, gkaf1020",
            "user_intent": user_intent,
        },
        confidence=confidence,
        cost=cost,
    )


# ============================================================================
# MatPubChemAgent
# ============================================================================


class MatPubChemAgent(MatWAUAgentBase):
    """mat-pubchem-agent — PubChem 化合物数据查询助手(v1.3.3-Academic M1)"""

    name = "mat-pubchem-agent"

    def __init__(
        self,
        *,
        default_n_results: int = 5,
        cost_per_query: float = 0.01,
        use_real_pubchem: bool = True,
        client: PubChemClient | None = None,
        context_manager: ContextManager | None = None,
        safety_guard: SafetyGuard | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            context_manager=context_manager,
            safety_guard=safety_guard,
            **kwargs,
        )
        self.default_n_results = default_n_results
        self.cost_per_query = cost_per_query
        self.use_real_pubchem = use_real_pubchem
        self._client = client or PubChemClient(
            max_results=default_n_results,
            enable_cache=True,
        )

        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return """你是材料科学 PubChem 化合物数据查询助手(mat-pubchem-agent)。

能力:
1. 解析 user_intent → 化学式 / 名字(CID / SMILES / IUPAC / 通用名)
2. 调 PubChem REST API(https://pubchem.ncbi.nlm.nih.gov/rest/pug)查化合物
3. 返回字段:CID / MolecularFormula / MolecularWeight / IUPACName /
   CanonicalSMILES / IsomericSMILES / InChI / InChIKey
4. LRU cache(v1.3.3):同 query < 1ms 命中
5. 失败 fallback 到 mock(W14 向后兼容)

适用场景:
- "查 LiCoO2 的 SMILES"
- "查询 PMMA 的 IUPAC 名称"
- "LiCoO2 的 CID 是多少"
- 任何已知化学式 / 名字的化合物查询

约束:
- 速率 5 req/sec(per PubChem docs)— LRU cache 复用
- 不下载结构图(只元数据)
- 单次返回最多 5 个(默认),可通过 context.n_results 调整
- 0 行 UI 代码
"""

    def act(self, ctx: dict[str, Any], tools: list[str]) -> AgentResponse:
        user_message = ctx.get("user_message") or ctx.get("message") or ""
        config: PubChemAgentConfig = ctx.get("_input_config") or PubChemAgentConfig()

        if not user_message:
            return self._empty_response("用户 query 为空")

        try:
            if self.use_real_pubchem:
                refs, is_real = self._client.search(
                    user_message,
                    max_results=config.n_results,
                )
            else:
                refs, is_real = _mock_pubchem_response(user_message, config.n_results)
        except Exception as e:
            return self._error_response(f"PubChem 查询失败: {e}")

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
        ctx["_input_config"] = PubChemAgentConfig.from_dict(req.context)
        ctx["_input_artifacts"] = req.artifacts or {}
        return ctx

    def _empty_response(self, reason: str) -> AgentResponse:
        return AgentResponse(
            reply=f"⚠️ mat-pubchem: {reason}",
            artifacts={"records": [], "n_results": 0, "source_platform": "PubChem"},
            confidence=0.3,
        )

    def _error_response(self, error: str) -> AgentResponse:
        return AgentResponse(
            reply=f"❌ mat-pubchem 错误: {error}",
            artifacts={"records": [], "n_results": 0, "source_platform": "PubChem"},
            confidence=0.0,
            error=error,
        )


# ============================================================================
# 内部 helper: mock 模式(W14 向后兼容)
# ============================================================================


def _mock_pubchem_response(
    user_intent: str, n: int
) -> tuple[list[PubChemReference], bool]:
    """mock 模式快捷调用 — 返回假 PubChem 化合物(W14 行为)"""
    refs = []
    for i in range(n):
        refs.append(
            PubChemReference(
                cid=1000000 + i,
                name=f"mock_{user_intent[:20]}_{i}",
                molecular_formula=f"C{i}H{i+1}O{i}",
                iupac_name=f"mock compound {i + 1} of {user_intent[:30]}",
                canonical_smiles=f"[mock{i}]",
                isomeric_smiles=f"[mock{i}]",
                molecular_weight=100.0 + i * 10,
                url=f"https://pubchem.ncbi.nlm.nih.gov/compound/{1000000 + i}",
            )
        )
    return refs, False


# ============================================================================
# 工厂
# ============================================================================


def create_default_agent() -> MatPubChemAgent:
    """便利函数:创建默认配置 agent"""
    return MatPubChemAgent(default_n_results=5)


# ============================================================================
# CLI demo
# ============================================================================


if __name__ == "__main__":
    print("🚀 MatPubChemAgent Demo")
    print("=" * 60)

    agent = create_default_agent()
    print(f"   {agent}")

    print("\n💊 Demo 1: PubChem 真查 LiCoO2")
    req1 = AgentRequest(
        run_id="pubchem-demo-1",
        message="LiCoO2 SMILES",
    )
    r1 = agent.run(req1)
    print(r1.reply)

    print("\n\n💊 Demo 2: PubChem 真查 water")
    req2 = AgentRequest(
        run_id="pubchem-demo-2",
        message="water",
    )
    r2 = agent.run(req2)
    print(r2.reply)

    print("\n\n💊 Demo 3: mock 模式")
    agent3 = MatPubChemAgent(use_real_pubchem=False)
    req3 = AgentRequest(
        run_id="pubchem-demo-3",
        message="test",
    )
    r3 = agent3.run(req3)
    print(r3.reply)


__all__ = [
    "MatPubChemAgent",
    "PubChemAgentConfig",
    "create_default_agent",
]