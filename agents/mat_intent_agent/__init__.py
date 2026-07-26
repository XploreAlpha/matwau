"""mat-intent-agent — 材料科学意图翻译官

业务层意图解析(per WauProject 拍板):
- wau-intent(平台层):用户想干啥 → 路由到哪个 WAU 能力
- mat-intent(业务层):材料任务具体干啥 → 调 mat-lit/gen/sim/exp

5 个子类:
- design_new_material
- optimize_existing
- explain_failure
- literature_review
- experiment_planning

3 个 skill:
- material_system(锂电/固态电解质/催化剂/...)
- target_props(能量密度>500Wh/kg, ...)
- constraints(元素/禁止/数量/...)

Stage 1 mock 用关键词 + 规则,Stage 2 接真 LLM

W37.9 v1.1.1-Academic: re-export MatIntentAgent + create_default_agent for
`from agents.mat_intent_agent import MatIntentAgent` style imports
(W1 demo + 学院方教学演示 import 路径).
"""
from .mat_intent_agent import MatIntentAgent, create_default_agent

__all__ = ["MatIntentAgent", "create_default_agent"]