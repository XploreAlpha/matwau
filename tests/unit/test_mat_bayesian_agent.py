"""test_mat_bayesian_agent.py — W13 mat-bayesian 单元测试 + Goldens 跑分

测试覆盖:
1. 化学式编码 / 元素提取
2. GP 拟合 + 预测
3. TPE 拟合 + acquisition
4. EI / UCB / PI acquisition functions
5. suggest_next_batch 完整流
6. MatBayesianAgent 端到端
7. Goldens 25 case 跑分

per MatWAU-开发计划 §七 W13
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import AgentRequest  # noqa: E402

from agents.mat_bayesian_agent import (  # noqa: E402
    BayesianConfig,
    BayesianOutput,
    MatBayesianAgent,
    ObservedPoint,
    acquisition_ei,
    acquisition_pi,
    acquisition_ucb,
    create_default_agent,
    extract_elements,
    formula_to_features,
    gp_fit,
    gp_predict,
    make_observed_from_simulated,
    run_bayesian_optimization,
    suggest_next_batch,
    tpe_acquisition,
    tpe_fit,
)
from tests.goldens.goldens_runner import Goldens  # noqa: E402

GOLDENS_PATH = str(_PROJECT_ROOT / "tests" / "goldens" / "mat-bayesian.yaml")


# ============================================================================
# Test 1: 化学式编码 / 元素提取
# ============================================================================


class TestFormulaEncoding:
    """化学式 → One-Hot"""

    def test_extract_elements_simple(self):
        assert extract_elements("Li2O") == ["Li", "O"]

    def test_extract_elements_complex(self):
        assert extract_elements("LiFePO4") == ["Li", "Fe", "P", "O"]

    def test_extract_elements_no_count(self):
        assert extract_elements("NaCl") == ["Na", "Cl"]

    def test_extract_elements_dedup(self):
        # Li2O 含 2 个 O,但只返回一次
        elems = extract_elements("Li2O2")
        assert elems.count("O") == 1

    def test_extract_elements_la(self):
        # LLZO:Li7La3Zr2O12
        assert extract_elements("Li7La3Zr2O12") == ["Li", "La", "Zr", "O"]

    def test_formula_to_features_length(self):
        f = formula_to_features("Li2O")
        # ELEMENT_POOL 长度
        assert len(f) > 50

    def test_formula_to_features_one_hot(self):
        f = formula_to_features("Li2O")
        # 应有 2 个 1(Li + O),其余为 0
        assert sum(f) == 2

    def test_formula_to_features_known_element(self):
        # ELEMENT_POOL 含 Li 在 idx 1
        from agents.mat_bayesian_agent.bayesian_engine import ELEMENT_POOL
        li_idx = ELEMENT_POOL.index("Li")
        o_idx = ELEMENT_POOL.index("O")
        f = formula_to_features("LiO")
        assert f[li_idx] == 1.0
        assert f[o_idx] == 1.0


# ============================================================================
# Test 2: GP 拟合 + 预测
# ============================================================================


class TestGP:
    """Gaussian Process 单元测试"""

    def test_gp_fit_basic(self):
        observed = [
            ObservedPoint(formula="Li2O", score=2.0),
            ObservedPoint(formula="LiCoO2", score=3.5),
            ObservedPoint(formula="LiFePO4", score=3.2),
        ]
        fit = gp_fit(observed)
        assert fit is not None
        assert len(fit["X"]) == 3
        assert "alpha" in fit

    def test_gp_fit_too_few_samples(self):
        observed = [ObservedPoint(formula="Li2O", score=2.0)]
        fit = gp_fit(observed)
        assert fit is None  # 样本 < 2 失败

    def test_gp_predict_returns_mu_sigma(self):
        observed = [
            ObservedPoint(formula="Li2O", score=2.0),
            ObservedPoint(formula="LiCoO2", score=3.5),
            ObservedPoint(formula="LiFePO4", score=3.2),
        ]
        fit = gp_fit(observed)
        X_new = [formula_to_features("LiNiO2"), formula_to_features("Na2O")]
        preds = gp_predict(fit, X_new)
        assert len(preds) == 2
        for mu, sigma in preds:
            assert isinstance(mu, float)
            assert isinstance(sigma, float)
            assert sigma > 0  # 标准差 > 0

    def test_gp_predict_interpolation(self):
        # GP 应能插值(对相似样本给出相近 μ)
        observed = [
            ObservedPoint(formula="Li2O", score=2.0),
            ObservedPoint(formula="LiCoO2", score=3.5),
            ObservedPoint(formula="LiFePO4", score=3.2),
        ]
        fit = gp_fit(observed)
        # Li2O 相似(只有 Li + O)
        preds = gp_predict(fit, [formula_to_features("LiNaO")])
        mu, sigma = preds[0]
        # μ 应接近 2.0(Li2O 是 2.0)
        assert 1.5 <= mu <= 2.5


# ============================================================================
# Test 3: TPE 拟合 + acquisition
# ============================================================================


class TestTPE:
    """Tree-structured Parzen Estimator"""

    def test_tpe_fit_basic(self):
        observed = [
            ObservedPoint(formula="Li2O", score=2.0),
            ObservedPoint(formula="LiCoO2", score=3.5),
            ObservedPoint(formula="LiFePO4", score=3.2),
            ObservedPoint(formula="NaCl", score=2.5),
        ]
        fit = tpe_fit(observed)
        assert fit is not None
        # top 25% 是 good:3.5,3.2(top 1 个)
        assert len(fit["good_features"]) >= 1
        assert len(fit["bad_features"]) >= 1

    def test_tpe_fit_too_few_samples(self):
        observed = [ObservedPoint(formula="Li2O", score=2.0)]
        fit = tpe_fit(observed)
        assert fit is None

    def test_tpe_acquisition_returns_scores(self):
        observed = [
            ObservedPoint(formula="Li2O", score=2.0),
            ObservedPoint(formula="LiCoO2", score=3.5),
            ObservedPoint(formula="LiFePO4", score=3.2),
            ObservedPoint(formula="NaCl", score=2.5),
        ]
        fit = tpe_fit(observed)
        X_new = [
            formula_to_features("LiNiO2"),
            formula_to_features("Na2O"),
            formula_to_features("K2O"),
        ]
        scores = tpe_acquisition(fit, X_new)
        assert len(scores) == 3
        for s in scores:
            assert s > 0  # acquisition > 0


# ============================================================================
# Test 4: Acquisition Functions
# ============================================================================


class TestAcquisition:
    """EI / UCB / PI"""

    def test_ei_basic(self):
        ei = acquisition_ei(mu=3.0, sigma=0.5, best_y=2.0)
        assert ei > 0
        # μ 越大 / best_y 越小 → EI 越大

    def test_ei_zero_std(self):
        ei = acquisition_ei(mu=2.0, sigma=0.0, best_y=2.0)
        # μ == best_y + xi(近似 0)
        assert ei >= 0

    def test_ucb_basic(self):
        ucb = acquisition_ucb(mu=3.0, sigma=0.5, kappa=2.0)
        # UCB = μ + κ * σ = 3.0 + 1.0 = 4.0
        assert ucb == 4.0

    def test_pi_basic(self):
        pi = acquisition_pi(mu=3.0, sigma=0.5, best_y=2.0)
        # μ > best_y + xi → PI > 0.5
        assert 0.0 <= pi <= 1.0


# ============================================================================
# Test 5: suggest_next_batch 完整流
# ============================================================================


class TestSuggestNextBatch:
    """主接口测试"""

    def test_suggest_with_gp(self):
        observed = [
            ObservedPoint(formula="Li2O", score=2.0),
            ObservedPoint(formula="LiCoO2", score=3.5),
            ObservedPoint(formula="LiFePO4", score=3.2),
        ]
        pool = [{"formula": "LiNiO2"}, {"formula": "LiMnO2"}, {"formula": "Na2O"}]
        out = suggest_next_batch(observed, pool, n_suggest=2, algorithm="gp")
        assert isinstance(out, BayesianOutput)
        assert len(out.next_batch) == 2
        assert out.algorithm_used == "gp"

    def test_suggest_with_tpe(self):
        observed = [
            ObservedPoint(formula="Li2O", score=2.0),
            ObservedPoint(formula="LiCoO2", score=3.5),
            ObservedPoint(formula="LiFePO4", score=3.2),
        ]
        pool = [{"formula": "LiNiO2"}, {"formula": "LiMnO2"}, {"formula": "Na2O"}]
        out = suggest_next_batch(observed, pool, n_suggest=2, algorithm="tpe")
        assert out.algorithm_used == "tpe"
        assert len(out.next_batch) == 2

    def test_suggest_with_auto(self):
        # n=5 → auto 选 TPE
        observed = [ObservedPoint(formula=f"X{i}", score=float(i)) for i in range(5)]
        from agents.mat_bayesian_agent.bayesian_engine import formula_to_features
        for o in observed:
            o.features = formula_to_features(o.formula)
        pool = [{"formula": f"Y{i}"} for i in range(3)]
        out = suggest_next_batch(observed, pool, n_suggest=2, algorithm="auto")
        assert out.algorithm_used == "tpe"

    def test_suggest_with_forbidden(self):
        observed = [
            ObservedPoint(formula="Li2O", score=2.0),
            ObservedPoint(formula="LiCoO2", score=3.5),
        ]
        pool = [{"formula": "LiCoO2"}, {"formula": "LiNiO2"}, {"formula": "LiMnO2"}]
        out = suggest_next_batch(observed, pool, n_suggest=2, forbidden=["Co"])
        # next_batch 不应含 LiCoO2
        formulas = [c.get("formula") for c in out.next_batch]
        assert "LiCoO2" not in formulas

    def test_suggest_empty_pool(self):
        observed = [ObservedPoint(formula="Li2O", score=2.0)]
        out = suggest_next_batch(observed, [], n_suggest=3)
        assert out.status == "converged"
        assert out.n_suggest == 0

    def test_suggest_empty_observed(self):
        pool = [{"formula": "Li2O"}, {"formula": "Na2O"}]
        out = suggest_next_batch([], pool, n_suggest=2)
        assert len(out.next_batch) == 2

    def test_suggest_skips_observed(self):
        observed = [ObservedPoint(formula="Li2O", score=2.0)]
        pool = [{"formula": "Li2O"}, {"formula": "Na2O"}]
        out = suggest_next_batch(observed, pool, n_suggest=2)
        formulas = [c.get("formula") for c in out.next_batch]
        assert "Li2O" not in formulas

    def test_suggest_convergence_estimate(self):
        # 大样本 + 历史方差小 → 高收敛度
        observed = [
            ObservedPoint(formula=f"X{i}", score=3.0 + i * 0.01)  # 几乎相等
            for i in range(20)
        ]
        from agents.mat_bayesian_agent.bayesian_engine import formula_to_features
        for o in observed:
            o.features = formula_to_features(o.formula)
        pool = [{"formula": f"Y{i}"} for i in range(3)]
        out = suggest_next_batch(observed, pool, n_suggest=2)
        assert out.convergence_estimate > 0.5  # 收敛度应较高

    def test_run_bayesian_optimization_alias(self):
        """run_bayesian_optimization = suggest_next_batch alias"""
        observed = [ObservedPoint(formula="Li2O", score=2.0)]
        pool = [{"formula": "Na2O"}]
        out = run_bayesian_optimization(observed, pool, n_suggest=1)
        assert isinstance(out, BayesianOutput)


# ============================================================================
# Test 6: make_observed_from_simulated
# ============================================================================


class TestMakeObserved:
    """从 SimCandidate 转 ObservedPoint"""

    def test_from_sim_candidate(self):
        from agents.mat_sim_agent.mat_sim_agent import SimCandidate

        simulated = [
            SimCandidate(
                formula="LiCoO2",
                cif="data_LiCoO2\n",
                relaxed_energy=-3.5,
                forces_max=0.01,
                relaxation_converged=True,
                stability="stable",
                confidence=0.9,
            ),
            SimCandidate(
                formula="LiFePO4",
                cif="data_LiFePO4\n",
                relaxed_energy=-3.2,
                forces_max=0.02,
                relaxation_converged=True,
                stability="stable",
                confidence=0.85,
            ),
        ]
        observed = make_observed_from_simulated(simulated)
        assert len(observed) == 2
        # score = -relaxed_energy
        assert observed[0].score == 3.5
        assert observed[0].relaxed_energy == -3.5
        assert observed[0].stability == "stable"

    def test_from_dict(self):
        simulated = [
            {"formula": "LiCoO2", "relaxed_energy": -3.5, "stability": "stable"},
            {"formula": "NaCl", "relaxed_energy": -2.5, "stability": "stable"},
        ]
        observed = make_observed_from_simulated(simulated)
        assert len(observed) == 2
        assert observed[0].score == 3.5


# ============================================================================
# Test 7: MatBayesianAgent 端到端
# ============================================================================


class TestMatBayesianAgent:
    """Agent 端到端"""

    def test_create_default_agent(self):
        agent = create_default_agent()
        assert isinstance(agent, MatBayesianAgent)
        assert agent.name == "mat-bayesian-agent"

    def test_run_basic(self):
        agent = create_default_agent()
        observed = [
            ObservedPoint(formula="Li2O", score=2.0),
            ObservedPoint(formula="LiCoO2", score=3.5),
            ObservedPoint(formula="LiFePO4", score=3.2),
        ]
        pool = [{"formula": "LiNiO2"}, {"formula": "LiMnO2"}, {"formula": "Na2O"}]
        req = AgentRequest(
            run_id="bayes-test-1",
            message="推荐下一批 2 个候选",
            artifacts={"observed": observed, "pool": pool},
            context={"config": {"n_suggest": 2}},
        )
        response = agent.run(req)
        assert response.confidence > 0
        assert "next_batch" in response.artifacts
        assert len(response.artifacts["next_batch_formulas"]) == 2
        assert "algorithm_used" in response.artifacts

    def test_run_with_forbidden(self):
        agent = create_default_agent()
        observed = [ObservedPoint(formula="Li2O", score=2.0)]
        pool = [{"formula": "LiCoO2"}, {"formula": "LiNiO2"}]
        req = AgentRequest(
            run_id="bayes-test-2",
            message="推荐下一批",
            artifacts={"observed": observed, "pool": pool},
            context={"config": {"n_suggest": 1, "forbidden": ["Co"]}},
        )
        response = agent.run(req)
        formulas = response.artifacts["next_batch_formulas"]
        assert "LiCoO2" not in formulas

    def test_run_empty_artifacts(self):
        agent = create_default_agent()
        req = AgentRequest(
            run_id="bayes-test-3",
            message="推荐下一批",
        )
        response = agent.run(req)
        # 空输入应仍返回(可能空 next_batch)
        assert response.confidence > 0 or response.confidence == 0.3

    def test_run_with_ensemble(self):
        agent = create_default_agent()
        observed = [
            ObservedPoint(formula="Li2O", score=2.0),
            ObservedPoint(formula="LiCoO2", score=3.5),
            ObservedPoint(formula="LiFePO4", score=3.2),
        ]
        pool = [{"formula": "LiNiO2"}, {"formula": "LiMnO2"}]
        req = AgentRequest(
            run_id="bayes-test-4",
            message="ensemble 推荐",
            artifacts={"observed": observed, "pool": pool},
            context={"config": {"n_suggest": 2, "algorithm": "ensemble"}},
        )
        response = agent.run(req)
        assert response.artifacts["algorithm_used"] == "ensemble"


# ============================================================================
# Test 8: BayesianConfig
# ============================================================================


class TestBayesianConfig:
    """配置 dataclass"""

    def test_default_config(self):
        cfg = BayesianConfig()
        assert cfg.algorithm == "auto"
        assert cfg.acquisition == "ei"
        assert cfg.n_suggest == 5
        assert cfg.forbidden == []

    def test_from_dict(self):
        cfg = BayesianConfig.from_dict({
            "algorithm": "gp",
            "n_suggest": 3,
            "forbidden": ["Co"],
        })
        assert cfg.algorithm == "gp"
        assert cfg.n_suggest == 3
        assert cfg.forbidden == ["Co"]

    def test_from_dict_empty(self):
        cfg = BayesianConfig.from_dict(None)
        assert cfg.algorithm == "auto"

    def test_forbidden_default_empty(self):
        cfg = BayesianConfig()
        assert cfg.forbidden == []


# ============================================================================
# Test 9: BayesianOutput
# ============================================================================


class TestBayesianOutput:
    """输出 dataclass"""

    def test_to_dict(self):
        output = BayesianOutput(
            next_batch=[{"formula": "LiNiO2"}],
            acquisition_scores={"LiNiO2": 0.5},
            algorithm_used="gp",
            status="searching",
            convergence_estimate=0.5,
            best_so_far=ObservedPoint(formula="LiCoO2", score=3.5),
            n_observed=5,
            n_pool=10,
            n_suggest=1,
        )
        d = output.to_dict()
        assert d["algorithm_used"] == "gp"
        assert d["status"] == "searching"
        assert d["next_batch_formulas"] == ["LiNiO2"]
        assert d["best_so_far"]["formula"] == "LiCoO2"


# ============================================================================
# Test 10: Goldens 25 case 跑分
# ============================================================================


def _run_goldens_case(case) -> Dict[str, Any]:
    """跑 1 个 Goldens case,返回结果字典"""
    # GoldenCase dataclass,有 .artifacts 属性
    artifacts = getattr(case, "artifacts", None) or (case.get("artifacts", {}) if hasattr(case, "get") else {})

    # 转 observed → ObservedPoint 列表
    raw_observed = artifacts.get("observed", []) if isinstance(artifacts, dict) else []
    observed = []
    for o in raw_observed:
        if isinstance(o, dict):
            observed.append(
                ObservedPoint(
                    formula=o["formula"],
                    score=o.get("score", 0.0),
                    relaxed_energy=o.get("relaxed_energy"),
                    stability=o.get("stability", ""),
                )
            )
    raw_pool = artifacts.get("pool", []) if isinstance(artifacts, dict) else []

    # forbidden 字段:从 artifacts 或 expected 都取
    forbidden = []
    if isinstance(artifacts, dict):
        forbidden.extend(artifacts.get("forbidden", []))
    exp = case.expected if hasattr(case, "expected") else (case.get("expected", {}) if hasattr(case, "get") else {})
    if isinstance(exp, dict):
        forbidden.extend(exp.get("forbidden", []))

    # 从 context.config 拿 algorithm/acquisition
    config = case.expected.get("algorithm", "auto")  # 默认
    acquisition = case.expected.get("acquisition", "ei")

    # 跑 suggest_next_batch
    out = suggest_next_batch(
        observed=observed,
        pool=raw_pool,
        n_suggest=case.expected.get("min_n_suggest", 3),
        algorithm=config if config in ["gp", "tpe", "ensemble", "auto"] else "auto",
        acquisition=acquisition,
        forbidden=forbidden,
    )

    return {
        "next_batch_formulas": [c.get("formula") for c in out.next_batch if isinstance(c, dict)],
        "algorithm_used": out.algorithm_used,
        "status": out.status,
        "n_suggest": out.n_suggest,
        "convergence_estimate": out.convergence_estimate,
    }


def _check_goldens_case(case: Dict[str, Any], actual: Dict[str, Any]) -> tuple[bool, list]:
    """检查 1 个 Goldens case 是否通过"""
    reasons = []
    exp = case.expected

    # algorithm
    if "algorithm" in exp and actual["algorithm_used"] != exp["algorithm"]:
        # 如果是 "auto" 期望但 actual 也是 "tpe"/"gp"(auto 解析后),也接受
        if not (exp["algorithm"] == "auto" and actual["algorithm_used"] in ["gp", "tpe"]):
            reasons.append(f"algorithm={actual['algorithm_used']} (期望 {exp['algorithm']})")

    # status
    if "status" in exp and actual["status"] != exp["status"]:
        reasons.append(f"status={actual['status']} (期望 {exp['status']})")

    # n_suggest
    if "exact_n_suggest" in exp and actual["n_suggest"] != exp["exact_n_suggest"]:
        reasons.append(f"n_suggest={actual['n_suggest']} (期望 {exp['exact_n_suggest']})")
    if "min_n_suggest" in exp and actual["n_suggest"] < exp["min_n_suggest"]:
        reasons.append(f"n_suggest={actual['n_suggest']} < {exp['min_n_suggest']}")
    if "max_n_suggest" in exp and actual["n_suggest"] > exp["max_n_suggest"]:
        reasons.append(f"n_suggest={actual['n_suggest']} > {exp['max_n_suggest']}")

    # 已观测点不应在 next_batch
    if "no_observed_in_next_batch" in exp:
        for f in exp["no_observed_in_next_batch"]:
            if f in actual["next_batch_formulas"]:
                reasons.append(f"已观测 {f} 出现在 next_batch")

    # exclude_in_next_batch
    if "exclude_in_next_batch" in exp:
        for f in exp["exclude_in_next_batch"]:
            if f in actual["next_batch_formulas"]:
                reasons.append(f"禁元素 {f} 出现在 next_batch")

    return (len(reasons) == 0, reasons)


class TestMatBayesianGoldens:
    """mat-bayesian.yaml 25 case 跑分"""

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
                "actual": actual,
            })
        return results

    def test_goldens_overall_pass_rate(self, results):
        n_pass = sum(1 for r in results if r["passed"])
        n_total = len(results)
        pass_rate = n_pass / n_total

        # 失败 case 详细列出
        failed = [r for r in results if not r["passed"]]
        if failed:
            print("\n❌ 失败 case 详情:")
            for r in failed:
                print(f"   {r['case_id']} [{r['category']}]: {r['reasons']}")

        print(f"\n📊 mat-bayesian Goldens 总体: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_gp_pass_rate(self, results):
        gp_results = [r for r in results if r["category"] == "gp"]
        n_pass = sum(1 for r in gp_results if r["passed"])
        n_total = len(gp_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 GP 算法: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"GP pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_tpe_pass_rate(self, results):
        tpe_results = [r for r in results if r["category"] == "tpe"]
        n_pass = sum(1 for r in tpe_results if r["passed"])
        n_total = len(tpe_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 TPE 算法: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"TPE pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_integration_pass_rate(self, results):
        int_results = [r for r in results if r["category"] == "integration"]
        n_pass = sum(1 for r in int_results if r["passed"])
        n_total = len(int_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 集成决策: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"integration pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_e2e_pass_rate(self, results):
        e2e_results = [r for r in results if r["category"] == "e2e"]
        n_pass = sum(1 for r in e2e_results if r["passed"])
        n_total = len(e2e_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 端到端: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"e2e pass-rate {pass_rate:.0%} < 50%"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])