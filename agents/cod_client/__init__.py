"""cod_client — COD(Crystallography Open Database)客户端(v1.3-Academic M1)

核心职责:
- 真查 COD REST API(https://www.crystallography.net/cod/,**无需 API key**)
- 拉 CIF 文本 + pymatgen(可选)解析空间群 + 晶格参数
- 失败 fallback 到 mock DB
- CanonicalKey 映射(供 mat_critic L4 跨源规则用)

数据规模:~50 万 实验晶体结构(实验测得,非 DFT)
引用:Gražulis et al., *Nucleic Acids Res.* 2012, **D13**
许可:CC0(完全开放)

设计要点(per requirements §四.2.2 风险):
- **不依赖 HTML 解析** — 直接拉 CIF + pymatgen 解析(网站改版也不破)
- 检索走 COD 的 /result.php 搜索页(返回 HTML 列出 cod-id,再用 cif-get.py 拉 CIF)
- 拉 CIF 时是已知稳定 endpoint(M1 阶段验证),不受网页改版影响

用法:
    from agents.cod_client import CodClient

    client = CodClient()
    refs, is_real = client.search("Ni3Cr2Fe2Mo", limit=10)
    for r in refs:
        print(r.cod_id, r.formula, r.spacegroup_h_m)

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M1 第 3-4 项
"""

from __future__ import annotations

import logging

from .client import (  # noqa: F401
    COD_BASE_URL,
    COD_CIF_URL_TEMPLATE,
    COD_TIMEOUT_SEC,
    CodClient,
    CodReference,
    is_cod_available,
    search_cod,
    fetch_cif,
)

__all__ = [
    "COD_BASE_URL",
    "COD_CIF_URL_TEMPLATE",
    "COD_TIMEOUT_SEC",
    "CodClient",
    "CodReference",
    "is_cod_available",
    "search_cod",
    "fetch_cif",
]