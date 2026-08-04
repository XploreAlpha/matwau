"""data_canonical — 跨数据源 canonical 抽象(v1.3-Academic M1 基础)

职责:
- 提供 CanonicalKey dataclass(归一化化学式 + Pearson 符号 + 空间群)
- 提供 from_record(record) 类方法:把任意 XxxRecord 转 CanonicalKey
- 提供 matches(other) 方法:判断两个 CanonicalKey 是否同物相

用途:
- mat_critic L4 跨数据源规则(per MatWAU-v1.3-Academic-dev-plan M3)
- cross_source_resolver 聚合器(M3)

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M1 第 9 项
"""
from .canonical_key import (  # noqa: F401
    CanonicalKey,
    normalize_formula,
    parse_pearson_symbol,
    spacegroup_to_number,
)

__all__ = [
    "CanonicalKey",
    "normalize_formula",
    "parse_pearson_symbol",
    "spacegroup_to_number",
]