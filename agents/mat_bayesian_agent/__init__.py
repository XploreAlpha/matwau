"""mat-bayesian-agent — 材料科学主动学习研究员

GP(Gaussian Process)+ TPE(Tree-structured Parzen Estimator)2 算法
Acquisition:EI / UCB / PI

适用场景:
- mat-gen → pool → mat-sim → score → mat-bayesian → next_batch 主动学习闭环
- 用最少实验次数找最优配方

Stage 1: 纯 NumPy 实现(无 sklearn / scipy 依赖)
Stage 2: 接 optuna / hyperopt / BoTorch

per MatWAU-开发计划 §七 W13
"""
from .bayesian_engine import (
    BayesianOutput,
    ObservedPoint,
    acquisition_ei,
    acquisition_pi,
    acquisition_ucb,
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
from .mat_bayesian_agent import (
    BayesianConfig,
    MatBayesianAgent,
    create_default_agent,
)

__all__ = [
    "BayesianConfig",
    "BayesianOutput",
    "MatBayesianAgent",
    "ObservedPoint",
    "acquisition_ei",
    "acquisition_pi",
    "acquisition_ucb",
    "create_default_agent",
    "extract_elements",
    "formula_to_features",
    "gp_fit",
    "gp_predict",
    "make_observed_from_simulated",
    "run_bayesian_optimization",
    "suggest_next_batch",
    "tpe_acquisition",
    "tpe_fit",
]