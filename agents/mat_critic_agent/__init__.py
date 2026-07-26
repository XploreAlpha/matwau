"""mat-critic-agent — 材料科学 3 路交叉验证员 + W30 跨机器人一致性 + W33 LLM 复核

替换 mat-orchestrator explain_failure workflow 的 StubAgent(per W12 拍板)。

打分(per W30):
- L1 物理一致性(0.3 权重):形成能 + 弛豫能 + forces_max 收敛
- L2 实验可行性(0.3 权重):元素可得性 + 烧结温度
- L3 安全规则(0.2 权重):用户禁元素 + 放射性 + 高毒
- L4 跨机器人一致性(0.2 权重,W30 NEW):ChemistReport 4 robot 结果交叉验证
  - R1 XRD matched_phase vs synth.product_formula
  - R2 EDS 元素 ⊆ synth 化学式
  - R3 DSC Tg/Tm 类一致
  - R4 cost-per-gram sanity
  - R5 XRD peak count 与结晶性

verdict 阈值:
- >= 0.7 → pass
- 0.5-0.7 → warn
- < 0.5 → fail

Stage 1: 纯规则引擎
Stage 2(W33):接 LLM 复核 — `enable_llm_review=True` 启用

per MatWAU-开发计划 §七 W12 + W30 + W33
"""
from .critic_engine import (
    CriticScore,
    CriticVerdict,
    CrossRobotScore,                 # W30 NEW
    FailureType,
    evaluate_candidates,
    evaluate_chemist_report,         # W30 NEW
    explain_failure,
    score_l1_physical,
    score_l2_synthesis,
    score_l3_safety,
    # W30 NEW 常量
    WEIGHT_L1_PHYSICAL,
    WEIGHT_L2_SYNTHESIS,
    WEIGHT_L3_SAFETY,
    WEIGHT_L4_CROSS_ROBOT,
    FAIL_XRD_PHASE_MISMATCH,
    FAIL_EDS_EXTRA_ELEMENTS,
    FAIL_DSC_CLASS_MISMATCH,
    FAIL_CROSS_ROBOT_INCONSISTENCY,
    FAIL_DATA_CONSISTENCY_LOW,
    RULE_R1_XRD_PHASE,
    RULE_R2_EDS_ELEMENTS,
    RULE_R3_DSC_CLASS,
    RULE_R4_COST_SANITY,
    RULE_R5_XRD_PEAK_COUNT,
)
from .cross_robot import (            # W30 NEW
    RobotEvidence,
    CrossRobotResult,
    CrossRobotConsistencyGuard,
    build_robot_evidence_list,
    evaluate_cross_robot,
    rule_xrd_phase_in_synth_product,
    rule_eds_elements_subset_of_synth,
    rule_dsc_class_matches_synth,
    rule_synth_cost_per_gram,
    rule_xrd_peak_count_for_crystallinity,
)
from .cross_robot_phase_library import (  # W30 NEW
    PHASE_ELEMENT_MAP,
    parse_formula_elements,
    match_phase_name,
    list_known_phases,
)
from .llm_reviewer import (           # W33 NEW
    LLMReviewer,
    LLMReviewResult,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    get_default_reviewer,
    reset_global_reviewer,
)
from .mat_critic_agent import (
    MatCriticAgent,
    CriticOutput,
    create_default_agent,
)

__all__ = [
    # Agent
    "MatCriticAgent",
    "CriticOutput",
    "create_default_agent",
    # Engine
    "CriticScore",
    "CrossRobotScore",
    "CriticVerdict",
    "FailureType",
    "evaluate_candidates",
    "evaluate_chemist_report",
    "explain_failure",
    "score_l1_physical",
    "score_l2_synthesis",
    "score_l3_safety",
    # W30 cross-robot
    "RobotEvidence",
    "CrossRobotResult",
    "CrossRobotConsistencyGuard",
    "build_robot_evidence_list",
    "evaluate_cross_robot",
    "rule_xrd_phase_in_synth_product",
    "rule_eds_elements_subset_of_synth",
    "rule_dsc_class_matches_synth",
    "rule_synth_cost_per_gram",
    "rule_xrd_peak_count_for_crystallinity",
    "PHASE_ELEMENT_MAP",
    "parse_formula_elements",
    "match_phase_name",
    "list_known_phases",
    # W30 常量
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
    # W33 LLM 复核
    "LLMReviewer",
    "LLMReviewResult",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "get_default_reviewer",
    "reset_global_reviewer",
]