"""materials_project_client / client.py — Materials Project API 真接入(W17-C)

支持:
- 真查 Materials Project REST API(公开查询无需 token)
- 失败 fallback(网络失败 / timeout / 4xx)
- 4 域关键词构造(per W15 + W17 metal_alloy)

Materials Project API:
- Base: https://api.materialsproject.org/
- 公开 endpoints(无需 token): /materials/summary
- 文档: https://docs.materialsproject.org/

Stage 1(W17-C 起点): mock 假数据
Stage 2(W17-C 真接入): 真查 MP API,失败 fallback 到 mock

per MatWAU-开发计划 §8 W17-C
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

MATERIALS_PROJECT_BASE_URL = "https://api.materialsproject.org"
MATERIALS_PROJECT_TIMEOUT_SEC = 8  # 单次 query timeout


@dataclass
class MaterialsProjectReference:
    """1 条 Materials Project 材料的引用(类比 ArxivReference)

    Attributes:
        mp_id: Materials Project ID(如 "mp-1234" — 化学式前缀 mp-)
        formula: 化学式(如 "LiCoO2")
        spacegroup: 空间群(国际符号)
        band_gap: 带隙(eV)
        formation_energy_per_atom: 形成能(eV/atom)
        energy_above_hull: 凸包距离(eV/atom,稳定性指标)
        density: 密度(g/cm³)
        volume: 体积(Å³)
        is_stable: 是否热力学稳定(凸包距离 = 0)
        crystal_system: 晶系(cubic/hexagonal/...)
        url: 详情页 URL
    """

    mp_id: str
    formula: str
    spacegroup: str = ""
    band_gap: float = 0.0
    formation_energy_per_atom: float = 0.0
    energy_above_hull: float = 0.0
    density: float = 0.0
    volume: float = 0.0
    is_stable: bool = False
    crystal_system: str = ""
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mp_id": self.mp_id,
            "formula": self.formula,
            "spacegroup": self.spacegroup,
            "band_gap": self.band_gap,
            "formation_energy_per_atom": self.formation_energy_per_atom,
            "energy_above_hull": self.energy_above_hull,
            "density": self.density,
            "volume": self.volume,
            "is_stable": self.is_stable,
            "crystal_system": self.crystal_system,
            "url": self.url,
        }


def is_materials_project_available() -> bool:
    """探测 Materials Project API 是否可用(同 arxiv 探测模式)"""
    try:
        url = f"{MATERIALS_PROJECT_BASE_URL}/materials/summary?formula=Si&_limit=1"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "MatWAU/1.0 (research; mailto:contact@matwau.local)"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _build_mp_query(formula_or_keywords: str, *, domain: str | None = None) -> str:
    """构造 MP query(类似 arxiv _build_query)

    MP summary API 接收 formula= 或 elements= 参数
    我们从 user_intent 提取化学式,fallback 到关键字搜索
    """
    import re
    text = formula_or_keywords or ""

    # 0. 优先匹配常见 cathode / 固态电解质 alias(NMC811 / LFP / LLZO 等)
    cathode_aliases = [
        "NMC811", "NMC622", "NMC111", "NMC", "LFP", "LCO", "LMO", "NCA",
        "LLZO", "LGPS", "LATP", "LAGP", "NASICON", "PZT",
        "Inconel 718", "Inconel 625", "Inconel",
        "Ti-6Al-4V", "Nitinol",
    ]
    for alias in cathode_aliases:
        if re.search(re.escape(alias), text, re.IGNORECASE):
            return alias

    # 1. 尝试匹配通用化学式(大写字母 + 可选小写 + 可选数字,2-15 字符)
    m = re.search(r"([A-Z][a-z]?\d*[A-Z][a-z]?\d+)", text)
    if m:
        # 排除像 "SiA" 这种伪化学式(只有 2 元素但第 1 个无数字且第 2 个无数字太随便)
        cand = m.group(1)
        # 至少要有 1 个数字 OR 至少 3 个大写字母(真实化学式)
        if any(c.isdigit() for c in cand) or sum(c.isupper() for c in cand) >= 3:
            return cand

    return text or ""


def _parse_mp_response(data: list[dict[str, Any]]) -> list[MaterialsProjectReference]:
    """解析 MP API JSON 响应 → List[MaterialsProjectReference]"""
    refs = []
    for item in data:
        try:
            ref = MaterialsProjectReference(
                mp_id=item.get("material_id", ""),
                formula=item.get("formula_pretty", item.get("formula", "")),
                spacegroup=item.get("symmetry", {}).get("symbol", ""),
                band_gap=item.get("band_gap", 0.0) or 0.0,
                formation_energy_per_atom=item.get("formation_energy_per_atom", 0.0) or 0.0,
                energy_above_hull=item.get("energy_above_hull", 0.0) or 0.0,
                density=item.get("density", 0.0) or 0.0,
                volume=item.get("volume", 0.0) or 0.0,
                is_stable=(item.get("energy_above_hull", 1.0) or 1.0) < 0.001,
                crystal_system=item.get("symmetry", {}).get("crystal_system", ""),
                url=f"https://materialsproject.org/materials/{item.get('material_id', '')}",
            )
            refs.append(ref)
        except Exception:
            continue
    return refs


def _mock_mp_response(query: str, *, n: int = 5) -> list[MaterialsProjectReference]:
    """W17-C mock 数据(Stage 1 fallback 路径)

    给已知化学式伪造 1 组稳定结构数据,跟 arxiv mock 模式一致
    """
    known = {
        "LiCoO2": [
            MaterialsProjectReference(
                mp_id="mp-18767", formula="LiCoO2",
                spacegroup="R-3m", band_gap=1.7,
                formation_energy_per_atom=-1.85,
                energy_above_hull=0.0,
                density=5.01, volume=98.7,
                is_stable=True, crystal_system="trigonal",
                url="https://materialsproject.org/materials/mp-18767",
            ),
            MaterialsProjectReference(
                mp_id="mp-22531", formula="LiCoO2",
                spacegroup="P63/mmc", band_gap=2.1,
                formation_energy_per_atom=-1.78,
                energy_above_hull=0.04,
                density=4.95, volume=99.5,
                is_stable=False, crystal_system="hexagonal",
                url="https://materialsproject.org/materials/mp-22531",
            ),
        ],
        "NMC": [
            MaterialsProjectReference(
                mp_id="mp-773731", formula="Li10Ni4Mn4Co4O24",
                spacegroup="R-3m", band_gap=0.5,
                formation_energy_per_atom=-1.45,
                energy_above_hull=0.0,
                density=4.78, volume=520.5,
                is_stable=True, crystal_system="trigonal",
                url="https://materialsproject.org/materials/mp-773731",
            ),
        ],
        "LLZO": [
            MaterialsProjectReference(
                mp_id="mp-943008", formula="Li7La3Zr2O12",
                spacegroup="Ia-3d", band_gap=5.1,
                formation_energy_per_atom=-2.95,
                energy_above_hull=0.0,
                density=5.13, volume=1294.6,
                is_stable=True, crystal_system="cubic",
                url="https://materialsproject.org/materials/mp-943008",
            ),
        ],
        "Inconel 718": [
            MaterialsProjectReference(
                mp_id="mp-NI-FE-CR-MO", formula="Ni19Fe18Cr5Mo",
                spacegroup="Fm-3m", band_gap=0.0,
                formation_energy_per_atom=-0.45,
                energy_above_hull=0.0,
                density=8.19, volume=53.4,
                is_stable=True, crystal_system="cubic",
                url="https://materialsproject.org/materials/mp-NI-FE-CR-MO",
            ),
        ],
    }

    q = (query or "").strip()
    if q in known:
        return known[q][:n]

    # 兜底:任意查询返回 1 个 generic entry
    return [
        MaterialsProjectReference(
            mp_id=f"mp-mock-{abs(hash(q)) % 100000:05d}",
            formula=q or "Unknown",
            spacegroup="P1",
            band_gap=0.0,
            formation_energy_per_atom=0.0,
            energy_above_hull=0.05,
            density=3.0,
            volume=100.0,
            is_stable=True,
            crystal_system="triclinic",
            url=f"https://materialsproject.org/materials/mp-mock-{abs(hash(q)) % 100000:05d}",
        )
    ][:n]


@dataclass
class MaterialsProjectClient:
    """Materials Project API 客户端(同 arxiv_client ArxivClient 心法)

    Attributes:
        timeout: 单次 query timeout(秒)
        user_agent: HTTP user-agent
        enable_fallback: 失败时降级到 mock(默认 True,从不崩)
        max_results: 默认返回几条
    """

    timeout: int = 8
    user_agent: str = "MatWAU/1.0 (research; mailto:contact@matwau.local)"
    enable_fallback: bool = True
    max_results: int = 5

    def search(
        self,
        user_intent: str,
        *,
        max_results: int | None = None,
        domain: str | None = None,
    ) -> tuple[list[MaterialsProjectReference], bool]:
        """查 Materials Project API

        Args:
            user_intent: 用户原始意图(中文 / 化学式)
            max_results: override self.max_results
            domain: 材料域(per W15 + W17 metal_alloy)

        Returns:
            (refs, is_real)
            - is_real=True:真查 MP API 返回
            - is_real=False:fallback 到 mock
        """
        n = max_results or self.max_results
        formula = _build_mp_query(user_intent, domain=domain)

        url = (
            f"{MATERIALS_PROJECT_BASE_URL}/materials/summary"
            f"?formula={urllib.parse.quote(formula)}"
            f"&_limit={n}&_fields=material_id,formula_pretty,symmetry,"
            f"band_gap,formation_energy_per_atom,energy_above_hull,"
            f"density,volume"
        )
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": self.user_agent},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                # MP API 返回 list 或 dict 包 list(根据 endpoint)
                if isinstance(data, dict):
                    items = data.get("data", [])
                else:
                    items = data
                if not items:
                    raise ValueError("empty list from MP")
                refs = _parse_mp_response(items)
                return (refs[:n], True)
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
            ValueError,
            Exception,
        ) as e:
            logger.debug(f"MaterialsProject API fail: {type(e).__name__} {e}")
            if self.enable_fallback:
                return (_mock_mp_response(formula, n=n), False)
            raise


def search_materials_project(
    user_intent: str,
    *,
    max_results: int = 5,
    domain: str | None = None,
) -> tuple[list[MaterialsProjectReference], bool]:
    """便捷函数(同 arxiv_client.search_arxiv)

    Returns:
        (refs, is_real)
    """
    client = MaterialsProjectClient(max_results=max_results)
    return client.search(user_intent, max_results=max_results, domain=domain)
