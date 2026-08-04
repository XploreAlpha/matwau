"""test_mat_intent_agent.py — W9 mat-intent-agent 单元测试 + Goldens 跑分

测试覆盖:
1. intent_classifier 单元测试
   - classify_subclass: 5 子类
   - identify_material_system: 11 material_system
   - identify_target_props: 8 target_props
   - extract_elements / extract_forbidden / extract_n_samples
   - parse_mat_intent: 整体解析
2. MatIntentAgent 单元测试
   - act() 解析 + 包装
   - 注入默认 harness
   - SafetyGuard 拦截
3. mat-intent.yaml Goldens 30 case 跑分
4. 与 MatPipeline 集成(端到端)

per MatWAU-开发计划 §六 W9
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import AgentRequest, AgentResponse  # noqa: E402
from matwau.pipeline import MatPipeline, create_default_pipeline  # noqa: E402

from agents.mat_intent_agent.intent_classifier import (  # noqa: E402
    SUBCLASSES,
    MATERIAL_SYSTEMS,
    TARGET_PROPS,
    MatIntent,
    classify_subclass,
    identify_material_system,
    identify_target_props,
    extract_elements,
    extract_forbidden,
    extract_n_samples,
    parse_mat_intent,
)
from agents.mat_intent_agent.mat_intent_agent import (  # noqa: E402
    MatIntentAgent,
    create_default_agent,
)
from tests.goldens.goldens_runner import Goldens  # noqa: E402

GOLDENS_PATH = str(_PROJECT_ROOT / "tests" / "goldens" / "mat-intent.yaml")


# ============================================================================
# 测试 1: constants 定义
# ============================================================================


class TestIntentConstants:
    """常量定义测试"""

    def test_subclasses_7(self):
        """5 + M3 2 个 = 7 子类"""
        assert len(SUBCLASSES) == 7
        assert "experiment_planning" in SUBCLASSES
        assert "design_new_material" in SUBCLASSES
        # M3 NEW
        assert "external_db_query" in SUBCLASSES
        assert "cross_source_validation" in SUBCLASSES

    def test_material_systems_11(self):
        """11 material_system"""
        assert len(MATERIAL_SYSTEMS) == 11
        assert "li_ion_cathode" in MATERIAL_SYSTEMS
        assert "solid_electrolyte" in MATERIAL_SYSTEMS

    def test_target_props_8(self):
        """8 target_props"""
        assert len(TARGET_PROPS) == 8
        assert "energy_density" in TARGET_PROPS
        assert "ionic_conductivity" in TARGET_PROPS


# ============================================================================
# 测试 2: classify_subclass
# ============================================================================


class TestClassifySubclass:
    """5 子类分类测试"""

    def test_experiment_planning_chinese(self):
        """中文:实验方案 → experiment_planning"""
        sub, conf, _ = classify_subclass("出 LiCoO2 实验方案")
        assert sub == "experiment_planning"
        assert conf >= 0.7

    def test_design_new_material_chinese(self):
        """中文:设计新 → design_new_material"""
        sub, conf, _ = classify_subclass("设计新型固态电解质")
        assert sub == "design_new_material"
        assert conf >= 0.7

    def test_optimize_existing_chinese(self):
        """中文:优化 → optimize_existing"""
        sub, conf, _ = classify_subclass("优化 LiCoO2 配方")
        assert sub == "optimize_existing"
        assert conf >= 0.7

    def test_explain_failure_chinese(self):
        """中文:为什么 → explain_failure"""
        sub, conf, _ = classify_subclass("为什么 XRD 谱不对")
        assert sub == "explain_failure"
        assert conf >= 0.7

    def test_literature_review_chinese(self):
        """中文:文献 → literature_review"""
        sub, conf, _ = classify_subclass("LLZO 最新文献综述")
        assert sub == "literature_review"
        assert conf >= 0.7

    def test_design_english(self):
        """英文:design new → design_new_material"""
        sub, conf, _ = classify_subclass("design new lithium battery cathode")
        assert sub == "design_new_material"

    def test_fallback(self):
        """fallback 默认 experiment_planning"""
        sub, conf, _ = classify_subclass("我想做个材料")
        assert sub == "experiment_planning"
        assert conf == 0.5


# ============================================================================
# 测试 3: identify_material_system
# ============================================================================


class TestIdentifyMaterialSystem:
    """11 material_system 识别测试"""

    def test_li_ion_cathode(self):
        assert identify_material_system("锂电池正极") == "li_ion_cathode"
        assert identify_material_system("NMC811 cathode") == "li_ion_cathode"

    def test_solid_electrolyte(self):
        assert identify_material_system("固态电解质") == "solid_electrolyte"
        assert identify_material_system("LLZO solid electrolyte") == "solid_electrolyte"

    def test_catalyst_her(self):
        assert identify_material_system("析氢催化剂") == "catalyst_her"
        assert identify_material_system("HER catalyst") == "catalyst_her"

    def test_catalyst_oer(self):
        assert identify_material_system("析氧催化剂") == "catalyst_oer"
        assert identify_material_system("OER catalyst") == "catalyst_oer"

    def test_solar_cell(self):
        assert identify_material_system("钙钛矿太阳能") == "solar_cell"
        assert identify_material_system("perovskite solar cell") == "solar_cell"

    def test_superconductor(self):
        assert identify_material_system("YBCO 高温超导") == "superconductor"

    def test_thermoelectric(self):
        assert identify_material_system("Bi2Te3 热电材料") == "thermoelectric"

    def test_permanent_magnet(self):
        assert identify_material_system("Nd2Fe14B 永磁") == "permanent_magnet"

    def test_semiconductor(self):
        assert identify_material_system("GaN 半导体") == "semiconductor"

    def test_hydrogen_storage(self):
        assert identify_material_system("MgH2 储氢") == "hydrogen_storage"

    def test_none(self):
        """未识别返回 None"""
        assert identify_material_system("") is None
        assert identify_material_system("xyz") is None


# ============================================================================
# 测试 4: identify_target_props
# ============================================================================


class TestIdentifyTargetProps:
    """8 target_props 识别测试"""

    def test_energy_density(self):
        assert "energy_density" in identify_target_props("能量密度 > 500 Wh/kg")

    def test_ionic_conductivity(self):
        assert "ionic_conductivity" in identify_target_props("电导率 > 1 mS/cm")

    def test_voltage(self):
        assert "voltage" in identify_target_props("高电压")

    def test_capacity(self):
        assert "capacity" in identify_target_props("高容量 200 mAh/g")

    def test_stability(self):
        assert "stability" in identify_target_props("高循环寿命")

    def test_band_gap(self):
        assert "band_gap" in identify_target_props("带隙 1.5 eV")

    def test_multiple_props(self):
        """多属性同时识别"""
        props = identify_target_props("能量密度 > 500 Wh/kg, 电导率 > 1 mS/cm")
        assert "energy_density" in props
        assert "ionic_conductivity" in props


# ============================================================================
# 测试 5: extract_elements / forbidden / n_samples
# ============================================================================


class TestConstraints:
    """constraints 提取测试"""

    def test_extract_elements_basic(self):
        """基本元素提取"""
        assert "Li" in extract_elements("出 LiCoO2")
        assert "Co" in extract_elements("出 LiCoO2")
        assert "O" in extract_elements("出 LiCoO2")

    def test_extract_elements_bi_te(self):
        """Bi/Te 双字符"""
        elems = extract_elements("出 Bi2Te3")
        assert "Bi" in elems
        assert "Te" in elems

    def test_extract_elements_excludes_wh(self):
        """Wh/kg 单位不抽 W"""
        elems = extract_elements("能量密度 > 500 Wh/kg")
        assert "W" not in elems

    def test_extract_forbidden_keyword(self):
        """无钴 → Co"""
        f = extract_forbidden("无钴锂电池正极")
        assert "Co" in f

    def test_extract_forbidden_explicit(self):
        """禁止: X、Y"""
        f = extract_forbidden("禁止: Co、Mn")
        assert "Co" in f
        assert "Mn" in f

    def test_extract_forbidden_precious(self):
        """无贵金属"""
        f = extract_forbidden("无贵金属固态电解质")
        assert "Pt" in f
        assert "Au" in f
        assert "Ag" in f

    def test_extract_n_samples(self):
        """n_samples 提取"""
        assert extract_n_samples("生成 10 个候选") == 10
        assert extract_n_samples("生成 5 个") == 5
        assert extract_n_samples("默认") == 5  # 默认


# ============================================================================
# 测试 6: parse_mat_intent 整合
# ============================================================================


class TestParseMatIntent:
    """parse_mat_intent 整体解析测试"""

    def test_li_ion_cathode(self):
        """锂电池正极完整解析"""
        intent = parse_mat_intent("出无钴锂电池正极实验方案,能量密度 > 500 Wh/kg")
        assert intent.subclass == "experiment_planning"
        assert intent.material_system == "li_ion_cathode"
        assert "energy_density" in intent.target_props
        assert "Co" in intent.forbidden

    def test_solid_electrolyte(self):
        """固态电解质完整解析"""
        intent = parse_mat_intent("出 LLZO 固态电解质实验方案,无贵金属")
        assert intent.subclass == "experiment_planning"
        assert intent.material_system == "solid_electrolyte"
        assert "Pt" in intent.forbidden
        assert "Au" in intent.forbidden

    def test_thermoelectric_bi_te(self):
        """热电材料 Bi/Te 解析"""
        intent = parse_mat_intent("出 Bi2Te3 热电材料实验方案")
        assert intent.subclass == "experiment_planning"
        assert intent.material_system == "thermoelectric"
        assert "Bi" in intent.elements
        assert "Te" in intent.elements

    def test_optimize_existing_with_props(self):
        """优化 + 性能提升"""
        intent = parse_mat_intent("优化 LiCoO2 配方,提高循环寿命")
        assert intent.subclass == "optimize_existing"
        assert "stability" in intent.target_props

    def test_confidence_reasonable(self):
        """confidence 合理(0.5-0.99)"""
        intent = parse_mat_intent("出 LiCoO2 实验方案")
        assert 0.5 <= intent.confidence <= 0.99


# ============================================================================
# 测试 7: MatIntentAgent.act()
# ============================================================================


class TestMatIntentAgent:
    """MatIntentAgent 主体测试"""

    def test_create_default_agent(self):
        """默认 agent 创建"""
        a = create_default_agent()
        assert isinstance(a, MatIntentAgent)
        assert a.name == "mat-intent-agent"
        assert a.default_downstream == "mat-pipeline"

    def test_act_basic(self):
        """act() 基本工作"""
        a = create_default_agent()
        req = AgentRequest(run_id="t1", message="出 LiCoO2 实验方案")
        r = a.run(req)
        assert r.reply
        assert r.artifacts["mat_intent"] is not None
        assert r.artifacts["subclass"] == "experiment_planning"
        assert r.artifacts["material_system"] == "li_ion_cathode"
        assert r.artifacts["downstream_agent"] == "mat-pipeline"

    def test_act_returns_mat_intent(self):
        """act() 返回 MatIntent"""
        a = create_default_agent()
        req = AgentRequest(run_id="t2", message="设计新型锂电池正极")
        r = a.run(req)
        mi = r.artifacts["mat_intent"]
        assert isinstance(mi, MatIntent)
        assert mi.subclass == "design_new_material"

    def test_act_empty_message(self):
        """空 message 不崩"""
        a = create_default_agent()
        req = AgentRequest(run_id="t3", message="")
        r = a.run(req)
        assert "⚠️" in r.reply or "空" in r.reply

    def test_custom_downstream(self):
        """自定义下游 agent"""
        a = MatIntentAgent(default_downstream="mat-orchestrator")
        req = AgentRequest(run_id="t4", message="出 LiCoO2 实验方案")
        r = a.run(req)
        assert r.artifacts["downstream_agent"] == "mat-orchestrator"


# ============================================================================
# 测试 8: mat-intent.yaml Goldens 跑分
# ============================================================================


def _check_goldens_case(intent: MatIntent, expected: dict) -> tuple[bool, list[str]]:
    """检查 1 个 Goldens case 是否通过"""
    reasons = []

    if "subclass" in expected:
        if intent.subclass != expected["subclass"]:
            reasons.append(f"subclass={intent.subclass} (期望 {expected['subclass']})")

    if "material_system" in expected:
        if intent.material_system != expected["material_system"]:
            reasons.append(
                f"material_system={intent.material_system} (期望 {expected['material_system']})"
            )

    if "target_props" in expected:
        for p in expected["target_props"]:
            if p not in intent.target_props:
                reasons.append(f"target_props 缺 {p}")

    if "elements" in expected:
        for e in expected["elements"]:
            if e not in intent.elements:
                reasons.append(f"elements 缺 {e}")

    if "elements_any" in expected:
        # 至少 expected 列表里出现 1 个
        if not any(e in intent.elements for e in expected["elements_any"]):
            reasons.append(
                f"elements_any={expected['elements_any']} 一个都不在 intent.elements={intent.elements}"
            )

    if "forbidden" in expected:
        for f in expected["forbidden"]:
            if f not in intent.forbidden:
                reasons.append(f"forbidden 缺 {f}")

    if "forbidden_any" in expected:
        # 至少 expected 列表里出现 1 个
        if not any(f in intent.forbidden for f in expected["forbidden_any"]):
            reasons.append(
                f"forbidden_any={expected['forbidden_any']} 一个都不在 intent.forbidden={intent.forbidden}"
            )

    if "n_samples" in expected:
        if intent.n_samples != expected["n_samples"]:
            reasons.append(f"n_samples={intent.n_samples} (期望 {expected['n_samples']})")

    return (len(reasons) == 0, reasons)


class TestMatIntentGoldens:
    """mat-intent.yaml 30 case 跑分"""

    @pytest.fixture(scope="class")
    def results(self):
        """跑全部 30 case 的结果"""
        g = Goldens(GOLDENS_PATH)
        cases = g.load()
        results = []
        for case in cases:
            intent = parse_mat_intent(case.intent)
            passed, reasons = _check_goldens_case(intent, case.expected)
            results.append(
                {
                    "case_id": case.id,
                    "category": case.category,
                    "passed": passed,
                    "reasons": reasons,
                    "intent": intent.to_dict(),
                }
            )
        return results

    def test_goldens_30_cases_pass_rate(self, results):
        """30 case pass-rate > 50%"""
        n_pass = sum(1 for r in results if r["passed"])
        n_total = len(results)
        pass_rate = n_pass / n_total

        print(f"\n📊 mat-intent Goldens: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_classify_pass_rate(self, results):
        """子分类 10 case pass-rate > 60%"""
        sub_results = [r for r in results if r["category"] == "classify"]
        n_pass = sum(1 for r in sub_results if r["passed"])
        n_total = len(sub_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 子类分类: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.6, f"classify pass-rate {pass_rate:.0%} < 60%"

    def test_goldens_system_pass_rate(self, results):
        """material_system 10 case pass-rate > 60%"""
        sys_results = [r for r in results if r["category"] == "system"]
        n_pass = sum(1 for r in sys_results if r["passed"])
        n_total = len(sys_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 material_system: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.6, f"system pass-rate {pass_rate:.0%} < 60%"

    def test_goldens_constraints_pass_rate(self, results):
        """constraints 10 case pass-rate > 60%"""
        con_results = [r for r in results if r["category"] == "constraints"]
        n_pass = sum(1 for r in con_results if r["passed"])
        n_total = len(con_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 constraints: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.6, f"constraints pass-rate {pass_rate:.0%} < 60%"


# ============================================================================
# 测试 9: 与 MatPipeline 集成
# ============================================================================


class TestIntentPipelineIntegration:
    """mat-intent + mat-pipeline 集成测试"""

    def test_intent_then_pipeline(self):
        """mat-intent → mat-pipeline 端到端"""
        intent_agent = create_default_agent()
        pipeline = create_default_pipeline()

        # 1. mat-intent 解析
        req1 = AgentRequest(run_id="i1", message="出 LiCoO2 实验方案")
        r1 = intent_agent.run(req1)
        mi = r1.artifacts["mat_intent"]

        # 2. mat-pipeline 用解析结果跑
        r2 = pipeline.run_full_pipeline(
            user_intent="出 LiCoO2 实验方案",
            elements=mi.elements if mi.elements else ["Li", "Co", "O"],
            forbidden=mi.forbidden,
            n_samples=mi.n_samples,
        )

        assert r2.success
        assert len(r2.final_recipes) >= 1

    def test_intent_driven_pipeline_forbidden(self):
        """mat-intent 解析出 forbidden → mat-pipeline 守住"""
        intent_agent = create_default_agent()
        pipeline = create_default_pipeline()

        # "无 Co" 解析出 forbidden Co
        req1 = AgentRequest(run_id="i2", message="出无 Co 锂电池正极实验方案")
        r1 = intent_agent.run(req1)
        mi = r1.artifacts["mat_intent"]

        assert "Co" in mi.forbidden

        # mat-pipeline 用 forbidden 跑
        r2 = pipeline.run_full_pipeline(
            user_intent="出无 Co 锂电池正极实验方案",
            elements=mi.elements if mi.elements else ["Li", "Ni", "Mn", "O"],
            forbidden=mi.forbidden,
        )

        # 配方不应含 Co
        for recipe in r2.final_recipes:
            assert "Co" not in recipe.formula, f"配方含违禁 Co: {recipe.formula}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])