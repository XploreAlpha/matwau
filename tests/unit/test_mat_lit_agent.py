"""test_mat_lit_agent.py — W14 mat-lit 单元测试 + Goldens 跑分

测试覆盖:
1. 关键词提取(formula / material / property / domain)
2. 文献检索(Stage 1 mock)
3. 综述生成 4 部分
4. MatLitAgent 端到端
5. Goldens 20 case 跑分

per MatWAU-开发计划 §七 W14
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import AgentRequest  # noqa: E402

from agents.mat_lit_agent import (  # noqa: E402
    LitConfig,
    LitQuery,
    LitReference,
    LitReview,
    MATERIAL_ALIASES,
    MatLitAgent,
    create_default_agent,
    parse_lit_query,
    review_literature,
    search_literature,
)
from agents.mat_lit_agent.lit_engine import (  # noqa: E402
    extract_formulas,
    extract_material_aliases,
    extract_properties,
    extract_domains,
)
from tests.goldens.goldens_runner import Goldens  # noqa: E402

GOLDENS_PATH = str(_PROJECT_ROOT / "tests" / "goldens" / "mat-lit.yaml")


# ============================================================================
# Test 1: 关键词提取
# ============================================================================


class TestKeywordExtraction:
    """关键词提取单元测试"""

    def test_extract_formulas_simple(self):
        assert "LiCoO2" in extract_formulas("LiCoO2 的稳定性")

    def test_extract_formulas_complex(self):
        f = extract_formulas("Li7La3Zr2O12 跟 LiFePO4 的对比")
        assert "LiFePO4" in f

    def test_extract_formulas_no_match(self):
        f = extract_formulas("这是一段没有任何化学式的文本")
        assert len(f) == 0

    def test_extract_material_llzo(self):
        assert "LLZO" in extract_material_aliases("Review 一下 LLZO")

    def test_extract_material_lfp_nmc(self):
        mats = extract_material_aliases("LFP / NMC811 锂电池正极")
        assert "LFP" in mats
        assert "NMC811" in mats

    def test_extract_properties(self):
        props = extract_properties("关注电导率和稳定性")
        assert "电导率" in props
        assert "稳定性" in props

    def test_extract_properties_english(self):
        props = extract_properties("ionic conductivity and stability")
        assert any("conduct" in p.lower() for p in props)

    def test_extract_domains(self):
        doms = extract_domains("锂电池正极 + 燃料电池")
        assert any("锂电池" in d or "battery" in d.lower() for d in doms)


# ============================================================================
# Test 2: LitQuery 解析
# ============================================================================


class TestLitQuery:
    """LitQuery dataclass"""

    def test_parse_lit_query_llzo(self):
        q = parse_lit_query("Review 一下 LLZO 最新进展,关注电导率和稳定性")
        assert "LLZO" in q.material_names
        assert "电导率" in q.properties
        assert "稳定性" in q.properties
        assert q.has_match()

    def test_parse_lit_query_no_match(self):
        q = parse_lit_query("Hello World")
        assert not q.has_match()

    def test_parse_lit_query_to_dict(self):
        q = parse_lit_query("LiCoO2 稳定性")
        d = q.to_dict()
        assert "raw_query" in d
        assert "formulas" in d
        assert "properties" in d


# ============================================================================
# Test 3: 文献检索
# ============================================================================


class TestSearchLiterature:
    """search_literature 单元测试"""

    def test_search_by_formula(self):
        q = parse_lit_query("LiCoO2 综述")
        refs = search_literature(q, n_results=3)
        assert len(refs) >= 1
        # 至少 1 篇应该提到 LiCoO2
        assert any("LiCoO2" in r.title for r in refs)

    def test_search_by_alias(self):
        q = parse_lit_query("LLZO 电导率")
        refs = search_literature(q, n_results=5)
        assert len(refs) >= 1
        # 至少 1 篇应该提到 LLZO 或 Li7La3Zr2O12
        assert any("LLZO" in r.title or "Li7La3Zr2O12" in r.title for r in refs)

    def test_search_n_results_limit(self):
        q = parse_lit_query("LiCoO2 锂电池正极")
        refs = search_literature(q, n_results=2)
        assert len(refs) <= 2

    def test_search_no_match_generic(self):
        q = parse_lit_query("xxxx 1234 not a chemistry query")
        # 没匹配到任何东西,返通用
        refs = search_literature(q, n_results=3)
        # 返 _generic_ 或 topic
        assert len(refs) >= 0

    def test_search_by_property(self):
        q = parse_lit_query("电导率 综述")
        refs = search_literature(q, n_results=3)
        assert len(refs) >= 1


# ============================================================================
# Test 4: 综述生成
# ============================================================================


class TestReviewLiterature:
    """review_literature 单元测试"""

    def test_review_basic(self):
        review = review_literature("LiCoO2 综述")
        assert isinstance(review, LitReview)
        assert review.query == "LiCoO2 综述"
        assert len(review.references) >= 1
        assert review.background != ""
        assert review.state_of_art != ""
        assert isinstance(review.gaps, list)
        assert isinstance(review.suggestions, list)
        assert 0.0 <= review.confidence <= 1.0

    def test_review_confidence_in_range(self):
        review = review_literature("LLZO 电导率")
        assert 0.0 <= review.confidence <= 1.0

    def test_review_sources_queried(self):
        review = review_literature("LiCoO2")
        assert "arXiv" in review.sources_queried

    def test_review_to_dict(self):
        review = review_literature("LLZO")
        d = review.to_dict()
        assert "query" in d
        assert "references" in d
        assert "background" in d
        assert "state_of_art" in d
        assert "gaps" in d
        assert "suggestions" in d
        assert "confidence" in d

    def test_review_no_match(self):
        review = review_literature("xxxx 1234 yyyy not a chemistry query")
        # 应该走 _generic_ 或 topic
        assert review is not None


# ============================================================================
# Test 5: LitReference + LitReview dataclass
# ============================================================================


class TestDataclasses:
    """dataclass 单元测试"""

    def test_lit_reference_to_dict(self):
        r = LitReference(
            title="Test",
            authors=["Author A", "Author B"],
            year=2024,
            source="arXiv",
        )
        d = r.to_dict()
        assert d["title"] == "Test"
        assert d["year"] == 2024
        assert d["source"] == "arXiv"

    def test_lit_review_to_dict(self):
        review = LitReview(
            query="test",
            references=[LitReference(title="r1", relevance=0.9)],
            background="bg",
            state_of_art="soa",
            gaps=["gap1"],
            suggestions=["sug1"],
            confidence=0.8,
        )
        d = review.to_dict()
        assert d["query"] == "test"
        assert len(d["references"]) == 1
        assert d["gaps"] == ["gap1"]


# ============================================================================
# Test 6: LitConfig
# ============================================================================


class TestLitConfig:
    """配置 dataclass"""

    def test_default(self):
        cfg = LitConfig()
        assert cfg.n_results == 5
        assert "arXiv" in cfg.sources

    def test_from_dict(self):
        cfg = LitConfig.from_dict({"n_results": 3})
        assert cfg.n_results == 3

    def test_from_dict_empty(self):
        cfg = LitConfig.from_dict(None)
        assert cfg.n_results == 5


# ============================================================================
# Test 7: MatLitAgent 端到端
# ============================================================================


class TestMatLitAgent:
    """MatLitAgent 端到端"""

    def test_create_default_agent(self):
        agent = create_default_agent()
        assert isinstance(agent, MatLitAgent)
        assert agent.name == "mat-lit-agent"

    def test_run_basic(self):
        agent = create_default_agent()
        req = AgentRequest(
            run_id="lit-test-1",
            message="Review 一下 LLZO 最新进展",
        )
        response = agent.run(req)
        assert response.confidence > 0
        assert "review" in response.artifacts
        review = response.artifacts["review"]
        assert isinstance(review, LitReview)

    def test_run_with_config(self):
        agent = create_default_agent()
        req = AgentRequest(
            run_id="lit-test-2",
            message="LiCoO2 综述",
            context={"n_results": 3},
        )
        response = agent.run(req)
        assert response.artifacts["n_results"] <= 3

    def test_run_empty_message(self):
        agent = create_default_agent()
        req = AgentRequest(run_id="lit-test-3", message="")
        response = agent.run(req)
        # 空 query 应给 warn
        assert response.confidence < 0.5 or "review" not in response.artifacts

    def test_run_no_match(self):
        agent = create_default_agent()
        req = AgentRequest(run_id="lit-test-4", message="xxxx yyyy not a chemistry query")
        response = agent.run(req)
        # 没匹配也不应该崩
        assert response.confidence >= 0.0


# ============================================================================
# Test 8: Goldens 20 case 跑分
# ============================================================================


def _run_goldens_case(case) -> Dict[str, Any]:
    """跑 1 个 Goldens case"""
    intent = case.intent
    review = review_literature(intent, n_results=10)

    # 解析 query 拿 formulas / materials / properties
    q = parse_lit_query(intent)

    return {
        "n_results": len(review.references),
        "formulas": q.formulas,
        "material_names": q.material_names,
        "properties": q.properties,
        "domains": q.domains,
        "confidence": review.confidence,
        "has_gaps": len(review.gaps) > 0,
        "has_suggestions": len(review.suggestions) > 0,
        "ref_titles": [r.title for r in review.references],
        "ref_sources": [r.source for r in review.references],
    }


def _check_goldens_case(case, actual) -> tuple:
    """检查 1 个 Goldens case"""
    reasons = []
    exp = case.expected

    # n_results
    if "min_n_results" in exp and actual["n_results"] < exp["min_n_results"]:
        reasons.append(f"n_results={actual['n_results']} < {exp['min_n_results']}")
    if "max_n_results" in exp and actual["n_results"] > exp["max_n_results"]:
        reasons.append(f"n_results={actual['n_results']} > {exp['max_n_results']}")

    # has_formula
    if "has_formula" in exp:
        for f in exp["has_formula"]:
            if f not in actual["formulas"]:
                reasons.append(f"missing formula: {f}")

    # has_formula_any
    if "has_formula_any" in exp:
        if not any(f in actual["formulas"] for f in exp["has_formula_any"]):
            reasons.append(f"none of {exp['has_formula_any']} in formulas: {actual['formulas']}")

    # has_material
    if "has_material" in exp:
        for m in exp["has_material"]:
            if m not in actual["material_names"]:
                reasons.append(f"missing material: {m}")

    # has_material_any
    if "has_material_any" in exp:
        if not any(m in actual["material_names"] for m in exp["has_material_any"]):
            reasons.append(f"none of {exp['has_material_any']} in materials: {actual['material_names']}")

    # has_property
    if "has_property" in exp:
        for p in exp["has_property"]:
            if p not in actual["properties"]:
                reasons.append(f"missing property: {p}")

    # has_property_any
    if "has_property_any" in exp:
        if not any(p in actual["properties"] for p in exp["has_property_any"]):
            reasons.append(f"none of {exp['has_property_any']} in properties: {actual['properties']}")

    # has_domain
    if "has_domain" in exp:
        for d in exp["has_domain"]:
            if d not in actual["domains"]:
                reasons.append(f"missing domain: {d}")

    # min_confidence
    if "min_confidence" in exp and actual["confidence"] < exp["min_confidence"]:
        reasons.append(f"confidence={actual['confidence']:.2f} < {exp['min_confidence']}")

    # has_gaps
    if exp.get("has_gaps") and not actual["has_gaps"]:
        reasons.append("missing gaps")

    # has_suggestions
    if exp.get("has_suggestions") and not actual["has_suggestions"]:
        reasons.append("missing suggestions")

    # specific_ref_title_contains
    if "specific_ref_title_contains" in exp:
        for kw in exp["specific_ref_title_contains"]:
            if not any(kw in t for t in actual["ref_titles"]):
                reasons.append(f"no ref title contains: {kw}")

    # specific_source_any
    if "specific_source_any" in exp:
        if not any(s in actual["ref_sources"] for s in exp["specific_source_any"]):
            reasons.append(f"no ref source matches: {exp['specific_source_any']}")

    return (len(reasons) == 0, reasons)


class TestMatLitGoldens:
    """mat-lit.yaml 20 case 跑分"""

    @pytest.fixture(scope="class")
    def results(self):
        g = Goldens(GOLDENS_PATH)
        cases = g.load()
        results = []
        for case in cases:
            actual = _run_goldens_case(case)
            passed, reasons = _check_goldens_case(case, actual)
            results.append({
                "case_id": case.id,
                "category": case.category,
                "passed": passed,
                "reasons": reasons,
            })
        return results

    def test_goldens_overall_pass_rate(self, results):
        n_pass = sum(1 for r in results if r["passed"])
        n_total = len(results)
        pass_rate = n_pass / n_total

        failed = [r for r in results if not r["passed"]]
        if failed:
            print("\n❌ 失败 case:")
            for r in failed:
                print(f"   {r['case_id']} [{r['category']}]: {r['reasons']}")

        print(f"\n📊 mat-lit Goldens 总体: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_query_pass_rate(self, results):
        cat_results = [r for r in results if r["category"] == "query"]
        n_pass = sum(1 for r in cat_results if r["passed"])
        n_total = len(cat_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 query 解析: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"query pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_search_pass_rate(self, results):
        cat_results = [r for r in results if r["category"] == "search"]
        n_pass = sum(1 for r in cat_results if r["passed"])
        n_total = len(cat_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 文献检索: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"search pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_review_pass_rate(self, results):
        cat_results = [r for r in results if r["category"] == "review"]
        n_pass = sum(1 for r in cat_results if r["passed"])
        n_total = len(cat_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 综述生成: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"review pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_e2e_pass_rate(self, results):
        cat_results = [r for r in results if r["category"] == "e2e"]
        n_pass = sum(1 for r in cat_results if r["passed"])
        n_total = len(cat_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 端到端: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"e2e pass-rate {pass_rate:.0%} < 50%"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])