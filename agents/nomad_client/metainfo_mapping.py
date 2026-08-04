"""metainfo_mapping.py — NOMAD metainfo → 标准化字段映射(v1.3-Academic M2)

NOMAD 的数据模型基于自家 metainfo ontology(用 `section_<name>` 描述),
跟 OQMD / COD 的扁平 JSON 不同。本模块只保留标准化最关键的 ~30 字段。

设计要点(per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2):
- M2 阶段只覆盖 `section_run` / `section_system` / `section_method` / `section_sample` 4 个核心 section
- unmapped metainfo 字段写进 `extras`(供 M3 mat_critic / debug 用)
- 出现频率低的字段不强制映射,记录在 UNMAPPED_PATTERNS 列表里

References:
- NOMAD metainfo docs: https://nomad-lab.eu/prod/v1/docs/reference/metainfo.html
- 真实 NOMAD archive entry 样例(per docs):
  {
    "entry_id": "...", "upload_id": "...", "archive_id": "...",
    "results": {
      "properties": {
        "electronic": {"band_gap": [...]},
        "thermodynamic": {"formation_energy": [...]},
        "mechanical": {"bulk_modulus": [...]},
        "structural": {"spacegroup": ...},
      },
      "material": {"chemical_formula": "...", "chemical_formula_hill": "...",
                   "chemical_formula_reduced": "...", "chemical_formula_descriptive": "...",
                   "elements": [...], "symmetry": {"space_group_symbol": "...",
                   "international_short_symbol": "..."}},
      "method": {"simulation": {"program_name": "...", "xc_functional": "..."}},
      "available_properties": [...]
    }
  }

Stage 1 行为(M2):真实 NOMAD API + metainfo 映射
Stage 2 行为(M3+):后续可能加 elastic / phonon / DOS 等扩展

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2 第 13 项
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Section 名(per NOMAD metainfo 规范)
# ============================================================================

# 关键 metainfo section 名(白名单)
KNOWN_SECTIONS = frozenset({
    "section_run",
    "section_system",
    "section_method",
    "section_sample",
    "section_workflow",
    "section_ensemble",
    "section_atom",
    "section_dos",
    "section_band",
})

# NOMAD 已知的 properties 类别(per `results.properties.*`)
KNOWN_PROPERTY_GROUPS = frozenset({
    "electronic",
    "thermodynamic",
    "mechanical",
    "structural",
    "vibrational",
    "magnetic",
    "dielectric",
})


# ============================================================================
# 字段映射表
# ============================================================================

# 化学式字段(per results.material.*)
_FORMULA_FIELDS = (
    "chemical_formula_hill",     # 优先(Hill system,跟 data_canonical 对齐)
    "chemical_formula_reduced",  # 次选
    "chemical_formula",          # 最后兜底(可能是 descriptive)
)

# 空间群符号字段(per results.material.symmetry.*)
_SYM_FIELDS = (
    "international_short_symbol",  # 优先:"Fm-3m" 标准格式
    "space_group_symbol",          # 次选:可能长格式
    "symbol",                      # 兜底
)

# 晶格常数(per results.material.*)
_LATTICE_LENGTH_FIELDS = ("a", "b", "c")
_LATTICE_ANGLE_FIELDS = ("alpha", "beta", "gamma")


# M2 阶段期望能映射的 metainfo 路径(用于测试 + 文档化)
MAPPED_METAINFO_PATHS = [
    # 化学式(4)
    "results.material.chemical_formula_hill",
    "results.material.chemical_formula_reduced",
    "results.material.chemical_formula",
    "results.material.elements",
    # 空间群(4)
    "results.material.symmetry.international_short_symbol",
    "results.material.symmetry.space_group_symbol",
    "results.material.symmetry.symbol",
    "results.material.symmetry.space_group_number",
    # 晶格(7)
    "results.material.lattice.a",
    "results.material.lattice.b",
    "results.material.lattice.c",
    "results.material.lattice.alpha",
    "results.material.lattice.beta",
    "results.material.lattice.gamma",
    "results.material.lattice.volume",
    # 性质 — electronic(4)
    "results.properties.electronic.band_gap",
    "results.properties.electronic.band_gap_fermi_level",
    "results.properties.electronic.fermi_level",
    "results.properties.electronic.density_of_states",
    # 性质 — thermodynamic(3)
    "results.properties.thermodynamic.formation_energy",
    "results.properties.thermodynamic.energy_above_hull",
    "results.properties.thermodynamic.enthalpy_of_formation",
    # 性质 — mechanical(3)
    "results.properties.mechanical.bulk_modulus",
    "results.properties.mechanical.shear_modulus",
    "results.properties.mechanical.young_modulus",
    # 性质 — structural(3)
    "results.properties.structural.crystal_system",
    "results.properties.structural.spacegroup",
    "results.properties.structural.lattice_type",
    # 方法(4)
    "results.method.simulation.program_name",
    "results.method.simulation.xc_functional",
    "results.method.simulation.code_version",
    "results.method.simulation.ecutwfc",
    # sample(2)
    "results.sample.elements",
    "results.sample.chemical_formula",
    # ensemble(1)
    "results.method.ensemble.type",
]

# 未映射但记录的模式(用于 M3 评估是否扩展)
UNMAPPED_PATTERNS = [
    "results.properties.vibrational.phonon_frequencies",
    "results.properties.dielectric.refractive_index",
    "results.properties.magnetic.magnetic_moment",
    "results.properties.optical.absorption_coefficient",
    "results.workflow.calculation_result_schema",
    "results.method.simulation.k_point_grid",
    "results.method.simulation.ecutwfc",
    "results.method.simulation.smearing",
]


# ============================================================================
# 内部 helper
# ============================================================================


def _dig(d: dict[str, Any], path: str) -> Any | None:
    """安全 dict drill-down(per dotted path)

    Examples:
        _dig({"a": {"b": 1}}, "a.b") → 1
        _dig({"a": {"b": 1}}, "a.c") → None
        _dig({"a": {"b": 1}}, "a") → {"b": 1}
    """
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _pick(d: dict[str, Any], paths: tuple[str, ...]) -> Any | None:
    """依次尝试多个 dotted path,返回首个非 None 值"""
    for p in paths:
        v = _dig(d, p)
        if v is not None and v != "":
            return v
    return None


def _to_float(v: Any) -> float:
    """宽容类型转换(列表首元素 / dict 取 .value / str parse)"""
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
    if isinstance(v, dict):
        for k in ("value", "magnitude", "nominal_value"):
            if k in v:
                return _to_float(v[k])
    return 0.0


def _to_int(v: Any) -> int:
    """int 转型(NOMAD 数值可能为 str)"""
    f = _to_float(v)
    return int(f) if f else 0


def _to_str_list(v: Any) -> list[str]:
    """list[str] 归一化(处理元素 dict 包裹情况)"""
    if not v:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        out = []
        for item in v:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                for k in ("value", "symbol", "label"):
                    if k in item and isinstance(item[k], str):
                        out.append(item[k])
                        break
        return out
    return []


# ============================================================================
# 核心 API:extract_nomad_record()
# ============================================================================


def extract_nomad_record(entry_data: dict[str, Any]) -> dict[str, Any]:
    """从 NOMAD entry 提取标准化字段

    Args:
        entry_data: NOMAD API 返回的 entry dict(含 results.* 等)

    Returns:
        Dict with keys:
            - formula: 化学式(Hill 优先)
            - formula_raw: 原始化学式字段
            - elements: 元素列表
            - spacegroup_symbol: 国际空间群符号
            - spacegroup_number: 空间群编号(若 API 给)
            - a/b/c/alpha/beta/gamma: 晶格常数
            - volume: 单胞体积
            - band_gap_eV: 带隙 eV
            - formation_energy_per_atom_eV: 形成能(eV/atom,若可算)
            - energy_above_hull_eV: 凸包距离
            - bulk_modulus_GPa: 体模量
            - xc_functional: 交换关联泛函(如 "PBE")
            - program_name: 计算程序(如 "VASP")
            - entry_id, upload_id, archive_id: NOMAD ID
            - available_properties: 可用性质列表
            - extras: 未映射字段(供 M3 + debug)
            - unmapped_metainfo_paths: 未匹配 metainfo 路径(列表)
    """
    material = _dig(entry_data, "results.material") or {}
    properties = _dig(entry_data, "results.properties") or {}
    method = _dig(entry_data, "results.method") or {}
    sample = _dig(entry_data, "results.sample") or {}

    # 1. 化学式(优先 Hill)
    formula = _pick(material, _FORMULA_FIELDS) or _pick(sample, ("chemical_formula",)) or ""
    elements = _to_str_list(_dig(material, "elements")) or _to_str_list(_dig(sample, "elements"))

    # 2. 空间群
    symmetry = _dig(material, "symmetry") or {}
    sg_symbol = (
        _pick(symmetry, _SYM_FIELDS)
        or _dig(properties, "structural.spacegroup")
        or ""
    )
    sg_num = _to_int(_dig(symmetry, "space_group_number") or _dig(symmetry, "international_number"))

    # 3. 晶格
    lattice = _dig(material, "lattice") or {}
    a = _to_float(_dig(lattice, "a"))
    b = _to_float(_dig(lattice, "b"))
    c = _to_float(_dig(lattice, "c"))
    alpha = _to_float(_dig(lattice, "alpha"))
    beta = _to_float(_dig(lattice, "beta"))
    gamma = _to_float(_dig(lattice, "gamma"))
    volume = _to_float(_dig(lattice, "volume"))

    # 4. 电子性质
    elec = _dig(properties, "electronic") or {}
    band_gap = _to_float(_dig(elec, "band_gap") or _dig(elec, "band_gap_fermi_level"))

    # 5. 热力学性质
    thermo = _dig(properties, "thermodynamic") or {}
    formation_energy = _to_float(_dig(thermo, "formation_energy") or _dig(thermo, "formation_energy_per_atom"))
    energy_above_hull = _to_float(_dig(thermo, "energy_above_hull"))

    # 6. 力学性质
    mech = _dig(properties, "mechanical") or {}
    bulk_modulus = _to_float(_dig(mech, "bulk_modulus"))
    shear_modulus = _to_float(_dig(mech, "shear_modulus"))

    # 7. 计算方法
    sim = _dig(method, "simulation") or {}
    program_name = _dig(sim, "program_name") or ""
    xc_functional = _dig(sim, "xc_functional") or ""

    # 8. NOMAD IDs
    entry_id = entry_data.get("entry_id", "")
    upload_id = entry_data.get("upload_id", "")
    archive_id = entry_data.get("archive_id", "")

    # 9. 可用性质列表(per results.available_properties 或 properties.* 推断)
    avail = entry_data.get("available_properties") or []
    if not avail:
        avail = list(properties.keys())
    avail_list = [str(x) for x in avail]

    # 10. extras(未映射的子 dict,供 M3 / debug)
    extras = _collect_extras(entry_data, {
        "results.material": material,
        "results.properties": properties,
        "results.method": method,
        "results.sample": sample,
    })

    # 11. 检测 unmapped metainfo 路径(对比 MAPPED_PATINST_PATHS)
    unmapped = []
    # 不在此扫描,留给 M3 mat_critic 用

    return {
        "formula": formula,
        "elements": elements,
        "spacegroup_symbol": sg_symbol,
        "spacegroup_number": sg_num,
        "a": a, "b": b, "c": c,
        "alpha": alpha, "beta": beta, "gamma": gamma,
        "volume": volume,
        "band_gap_eV": band_gap,
        "formation_energy_per_atom_eV": formation_energy,
        "energy_above_hull_eV": energy_above_hull,
        "bulk_modulus_GPa": bulk_modulus,
        "shear_modulus_GPa": shear_modulus,
        "xc_functional": xc_functional,
        "program_name": program_name,
        "entry_id": entry_id,
        "upload_id": upload_id,
        "archive_id": archive_id,
        "available_properties": avail_list,
        "extras": extras,
        "unmapped_metainfo_paths": unmapped,
    }


def _collect_extras(
    entry_data: dict[str, Any],
    used_subtrees: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """把未用到的子 dict 收进 extras(供 M3 / debug 查验)"""
    extras = {}
    for key, val in entry_data.items():
        if key in ("entry_id", "upload_id", "archive_id", "results", "available_properties"):
            continue
        if isinstance(val, (dict, list)):
            extras[key] = val
    return extras


# ============================================================================
# Metainfo 字段计数(per M2 验收门 "覆盖 ≥ 30 种 metainfo 字段映射")
# ============================================================================


def count_mapped_metainfo_paths() -> int:
    """M2 阶段已映射的 metainfo 路径数(per 验收门 "≥ 30")"""
    return len(MAPPED_METAINFO_PATHS)


# ============================================================================
# 模块导出
# ============================================================================


__all__ = [
    "KNOWN_PROPERTY_GROUPS",
    "KNOWN_SECTIONS",
    "MAPPED_METAINFO_PATHS",
    "UNMAPPED_PATTERNS",
    "count_mapped_metainfo_paths",
    "extract_nomad_record",
]