"""nomad_client / client.py — NOMAD API 真接入(v1.3-Academic M2)

支持:
- 真查 NOMAD REST API(https://nomad-lab.eu/prod/v1/api/v1/,免费 signup 选)
- 解析 entries + 提取标准化字段(per metainfo_mapping.py)
- 失败 fallback 到 mock DB
- LRU cache(per 学院版"在线优先 + cache"原则)
- metainfo_unmapped 字段供 mat_critic L4 规则调试用

NOMAD API 文档:
- Base: https://nomad-lab.eu/prod/v1/api/v1/
- Search: GET /entries?search=<query>&per_page=N
- Auth: 可选 Bearer token(per NOMAD 文档,免费注册)
- 响应:JSON,字段:entry_id / upload_id / results.material.* / results.properties.*

Stage 1 行为(v1.3 M2):真查 NOMAD + metainfo 映射 + mock fallback
Stage 2 行为(后续):M3 mat_critic L4 跨源规则会用 metainfo_unmapped

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .metainfo_mapping import extract_nomad_record, MAPPED_METAINFO_PATHS

logger = logging.getLogger(__name__)

NOMAD_API_URL_DEFAULT = "https://nomad-lab.eu/prod/v1/api/v1"
NOMAD_TIMEOUT_SEC = 12  # NOMAD 响应慢,12 秒

# 环境变量覆盖(NOMAD API URL 未来可能变,学院方可控)
ENV_NOMAD_API_BASE = "MATWAU_NOMAD_API_BASE"
ENV_NOMAD_TOKEN = "MATWAU_NOMAD_TOKEN"  # 可选 Bearer token


# ============================================================================
# NomadReference dataclass
# ============================================================================


@dataclass
class NomadReference:
    """1 条 NOMAD archive entry 引用

    Attributes:
        entry_id: NOMAD entry ID(如 "abc123XYZ")
        upload_id: NOMAD upload ID
        archive_id: NOMAD archive ID
        formula: 化学式(Hill system 优先)
        elements: 元素列表
        spacegroup_symbol: 国际空间群符号
        spacegroup_number: 空间群编号 1-230(0 = 未知)
        a, b, c: 晶格常数(Å)
        alpha, beta, gamma: 晶格角(°)
        volume: 体积(Å³)
        band_gap_eV: 带隙(eV)
        formation_energy_per_atom_eV: 形成能(eV/atom)
        energy_above_hull_eV: 凸包距离(eV/atom)
        bulk_modulus_GPa: 体模量(GPa)
        xc_functional: 交换关联泛函(如 "PBE")
        program_name: 计算程序(如 "VASP")
        url: NOMAD entry URL
        available_properties: 可用性质列表
        metainfo_unmapped: 未映射的 metainfo 字段(供 M3 用)
    """

    entry_id: str
    upload_id: str = ""
    archive_id: str = ""
    formula: str = ""
    elements: List[str] = field(default_factory=list)
    spacegroup_symbol: str = ""
    spacegroup_number: int = 0
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    alpha: float = 0.0
    beta: float = 0.0
    gamma: float = 0.0
    volume: float = 0.0
    band_gap_eV: float = 0.0
    formation_energy_per_atom_eV: float = 0.0
    energy_above_hull_eV: float = 0.0
    bulk_modulus_GPa: float = 0.0
    xc_functional: str = ""
    program_name: str = ""
    url: str = ""
    available_properties: List[str] = field(default_factory=list)
    metainfo_unmapped: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "upload_id": self.upload_id,
            "archive_id": self.archive_id,
            "formula": self.formula,
            "elements": self.elements,
            "spacegroup_symbol": self.spacegroup_symbol,
            "spacegroup_number": self.spacegroup_number,
            "a": self.a, "b": self.b, "c": self.c,
            "alpha": self.alpha, "beta": self.beta, "gamma": self.gamma,
            "volume": self.volume,
            "band_gap_eV": self.band_gap_eV,
            "formation_energy_per_atom_eV": self.formation_energy_per_atom_eV,
            "energy_above_hull_eV": self.energy_above_hull_eV,
            "bulk_modulus_GPa": self.bulk_modulus_GPa,
            "xc_functional": self.xc_functional,
            "program_name": self.program_name,
            "url": self.url,
            "available_properties": self.available_properties,
            "metainfo_unmapped": self.metainfo_unmapped,
        }


# ============================================================================
# LRU cache(per 学院版 "在线优先 + cache")
# ============================================================================


class _LRUCache(OrderedDict):
    """LRU cache(简单 OrderedDict 实现,FIFO eviction on maxsize)"""

    def __init__(self, maxsize: int = 64) -> None:
        super().__init__()
        self.maxsize = maxsize

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        if key not in self:
            return default
        self.move_to_end(key)
        return super().get(key, default)

    def put(self, key: str, value: Any) -> None:
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            self.popitem(last=False)


# ============================================================================
# is_nomad_available()
# ============================================================================


def _nomad_api_base() -> str:
    """读取环境变量覆盖的 API base URL"""
    return os.environ.get(ENV_NOMAD_API_BASE, NOMAD_API_URL_DEFAULT).rstrip("/")


def _nomad_auth_headers() -> Dict[str, str]:
    """读取可选 Bearer token"""
    token = os.environ.get(ENV_NOMAD_TOKEN)
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def is_nomad_available() -> bool:
    """探测 NOMAD API 是否可达(轻量 ping)"""
    try:
        url = f"{_nomad_api_base()}/entries?per_page=1"
        headers = {"User-Agent": "MatWAU/1.3-Academic (research; mailto:contact@matwau.local)"}
        headers.update(_nomad_auth_headers())
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


# ============================================================================
# _build_nomad_query()
# ============================================================================


def _build_nomad_query(user_intent: str) -> str:
    """从 user_intent 构造 NOMAD search query

    NOMAD 接受 free-text 搜索(per docs);但建议用 chemical_formula_reduced:NiCo

    Args:
        user_intent: 用户原始意图

    Returns:
        NOMAD 兼容的 query 字符串
    """
    text = (user_intent or "").strip()
    if not text:
        return ""

    # 1. 优先匹配常见合金 alias(per OQMD/COD 同样处理)
    alloy_aliases = [
        "Inconel 718", "Inconel 625", "Inconel",
        "Ti-6Al-4V", "Nitinol", "NMC811", "NMC", "LFP", "LCO",
        "LLZO", "LGPS",
    ]
    for alias in alloy_aliases:
        if re.search(re.escape(alias), text, re.IGNORECASE):
            return alias

    # 2. 提取化学式
    m = re.search(r"((?:[A-Z][a-z]?\d*){2,})", text)
    if m:
        cand = m.group(1)
        if any(c.isdigit() for c in cand):
            return cand

    # 3. 单元素
    m2 = re.search(r"\b([A-Z][a-z]?)\b", text)
    if m2:
        elem = m2.group(1)
        if elem not in ("I", "A"):
            return elem

    return text[:30]


# ============================================================================
# _parse_nomad_response()
# ============================================================================


def _parse_nomad_response(data: Any) -> List[NomadReference]:
    """解析 NOMAD API JSON 响应 → List[NomadReference]

    NOMAD 响应结构:
    {
        "data": [
            {
                "entry_id": "...",
                "upload_id": "...",
                "archive_id": "...",
                "results": {"material": {...}, "properties": {...}, "method": {...}, "sample": {...}},
                "available_properties": [...]
            },
            ...
        ],
        "pagination": {...}
    }
    """
    refs: List[NomadReference] = []
    if not isinstance(data, dict):
        return refs
    items = data.get("data") or data.get("entries") or []
    if not isinstance(items, list):
        return refs

    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            extracted = extract_nomad_record(item)
            # entry_id 是必需
            if not extracted.get("entry_id"):
                # 兜底:从 archive_id 推
                if extracted.get("archive_id"):
                    extracted["entry_id"] = extracted["archive_id"]
                else:
                    continue
            entry_id = extracted["entry_id"]
            url = f"{_nomad_api_base()}/entry/id/{entry_id}"
            ref = NomadReference(
                entry_id=entry_id,
                upload_id=extracted.get("upload_id", ""),
                archive_id=extracted.get("archive_id", ""),
                formula=extracted.get("formula", ""),
                elements=extracted.get("elements", []),
                spacegroup_symbol=extracted.get("spacegroup_symbol", ""),
                spacegroup_number=int(extracted.get("spacegroup_number", 0) or 0),
                a=extracted.get("a", 0.0),
                b=extracted.get("b", 0.0),
                c=extracted.get("c", 0.0),
                alpha=extracted.get("alpha", 0.0),
                beta=extracted.get("beta", 0.0),
                gamma=extracted.get("gamma", 0.0),
                volume=extracted.get("volume", 0.0),
                band_gap_eV=extracted.get("band_gap_eV", 0.0),
                formation_energy_per_atom_eV=extracted.get("formation_energy_per_atom_eV", 0.0),
                energy_above_hull_eV=extracted.get("energy_above_hull_eV", 0.0),
                bulk_modulus_GPa=extracted.get("bulk_modulus_GPa", 0.0),
                xc_functional=extracted.get("xc_functional", ""),
                program_name=extracted.get("program_name", ""),
                url=url,
                available_properties=extracted.get("available_properties", []),
                metainfo_unmapped=extracted.get("unmapped_metainfo_paths", []),
            )
            refs.append(ref)
        except Exception as e:
            logger.debug("NOMAD record parse failed: %s", e)
            continue
    return refs


# ============================================================================
# _mock_nomad_response()
# ============================================================================


def _mock_nomad_response(query: str, *, n: int = 5) -> List[NomadReference]:
    """NOMAD mock 数据(Stage 1 fallback)

    给已知化学式伪造 1 组综合 entry(metainfo 含 3 段 properties)
    """
    known = {
        "Si": [
            NomadReference(
                entry_id="nomad-mock-Si-001",
                formula="Si", elements=["Si"],
                spacegroup_symbol="Fd-3m", spacegroup_number=227,
                a=5.43, b=5.43, c=5.43,
                alpha=90.0, beta=90.0, gamma=90.0,
                volume=40.9, band_gap_eV=1.11,
                xc_functional="PBE", program_name="VASP",
                available_properties=["electronic", "thermodynamic"],
                url="https://nomad-lab.eu/prod/v1/api/v1/entry/id/nomad-mock-Si-001",
            ),
        ],
        "LiCoO2": [
            NomadReference(
                entry_id="nomad-mock-LCO-001",
                formula="LiCoO2", elements=["Li", "Co", "O"],
                spacegroup_symbol="R-3m", spacegroup_number=166,
                a=2.815, b=2.815, c=14.05,
                alpha=90.0, beta=90.0, gamma=120.0,
                volume=96.5, band_gap_eV=2.3,
                formation_energy_per_atom_eV=-1.78,
                xc_functional="PBE+U", program_name="VASP",
                available_properties=["electronic", "thermodynamic"],
                url="https://nomad-lab.eu/prod/v1/api/v1/entry/id/nomad-mock-LCO-001",
            ),
        ],
        "LLZO": [
            NomadReference(
                entry_id="nomad-mock-LLZO-001",
                formula="Li7La3Zr2O12",
                elements=["Li", "La", "Zr", "O"],
                spacegroup_symbol="Ia-3d", spacegroup_number=230,
                a=12.97, b=12.97, c=12.97,
                alpha=90.0, beta=90.0, gamma=90.0,
                volume=2180.5, band_gap_eV=5.5,
                bulk_modulus_GPa=110.0,
                xc_functional="PBE", program_name="VASP",
                available_properties=["electronic", "mechanical"],
                url="https://nomad-lab.eu/prod/v1/api/v1/entry/id/nomad-mock-LLZO-001",
            ),
        ],
        "TiO2": [
            NomadReference(
                entry_id="nomad-mock-TiO2-001",
                formula="TiO2", elements=["Ti", "O"],
                spacegroup_symbol="P4_2/mnm", spacegroup_number=136,
                a=4.594, b=4.594, c=2.959,
                alpha=90.0, beta=90.0, gamma=90.0,
                volume=62.45, band_gap_eV=3.0,
                xc_functional="PBE", program_name="VASP",
                available_properties=["electronic"],
                url="https://nomad-lab.eu/prod/v1/api/v1/entry/id/nomad-mock-TiO2-001",
            ),
        ],
    }

    q = (query or "").strip()
    if q in known:
        return known[q][:n]

    return [
        NomadReference(
            entry_id=f"nomad-mock-{abs(hash(q)) % 100000:05d}",
            formula=q or "Unknown",
            spacegroup_symbol="Pm-3m", spacegroup_number=221,
            a=3.0, b=3.0, c=3.0,
            alpha=90.0, beta=90.0, gamma=90.0,
            volume=27.0, band_gap_eV=1.0,
            xc_functional="PBE", program_name="VASP",
            available_properties=["electronic"],
            url=f"https://nomad-lab.eu/prod/v1/api/v1/entry/id/nomad-mock-{abs(hash(q)) % 100000:05d}",
        )
    ][:n]


# ============================================================================
# NomadClient dataclass
# ============================================================================


@dataclass
class NomadClient:
    """NOMAD API 客户端(v1.3-Academic M2,沿用 OQMD/COD client 心法)

    Attributes:
        timeout: 单次 query timeout(秒,NOMAD 慢 → 默认 12)
        user_agent: HTTP user-agent
        enable_fallback: 失败时降级到 mock(默认 True)
        max_results: 默认返回几条
        use_cache: 是否启用 LRU cache(per 学院版"在线优先 + cache")
        cache_maxsize: LRU cache 最大条目
    """

    timeout: int = NOMAD_TIMEOUT_SEC
    user_agent: str = "MatWAU/1.3-Academic (research; mailto:contact@matwau.local)"
    enable_fallback: bool = True
    max_results: int = 5
    use_cache: bool = True
    cache_maxsize: int = 64

    def __post_init__(self) -> None:
        # LRU cache(per 学院版)
        if self.use_cache and not hasattr(self, "_cache"):
            object.__setattr__(self, "_cache", _LRUCache(maxsize=self.cache_maxsize))

    def search(
        self,
        user_intent: str,
        *,
        max_results: Optional[int] = None,
    ) -> Tuple[List[NomadReference], bool]:
        """查 NOMAD,返回 (refs, is_real)

        Args:
            user_intent: 用户原始意图(化学式 / 中文)
            max_results: override self.max_results

        Returns:
            (refs, is_real)
            - is_real=True:真 NOMAD API 返回
            - is_real=False:fallback 到 mock
        """
        n = max_results or self.max_results
        formula = _build_nomad_query(user_intent)
        if not formula:
            return [], False

        # 1. LRU cache 查
        cache_key = f"search::{formula}::{n}"
        if self.use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached, True

        # 2. 真查 NOMAD
        url = (
            f"{_nomad_api_base()}/entries"
            f"?per_page={n}"
            f"&search={urllib.parse.quote(formula)}"
        )
        try:
            headers = {"User-Agent": self.user_agent}
            headers.update(_nomad_auth_headers())
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
            if not data or not isinstance(data, dict):
                raise ValueError("NOMAD 返回空 dict")
            refs = _parse_nomad_response(data)
            if not refs:
                # 兜底:data 不含 entries 时也算空
                if self.enable_fallback:
                    refs = _mock_nomad_response(formula, n=n)
                    return (refs, False)
                return ([], False)
            # 截断到 n
            refs = refs[:n]
            # 3. 写 cache
            if self.use_cache:
                self._cache.put(cache_key, refs)
            return (refs, True)
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
            ValueError,
            Exception,
        ) as e:
            logger.debug(f"NOMAD API fail: {type(e).__name__} {e}")
            if self.enable_fallback:
                refs = _mock_nomad_response(formula, n=n)
                return (refs, False)
            raise

    def to_canonical(self, ref: NomadReference) -> Any:
        """NomadReference → CanonicalKey(供 M3 mat_critic L4 跨源规则用)"""
        from agents.data_canonical import CanonicalKey
        # NOMAD 有 spacegroup_number 直接给(sym.* 字段已转)
        return CanonicalKey.from_formula_spacegroup(
            ref.formula, ref.spacegroup_symbol,
            pearson="",  # NOMAD 没直接给 pearson
        )


# ============================================================================
# 模块级便捷函数
# ============================================================================


def search_nomad(
    user_intent: str,
    *,
    max_results: int = 5,
) -> Tuple[List[NomadReference], bool]:
    """便捷函数:查 NOMAD"""
    client = NomadClient(max_results=max_results)
    return client.search(user_intent, max_results=max_results)


__all__ = [
    "NOMAD_API_URL_DEFAULT",
    "NOMAD_TIMEOUT_SEC",
    "ENV_NOMAD_API_BASE",
    "ENV_NOMAD_TOKEN",
    "NomadReference",
    "NomadClient",
    "is_nomad_available",
    "search_nomad",
    "MAPPED_METAINFO_PATHS",
]