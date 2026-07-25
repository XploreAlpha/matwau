"""mat-critic-agent — 材料科学 3 路交叉验证员

替换 mat-orchestrator explain_failure workflow 的 StubAgent(per W12 拍板)。

3 路打分:
- L1 物理一致性(0.4 权重):形成能 + 弛豫能 + forces_max 收敛
- L2 实验可行性(0.4 权重):元素可得性 + 烧结温度
- L3 安全规则(0.2 权重):用户禁元素 + 放射性 + 高毒

verdict 阈值:
- >= 0.7 → pass
- 0.5-0.7 → warn
- < 0.5 → fail

Stage 1: 纯规则引擎
Stage 2: 接 LLM 复核

per MatWAU-开发计划 §七 W12
"""
from .critic_engine import (
    CriticScore,
    CriticVerdict,
    FailureType,
    evaluate_candidates,
    explain_failure,
    score_l1_physical,
    score_l2_synthesis,
    score_l3_safety,
)
from .mat_critic_agent import (
    MatCriticAgent,
    CriticOutput,
    create_default_agent,
)

__all__ = [
    "MatCriticAgent",
    "CriticOutput",
    "create_default_agent",
    "CriticScore",
    "CriticVerdict",
    "FailureType",
    "evaluate_candidates",
    "explain_failure",
    "score_l1_physical",
    "score_l2_synthesis",
    "score_l3_safety",
]