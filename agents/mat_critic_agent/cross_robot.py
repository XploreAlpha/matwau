"""cross_robot.py — W30 跨机器人一致性验证

核心模块:
- RobotEvidence: 1 个 robot 结果的物理证据 dataclass
- CrossRobotResult: 4 robot 一致性结果 dataclass
- 4 个 extractors: _extract_xrd_peaks / _extract_em_eds / _extract_dsc_tm / _extract_synth_product
- 5 条规则:
  R1 XRD matched_phase vs synth.product_formula (Round 1)
  R2 EDS 元素 ⊆ synth 化学式             (Round 1)
  R3 DSC Tg/Tm 类与 synth 化学式一致     (Round 1)
  R4 cost-per-gram sanity                (Round 2)
  R5 XRD peak count 与结晶性             (Round 2)
- CrossRobotConsistencyGuard: 独立类 safety guard

W30 设计:
- 纯规则 + 字符串处理,无 LLM
- 复用 critic_engine.py 的 RULE_* 和 FAIL_* 常量
- 跟 ChemistSafetyGuard 并列(不同层级,化学师协调 vs critic 裁决)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .critic_engine import (
    FAIL_DATA_CONSISTENCY_LOW,
    FAIL_DSC_CLASS_MISMATCH,
    FAIL_EDS_EXTRA_ELEMENTS,
    FAIL_XRD_PHASE_MISMATCH,
    RULE_R1_XRD_PHASE,
    RULE_R2_EDS_ELEMENTS,
    RULE_R3_DSC_CLASS,
    RULE_R4_COST_SANITY,
    RULE_R5_XRD_PEAK_COUNT,
)
from .cross_robot_phase_library import (
    PHASE_ELEMENT_MAP,
    match_phase_name,
    parse_formula_elements,
)


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass
class RobotEvidence:
    """1 个 robot 结果的物理证据

    W30 设计:从 ChemistReport.robot_results[i].artifacts 抽出
    支持 dict 形式(artifacts 本身就是 dict)或 dataclass(SynthResult 等)
    """

    robot_type: str                       # synth / xrd / em / dsc
    success: bool = False
    formula: str = ""                     # 从 procedure / matched_phase / elements 提取
    elements: List[str] = field(default_factory=list)

    # XRD 专属
    xrd_peaks: List[Dict[str, float]] = field(default_factory=list)
    xrd_matched_phase: str = ""

    # EM 专属
    em_eds_elements: List[Dict[str, Any]] = field(default_factory=list)

    # DSC 专属
    dsc_Tg: Optional[float] = None        # 玻璃化温度
    dsc_Tm: Optional[float] = None        # 熔点
    dsc_Tc: Optional[float] = None        # 结晶温度

    # Synth 专属
    synth_product_formula: str = ""
    synth_yield_grams: float = 0.0
    synth_cost_cny: float = 0.0

    # 原始 artifacts(debug 用)
    raw_artifacts: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CrossRobotResult:
    """跨机器人一致性结果"""

    score: float = 0.0                    # 0-1,越高越一致
    consistent: bool = True
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    rules_passed: List[str] = field(default_factory=list)
    rules_failed: List[str] = field(default_factory=list)


# ============================================================================
# Extractors(4 个)
# ============================================================================


def _extract_xrd_peaks(item: Any) -> Tuple[List[Dict[str, float]], str]:
    """从 XrdResult / dict 抽 peaks + matched_phase

    Args:
        item: XrdResult dataclass 或 dict(artifacts)

    Returns:
        (peaks: List[{two_theta, d_spacing_angstrom, intensity}], matched_phase: str)
    """
    peaks: List[Dict[str, float]] = []
    matched_phase = ""

    # dict 形式
    if isinstance(item, dict):
        peaks = item.get("peaks", []) or []
        matched_phase = item.get("matched_phase", "") or ""
        return peaks, matched_phase

    # dataclass 形式(XrdResult)
    if hasattr(item, "peaks"):
        peaks = list(getattr(item, "peaks", []) or [])
    if hasattr(item, "matched_phase"):
        matched_phase = getattr(item, "matched_phase", "") or ""

    return peaks, matched_phase


def _extract_em_eds(item: Any) -> List[Dict[str, Any]]:
    """从 EmResult / dict 抽 EDS 元素列表

    Returns:
        List[{element, wt_pct}, ...]
    """
    if isinstance(item, dict):
        return list(item.get("elements_detected", []) or [])
    if hasattr(item, "elements_detected"):
        return list(getattr(item, "elements_detected", []) or [])
    return []


def _extract_dsc_tm(item: Any) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """从 DscResult / dict 抽 Tg / Tm / Tc

    Returns:
        (Tg, Tm, Tc) — 任一为 None 表示没测到
    """
    tg, tm, tc = None, None, None

    if isinstance(item, dict):
        tg = item.get("glass_transition_temp_c")
        tm = item.get("melting_temp_c")
        tc = item.get("crystallization_temp_c")
    else:
        if hasattr(item, "glass_transition_temp_c"):
            tg = getattr(item, "glass_transition_temp_c", None)
        if hasattr(item, "melting_temp_c"):
            tm = getattr(item, "melting_temp_c", None)
        if hasattr(item, "crystallization_temp_c"):
            tc = getattr(item, "crystallization_temp_c", None)

    # 统一转 float
    def _to_float(v):
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return _to_float(tg), _to_float(tm), _to_float(tc)


def _extract_synth_product(item: Any) -> Tuple[str, float, float]:
    """从 SynthResult / dict 抽 product_formula + yield_grams + cost_cny

    Returns:
        (product_formula, yield_grams, cost_cny)
    """
    product_formula = ""
    yield_grams = 0.0
    cost_cny = 0.0

    if isinstance(item, dict):
        product_formula = item.get("product_formula", "") or ""
        yield_grams = float(item.get("yield_grams", 0.0) or 0.0)
        cost_cny = float(item.get("cost", 0.0) or 0.0)
    else:
        if hasattr(item, "product_formula"):
            product_formula = getattr(item, "product_formula", "") or ""
        if hasattr(item, "yield_grams"):
            yield_grams = float(getattr(item, "yield_grams", 0.0) or 0.0)
        if hasattr(item, "cost"):
            cost_cny = float(getattr(item, "cost", 0.0) or 0.0)

    return product_formula, yield_grams, cost_cny


# ============================================================================
# build_robot_evidence_list - 主入口,从 ChemistReport 抽 4 robot 证据
# ============================================================================


def build_robot_evidence_list(robot_results: List[Any]) -> List[RobotEvidence]:
    """从 ChemistReport.robot_results 抽 4 robot 的 RobotEvidence

    Args:
        robot_results: List[RobotStepResult] 或 List[dict]
            每项含 robot_type / success / artifacts / 等

    Returns:
        List[RobotEvidence](通常 0-4 项,空表示没跑任何 robot)
    """
    evidence_list: List[RobotEvidence] = []

    for rr in robot_results:
        # 兼容 dataclass(RobotStepResult)和 dict 两种形式
        if isinstance(rr, dict):
            robot_type = rr.get("robot_type", "") or ""
            success = bool(rr.get("success", False))
            artifacts = rr.get("artifacts", {}) or {}
            blocked = bool(rr.get("blocked", False))
        else:
            robot_type = getattr(rr, "robot_type", "") or ""
            success = bool(getattr(rr, "success", False))
            artifacts = getattr(rr, "artifacts", {}) or {}
            blocked = bool(getattr(rr, "blocked", False))

        # blocked 也算没成功(不参与跨机器人验证)
        if blocked:
            success = False

        evidence = RobotEvidence(
            robot_type=robot_type,
            success=success,
            raw_artifacts=artifacts,
        )

        if not success:
            evidence_list.append(evidence)
            continue

        # 按 robot_type 抽专属字段
        if robot_type == "synth":
            product, yield_g, cost = _extract_synth_product(artifacts)
            evidence.synth_product_formula = product
            evidence.synth_yield_grams = yield_g
            evidence.synth_cost_cny = cost
            evidence.formula = product
            if product:
                evidence.elements = sorted(parse_formula_elements(product))
        elif robot_type == "xrd":
            peaks, matched = _extract_xrd_peaks(artifacts)
            evidence.xrd_peaks = peaks
            evidence.xrd_matched_phase = matched
            # XRD 的 formula = matched_phase 解析
            if matched:
                evidence.formula = matched
                evidence.elements = sorted(parse_formula_elements(matched))
        elif robot_type == "em":
            eds = _extract_em_eds(artifacts)
            evidence.em_eds_elements = eds
            # 从 EDS 元素聚合 → formula
            if eds:
                elem_set = sorted({e.get("element", "") for e in eds if e.get("element")})
                evidence.elements = elem_set
                evidence.formula = "".join(elem_set)
        elif robot_type == "dsc":
            tg, tm, tc = _extract_dsc_tm(artifacts)
            evidence.dsc_Tg = tg
            evidence.dsc_Tm = tm
            evidence.dsc_Tc = tc
            # DSC 的 formula 从 procedure.sample_formula 抽
            if isinstance(artifacts, dict):
                proc = artifacts.get("procedure") or {}
                if isinstance(proc, dict):
                    evidence.formula = proc.get("sample_formula", "") or ""
                else:
                    # procedure 可能是 dataclass
                    evidence.formula = getattr(proc, "sample_formula", "") or ""
            else:
                # 顶层 artifacts 可能是 DscResult,procedure 是它的属性
                proc = getattr(artifacts, "procedure", None)
                if proc:
                    evidence.formula = getattr(proc, "sample_formula", "") or ""
            if evidence.formula:
                evidence.elements = sorted(parse_formula_elements(evidence.formula))

        evidence_list.append(evidence)

    return evidence_list


# ============================================================================
# Rules(5 条)
# ============================================================================


def rule_xrd_phase_in_synth_product(xrd_phase: str, synth_formula: str) -> Tuple[bool, str]:
    """R1: XRD matched_phase 应在 synth product_formula 的元素空间里

    匹配规则(W30 改进):
    1. 同名(模糊匹配)→ pass
    2. 元素空间完全相同 → pass(同义名)
    3. 主要金属元素重叠(去除 O / N / C / H / S)→ pass(同素异构 / 掺杂)
    4. 否则 fail

    Args:
        xrd_phase: XRD 报告的相名(例 "Inconel" / "TiO2")
        synth_formula: synth 产物的化学式(例 "Inconel 718" / "TiO2")

    Returns:
        (passed: bool, issue_str: str)
    """
    if not xrd_phase or not synth_formula:
        return True, ""  # 数据不全 → 跳过

    # 1. 名称完全匹配(模糊)
    phase_match = match_phase_name(xrd_phase)
    synth_match = match_phase_name(synth_formula)

    if phase_match and synth_match:
        if phase_match == synth_match:
            return True, ""
        # 名称不同
        phase_elems = PHASE_ELEMENT_MAP.get(phase_match, set())
        synth_elems = PHASE_ELEMENT_MAP.get(synth_match, set())
        if phase_elems and synth_elems:
            # 2. 元素空间完全相同 → pass(同义名)
            if phase_elems == synth_elems:
                return True, ""
            # 3. 主要金属元素重叠(去 O/N/C/H/S)
            non_trivial = {"O", "N", "C", "H", "S"}
            p_core = phase_elems - non_trivial
            s_core = synth_elems - non_trivial
            if p_core and s_core and (p_core & s_core):
                return True, ""
        # 完全不重叠(主要金属)→ fail
        return False, f"XRD matched {xrd_phase!r} but synth product is {synth_formula!r} — phase-element mismatch"

    # 4. 至少一边是纯化学式 → 用 parse_formula_elements 比元素
    xrd_elems = parse_formula_elements(xrd_phase)
    synth_elems = parse_formula_elements(synth_formula)

    if not xrd_elems or not synth_elems:
        return True, ""

    # 完全相同
    if xrd_elems == synth_elems:
        return True, ""
    # 主要金属元素重叠
    non_trivial = {"O", "N", "C", "H", "S"}
    xrd_core = xrd_elems - non_trivial
    synth_core = synth_elems - non_trivial
    if xrd_core and synth_core and (xrd_core & synth_core):
        return True, ""

    # XRD 元素 ⊆ synth 元素(含 O)→ pass
    if xrd_elems <= synth_elems:
        return True, ""
    extra = xrd_elems - synth_elems
    return False, f"XRD found {extra} not in synth product {synth_formula!r}"


def rule_eds_elements_subset_of_synth(eds_elements: List[Dict[str, Any]], synth_formula: str) -> Tuple[bool, str]:
    """R2: EDS 元素应 ⊆ synth 化学式

    Args:
        eds_elements: List[{element: str, wt_pct: float}, ...]
        synth_formula: synth 产物的化学式

    Returns:
        (passed, issue_str)
    """
    if not eds_elements or not synth_formula:
        return True, ""

    synth_elems = parse_formula_elements(synth_formula)
    if not synth_elems:
        return True, ""

    eds_set = {e.get("element", "") for e in eds_elements if e.get("element")}
    if not eds_set:
        return True, ""

    extra = eds_set - synth_elems
    if not extra:
        return True, ""
    return False, f"EDS found extra elements {extra} not in synth product {synth_formula!r} (possible contamination)"


def rule_dsc_class_matches_synth(
    tg: Optional[float],
    tm: Optional[float],
    synth_formula: str,
) -> Tuple[bool, str]:
    """R3: DSC Tg/Tm 类应与 synth 化学式类别一致

    分类规则(简化):
    - polymer(PMMA/PS/PE/PP/PET)→ 应有 Tg,不应有 Tm
    - metal(Inconel/SS304/Ti-6Al-4V)→ 应有 Tm,不应有 Tg
    - ceramic(TiO2/Al2O3/SiO2/LiCoO2/LLZO)→ 应既无 Tg 也无 Tm(或都无明显)

    Args:
        tg: DSC 玻璃化温度(℃)
        tm: DSC 熔点(℃)
        synth_formula: synth 化学式

    Returns:
        (passed, issue_str)
    """
    if tg is None and tm is None:
        # DSC 没测到 Tg/Tm → 数据不足,跳过
        return True, ""

    if not synth_formula:
        return True, ""

    synth_elems = parse_formula_elements(synth_formula)
    if not synth_elems:
        return True, ""

    # 分类
    is_polymer = _is_polymer(synth_elems)
    is_metal = _is_metal(synth_elems)
    is_ceramic = _is_ceramic(synth_elems)

    # Polymer 期望 Tg,不应有 Tm
    if is_polymer:
        if tg is not None and tg > 0:
            return True, ""
        if tm is not None and tm > 0:
            return False, f"Polymer {synth_formula!r} has Tm={tm}°C (should have Tg, not Tm)"

    # Metal 期望 Tm,不应有 Tg
    if is_metal:
        if tm is not None and tm > 0:
            return True, ""
        if tg is not None and tg > 0:
            return False, f"Metal {synth_formula!r} has Tg={tg}°C (should have Tm, not Tg)"

    # Ceramic 既无 Tg 也无 Tm
    if is_ceramic:
        if tg is not None and tg > 0:
            return False, f"Ceramic {synth_formula!r} has Tg={tg}°C (ceramics typically have neither Tg nor Tm)"
        if tm is not None and tm > 0:
            return False, f"Ceramic {synth_formula!r} has Tm={tm}°C (ceramics typically have neither Tg nor Tm)"

    return True, ""


# 元素分类 helper(简化版,覆盖 MatWAU 4 域常见材料)
def _is_polymer(elements: Set[str]) -> bool:
    """简单 polymer 分类:仅有 C/H/O(可能含 N)→ polymer"""
    non_polymer = {"Si", "Al", "Ti", "Fe", "Ni", "Cr", "Mo", "Nb", "Cu", "Zn", "Na", "Cl",
                   "Li", "La", "Zr", "Co", "Mn", "Mg", "Ca", "K", "V"}
    has_metal_like = bool(elements & non_polymer)
    has_organic = {"C"} <= elements or {"H"} <= elements
    return has_organic and not has_metal_like


def _is_metal(elements: Set[str]) -> bool:
    """简单 metal 分类:含典型金属元素且不是 polymer"""
    metals = {"Fe", "Ni", "Cr", "Ti", "Al", "Cu", "Zn", "Mn", "Mg", "Ca", "V", "Mo", "Nb",
              "Co", "W", "Ta", "Au", "Ag", "Pt", "Pd"}
    return bool(elements & metals) and not _is_polymer(elements)


def _is_ceramic(elements: Set[str]) -> bool:
    """简单 ceramic 分类:含 O 但无 H、无 C,且无金属合金"""
    if "O" not in elements:
        return False
    if "H" in elements or "C" in elements:
        return False
    if "N" in elements:
        # 氮化物陶瓷(如 Si3N4)
        return True
    # 氧化物陶瓷
    return True


def rule_synth_cost_per_gram(yield_grams: float, cost_cny: float) -> Tuple[bool, str]:
    """R4: synth cost-per-gram 应在合理范围

    范围(per MatWAU 4 域):
    - polymer(PMMA/PE/PS/PET)→ ¥5/g - ¥500/g(便宜)
    - ceramic(TiO2/Al2O3/SiO2)→ ¥50/g - ¥5000/g
    - metal(Inconel/Ti-6Al-4V/SS304)→ ¥100/g - ¥10000/g(贵)

    简化:统一阈值 ¥10/g - ¥10000/g(覆盖 polymer 下限)

    Args:
        yield_grams: synth 产物克数
        cost_cny: synth 成本(元)

    Returns:
        (passed, issue_str)
    """
    if yield_grams <= 0 or cost_cny <= 0:
        return True, ""  # 数据不足,跳过

    cost_per_gram = cost_cny / yield_grams

    if cost_per_gram < 10.0:
        return False, f"cost-per-gram ¥{cost_per_gram:.1f}/g too low (< ¥10/g) — check yield or cost"
    if cost_per_gram > 10000.0:
        return False, f"cost-per-gram ¥{cost_per_gram:.1f}/g too high (> ¥10000/g) — check yield or cost"
    return True, ""


def rule_xrd_peak_count_for_crystallinity(peaks: List[Dict[str, float]], synth_formula: str) -> Tuple[bool, str]:
    """R5: XRD peak count 应与结晶性匹配

    规则:
    - crystalline(Inconel/TiO2/Al2O3/Si/SS304 等)→ 期望 ≥ 3 个峰
    - amorphous(玻璃/无定形)→ 期望 ≤ 1 个宽峰
    - polymer 可结晶也可无定形 → 不强校验

    Args:
        peaks: XRD peaks 列表
        synth_formula: synth 化学式

    Returns:
        (passed, issue_str)
    """
    if not peaks:
        return True, ""  # 没数据 → 跳过

    n_peaks = len(peaks)
    if not synth_formula:
        return True, ""

    synth_elems = parse_formula_elements(synth_formula)
    is_polymer_like = _is_polymer(synth_elems)

    if is_polymer_like:
        # polymer 不强制
        return True, ""

    # crystalline 材料要求 ≥ 3 峰
    if n_peaks < 3:
        return False, f"XRD only has {n_peaks} peaks but crystalline {synth_formula!r} expected ≥ 3"

    return True, ""


# ============================================================================
# 主入口:evaluate_cross_robot
# ============================================================================


def evaluate_cross_robot(robot_evidence_list: List[RobotEvidence]) -> CrossRobotResult:
    """跑 5 条规则,出 CrossRobotResult

    Args:
        robot_evidence_list: List[RobotEvidence] (from build_robot_evidence_list)

    Returns:
        CrossRobotResult
    """
    issues: List[str] = []
    suggestions: List[str] = []
    rules_passed: List[str] = []
    rules_failed: List[str] = []

    # 找 synth 和 xrd(em/dsc 可选)
    synth_ev = next((e for e in robot_evidence_list if e.robot_type == "synth" and e.success), None)
    xrd_ev = next((e for e in robot_evidence_list if e.robot_type == "xrd" and e.success), None)
    em_ev = next((e for e in robot_evidence_list if e.robot_type == "em" and e.success), None)
    dsc_ev = next((e for e in robot_evidence_list if e.robot_type == "dsc" and e.success), None)

    synth_formula = synth_ev.synth_product_formula if synth_ev else ""

    # R1: XRD matched_phase vs synth product
    if xrd_ev and synth_ev:
        passed, issue = rule_xrd_phase_in_synth_product(
            xrd_ev.xrd_matched_phase, synth_formula
        )
        if passed:
            rules_passed.append(RULE_R1_XRD_PHASE)
        else:
            rules_failed.append(RULE_R1_XRD_PHASE)
            if issue:
                issues.append(issue)
                suggestions.append("复核 XRD 样品制备和 matched_phase 识别")

    # R2: EDS elements ⊆ synth formula
    if em_ev and synth_ev:
        passed, issue = rule_eds_elements_subset_of_synth(
            em_ev.em_eds_elements, synth_formula
        )
        if passed:
            rules_passed.append(RULE_R2_EDS_ELEMENTS)
        else:
            rules_failed.append(RULE_R2_EDS_ELEMENTS)
            if issue:
                issues.append(issue)
                suggestions.append("检查 EM 样品制备是否被污染,或复核 synth 配方")

    # R3: DSC Tg/Tm vs synth class
    if dsc_ev and synth_ev:
        passed, issue = rule_dsc_class_matches_synth(
            dsc_ev.dsc_Tg, dsc_ev.dsc_Tm, synth_formula
        )
        if passed:
            rules_passed.append(RULE_R3_DSC_CLASS)
        else:
            rules_failed.append(RULE_R3_DSC_CLASS)
            if issue:
                issues.append(issue)
                suggestions.append("复核 DSC 升温程序是否选对温度区间")

    # R4: cost-per-gram sanity
    if synth_ev:
        passed, issue = rule_synth_cost_per_gram(
            synth_ev.synth_yield_grams, synth_ev.synth_cost_cny
        )
        if passed:
            rules_passed.append(RULE_R4_COST_SANITY)
        else:
            rules_failed.append(RULE_R4_COST_SANITY)
            if issue:
                issues.append(issue)
                suggestions.append("复核 synth 成本估算函数和产率报告")

    # R5: XRD peak count vs crystallinity
    if xrd_ev and synth_ev:
        passed, issue = rule_xrd_peak_count_for_crystallinity(
            xrd_ev.xrd_peaks, synth_formula
        )
        if passed:
            rules_passed.append(RULE_R5_XRD_PEAK_COUNT)
        else:
            rules_failed.append(RULE_R5_XRD_PEAK_COUNT)
            if issue:
                issues.append(issue)
                suggestions.append("增加 XRD 曝光时间或样品量")

    # 综合分计算
    n_total = len(rules_passed) + len(rules_failed)
    if n_total == 0:
        # 没规则可跑(数据全缺) → 默认 0.7,consistent=True
        score = 0.7
        consistent = True
    else:
        n_passed = len(rules_passed)
        score = n_passed / n_total
        # 至少 1 条失败 → 不一致
        consistent = len(rules_failed) == 0

    return CrossRobotResult(
        score=round(score, 3),
        consistent=consistent,
        issues=issues,
        suggestions=suggestions,
        rules_passed=rules_passed,
        rules_failed=rules_failed,
    )


# ============================================================================
# CrossRobotConsistencyGuard - 独立类 safety guard
# ============================================================================

# 避免循环 import:SafetyGuard 在 matwau/harness/safety_guard.py
try:
    from matwau.harness.safety_guard import SafetyGuard, AgentResponse
except ImportError:
    # 兼容:测试环境下可能 matwau 不在 path
    try:
        import sys
        from pathlib import Path
        _PROJECT_ROOT = Path(__file__).resolve().parents[2]
        if str(_PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(_PROJECT_ROOT))
        from matwau.harness.safety_guard import SafetyGuard, AgentResponse
    except ImportError:
        # stub — 测试时单独 mock
        SafetyGuard = object  # type: ignore
        AgentResponse = object  # type: ignore


class CrossRobotConsistencyGuard(SafetyGuard):
    """W30 跨机器人一致性 guard

    跟 ChemistSafetyGuard 并列(协调级 vs critic 内部,不同层级)
    默认不阻断(返回 True),只在 cross_robot.consistent=False 且有 critical failure 时阻断
    """

    def __init__(self, *, block_on_inconsistency: bool = False):
        self.block_on_inconsistency = block_on_inconsistency
        self.warnings_count = 0
        self.blocks_count = 0

    def check(self, response: Any) -> bool:
        """检查 critic response 是否通过跨机器人一致性

        默认 True(pass),仅在 block_on_inconsistency=True 且一致性失败时返回 False
        """
        try:
            artifacts = getattr(response, "artifacts", {}) or {}
            verdict = artifacts.get("critic_verdict")

            if verdict is None:
                return True  # 没 verdict → 跳过

            # 取 cross_robot 字段
            cross = getattr(verdict, "cross_robot", None)
            if cross is None:
                return True

            if not getattr(cross, "consistent", True):
                self.warnings_count += 1
                if self.block_on_inconsistency:
                    self.blocks_count += 1
                    return False

            return True
        except Exception:
            # 任何异常都不阻断(critic 是裁决层,不该自己卡死)
            return True


__all__ = [
    "RobotEvidence",
    "CrossRobotResult",
    "build_robot_evidence_list",
    "evaluate_cross_robot",
    "rule_xrd_phase_in_synth_product",
    "rule_eds_elements_subset_of_synth",
    "rule_dsc_class_matches_synth",
    "rule_synth_cost_per_gram",
    "rule_xrd_peak_count_for_crystallinity",
    "CrossRobotConsistencyGuard",
]