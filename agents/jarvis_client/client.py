"""jarvis_client / client.py — JARVIS(Joint Automated Reverse Engineering & Scoring
Materials Database)客户端(v1.3-Academic M2)

支持:
- 真查 JARVIS REST API(https://jarvis.nist.gov/,可选 Bearer token)
- 解析 JSON → JarvReference dataclass
- 失败 fallback 到 mock DB
- jarvis-tools Python 包作为 **optional**(学院方精简镜像可能装不下,降级到纯 REST)
- LRU cache(per 学院版"在线优先 + cache"原则)

JARVIS API 文档:
- 主站:https://jarvis.nist.gov/
- API 入口:https://jarvis.nist.gov/api/
- 可选认证:免费 signup,获取 Bearer token
- jarvis-tools Python 包:jarvis.db.figshare(本地缓存) + jarvis.core.atoms(结构数据)
- 数据规模:~75K 材料(3D + 2D 综合)

Stage 1 行为(v1.3 M2):REST 真查 + jarvis-tools 可选 + mock fallback
Stage 2 行为(M3+):M3 mat_critic L4 跨源规则会用 JarvReference + 形成能比对

设计要点(per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2 风险):
- 不强制 `pip install jarvis-tools`(依赖太重,学院方精简镜像装不下)
- 仅 `try: from jarvis.db.figshare import get_jdb_data` — 失败 → 降级到 REST-only
- jarvis-tools 不可用时仍能跑(学院方 W4 离线环境可演示)

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

logger = logging.getLogger(__name__)

JARVIS_API_URL_DEFAULT = "https://jarvis.nist.gov/api"
JARVIS_TIMEOUT_SEC = 10

# 环境变量覆盖(per 学院方 IT 配置)
ENV_JARVIS_API_BASE = "MATWAU_JARVIS_API_BASE"
ENV_JARVIS_TOKEN = "MATWAU_JARVIS_TOKEN"  # 可选 Bearer token

# Optional jarvis-tools 包探测(per dev-plan 风险 P2)
_JARVIS_TOOLS_AVAILABLE = None  # cache 探测结果


def _check_jarvis_tools() -> bool:
    """探测 jarvis-tools 是否可用(只探测一次)"""
    global _JARVIS_TOOLS_AVAILABLE
    if _JARVIS_TOOLS_AVAILABLE is None:
        try:
            from jarvis.db.figshare import get_jdb_data  # type: ignore[import-not-found]  # noqa: F401
            _JARVIS_TOOLS_AVAILABLE = True
        except Exception:
            _JARVIS_TOOLS_AVAILABLE = False
    return bool(_JARVIS_TOOLS_AVAILABLE)


# ============================================================================
# JarvReference dataclass
# ============================================================================


@dataclass
class JarvReference:
    """1 条 JARVIS 材料引用

    Attributes:
        jid: JARVIS ID(如 "JVASP-12345")
        formula: 化学式
        elements: 元素列表
        spacegroup_symbol: 国际空间群符号
        spacegroup_number: 空间群编号 1-230(0 = 未知)
        a, b, c: 晶格常数(Å)
        alpha, beta, gamma: 晶格角(°)
        volume: 体积(Å³)
        formation_energy_per_atom_eV: 形成能(eV/atom)
        band_gap_eV: 带隙(eV)
        bulk_modulus_GPa: 体模量(GPa,VASP PBE 默认)
        magmom: 磁矩(μB)
        dimensionality: 2D / 3D(per jarvis-tools 区分)
        is_2d: 是否 2D 材料(per jarvis 二维库)
        xc_functional: 交换关联泛函(默认 PBE)
        url: JARVIS 详情页 URL
    """

    jid: str
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
    formation_energy_per_atom_eV: float = 0.0
    band_gap_eV: float = 0.0
    bulk_modulus_GPa: float = 0.0
    magmom: float = 0.0
    dimensionality: str = "3D"
    is_2d: bool = False
    xc_functional: str = "PBE"
    url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "jid": self.jid,
            "formula": self.formula,
            "elements": self.elements,
            "spacegroup_symbol": self.spacegroup_symbol,
            "spacegroup_number": self.spacegroup_number,
            "a": self.a, "b": self.b, "c": self.c,
            "alpha": self.alpha, "beta": self.beta, "gamma": self.gamma,
            "volume": self.volume,
            "formation_energy_per_atom_eV": self.formation_energy_per_atom_eV,
            "band_gap_eV": self.band_gap_eV,
            "bulk_modulus_GPa": self.bulk_modulus_GPa,
            "magmom": self.magmom,
            "dimensionality": self.dimensionality,
            "is_2d": self.is_2d,
            "xc_functional": self.xc_functional,
            "url": self.url,
        }


# ============================================================================
# LRU cache
# ============================================================================


class _LRUCache(OrderedDict):
    """LRU cache(简单 OrderedDict 实现)"""

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
# is_jarvis_available()
# ============================================================================


def _jarvis_api_base() -> str:
    """读取环境变量覆盖的 API base URL"""
    return os.environ.get(ENV_JARVIS_API_BASE, JARVIS_API_URL_DEFAULT).rstrip("/")


def _jarvis_auth_headers() -> Dict[str, str]:
    """读取可选 Bearer token"""
    token = os.environ.get(ENV_JARVIS_TOKEN)
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def is_jarvis_available() -> bool:
    """探测 JARVIS API 是否可达(轻量 ping)"""
    try:
        url = f"{_jarvis_api_base()}/jarvisdb/elements"
        headers = {"User-Agent": "MatWAU/1.3-Academic (research; mailto:contact@matwau.local)"}
        headers.update(_jarvis_auth_headers())
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def is_jarvis_tools_available() -> bool:
    """探测 jarvis-tools Python 包是否安装"""
    return _check_jarvis_tools()


# ============================================================================
# _build_jarvis_query()
# ============================================================================


def _build_jarvis_query(user_intent: str) -> str:
    """从 user_intent 构造 JARVIS search query

    JARVIS REST API 接受 formula 或 elements list

    Args:
        user_intent: 用户原始意图

    Returns:
        化学式 / 元素列表;若未提取到返回 ""
    """
    text = (user_intent or "").strip()
    if not text:
        return ""

    # 1. 优先合金 alias
    alloy_aliases = [
        "Inconel 718", "Inconel 625", "Inconel",
        "Ti-6Al-4V", "Nitinol", "NMC811", "NMC", "LFP", "LCO",
        "LLZO", "LGPS",
    ]
    for alias in alloy_aliases:
        if re.search(re.escape(alias), text, re.IGNORECASE):
            return alias

    # 2. 提取化学式(2+ 个元素)
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
# _parse_jarvis_response()
# ============================================================================


def _to_float(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0
    if isinstance(v, list) and v:
        return _to_float(v[0])
    return 0.0


def _to_int(v: Any) -> int:
    f = _to_float(v)
    return int(f) if f else 0


def _parse_jarvis_response(data: Any) -> List[JarvReference]:
    """解析 JARVIS API JSON 响应 → List[JarvReference]

    JARVIS 响应结构(per NIST API docs):
    {
        "results": [
            {
                "jid": "JVASP-12345",
                "formula": "Si2",
                "elements": ["Si"],
                "spg_symbol": "Fd-3m",
                "spg_number": 227,
                "a": 5.43, "b": 5.43, "c": 5.43,
                "alpha": 90, "beta": 90, "gamma": 90,
                "volume": 40.9,
                "Ef": -0.01,           # 形成能 eV/atom
                "gap": 1.11,           # 带隙 eV
                "bulk_modulus": 88.0,
                "magmom": 0.0,
                "dim": "3D",            # dimensionality
                "is_2d": false,
                "func": "PBE"
            },
            ...
        ]
    }
    """
    refs: List[JarvReference] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("results") or data.get("data") or data.get("entries") or []
        if not isinstance(items, list):
            return refs
    else:
        return refs

    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            jid = item.get("jid") or item.get("id") or item.get("JVASP")
            if not jid:
                continue
            elements_raw = item.get("elements") or item.get("element_list") or []
            elements: List[str] = []
            if isinstance(elements_raw, str):
                elements = re.findall(r"[A-Z][a-z]?", elements_raw)
            elif isinstance(elements_raw, list):
                for e in elements_raw:
                    if isinstance(e, str):
                        elements.append(e)
                    elif isinstance(e, dict):
                        for k in ("element", "symbol", "name"):
                            if k in e and isinstance(e[k], str):
                                elements.append(e[k])
                                break
            ref = JarvReference(
                jid=str(jid),
                formula=item.get("formula", "") or item.get("composition", ""),
                elements=elements,
                spacegroup_symbol=item.get("spg_symbol", "") or item.get("spg", "") or item.get("spacegroup", ""),
                spacegroup_number=_to_int(item.get("spg_number") or item.get("sg_number")),
                a=_to_float(item.get("a")),
                b=_to_float(item.get("b")),
                c=_to_float(item.get("c")),
                alpha=_to_float(item.get("alpha")),
                beta=_to_float(item.get("beta")),
                gamma=_to_float(item.get("gamma")),
                volume=_to_float(item.get("volume")),
                formation_energy_per_atom_eV=_to_float(item.get("Ef") or item.get("Ef_atom") or item.get("formation_energy")),
                band_gap_eV=_to_float(item.get("gap") or item.get("band_gap")),
                bulk_modulus_GPa=_to_float(item.get("bulk_modulus") or item.get("kv")),
                magmom=_to_float(item.get("magmom") or item.get("total_magmom")),
                dimensionality=str(item.get("dim") or item.get("dimensionality") or "3D"),
                is_2d=bool(item.get("is_2d") or item.get("dim") == "2D"),
                xc_functional=item.get("func") or item.get("xc") or "PBE",
                url=f"https://jarvis.nist.gov/details/{jid}",
            )
            refs.append(ref)
        except Exception as e:
            logger.debug("JARVIS record parse failed: %s", e)
            continue
    return refs


# ============================================================================
# _mock_jarvis_response()
# ============================================================================


def _mock_jarvis_response(query: str, *, n: int = 5) -> List[JarvReference]:
    """JARVIS mock 数据(Stage 1 fallback)

    给已知化学式伪造 1 组综合 entry(3D + 2D 区分)
    """
    known = {
        "Si": [
            JarvReference(
                jid="JVASP-1001", formula="Si", elements=["Si"],
                spacegroup_symbol="Fd-3m", spacegroup_number=227,
                a=5.43, b=5.43, c=5.43,
                alpha=90.0, beta=90.0, gamma=90.0,
                volume=40.9,
                formation_energy_per_atom_eV=0.0, band_gap_eV=1.11,
                bulk_modulus_GPa=88.0,
                dimensionality="3D", is_2d=False,
                url="https://jarvis.nist.gov/details/JVASP-1001",
            ),
        ],
        "MoS2": [
            JarvReference(
                jid="JVASP-2001", formula="MoS2", elements=["Mo", "S"],
                spacegroup_symbol="P63/mmc", spacegroup_number=194,
                a=3.16, b=3.16, c=12.30,
                alpha=90.0, beta=90.0, gamma=120.0,
                volume=106.3,
                formation_energy_per_atom_eV=-1.04, band_gap_eV=1.68,
                bulk_modulus_GPa=120.0,
                dimensionality="2D", is_2d=True,
                url="https://jarvis.nist.gov/details/JVASP-2001",
            ),
        ],
        "GaN": [
            JarvReference(
                jid="JVASP-3001", formula="GaN", elements=["Ga", "N"],
                spacegroup_symbol="P63mc", spacegroup_number=186,
                a=3.19, b=3.19, c=5.19,
                alpha=90.0, beta=90.0, gamma=120.0,
                volume=45.7,
                formation_energy_per_atom_eV=-0.97, band_gap_eV=3.4,
                bulk_modulus_GPa=210.0,
                dimensionality="3D", is_2d=False,
                url="https://jarvis.nist.gov/details/JVASP-3001",
            ),
        ],
        "LiCoO2": [
            JarvReference(
                jid="JVASP-4001", formula="LiCoO2", elements=["Li", "Co", "O"],
                spacegroup_symbol="R-3m", spacegroup_number=166,
                a=2.815, b=2.815, c=14.05,
                alpha=90.0, beta=90.0, gamma=120.0,
                volume=96.5,
                formation_energy_per_atom_eV=-1.78, band_gap_eV=2.3,
                bulk_modulus_GPa=180.0,
                dimensionality="3D", is_2d=False,
                url="https://jarvis.nist.gov/details/JVASP-4001",
            ),
        ],
    }

    q = (query or "").strip()
    if q in known:
        return known[q][:n]

    return [
        JarvReference(
            jid=f"JVASP-mock-{abs(hash(q)) % 100000:05d}",
            formula=q or "Unknown",
            spacegroup_symbol="Pm-3m", spacegroup_number=221,
            a=3.0, b=3.0, c=3.0,
            alpha=90.0, beta=90.0, gamma=90.0,
            volume=27.0,
            formation_energy_per_atom_eV=-1.0, band_gap_eV=1.0,
            bulk_modulus_GPa=100.0,
            dimensionality="3D", is_2d=False,
            url=f"https://jarvis.nist.gov/details/JVASP-mock-{abs(hash(q)) % 100000:05d}",
        )
    ][:n]


# ============================================================================
# JarvClient dataclass
# ============================================================================


@dataclass
class JarvClient:
    """JARVIS API 客户端(v1.3-Academic M2,沿用 OQMD/COD/NOMAD client 心法)

    Attributes:
        timeout: 单次 query timeout(秒)
        user_agent: HTTP user-agent
        enable_fallback: 失败时降级到 mock(默认 True)
        max_results: 默认返回几条
        use_cache: 是否启用 LRU cache
        cache_maxsize: LRU cache 最大条目
        allow_jarvis_tools: 是否允许用 jarvis-tools 增强(若环境装了该包)
    """

    timeout: int = JARVIS_TIMEOUT_SEC
    user_agent: str = "MatWAU/1.3-Academic (research; mailto:contact@matwau.local)"
    enable_fallback: bool = True
    max_results: int = 5
    use_cache: bool = True
    cache_maxsize: int = 64
    allow_jarvis_tools: bool = True

    def __post_init__(self) -> None:
        if self.use_cache and not hasattr(self, "_cache"):
            object.__setattr__(self, "_cache", _LRUCache(maxsize=self.cache_maxsize))

    def search(
        self,
        user_intent: str,
        *,
        max_results: Optional[int] = None,
    ) -> Tuple[List[JarvReference], bool]:
        """查 JARVIS,返回 (refs, is_real)

        Args:
            user_intent: 用户原始意图(化学式 / 中文)
            max_results: override self.max_results

        Returns:
            (refs, is_real)
            - is_real=True:真 JARVIS API 返回
            - is_real=False:fallback 到 mock
        """
        n = max_results or self.max_results
        formula = _build_jarvis_query(user_intent)
        if not formula:
            return [], False

        # 1. LRU cache 查
        cache_key = f"search::{formula}::{n}"
        if self.use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached, True

        # 2. 真查 JARVIS REST
        url = (
            f"{_jarvis_api_base()}/jarvisdb/3dmat"
            f"?formula={urllib.parse.quote(formula)}"
            f"&limit={n}"
        )
        try:
            headers = {"User-Agent": self.user_agent}
            headers.update(_jarvis_auth_headers())
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
            if not data:
                raise ValueError("JARVIS 返回空")
            refs = _parse_jarvis_response(data)
            if not refs and self.enable_fallback:
                refs = _mock_jarvis_response(formula, n=n)
                return (refs, False)
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
            logger.debug(f"JARVIS API fail: {type(e).__name__} {e}")
            if self.enable_fallback:
                refs = _mock_jarvis_response(formula, n=n)
                return (refs, False)
            raise

    def to_canonical(self, ref: JarvReference) -> Any:
        """JarvReference → CanonicalKey(供 M3 mat_critic L4 跨源规则用)"""
        from agents.data_canonical import CanonicalKey
        return CanonicalKey.from_formula_spacegroup(
            ref.formula, ref.spacegroup_symbol,
        )


# ============================================================================
# 模块级便捷函数
# ============================================================================


def search_jarvis(
    user_intent: str,
    *,
    max_results: int = 5,
) -> Tuple[List[JarvReference], bool]:
    """便捷函数:查 JARVIS"""
    client = JarvClient(max_results=max_results)
    return client.search(user_intent, max_results=max_results)


__all__ = [
    "JARVIS_API_URL_DEFAULT",
    "JARVIS_TIMEOUT_SEC",
    "ENV_JARVIS_API_BASE",
    "ENV_JARVIS_TOKEN",
    "JarvReference",
    "JarvClient",
    "is_jarvis_available",
    "is_jarvis_tools_available",
    "search_jarvis",
]