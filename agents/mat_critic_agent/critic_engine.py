"""critic_engine.py — mat-critic 的 3 路打分引擎

3 路交叉验证(per MatWAU-开发计划 §七 W12):
  L1 物理一致性(0.4 权重):形成能 + 弛豫能是否合理区间
  L2 实验可行性(0.4 权重):元素可得性 + 合成温度可达
  L3 安全规则(0.2 权重):禁元素 + 放射性 + 毒性

verdict 阈值:
  >= 0.7 → pass(可信)
  0.5-0.7 → warn(有疑,需复核)
  < 0.5  → fail(不可信,推荐丢弃)

Stage 1 / Phase 1:纯规则引擎(无 LLM,关键词 + 数值比较)
Stage 2(WAU v1.0.0 GA 后):接 LLM 复核
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ============================================================================
# 常量
# ============================================================================


# 形成能合理区间(单位:eV/atom)
ENERGY_VALID_RANGE = (-6.0, 0.0)        # 稳定结构应 < -1.0
ENERGY_SUSPICIOUS = 0.5                 # > 此值 → 不稳定

# 弛豫后力(eV/Å)合理范围
FORCES_VALID_MAX = 0.5                  # > 此值 → 弛豫未收敛

# 合成温度合理范围(℃)
SINTERING_TEMP_RANGE = (200, 1500)
SINTERING_TEMP_IMPOSSIBLE = 1700        # 超过此温度 → 工业炉难做

# 元素可得性(per 地球丰度 + 价格)
ELEMENT_AVAILABILITY = {
    # 极丰富(地壳 > 1000 ppm)
    "abundant": ["O", "Si", "Al", "Fe", "Ca", "Na", "K", "Mg", "H", "C", "N", "S", "P", "Ti", "Mn"],
    # 常见(< 1000 ppm)
    "common": ["Li", "Be", "B", "F", "Cl", "Sc", "V", "Cr", "Co", "Ni", "Cu", "Zn", "Ga", "Ge",
               "As", "Se", "Br", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Ru", "Rh", "Pd",
               "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Cs", "Ba", "La", "Ce",
               "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
               "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl",
               "Pb", "Bi"],
    # 稀有 / 放射性(需要特殊许可)
    "rare_radioactive": ["Po", "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu",
                         "Am", "Cm", "Bk", "Cf"],
    # 极毒 / 危险(实验禁止或严管)
    "toxic": ["Be", "As", "Cd", "Hg", "Pb", "Cr"],   # 注意 Cr(VI) 极毒
}

# 高毒元素(per OSHA / EPA 严管)
TOXIC_ELEMENTS = {"Be", "As", "Cd", "Hg", "Pb"}        # 强毒性

# 放射性元素(per NRC 监管)
RADIOACTIVE_ELEMENTS = {"Po", "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu",
                        "Am", "Cm", "Bk", "Cf", "Tc"}

# 用户自定义禁止元素(从 user_intent 提取)
USER_FORBIDDEN_KEYWORDS = [
    "无钴", "不含钴", "无 Co", "无Co", "no co", "no cobalt", "without co",
    "无 Pt", "无Pt", "no pt", "without pt",
    "无 Au", "无Au", "no au", "without au",
    "无贵金属", "no precious",
    "无 Ni", "无Ni", "no ni", "without ni",
]


# ============================================================================
# W30 新增常量 - 跨机器人一致性
# ============================================================================

# 4 路权重(总 1.0)
WEIGHT_L1_PHYSICAL = 0.3
WEIGHT_L2_SYNTHESIS = 0.3
WEIGHT_L3_SAFETY = 0.2
WEIGHT_L4_CROSS_ROBOT = 0.2

# W30 新增 - 5 个 FailureType.code
FAIL_XRD_PHASE_MISMATCH = "xrd_phase_mismatch"
FAIL_EDS_EXTRA_ELEMENTS = "eds_extra_elements"
FAIL_DSC_CLASS_MISMATCH = "dsc_class_mismatch"
FAIL_CROSS_ROBOT_INCONSISTENCY = "cross_robot_inconsistency"
FAIL_DATA_CONSISTENCY_LOW = "data_consistency_low"

# 跨机器人规则名(给 issues 和 suggestions 用)
RULE_R1_XRD_PHASE = "R1_xrd_phase_in_synth_product"
RULE_R2_EDS_ELEMENTS = "R2_eds_elements_subset_of_synth"
RULE_R3_DSC_CLASS = "R3_dsc_class_matches_synth"
RULE_R4_COST_SANITY = "R4_synth_cost_per_gram"
RULE_R5_XRD_PEAK_COUNT = "R5_xrd_peak_count_for_crystallinity"


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class CriticScore:
    """1 路打分(0-1)"""

    name: str                           # L1 / L2 / L3 / L4
    score: float                        # 0-1,越高越可信
    weight: float                       # 该路权重
    issues: List[str] = field(default_factory=list)   # 问题列表
    suggestions: List[str] = field(default_factory=list)  # 修复建议


# W30 - L4 跨机器人一致性打分
@dataclass
class CrossRobotScore:
    """L4 跨机器人一致性打分(W30 新增)

    吃 ChemistReport 中 4 robot 结果,跑物理一致性验证:
    - R1 XRD matched_phase vs synth.product_formula
    - R2 EDS 元素 ⊆ synth 化学式
    - R3 DSC Tg/Tm 类一致
    - R4 cost-per-gram sanity(Round 2)
    - R5 XRD peak count 与结晶性(Round 2)

    注:不复用 CriticScore(继承会跟 dataclass 字段顺序冲突),独立 dataclass
    但保持相同字段语义(name/score/weight/issues/suggestions),CriticVerdict.to_dict() 一致处理
    """

    name: str = "L4_cross_robot"
    score: float = 0.0
    weight: float = 0.2
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    consistent: bool = True             # 4 robot 结果是否一致
    rules_passed: List[str] = field(default_factory=list)
    rules_failed: List[str] = field(default_factory=list)


@dataclass
class FailureType:
    """1 个失败类型识别"""

    code: str                           # energy_too_high / synthesis_impossible / safety_violation / data_inconsistent
    severity: str                       # critical / warning / info
    confidence: float                   # 0-1
    evidence: List[str] = field(default_factory=list)
    fix_suggestions: List[str] = field(default_factory=list)


@dataclass
class CriticVerdict:
    """最终 verdict"""

    overall_score: float                # 加权综合分
    verdict: str                        # pass / warn / fail
    l1: CriticScore                     # 物理一致性
    l2: CriticScore                     # 实验可行性
    l3: CriticScore                     # 安全规则
    cross_robot: CrossRobotScore = field(default_factory=CrossRobotScore)  # W30 NEW
    failures: List[FailureType] = field(default_factory=list)
    top_suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_score": round(self.overall_score, 3),
            "verdict": self.verdict,
            "l1_physical": {
                "score": round(self.l1.score, 3),
                "weight": self.l1.weight,
                "issues": self.l1.issues,
            },
            "l2_synthesis": {
                "score": round(self.l2.score, 3),
                "weight": self.l2.weight,
                "issues": self.l2.issues,
            },
            "l3_safety": {
                "score": round(self.l3.score, 3),
                "weight": self.l3.weight,
                "issues": self.l3.issues,
            },
            "l4_cross_robot": {  # W30 NEW
                "score": round(self.cross_robot.score, 3),
                "weight": self.cross_robot.weight,
                "issues": self.cross_robot.issues,
                "consistent": self.cross_robot.consistent,
                "rules_passed": self.cross_robot.rules_passed,
                "rules_failed": self.cross_robot.rules_failed,
            },
            "failures": [
                {
                    "code": f.code,
                    "severity": f.severity,
                    "confidence": round(f.confidence, 3),
                    "evidence": f.evidence,
                    "fix_suggestions": f.fix_suggestions,
                }
                for f in self.failures
            ],
            "top_suggestions": self.top_suggestions,
        }


# ============================================================================
# L1 物理一致性打分
# ============================================================================


def _extract_energies(req_or_candidate: Any) -> List[Tuple[float, str]]:
    """从 candidate / job / recipe 抽取能量"""
    energies = []

    # 1. GenCandidate.estimated_energy
    if hasattr(req_or_candidate, "estimated_energy"):
        e = req_or_candidate.estimated_energy
        if e is not None and e != 0.0:
            energies.append((float(e), "estimated_energy"))

    # 2. SimResult / SimCandidate.relaxed_energy
    if hasattr(req_or_candidate, "relaxed_energy"):
        e = req_or_candidate.relaxed_energy
        if e is not None:
            energies.append((float(e), "relaxed_energy"))

    # 3. HPCJobResult.energy / total_energy
    for attr in ("total_energy", "energy_per_atom", "energy"):
        if hasattr(req_or_candidate, attr):
            e = getattr(req_or_candidate, attr)
            if e is not None:
                energies.append((float(e), attr))

    # 4. dict 形式
    if isinstance(req_or_candidate, dict):
        for key in ("estimated_energy", "relaxed_energy", "total_energy", "energy_per_atom"):
            if key in req_or_candidate:
                energies.append((float(req_or_candidate[key]), key))

    return energies


def _extract_forces(item: Any) -> Optional[float]:
    """抽取最大原子受力"""
    if hasattr(item, "forces_max"):
        return float(item.forces_max) if item.forces_max is not None else None
    if isinstance(item, dict) and "forces_max" in item:
        return float(item["forces_max"])
    return None


def score_l1_physical(candidates: List[Any], req_message: str = "") -> CriticScore:
    """L1 物理一致性打分

    评分规则:
    - 0.9-1.0: 形成能 < -3.0 eV/atom,弛豫收敛 → 极稳定
    - 0.7-0.9: -3.0 <= energy < -1.5 → 稳定
    - 0.4-0.7: -1.5 <= energy < -0.5 → 亚稳
    - 0.0-0.4: energy >= -0.5 或 > 0.5(不收敛) → 不稳定

    同时检查 forces_max(> 0.5 eV/Å → 未收敛)
    """
    if not candidates:
        return CriticScore(
            name="L1_physical",
            score=0.5,
            weight=WEIGHT_L1_PHYSICAL,
            issues=["无候选,无法评估物理一致性"],
            suggestions=["确认上游 mat-gen / mat-sim / mat-hpc 至少产出 1 个候选"],
        )

    issues = []
    suggestions = []
    n_unstable = 0
    n_unconverged = 0
    n_total = len(candidates)

    for cand in candidates:
        # 能量检查
        energies = _extract_energies(cand)
        for energy, src in energies:
            if energy >= ENERGY_SUSPICIOUS:
                n_unstable += 1
                formula = getattr(cand, "formula", None) or (
                    cand.get("formula") if isinstance(cand, dict) else "?"
                )
                issues.append(f"{formula} {src}={energy:.2f} eV/atom 异常(高于阈值 0.5)")
                suggestions.append(
                    f"复核 {formula}:检查上游 mat-gen 是否构造了非物理结构(mat-gen constraints)"
                )
                break

        # 力检查
        forces = _extract_forces(cand)
        if forces is not None and forces > FORCES_VALID_MAX:
            n_unconverged += 1
            formula = getattr(cand, "formula", None) or "?"
            issues.append(f"{formula} forces_max={forces:.3f} eV/Å 弛豫未收敛(>{FORCES_VALID_MAX})")
            suggestions.append(f"{formula} 增加 mat-sim 弛豫步数 / 调小 force_threshold")

    # 综合分数
    if n_unstable + n_unconverged == 0:
        # 全部稳定且收敛 → 按形成能再细分
        all_energies = []
        for cand in candidates:
            energies = _extract_energies(cand)
            for e, _ in energies:
                all_energies.append(e)
        if all_energies:
            avg_e = sum(all_energies) / len(all_energies)
            if avg_e < -3.0:
                score = 0.95
            elif avg_e < -2.0:
                score = 0.85
            elif avg_e < -1.0:
                score = 0.75
            else:
                score = 0.6
        else:
            score = 0.7  # 没能量数据,默认中等可信
    else:
        # 有问题
        frac_bad = (n_unstable + n_unconverged) / n_total
        score = max(0.0, 0.7 - frac_bad * 0.6)  # 70% 起步,扣分
        if frac_bad >= 0.8:
            score = max(0.1, score)
            suggestions.append(">80% 候选物理不合理,建议回退到 mat-gen 重新生成")

    return CriticScore(
        name="L1_physical",
        score=score,
        weight=WEIGHT_L1_PHYSICAL,
        issues=issues[:5],  # 最多 5 条
        suggestions=suggestions[:5],
    )


# ============================================================================
# L2 实验可行性打分
# ============================================================================


def _extract_elements(item: Any) -> List[str]:
    """从 candidate / recipe 抽元素"""
    if hasattr(item, "formula"):
        return _parse_formula_elements(item.formula)
    if isinstance(item, dict) and "formula" in item:
        return _parse_formula_elements(item["formula"])
    if hasattr(item, "elements"):
        return list(item.elements or [])
    if isinstance(item, dict) and "elements" in item:
        return list(item["elements"])
    return []


def _parse_formula_elements(formula: str) -> List[str]:
    """从化学式抽元素(per W8 修复:2 字符元素优先)

    从全部 ELEMENT_AVAILABILITY 池子(abundant / common / rare_radioactive / toxic)匹配,
    这样放射性元素(Th / U / Pu)和高毒元素(Be / As / Cd / Hg / Pb)才能被识别。
    """
    all_elements = [e for cat in ELEMENT_AVAILABILITY.values() for e in cat]
    element_pool_2char = [e for e in all_elements if len(e) == 2]
    element_pool_1char = [e for e in all_elements if len(e) == 1]
    element_pool = sorted(element_pool_2char + element_pool_1char, key=lambda x: (-len(x), x))

    elements = []
    for elem in element_pool:
        if elem in formula:
            # 单字符不能被 2 字符覆盖
            if len(elem) == 1 and any(elem in e for e in elements if len(e) >= 2):
                continue
            elements.append(elem)
    return elements


def _extract_sintering_temp(item: Any) -> Optional[float]:
    """抽烧结温度(per ExpRecipe / SinteringRecipe / dict)"""
    # 1. ExpRecipe 有 sintering 子对象
    if hasattr(item, "sintering"):
        sinter = item.sintering
        if hasattr(sinter, "temperature_c"):
            return float(sinter.temperature_c)
        if isinstance(sinter, dict) and "temperature_c" in sinter:
            return float(sinter["temperature_c"])
    # 2. dict 形式(含 sintering 子对象 或顶层 sintering_temperature_c)
    if isinstance(item, dict):
        if "sintering" in item:
            sinter = item["sintering"]
            if isinstance(sinter, dict) and "temperature_c" in sinter:
                return float(sinter["temperature_c"])
        # 顶层 key(测试常用)
        if "sintering_temperature_c" in item:
            return float(item["sintering_temperature_c"])
    # 3. 顶层属性(per ExpRecipe 也可能直接有 temperature_c)
    if hasattr(item, "sintering_temperature_c"):
        return float(item.sintering_temperature_c)
    return None


def score_l2_synthesis(candidates: List[Any], req_message: str = "") -> CriticScore:
    """L2 实验可行性打分

    检查:
    - 元素可得性(abundant / common / rare_radioactive)
    - 合成温度范围(200-1500 ℃ 工业可达,>1700 工业炉难做)
    - 烧结经验匹配(per mat-exp 经验数据库)
    """
    if not candidates:
        return CriticScore(
            name="L2_synthesis",
            score=0.5,
            weight=WEIGHT_L2_SYNTHESIS,
            issues=["无候选"],
            suggestions=["确认上游产出候选"],
        )

    issues = []
    suggestions = []

    n_rare = 0
    n_temp_impossible = 0
    n_total = len(candidates)

    for cand in candidates:
        # 元素检查
        elements = _extract_elements(cand)
        rare_in = [e for e in elements if e in ELEMENT_AVAILABILITY["rare_radioactive"]]
        if rare_in:
            n_rare += 1
            formula = getattr(cand, "formula", None) or "?"
            issues.append(f"{formula} 含稀有/放射性元素 {rare_in},需特殊许可")
            suggestions.append(f"{formula}: 替换为常见元素(La/Ce 替代 Ac/Th,U 替代 Pu)")

        # 温度检查(仅对 ExpRecipe)
        temp = _extract_sintering_temp(cand)
        if temp is not None:
            if temp > SINTERING_TEMP_IMPOSSIBLE:
                n_temp_impossible += 1
                formula = getattr(cand, "formula", None) or "?"
                issues.append(f"{formula} 烧结温度 {temp}℃ 超出工业炉能力(>1700℃)")
                suggestions.append(f"{formula}: 降低烧结温度(助熔剂 / 低温合成路线)")
            elif temp < SINTERING_TEMP_RANGE[0]:
                issues.append(f"{formula} 烧结温度 {temp}℃ 过低,可能不反应")

    # 综合分数
    score = 0.85  # 默认 85% 可行
    if n_rare > 0:
        frac_rare = n_rare / n_total
        score -= 0.5 * frac_rare
    if n_temp_impossible > 0:
        frac_impossible = n_temp_impossible / n_total
        score -= 0.4 * frac_impossible

    score = max(0.0, min(1.0, score))

    if score < 0.5:
        suggestions.append("实验可行性差,建议换元素 / 换合成路线")

    return CriticScore(
        name="L2_synthesis",
        score=score,
        weight=WEIGHT_L2_SYNTHESIS,
        issues=issues[:5],
        suggestions=suggestions[:5],
    )


# ============================================================================
# L3 安全规则打分
# ============================================================================


def _extract_user_forbidden(req_message: str) -> List[str]:
    """从 user_intent 抽禁止元素"""
    msg_lower = req_message.lower()
    forbidden = []
    if "无钴" in req_message or "不含钴" in req_message or "无 co" in msg_lower or "无Co" in req_message:
        forbidden.append("Co")
    if "无贵金属" in req_message or "no precious" in msg_lower:
        forbidden.extend(["Pt", "Au", "Ag"])
    if "无 pt" in msg_lower or "无Pt" in req_message:
        forbidden.append("Pt")
    if "无 au" in msg_lower or "无Au" in req_message:
        forbidden.append("Au")
    if "无 ni" in msg_lower or "无Ni" in req_message:
        forbidden.append("Ni")
    if "无 ag" in msg_lower or "无Ag" in req_message:
        forbidden.append("Ag")
    return forbidden


def score_l3_safety(candidates: List[Any], req_message: str = "") -> CriticScore:
    """L3 安全规则打分

    检查:
    - 用户自定义禁元素(user_intent 提取)
    - 高毒元素(Be / As / Cd / Hg / Pb)
    - 放射性元素(U / Pu 等)
    """
    if not candidates:
        return CriticScore(
            name="L3_safety",
            score=0.7,
            weight=WEIGHT_L3_SAFETY,
            issues=["无候选"],
            suggestions=[],
        )

    issues = []
    suggestions = []
    user_forbidden = _extract_user_forbidden(req_message)

    n_user_violation = 0
    n_toxic = 0
    n_radioactive = 0
    n_total = len(candidates)

    for cand in candidates:
        elements = _extract_elements(cand)
        formula = getattr(cand, "formula", None) or "?"

        # 1. 用户禁元素
        user_hit = [e for e in elements if e in user_forbidden]
        if user_hit:
            n_user_violation += 1
            issues.append(f"{formula} 含用户禁元素 {user_hit}")
            suggestions.append(
                f"{formula}: 重新生成,排除 {user_hit}(改 mat-gen constraints)"
            )

        # 2. 高毒元素
        toxic_hit = [e for e in elements if e in TOXIC_ELEMENTS]
        if toxic_hit:
            n_toxic += 1
            issues.append(f"{formula} 含高毒元素 {toxic_hit}(OSHA 严管)")
            suggestions.append(
                f"{formula}: 加 PPE / 通风橱 / 申报,或换用低毒元素替代"
            )

        # 3. 放射性
        radio_hit = [e for e in elements if e in RADIOACTIVE_ELEMENTS]
        if radio_hit:
            n_radioactive += 1
            issues.append(f"{formula} 含放射性元素 {radio_hit}(NRC 监管)")
            suggestions.append(f"{formula}: 需 NRC 许可 + 屏蔽设施")

    # 综合分数(per 安全零容忍:硬阈值)
    score = 1.0
    # 用户约束违反 → 立即降至 0.4(fail 阈值,verdict 必然 fail)
    if n_user_violation > 0:
        score = min(score, 0.4)
    # 放射性元素 → 立即降至 0.3
    if n_radioactive > 0:
        score = min(score, 0.3)
    # 高毒元素 → 减分到 0.65(warn 阈值,verdict=warn)
    if n_toxic > 0:
        score = min(score, 0.65)

    score = max(0.0, min(1.0, score))

    if n_radioactive > 0:
        issues.append("⚠️ 含放射性元素,强烈建议替代")

    return CriticScore(
        name="L3_safety",
        score=score,
        weight=WEIGHT_L3_SAFETY,
        issues=issues[:5],
        suggestions=suggestions[:5],
    )


# ============================================================================
# 失败类型识别
# ============================================================================


def identify_failures(
    l1: CriticScore,
    l2: CriticScore,
    l3: CriticScore,
) -> List[FailureType]:
    """从 3 路打分识别失败类型

    严重等级:
    - critical: 安全零容忍(放射性 / 用户禁元素)→ 立即 fail
    - warning: 可处理(物理异常 / 合成困难 / 高毒可 PPE)→ 影响 verdict 到 warn
    """
    failures = []

    # L1 失败 → energy_too_high / data_inconsistent
    if l1.score < 0.5:
        is_converged = not any("未收敛" in i or "不收敛" in i for i in l1.issues)
        if is_converged:
            failures.append(FailureType(
                code="energy_too_high",
                severity="warning",  # 形成能异常是 warning(可重新生成)
                confidence=round(1.0 - l1.score, 3),
                evidence=l1.issues[:3],
                fix_suggestions=l1.suggestions[:3],
            ))
        else:
            failures.append(FailureType(
                code="data_inconsistent",
                severity="warning",  # 未收敛是 warning(可调参数)
                confidence=round(1.0 - l1.score, 3),
                evidence=l1.issues[:3],
                fix_suggestions=l1.suggestions[:3],
            ))

    # L2 失败 → synthesis_impossible / synthesis_difficult
    if l2.score < 0.5:
        is_temp = any("温度" in i or "炉" in i for i in l2.issues)
        is_rare = any("稀有" in i or "放射性" in i for i in l2.issues)
        if is_rare:
            # 稀有/放射性 → critical(零容忍)
            failures.append(FailureType(
                code="synthesis_difficult",
                severity="critical",
                confidence=round(1.0 - l2.score, 3),
                evidence=l2.issues[:3],
                fix_suggestions=l2.suggestions[:3],
            ))
        elif is_temp:
            # 温度问题 → warning(可换工艺)
            failures.append(FailureType(
                code="synthesis_impossible",
                severity="warning",
                confidence=round(1.0 - l2.score, 3),
                evidence=l2.issues[:3],
                fix_suggestions=l2.suggestions[:3],
            ))
        else:
            failures.append(FailureType(
                code="synthesis_difficult",
                severity="warning",
                confidence=round(1.0 - l2.score, 3),
                evidence=l2.issues[:3],
                fix_suggestions=l2.suggestions[:3],
            ))

    # L3 失败
    # 检查 issues 里的关键信号(不只看 score < 0.5)
    is_radio = any("放射" in i for i in l3.issues)
    is_toxic = any("高毒" in i or "OSHA" in i for i in l3.issues)
    is_user_violation = any("用户禁" in i or "禁元素" in i for i in l3.issues)

    if l3.score < 0.5 or is_radio or is_user_violation or is_toxic:
        if is_radio:
            # 放射性 → critical
            failures.append(FailureType(
                code="radioactive_hazard",
                severity="critical",
                confidence=round(1.0 - l3.score, 3),
                evidence=l3.issues[:3],
                fix_suggestions=l3.suggestions[:3],
            ))
        elif is_user_violation:
            # 用户禁元素 → critical(零容忍)
            failures.append(FailureType(
                code="safety_violation",
                severity="critical",
                confidence=round(1.0 - l3.score, 3),
                evidence=l3.issues[:3],
                fix_suggestions=l3.suggestions[:3],
            ))
        elif is_toxic:
            # 高毒 → warning(可 PPE)
            failures.append(FailureType(
                code="toxicity_warning",
                severity="warning",
                confidence=round(1.0 - l3.score, 3),
                evidence=l3.issues[:3],
                fix_suggestions=l3.suggestions[:3],
            ))
        else:
            # 其他低分(L3 极差)→ critical
            failures.append(FailureType(
                code="safety_violation",
                severity="critical" if l3.score < 0.3 else "warning",
                confidence=round(1.0 - l3.score, 3),
                evidence=l3.issues[:3],
                fix_suggestions=l3.suggestions[:3],
            ))

    return failures


# ============================================================================
# 综合 verdict
# ============================================================================


def aggregate_verdict(
    l1: CriticScore,
    l2: CriticScore,
    l3: CriticScore,
    failures: List[FailureType],
    cross_robot: Optional[CrossRobotScore] = None,
) -> str:
    """综合判定 pass / warn / fail

    规则:
    - 任何 critical failure(安全零容忍 / 放射性 / 用户禁元素)→ fail
    - 其他 critical(物理 / 合成极差)→ fail
    - warning(物理异常 / 合成困难 / 高毒)→ warn(即使总分高)
    - 纯 warning + 总分高 → warn
    - 无 critical / warning + 总分高 → pass

    W30:支持 4 路加权(L1/L2/L3/L4 cross_robot)。如未传 cross_robot,沿用原 3 路加权。
    """
    if cross_robot is None or cross_robot.score == 0.0:
        # 向后兼容 - 3 路加权
        overall = l1.score * l1.weight + l2.score * l2.weight + l3.score * l3.weight
    else:
        # W30 - 4 路加权
        overall = (
            l1.score * l1.weight
            + l2.score * l2.weight
            + l3.score * l3.weight
            + cross_robot.score * cross_robot.weight
        )

    # 1. critical(安全零容忍)→ 立即 fail
    critical_failures = [f for f in failures if f.severity == "critical"]
    if critical_failures:
        return "fail"

    # 2. warning → warn(即使总分高,也至少是 warn)
    has_warning = any(f.severity == "warning" for f in failures)
    if has_warning:
        return "warn"

    # 3. 无任何 failure,按综合分
    if overall >= 0.7:
        return "pass"
    if overall >= 0.5:
        return "warn"
    return "fail"


# ============================================================================
# 主入口
# ============================================================================


def evaluate_candidates(
    candidates: List[Any],
    *,
    user_intent: str = "",
    prior_failures: List[FailureType] = None,
) -> CriticVerdict:
    """3 路交叉验证主入口(W30 保持向后兼容 — 默认走 3 路,不打 L4)

    如需 4 路(L1/L2/L3/L4 cross_robot),请用 `evaluate_chemist_report(report, user_intent=...)`。

    Args:
        candidates: 候选列表(GenCandidate / SimCandidate / HPCJobResult / ExpRecipe / dict)
        user_intent: 用户原始意图(用于安全规则 + 失败关键词诊断)
        prior_failures: 上游失败信息(可选,用于交叉验证)

    Returns:
        CriticVerdict (cross_robot 字段为空 default)
    """
    # L1 / L2 / L3 打分
    l1 = score_l1_physical(candidates, user_intent)
    l2 = score_l2_synthesis(candidates, user_intent)
    l3 = score_l3_safety(candidates, user_intent)

    # 失败识别
    failures = identify_failures(l1, l2, l3)

    # 关键词-based 额外诊断(per user_intent 触发)
    if user_intent:
        keyword_failures = _keyword_based_failures(user_intent)
        failures.extend(keyword_failures)

    if prior_failures:
        failures.extend(prior_failures)

    # 综合分(3 路)
    overall = l1.score * l1.weight + l2.score * l2.weight + l3.score * l3.weight

    # verdict
    verdict = aggregate_verdict(l1, l2, l3, failures)

    # top 建议:从 3 路合并,按分数高低排序(分数越低越优先)
    all_suggestions = []
    for s in [l3, l2, l1]:  # 顺序反过来(L3 优先,权重低但关键)
        for sug in s.suggestions:
            if sug not in all_suggestions:
                all_suggestions.append(sug)

    # 关键词诊断建议也加进来
    for f in failures:
        for sug in f.fix_suggestions:
            if sug not in all_suggestions:
                all_suggestions.append(sug)

    top_suggestions = all_suggestions[:5]

    return CriticVerdict(
        overall_score=round(overall, 3),
        verdict=verdict,
        l1=l1,
        l2=l2,
        l3=l3,
        failures=failures,
        top_suggestions=top_suggestions,
    )


def evaluate_chemist_report(
    report: Any,
    *,
    user_intent: str = "",
) -> CriticVerdict:
    """W30 新入口:吃 ChemistReport,跑 L1-L4 4 路打分(含跨机器人一致性)

    Args:
        report: ChemistReport dataclass(or dict 含 robot_results 字段)
        user_intent: 用户原始意图(用于 L2/L3 user-forbidden 关键词)

    Returns:
        CriticVerdict with cross_robot 字段填充

    实现:
    1. 从 report.robot_results 抽 4 robot artifacts → RobotEvidence 列表
    2. 把 4 robot 结果展平 → 走 L1/L2/L3 (per-robot 元素 + 物理证据)
    3. 跑 L4 跨机器人一致性(5 条规则)
    4. 4 路加权 → verdict
    """
    # 0. 懒加载避免循环 import
    from .cross_robot import build_robot_evidence_list, evaluate_cross_robot

    # 1. 抽 ChemistReport 字段
    if isinstance(report, dict):
        robot_results = report.get("robot_results", [])
        target_sample = report.get("target_sample", "")
    else:
        # ChemistReport dataclass
        robot_results = getattr(report, "robot_results", []) or []
        target_sample = getattr(report, "target_sample", "") or ""

    # 2. 抽 4 robot 物理证据
    robot_evidence = build_robot_evidence_list(robot_results)

    # 3. 展平给 L1/L2/L3 用 — 用 robot_evidence 转 candidates 形式
    # L1 看 energy,这里没有 DFT/HPC 数据,robot 都没有 → L1 默认 0.7
    # L2 看 element availability → 从 synth.product_formula + EM EDS 取元素
    # L3 看 user_forbidden + 毒/放射 → 从所有 robot artifacts 取元素
    l1_candidates = _evidence_to_l1_candidates(robot_evidence)
    l2_candidates = _evidence_to_l2_candidates(robot_evidence, target_sample)
    l3_candidates = _evidence_to_l3_candidates(robot_evidence, target_sample)

    # 4. 跑 L1/L2/L3
    l1 = score_l1_physical(l1_candidates, user_intent)
    l2 = score_l2_synthesis(l2_candidates, user_intent)
    l3 = score_l3_safety(l3_candidates, user_intent)

    # 5. 跑 L4 跨机器人一致性
    cross_result = evaluate_cross_robot(robot_evidence)
    l4 = _cross_result_to_score(cross_result)

    # 6. 失败识别(原 3 路 + W30 跨机器人新增)
    failures = identify_failures(l1, l2, l3)
    failures.extend(_cross_result_to_failures(cross_result))

    # 7. 关键词诊断(per user_intent 触发)
    if user_intent:
        keyword_failures = _keyword_based_failures(user_intent)
        failures.extend(keyword_failures)

    # 8. 4 路加权
    overall = (
        l1.score * l1.weight
        + l2.score * l2.weight
        + l3.score * l3.weight
        + l4.score * l4.weight
    )

    # 9. verdict(传入 l4 让 critical failure 检查用上 L4 失败)
    verdict = aggregate_verdict(l1, l2, l3, failures, cross_robot=l4)

    # 10. top 建议:4 路合并
    all_suggestions = []
    for s in [l3, l4, l2, l1]:
        for sug in s.suggestions:
            if sug not in all_suggestions:
                all_suggestions.append(sug)
    for f in failures:
        for sug in f.fix_suggestions:
            if sug not in all_suggestions:
                all_suggestions.append(sug)
    top_suggestions = all_suggestions[:5]

    return CriticVerdict(
        overall_score=round(overall, 3),
        verdict=verdict,
        l1=l1,
        l2=l2,
        l3=l3,
        cross_robot=l4,
        failures=failures,
        top_suggestions=top_suggestions,
    )


# W30 helpers - 把 RobotEvidence 转成 L1/L2/L3 兼容的 candidates 格式
def _evidence_to_l1_candidates(evidence_list: List[Any]) -> List[Dict[str, Any]]:
    """从 RobotEvidence 转 L1 物理一致性 candidates(只有 synth 能给能量)

    L1 看 energy/forces_max,robot 没有 DFT 输出 → 默认给空 list 让 L1 走默认分
    """
    cands = []
    for ev in evidence_list:
        if not ev.success:
            continue
        cand = {"formula": ev.formula or ev.synth_product_formula or "?"}
        cands.append(cand)
    return cands


def _evidence_to_l2_candidates(evidence_list: List[Any], target_sample: str) -> List[Dict[str, Any]]:
    """从 RobotEvidence 转 L2 实验可行性 candidates(用 synth.product + EM EDS 元素)"""
    cands = []
    for ev in evidence_list:
        if not ev.success:
            continue
        formula = ev.synth_product_formula or ev.formula or target_sample or "?"
        cand = {"formula": formula}
        cands.append(cand)
    return cands


def _evidence_to_l3_candidates(evidence_list: List[Any], target_sample: str) -> List[Dict[str, Any]]:
    """从 RobotEvidence 转 L3 安全 candidates(所有 robot 都给一个 formula 候选)"""
    cands = []
    for ev in evidence_list:
        if not ev.success:
            continue
        formula = ev.formula or ev.synth_product_formula or target_sample or "?"
        cand = {"formula": formula}
        cands.append(cand)
    return cands


def _cross_result_to_score(cross_result: Any) -> CrossRobotScore:
    """CrossRobotResult → CrossRobotScore dataclass"""
    return CrossRobotScore(
        name="L4_cross_robot",
        score=cross_result.score,
        weight=WEIGHT_L4_CROSS_ROBOT,
        issues=cross_result.issues[:5],
        suggestions=cross_result.suggestions[:5],
        consistent=cross_result.consistent,
        rules_passed=cross_result.rules_passed,
        rules_failed=cross_result.rules_failed,
    )


def _cross_result_to_failures(cross_result: Any) -> List[FailureType]:
    """CrossRobotResult → FailureType 列表(W30 新增 5 个 code)"""
    failures = []

    # 看 rules_failed,把每条失败规则转 1 个 FailureType
    rules_failed = cross_result.rules_failed or []
    issues = cross_result.issues or []

    # R1 XRD phase mismatch → critical(数据不一致,产物对不上)
    if RULE_R1_XRD_PHASE in rules_failed:
        failures.append(FailureType(
            code=FAIL_XRD_PHASE_MISMATCH,
            severity="critical",
            confidence=0.9,
            evidence=[i for i in issues if "XRD" in i or "phase" in i.lower()][:3],
            fix_suggestions=[
                "复核 mat-robot-synth 产物",
                "检查 XRD 样品是否被污染",
                "对比 ICSD 数据库参考谱",
            ],
        ))

    # R2 EDS 元素超出 → warning(可能是污染物)
    if RULE_R2_EDS_ELEMENTS in rules_failed:
        failures.append(FailureType(
            code=FAIL_EDS_EXTRA_ELEMENTS,
            severity="warning",
            confidence=0.85,
            evidence=[i for i in issues if "EDS" in i or "元素" in i][:3],
            fix_suggestions=[
                "检查 EM 样品制备:是否被污染",
                "复核 synth 配方是否漏元素",
            ],
        ))

    # R3 DSC 类不一致 → warning
    if RULE_R3_DSC_CLASS in rules_failed:
        failures.append(FailureType(
            code=FAIL_DSC_CLASS_MISMATCH,
            severity="warning",
            confidence=0.8,
            evidence=[i for i in issues if "DSC" in i or "Tg" in i or "Tm" in i][:3],
            fix_suggestions=[
                "复核 DSC 升温程序(可能选错温度区间)",
                "确认样品类别(polymer/metal/ceramic)",
            ],
        ))

    # R4 cost sanity → warning
    if RULE_R4_COST_SANITY in rules_failed:
        failures.append(FailureType(
            code=FAIL_DATA_CONSISTENCY_LOW,
            severity="warning",
            confidence=0.7,
            evidence=[i for i in issues if "cost" in i.lower() or "yield" in i.lower()][:3],
            fix_suggestions=[
                "复核 synth 产率报告",
                "检查成本估算函数",
            ],
        ))

    # R5 XRD peak count → warning
    if RULE_R5_XRD_PEAK_COUNT in rules_failed:
        failures.append(FailureType(
            code=FAIL_DATA_CONSISTENCY_LOW,
            severity="warning",
            confidence=0.7,
            evidence=[i for i in issues if "peak" in i.lower() or "结晶" in i][:3],
            fix_suggestions=[
                "检查 XRD 样品是否 amorphous(玻璃)",
                "增加曝光时间或样品量",
            ],
        ))

    # 整体不一致 → 1 个 info 提示
    if not cross_result.consistent and not rules_failed:
        failures.append(FailureType(
            code=FAIL_CROSS_ROBOT_INCONSISTENCY,
            severity="warning",
            confidence=0.6,
            evidence=cross_result.issues[:3],
            fix_suggestions=["人工复核 4 机器人结果的一致性"],
        ))

    return failures


def _keyword_based_failures(user_intent: str) -> List[FailureType]:
    """从 user_intent 关键词推断额外失败类型

    用于 explain_failure workflow(用户问"为什么 ... 失败")。
    即使没 LLM,也能从关键词给出针对性建议。
    """
    msg_lower = user_intent.lower()
    failures = []

    if "xrd" in msg_lower or "谱" in user_intent:
        failures.append(FailureType(
            code="xrd_mismatch",
            severity="warning",
            confidence=0.7,
            evidence=["XRD 谱与理论谱不匹配"],
            fix_suggestions=[
                "检查 mat-exp 理论谱计算(λ=1.5406 Å Cu Kα 正确)",
                "复核样品制备:是否均匀 / 是否含杂相",
                "对比 ICSD 数据库参考谱",
            ],
        ))

    if "合成失败" in user_intent or "synthesis failed" in msg_lower:
        failures.append(FailureType(
            code="synthesis_failed",
            severity="warning",
            confidence=0.7,
            evidence=["合成未成功"],
            fix_suggestions=[
                "提高烧结温度(>助熔剂熔点)",
                "延长保温时间(>2x)",
                "改用球磨 + 放电等离子烧结(SPS)",
                "通保护气(Ar/N2 防氧化)",
            ],
        ))

    if "能量异常" in user_intent or ("energy" in msg_lower and "high" in msg_lower):
        failures.append(FailureType(
            code="energy_anomaly",
            severity="critical",
            confidence=0.8,
            evidence=["形成能/弛豫能异常高"],
            fix_suggestions=[
                "复核 mat-gen:元素比例是否合理",
                "检查 mat-sim:弛豫步数 / 力阈值",
                "考虑换 CHGNet → M3GNet / PaiNN 重跑",
            ],
        ))

    return failures


# ============================================================================
# explain_failure 专用:解释特定失败
# ============================================================================


def explain_failure(
    user_intent: str,
    *,
    candidates: List[Any] = None,
    prior_outputs: Dict[str, Any] = None,
) -> CriticVerdict:
    """解释为什么实验/合成失败

    用户问:"为什么 XRD 谱不对"、"为什么合成失败"、"为什么能量异常"
    返回:CriticVerdict 含失败类型 + 证据 + 修复建议
    """
    # 1. 从 user_intent 推断失败类型
    msg_lower = user_intent.lower()
    candidates = candidates or []
    prior_outputs = prior_outputs or {}

    # 默认:用 evaluate_candidates 跑 1 次(若无候选,score 给 0.5 warn)
    if candidates:
        verdict = evaluate_candidates(candidates, user_intent=user_intent)
    else:
        # 无候选 → 给占位 verdict
        verdict = CriticVerdict(
            overall_score=0.5,
            verdict="warn",
            l1=CriticScore("L1_physical", 0.5, 0.4, ["无候选数据,无法定量评估"], []),
            l2=CriticScore("L2_synthesis", 0.5, 0.4, ["无候选数据"], []),
            l3=CriticScore("L3_safety", 0.7, 0.2, [], []),
            failures=[],
            top_suggestions=["提供失败的实验数据(mat-gen/sim/hpc/exp 输出)再分析"],
        )

    # 2. 加针对具体关键词的额外诊断
    extra_failures = []

    if "xrd" in msg_lower or "谱" in user_intent:
        extra_failures.append(FailureType(
            code="xrd_mismatch",
            severity="warning",
            confidence=0.7,
            evidence=["XRD 谱与理论谱不匹配"],
            fix_suggestions=[
                "检查 mat-exp 理论谱计算(λ=1.5406 Å Cu Kα 正确)",
                "复核样品制备:是否均匀 / 是否含杂相",
                "对比 ICSD 数据库参考谱",
            ],
        ))

    if "合成失败" in user_intent or "synthesis failed" in msg_lower:
        extra_failures.append(FailureType(
            code="synthesis_failed",
            severity="warning",
            confidence=0.7,
            evidence=["合成未成功"],
            fix_suggestions=[
                "提高烧结温度(>助熔剂熔点)",
                "延长保温时间(>2x)",
                "改用球磨 + 放电等离子烧结(SPS)",
                "通保护气(Ar/N2 防氧化)",
            ],
        ))

    if "能量异常" in user_intent or "energy" in msg_lower and "high" in msg_lower:
        extra_failures.append(FailureType(
            code="energy_anomaly",
            severity="critical",
            confidence=0.8,
            evidence=["形成能/弛豫能异常高"],
            fix_suggestions=[
                "复核 mat-gen:元素比例是否合理",
                "检查 mat-sim:弛豫步数 / 力阈值",
                "考虑换 CHGNet → M3GNet / PaiNN 重跑",
            ],
        ))

    if extra_failures:
        verdict.failures.extend(extra_failures)

    return verdict


__all__ = [
    "CriticScore",
    "CrossRobotScore",
    "CriticVerdict",
    "FailureType",
    "evaluate_candidates",
    "evaluate_chemist_report",  # W30 NEW
    "explain_failure",
    "score_l1_physical",
    "score_l2_synthesis",
    "score_l3_safety",
    # W30 NEW 常量
    "WEIGHT_L1_PHYSICAL",
    "WEIGHT_L2_SYNTHESIS",
    "WEIGHT_L3_SAFETY",
    "WEIGHT_L4_CROSS_ROBOT",
    "FAIL_XRD_PHASE_MISMATCH",
    "FAIL_EDS_EXTRA_ELEMENTS",
    "FAIL_DSC_CLASS_MISMATCH",
    "FAIL_CROSS_ROBOT_INCONSISTENCY",
    "FAIL_DATA_CONSISTENCY_LOW",
    "RULE_R1_XRD_PHASE",
    "RULE_R2_EDS_ELEMENTS",
    "RULE_R3_DSC_CLASS",
    "RULE_R4_COST_SANITY",
    "RULE_R5_XRD_PEAK_COUNT",
]