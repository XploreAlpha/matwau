"""mat_pubchem_agent — PubChem 化合物数据查询 wrapper agent(v1.3.3-Academic M1)

负责把 PubChemClient 的查询结果包装成 MatWAUAgentBase 的标准 AgentResponse,
供 mat_orchestrator / mat_lit_agent / /literature 端点使用。

能力:
1. 解析 user_intent → 化学式 / 名字(per PubChemClient._build_pubchem_query)
2. 调 PubChemClient.search 拉 CID + SMILES + IUPACName(LRU cache 自动复用)
3. 转 AgentResponse(records + is_real_query flag + confidence + cost)
4. 默认 confidence 启发式(n_results: 0→0.3, 1→0.6, ≥2→0.8)
5. 默认走真 PubChem API(v1.3.3),失败 fallback(向后兼容)
6. 与 mat_arxiv_agent / mat_oqmd_agent / mat_cod_agent / mat_nomad_agent / mat_jarvis_agent 模式对齐

per MatWAU-v1.3.3-Academic-dev-plan-20260806.md §三 M1
"""

from .mat_pubchem_agent import (
    MatPubChemAgent,
    PubChemAgentConfig,
    create_default_agent,
)

__all__ = [
    "MatPubChemAgent",
    "PubChemAgentConfig",
    "create_default_agent",
]