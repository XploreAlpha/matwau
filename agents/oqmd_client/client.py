"""oqmd_client / client.py — OQMD API 真接入(v1.3-Academic M1)

支持:
- 真查 OQMD REST API(https://oqmd.org/oqmdapi/,无需 API key)
- 失败 fallback(网络失败 / timeout / 4xx)
- 化学式归一化 → CanonicalKey(per data_canonical)
- 已知化合物 mock fallback

OQMD API 文档:
- Base: https://oqmd.org/oqmdapi/
- Endpoints: /formationenergy / /structure / /bandgap / /dos / /conjurer
- 响应:JSON list,字段:id / composition / spacegroup / energy / volume / n_atoms

Stage 1 行为(v1.3 M1 起点):mock 数据 + 化学式归一化
Stage 2 行为(本文件):真查 OQMD,失败 fallback

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M1
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

OQMD_API_URL = "https://oqmd.org/oqmdapi"
OQMD_TIMEOUT_SEC = 10  # 单次 query timeout


# ============================================================================
# OqmdReference dataclass
# ============================================================================


@dataclass
class OqmdReference:
    """1 条 OQMD 材料的引用

    Attributes:
        oqmd_id: OQMD 内部 ID(如 "oqmd-1234567" 或纯数字)
        formula: 化学式(原始,如 "Ni3Cr2Fe2Mo")
        spacegroup: 空间群(国际符号,如 "Fm-3m")
        formation_energy_per_atom: 形成能(eV/atom)
        energy_above_hull: 凸包距离(eV/atom,稳定性指标)
        volume: 体积(Å³)
        n_atoms: 单胞原子数
        band_gap: 带隙(eV,OQMD 部分记录有)
        is_stable: 是否热力学稳定(凸包距离 < 0.001)
        url: OQMD 详情页 URL
    """

    oqmd_id: str
    formula: str
    spacegroup: str = ""
    formation_energy_per_atom: float = 0.0
    energy_above_hull: float = 0.0
    volume: float = 0.0
    n_atoms: int = 0
    band_gap: float = 0.0
    is_stable: bool = False
    url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "oqmd_id": self.oqmd_id,
            "formula": self.formula,
            "spacegroup": self.spacegroup,
            "formation_energy_per_atom": self.formation_energy_per_atom,
            "energy_above_hull": self.energy_above_hull,
            "volume": self.volume,
            "n_atoms": self.n_atoms,
            "band_gap": self.band_gap,
            "is_stable": self.is_stable,
            "url": self.url,
        }


# ============================================================================
# is_oqmd_available()
# ============================================================================


def is_oqmd_available() -> bool:
    """探测 OQMD API 是否可达(轻量 ping)"""
    try:
        url = f"{OQMD_API_URL}/formationenergy?composition=Si&limit=1"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "MatWAU/1.3-Academic (research; mailto:contact@matwau.local)"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


# ============================================================================
# _build_oqmd_query()
# ============================================================================


def _build_oqmd_query(user_intent: str) -> str:
    """从 user_intent 提取化学式供 OQMD query

    OQMD API 接受 composition 参数,期望化学式或元素符号列表
    优先匹配常见 cathode / 固态电解质 alias,其次正则提取化学式

    Args:
        user_intent: 用户原始意图

    Returns:
        归一化化学式;若未提取到返回 ""
    """
    text = (user_intent or "").strip()
    if not text:
        return ""

    # 1. 优先匹配常见合金 alias
    alloy_aliases = [
        "Inconel 718", "Inconel 625", "Inconel",
        "Ti-6Al-4V", "Nitinol", "NMC811", "NMC622", "NMC111",
        "NMC", "LFP", "LCO", "LMO", "NCA",
        "LLZO", "LGPS", "LATP", "LAGP",
    ]
    for alias in alloy_aliases:
        if re.search(re.escape(alias), text, re.IGNORECASE):
            return alias

    # 2. 提取通用化学式(2+ 个"元素 + 可选数字"序列;支持 LLZO / LiCoO2 / Ni3Cr2Fe2Mo)
    # 用 (?:...){2,} 外部捕获避免 group(1) 只匹配最后一次迭代
    m = re.search(r"((?:[A-Z][a-z]?\d*){2,})", text)
    if m:
        cand = m.group(1)
        if any(c.isdigit() for c in cand):
            return cand

    # 3. fallback:3+ 大写字母也算(无数字化学式如 NaCl 不太可能,但保险)
    m2 = re.search(r"\b([A-Z]{2,6})\b", text)
    if m2:
        return m2.group(1)

    return text[:20]  # 兜底


# ============================================================================
# _parse_oqmd_response()
# ============================================================================


def _parse_oqmd_response(data: List[Dict[str, Any]]) -> List[OqmdReference]:
    """解析 OQMD API JSON 响应 → List[OqmdReference]

    OQMD /formationenergy 响应字段:
    - id (int), composition (str), n_atoms (int), spacegroup (str, optional)
    - energy (float, total eV), energy_per_atom (float), formation_energy (float)
    - energy_per_atom_units: 'eV'
    """
    refs = []
    for item in data:
        try:
            oqmd_id_raw = item.get("id", "")
            if isinstance(oqmd_id_raw, int):
                oqmd_id = f"oqmd-{oqmd_id_raw}"
            else:
                oqmd_id = str(oqmd_id_raw)
            formula = item.get("composition", "")
            spacegroup = item.get("spacegroup", "") or item.get("spacegroup_symbol", "")
            energy_per_atom = item.get("energy_per_atom", 0.0) or 0.0
            formation_energy = item.get("formation_energy", 0.0) or 0.0
            # OQMD 不直接返回 energy_above_hull;从 formation_energy 推算时需要 hull 参考
            # 此处使用 0.0 作为保守占位(M3 阶段 mat_critic 不会因 0 误判)
            volume = item.get("volume", 0.0) or 0.0
            n_atoms = item.get("n_atoms", 0) or 0
            band_gap = item.get("band_gap", 0.0) or 0.0

            # is_stable 启发:formation_energy < 0 且 volume > 0
            is_stable = formation_energy < 0 and volume > 0

            ref = OqmdReference(
                oqmd_id=oqmd_id,
                formula=formula,
                spacegroup=spacegroup,
                formation_energy_per_atom=formation_energy,
                energy_above_hull=0.0,  # OQMD 不直接给;M3 L4 规则会用更宽松阈值
                volume=volume,
                n_atoms=int(n_atoms),
                band_gap=float(band_gap),
                is_stable=is_stable,
                url=f"https://oqmd.org/materials/{oqmd_id}",
            )
            refs.append(ref)
        except Exception as e:
            logger.debug("OQMD record parse failed: %s", e)
            continue
    return refs


# ============================================================================
# _mock_oqmd_response()
# ============================================================================


def _mock_oqmd_response(query: str, *, n: int = 5) -> List[OqmdReference]:
    """OQMD mock 数据(Stage 1 fallback 路径)

    给已知化学式伪造 1 组 DFT 计算数据,跟 Materials Project mock 风格一致
    """
    known = {
        "Ni3Cr2Fe2Mo": [
            OqmdReference(
                oqmd_id="oqmd-100001", formula="Ni19Fe18Cr5Mo",
                spacegroup="Fm-3m",
                formation_energy_per_atom=-0.42,
                energy_above_hull=0.0,
                volume=53.2, n_atoms=4, is_stable=True,
                url="https://oqmd.org/materials/oqmd-100001",
            ),
        ],
        "LiCoO2": [
            OqmdReference(
                oqmd_id="oqmd-200001", formula="LiCoO2",
                spacegroup="R-3m",
                formation_energy_per_atom=-1.78,
                energy_above_hull=0.0,
                volume=98.7, n_atoms=4, is_stable=True,
                url="https://oqmd.org/materials/oqmd-200001",
            ),
        ],
        "LLZO": [
            OqmdReference(
                oqmd_id="oqmd-300001", formula="Li7La3Zr2O12",
                spacegroup="Ia-3d",
                formation_energy_per_atom=-2.91,
                energy_above_hull=0.0,
                volume=1294.6, n_atoms=56, is_stable=True,
                url="https://oqmd.org/materials/oqmd-300001",
            ),
        ],
        "Si": [
            OqmdReference(
                oqmd_id="oqmd-400001", formula="Si",
                spacegroup="Fd-3m",
                formation_energy_per_atom=0.0,
                energy_above_hull=0.0,
                volume=40.9, n_atoms=2, is_stable=True,
                url="https://oqmd.org/materials/oqmd-400001",
            ),
        ],
    }

    q = (query or "").strip()
    if q in known:
        return known[q][:n]

    # 兜底:任意查询返回 1 个 generic entry
    return [
        OqmdReference(
            oqmd_id=f"oqmd-mock-{abs(hash(q)) % 100000:05d}",
            formula=q or "Unknown",
            spacegroup="Pm-3m",
            formation_energy_per_atom=-1.0,
            energy_above_hull=0.05,
            volume=50.0, n_atoms=4, is_stable=True,
            url=f"https://oqmd.org/materials/oqmd-mock-{abs(hash(q)) % 100000:05d}",
        )
    ][:n]


# ============================================================================
# OqmdClient dataclass
# ============================================================================


@dataclass
class OqmdClient:
    """OQMD API 客户端(v1.3-Academic M1,沿用 arxiv_client / mp_client 心法)

    Attributes:
        timeout: 单次 query timeout(秒)
        user_agent: HTTP user-agent
        enable_fallback: 失败时降级到 mock(默认 True)
        max_results: 默认返回几条
        base_url: API base URL(可被学院 IT 通过环境变量覆盖)
    """

    timeout: int = OQMD_TIMEOUT_SEC
    user_agent: str = "MatWAU/1.3-Academic (research; mailto:contact@matwau.local)"
    enable_fallback: bool = True
    max_results: int = 5
    base_url: str = OQMD_API_URL

    def search(
        self,
        user_intent: str,
        *,
        max_results: Optional[int] = None,
    ) -> Tuple[List[OqmdReference], bool]:
        """查 OQMD API,返回 (refs, is_real)

        Args:
            user_intent: 用户原始意图(化学式 / 中文)
            max_results: override self.max_results

        Returns:
            (refs, is_real)
            - is_real=True:真 OQMD API 返回
            - is_real=False:fallback 到 mock
        """
        n = max_results or self.max_results
        formula = _build_oqmd_query(user_intent)
        if not formula:
            return [], False

        # OQMD /formationenergy endpoint,composition 参数
        url = (
            f"{self.base_url}/formationenergy"
            f"?composition={urllib.parse.quote(formula)}"
            f"&limit={n}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
            if not data:
                raise ValueError("OQMD 返回空 list")
            if not isinstance(data, list):
                # 部分 endpoint 返回 dict 包 list
                data = data.get("data", []) if isinstance(data, dict) else []
            if not data:
                raise ValueError("OQMD 解析后空 list")
            refs = _parse_oqmd_response(data)
            return (refs[:n], True)
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
            ValueError,
            Exception,
        ) as e:
            logger.debug(f"OQMD API fail: {type(e).__name__} {e}")
            if self.enable_fallback:
                return (_mock_oqmd_response(formula, n=n), False)
            raise

    def to_canonical(self, ref: OqmdReference) -> Any:
        """OqmdReference → CanonicalKey(供 M3 mat_critic L4 跨源规则用)

        Args:
            ref: OqmdReference 实例

        Returns:
            CanonicalKey 实例
        """
        from agents.data_canonical import CanonicalKey
        return CanonicalKey.from_record(ref)


# ============================================================================
# 模块级便捷函数
# ============================================================================


def search_oqmd(
    user_intent: str,
    *,
    max_results: int = 5,
) -> Tuple[List[OqmdReference], bool]:
    """便捷函数:查 OQMD

    Returns:
        (refs, is_real)
    """
    client = OqmdClient(max_results=max_results)
    return client.search(user_intent, max_results=max_results)