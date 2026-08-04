"""bayesian_engine.py — mat-bayesian 的 GP + TPE 算法引擎

主动学习 2 大算法(per MatWAU-开发计划 §七 W13):
  GP (Gaussian Process):RBF kernel 代理模型 + EI/UCB acquisition
  TPE (Tree-structured Parzen Estimator):good/bad KDE + ratio acquisition

输入:observed = [(formula, score), ...](来自 mat-sim / mat-hpc 实测)
      pool = List[GenCandidate](未实测候选)
输出:next_batch = top-N by acquisition score

Stage 1 / Phase 1:纯 NumPy 实现(无 sklearn / scipy 依赖)
Stage 2(WAU v1.0.0 GA 后):接 optuna / hyperopt

跟 mat-gen / mat-sim 协作流:
  mat-gen → pool
  mat-sim → 给前 N 个打分 → observed
  mat-bayesian → suggest_next_batch(observed, pool) → next_batch
  → mat-gen 重新生成新一批 ...

终止条件:连续 K 轮无提升 OR convergence_estimate >= 0.95
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

# ============================================================================
# 常量
# ============================================================================


# 元素池(per mat-gen 一致)— 用于 One-Hot encoding
ELEMENT_POOL = [
    "H", "Li", "Be", "B", "C", "N", "O", "F", "Na", "Mg", "Al", "Si", "P", "S", "Cl",
    "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge",
    "As", "Se", "Br", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd",
    "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W",
    "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi",
]
ELEMENT_INDEX = {e: i for i, e in enumerate(ELEMENT_POOL)}

# GP 超参数(Stage 1 固定)
GP_LENGTH_SCALE = 2.0       # RBF kernel 长度尺度
GP_NOISE = 0.1              # 观测噪声
GP_KERNEL_VAR = 1.0         # kernel 方差

# TPE 超参数
TPE_GAMMA = 0.25            # top 25% 视为 good
TPE_BANDWIDTH = 1.0         # KDE 带宽

# Acquisition 超参数
ACQ_XI = 0.01               # EI 探索度
ACQ_KAPPA = 2.0             # UCB 探索度

# 收敛阈值
CONVERGENCE_THRESHOLD = 0.95
MIN_OBSERVED = 3            # 至少 3 个观测点才能跑 BO


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class ObservedPoint:
    """1 个已观测点(candidate + 实测 score)

    score 越大越好(Stage 1 取 relaxed_energy 的负值:越负 → score 越高)
    """

    formula: str
    features: list[float] = field(default_factory=list)  # One-Hot 元素组成
    score: float = 0.0
    relaxed_energy: float | None = None  # 原始观测(eV/atom)
    stability: str = ""                     # stable / metastable / unstable

    def __post_init__(self) -> None:
        """features 缺省时自动从 formula 计算 One-Hot"""
        if not self.features and self.formula:
            self.features = formula_to_features(self.formula)

    def to_dict(self) -> dict[str, Any]:
        return {
            "formula": self.formula,
            "score": round(self.score, 4),
            "relaxed_energy": self.relaxed_energy,
            "stability": self.stability,
        }


@dataclass
class AcquisitionResult:
    """1 个候选的 acquisition 评分"""

    formula: str
    acquisition_score: float   # 越大越值得测
    predicted_score: float     # 模型预测均值
    predicted_std: float       # 模型预测标准差
    uncertainty: str           # high / medium / low


@dataclass
class BayesianOutput:
    """mat-bayesian 对外输出"""

    next_batch: list[Any]                                  # 建议下一批候选(GenCandidate / dict)
    acquisition_scores: dict[str, float]                  # formula → score
    algorithm_used: str                                    # gp / tpe / ensemble
    status: str                                            # searching / converging / converged
    convergence_estimate: float                            # 0-1
    best_so_far: ObservedPoint | None                   # 历史最佳
    n_observed: int
    n_pool: int
    n_suggest: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "next_batch_formulas": [getattr(c, "formula", c.get("formula", "?")) if isinstance(c, dict) or hasattr(c, "formula") else str(c) for c in self.next_batch],
            "acquisition_scores": {k: round(v, 4) for k, v in self.acquisition_scores.items()},
            "algorithm_used": self.algorithm_used,
            "status": self.status,
            "convergence_estimate": round(self.convergence_estimate, 3),
            "best_so_far": self.best_so_far.to_dict() if self.best_so_far else None,
            "n_observed": self.n_observed,
            "n_pool": self.n_pool,
            "n_suggest": self.n_suggest,
        }


# ============================================================================
# 化学式编码(One-Hot)
# ============================================================================


def extract_elements(formula: str) -> list[str]:
    """从化学式提取元素列表(去重,保序)

    例:'LiFePO4' → ['Li', 'Fe', 'P', 'O']
       'Na2Cl2' → ['Na', 'Cl']
    """
    tokens = re.findall(r"([A-Z][a-z]?)", formula)
    seen = set()
    elements = []
    for tok in tokens:
        if tok not in seen:
            seen.add(tok)
            elements.append(tok)
    return elements


def formula_to_features(formula: str, pool: list[str] | None = None) -> list[float]:
    """化学式 → One-Hot 元素组成向量

    Args:
        formula: 化学式
        pool: 元素池(默认 ELEMENT_POOL)

    Returns:
        List[float],长度 = len(pool),每项 ∈ {0, 1}
    """
    if pool is None:
        pool = ELEMENT_POOL
    elements = extract_elements(formula)
    features = [0.0] * len(pool)
    for e in elements:
        if e in pool:
            idx = pool.index(e)
            features[idx] = 1.0
    return features


# ============================================================================
# GP(Gaussian Process)代理模型 — 纯 NumPy 实现
# ============================================================================


def _rbf_kernel(
    x1: list[float],
    x2: list[float],
    length_scale: float = GP_LENGTH_SCALE,
    kernel_var: float = GP_KERNEL_VAR,
) -> float:
    """RBF kernel: k(x1, x2) = kernel_var * exp(-||x1-x2||^2 / (2 * length_scale^2))"""
    sq_dist = sum((a - b) ** 2 for a, b in zip(x1, x2))
    return kernel_var * math.exp(-sq_dist / (2.0 * length_scale ** 2))


def _kernel_matrix(
    X1: list[list[float]],
    X2: list[list[float]],
    length_scale: float = GP_LENGTH_SCALE,
    kernel_var: float = GP_KERNEL_VAR,
) -> list[list[float]]:
    """计算 kernel matrix K[i][j] = kernel(X1[i], X2[j])"""
    K = [[0.0] * len(X2) for _ in range(len(X1))]
    for i, x1 in enumerate(X1):
        for j, x2 in enumerate(X2):
            K[i][j] = _rbf_kernel(x1, x2, length_scale, kernel_var)
    return K


def _cholesky_solve(L: list[list[float]], b: list[float]) -> list[float]:
    """Cholesky 解 L @ L.T @ x = b

    注:Cholesky 分解 L 已经给出
    """
    n = len(L)
    # 前向替换 L @ y = b
    y = [0.0] * n
    for i in range(n):
        s = b[i] - sum(L[i][j] * y[j] for j in range(i))
        y[i] = s / L[i][i]
    # 回代 L.T @ x = y
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = y[i] - sum(L[j][i] * x[j] for j in range(i + 1, n))
        x[i] = s / L[i][i]
    return x


def _cholesky_decompose(K: list[list[float]], jitter: float = 1e-4) -> list[list[float]] | None:
    """Cholesky 分解 K = L @ L.T(返回 L,失败返回 None)

    注:加入 jitter 保证正定
    """
    n = len(K)
    # 加 jitter 到对角
    K_perturbed = [list(row) for row in K]
    for i in range(n):
        K_perturbed[i][i] += jitter

    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = K_perturbed[i][j] - sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                if s <= 0:
                    return None  # 非正定,失败
                L[i][j] = math.sqrt(s)
            else:
                if L[j][j] == 0:
                    return None
                L[i][j] = s / L[j][j]
    return L


def gp_fit(observed: list[ObservedPoint]) -> dict[str, Any] | None:
    """GP 拟合(纯 NumPy,无 sklearn)

    Args:
        observed: List[ObservedPoint]

    Returns:
        fit_state: dict {X, y, L, alpha, mean, std} 或 None(样本不足)
    """
    if len(observed) < 2:
        return None

    X = [o.features for o in observed]
    y = [o.score for o in observed]

    # 标准化 y(数值稳定)
    y_mean = sum(y) / len(y)
    y_centered = [yi - y_mean for yi in y]
    y_std = math.sqrt(sum((yi - y_mean) ** 2 for yi in y) / len(y)) or 1.0
    y_norm = [yi / y_std for yi in y_centered]

    # K + noise*I
    K = _kernel_matrix(X, X)
    n = len(K)
    for i in range(n):
        K[i][i] += GP_NOISE

    # Cholesky 分解
    L = _cholesky_decompose(K)
    if L is None:
        return None

    # alpha = K^-1 @ y_norm
    alpha = _cholesky_solve(L, y_norm)

    return {
        "X": X,
        "y_mean": y_mean,
        "y_std": y_std,
        "L": L,
        "alpha": alpha,
    }


def gp_predict(
    fit_state: dict[str, Any],
    X_new: list[list[float]],
) -> list[tuple[float, float]]:
    """GP 预测,返回 (μ, σ) 对每个新点

    Args:
        fit_state: gp_fit() 返回的字典
        X_new: 新候选的 features

    Returns:
        List[Tuple[mean, std]]
    """
    X_train = fit_state["X"]
    y_mean = fit_state["y_mean"]
    y_std = fit_state["y_std"]
    L = fit_state["L"]
    alpha = fit_state["alpha"]

    K_new = _kernel_matrix(X_new, X_train)
    K_new_new = [
        _rbf_kernel(x, x) for x in X_new
    ]

    # μ = K_new @ alpha(标准化空间)
    mu_norm = []
    for i in range(len(X_new)):
        s = sum(K_new[i][j] * alpha[j] for j in range(len(X_train)))
        mu_norm.append(s)

    # σ² = K_new_new_diag - diag(K_new @ K^-1 @ K_new.T)
    # 对每个 i:K_new[i] @ K^-1 @ K_new[i].T → 标量
    var_norm = []
    for i in range(len(X_new)):
        # 1. 解 K^-1 @ K_new[i].T → w,shape (n_train,)
        rhs = list(K_new[i])  # K_new 的第 i 行,shape (n_train,)
        w = _cholesky_solve(L, rhs)
        # 2. K_new[i] @ w → 标量
        s = sum(K_new[i][j] * w[j] for j in range(len(X_train)))
        var = max(K_new_new[i] - s, 1e-6)
        var_norm.append(var)

    # 反标准化
    mu = [y_mean + m * y_std for m in mu_norm]
    sigma = [math.sqrt(v) * y_std for v in var_norm]

    return list(zip(mu, sigma))


# ============================================================================
# TPE(Tree-structured Parzen Estimator) — Stage 1 简化版
# ============================================================================


def tpe_fit(observed: list[ObservedPoint]) -> dict[str, Any] | None:
    """TPE 拟合:划分 good / bad

    Args:
        observed: List[ObservedPoint]

    Returns:
        fit_state: dict {good_features, bad_features} 或 None(样本不足)
    """
    if len(observed) < 2:
        return None

    sorted_obs = sorted(observed, key=lambda o: o.score, reverse=True)
    n_good = max(1, int(len(observed) * TPE_GAMMA))
    good = sorted_obs[:n_good]
    bad = sorted_obs[n_good:]

    if not bad:
        # 全是 good → bad = good + 一点 jitter
        bad = sorted_obs

    return {
        "good_features": [o.features for o in good],
        "bad_features": [o.features for o in bad],
        "good_scores": [o.score for o in good],
        "bad_scores": [o.score for o in bad],
    }


def _gaussian_kde(
    X_query: list[list[float]],
    X_ref: list[list[float]],
    bandwidth: float = TPE_BANDWIDTH,
) -> list[float]:
    """高斯 KDE(per dim 独立)→ 返回每个 query 的密度

    简化:每维独立 KDE,取几何均值(等权平均假设)
    """
    if not X_ref:
        return [1e-6] * len(X_query)

    d = len(X_ref[0])
    n_ref = len(X_ref)
    densities = []
    for x in X_query:
        # 每维 KDE 估计
        dim_dens = []
        for dim in range(d):
            # 1D Gaussian KDE
            s = 0.0
            for ref in X_ref:
                diff = (x[dim] - ref[dim]) / bandwidth
                s += math.exp(-0.5 * diff ** 2)
            dim_dens.append(s / (n_ref * bandwidth * math.sqrt(2 * math.pi)))
        # 几何均值(避免一维 0 致整体 0)
        prod = 1.0
        for dd in dim_dens:
            prod *= max(dd, 1e-6)
        densities.append(prod ** (1.0 / d))
    return densities


def tpe_acquisition(
    fit_state: dict[str, Any],
    X_new: list[list[float]],
) -> list[float]:
    """TPE acquisition: l(x) / g(x)

    Args:
        fit_state: tpe_fit() 返回
        X_new: 候选 features

    Returns:
        List[float],越大越好
    """
    good_features = fit_state["good_features"]
    bad_features = fit_state["bad_features"]

    l_x = _gaussian_kde(X_new, good_features)
    g_x = _gaussian_kde(X_new, bad_features)

    # acquisition = l(x) / g(x),加 epsilon 防 0
    return [l / max(g, 1e-6) for l, g in zip(l_x, g_x)]


# ============================================================================
# Acquisition Functions
# ============================================================================


def acquisition_ei(
    mu: float,
    sigma: float,
    best_y: float,
    xi: float = ACQ_XI,
) -> float:
    """Expected Improvement(EI)

    EI = (μ - best_y - ξ) * Φ(Z) + σ * φ(Z)
    Z = (μ - best_y - ξ) / σ
    """
    if sigma < 1e-6:
        return max(mu - best_y - xi, 0.0)

    Z = (mu - best_y - xi) / sigma
    # 标准正态 CDF / PDF
    phi_z = math.exp(-0.5 * Z ** 2) / math.sqrt(2 * math.pi)
    Phi_z = 0.5 * (1.0 + math.erf(Z / math.sqrt(2)))
    return (mu - best_y - xi) * Phi_z + sigma * phi_z


def acquisition_ucb(
    mu: float,
    sigma: float,
    kappa: float = ACQ_KAPPA,
) -> float:
    """Upper Confidence Bound(UCB)

    UCB = μ + κ * σ
    """
    return mu + kappa * sigma


def acquisition_pi(
    mu: float,
    sigma: float,
    best_y: float,
    xi: float = ACQ_XI,
) -> float:
    """Probability of Improvement(PI)

    PI = Φ((μ - best_y - ξ) / σ)
    """
    if sigma < 1e-6:
        return 1.0 if mu > best_y + xi else 0.0
    Z = (mu - best_y - xi) / sigma
    return 0.5 * (1.0 + math.erf(Z / math.sqrt(2)))


# ============================================================================
# 统一 suggest_next_batch 接口
# ============================================================================


def suggest_next_batch(
    observed: list[ObservedPoint],
    pool: list[Any],
    n_suggest: int = 5,
    algorithm: str = "auto",       # auto / gp / tpe / ensemble
    acquisition: str = "ei",       # ei / ucb / pi
    forbidden: list[str] | None = None,
) -> BayesianOutput:
    """统一接口:根据 observed + pool,选下一批候选

    Args:
        observed: 已观测点(per mat-sim / hpc 输出)
        pool: 候选池(GenCandidate / dict / formula str)
        n_suggest: 建议多少个
        algorithm: "gp" / "tpe" / "ensemble" / "auto"
        acquisition: "ei" / "ucb" / "pi"
        forbidden: 禁止元素(如用户约束)

    Returns:
        BayesianOutput(next_batch + scores + status + convergence_estimate)
    """
    forbidden = forbidden or []

    # 1. 过滤 pool(去掉 forbidden / 已观测)
    observed_formulas = {o.formula for o in observed}
    valid_pool = []
    for c in pool:
        # 提取 formula
        if isinstance(c, dict):
            formula = c.get("formula", "")
        elif hasattr(c, "formula"):
            formula = c.formula
        elif isinstance(c, str):
            formula = c
        else:
            continue

        if not formula:
            continue
        if formula in observed_formulas:
            continue
        if any(f in formula for f in forbidden):
            continue
        valid_pool.append(c)

    if not valid_pool:
        # 无可用候选:已观测但 pool 全被过滤(全观测 / 全 forbidden)
        # n_observed == 0 → searching(没开始)
        # n_observed > 0 → converged(全测完了)
        return BayesianOutput(
            next_batch=[],
            acquisition_scores={},
            algorithm_used=algorithm,
            status="converged" if len(observed) > 0 else "searching",
            convergence_estimate=1.0 if len(observed) > 0 else 0.0,
            best_so_far=max(observed, key=lambda o: o.score) if observed else None,
            n_observed=len(observed),
            n_pool=0,
            n_suggest=0,    # 实际建议 0 个
        )

    # 2. 算法选择
    if algorithm == "auto":
        # 样本 < 10 → TPE(对小样本更鲁棒)
        # 样本 >= 10 → GP(精度高)
        # Stage 1 简化:小样本直接 TPE
        algorithm = "tpe" if len(observed) < 10 else "gp"

    # 3. 算 acquisition
    acq_func_map = {"ei": acquisition_ei, "ucb": acquisition_ucb, "pi": acquisition_pi}
    acq_func = acq_func_map.get(acquisition, acquisition_ei)

    valid_formulas = []
    X_pool = []
    for c in valid_pool:
        if isinstance(c, dict):
            formula = c.get("formula", "")
        elif hasattr(c, "formula"):
            formula = c.formula
        else:
            formula = str(c)
        if not formula:
            continue
        valid_formulas.append(formula)
        X_pool.append(formula_to_features(formula))

    scores: dict[str, float] = {}

    if algorithm == "gp":
        fit = gp_fit(observed)
        if fit is None:
            # 退化到 TPE
            return suggest_next_batch(
                observed, pool, n_suggest,
                algorithm="tpe", acquisition=acquisition, forbidden=forbidden,
            )
        best_y = max((o.score for o in observed), default=0.0)
        preds = gp_predict(fit, X_pool)
        for formula, (mu, sigma) in zip(valid_formulas, preds):
            scores[formula] = acq_func(mu, sigma, best_y) if acquisition != "ucb" else acq_func(mu, sigma)

    elif algorithm == "tpe":
        fit = tpe_fit(observed)
        if fit is None:
            # 退化到随机
            for formula in valid_formulas:
                scores[formula] = 1.0
        else:
            tpe_scores = tpe_acquisition(fit, X_pool)
            for formula, s in zip(valid_formulas, tpe_scores):
                scores[formula] = s

    elif algorithm == "ensemble":
        # GP + TPE 取 max
        gp_scores: dict[str, float] = {}
        tpe_scores_map: dict[str, float] = {}

        # GP
        fit_gp = gp_fit(observed)
        if fit_gp is not None:
            best_y = max((o.score for o in observed), default=0.0)
            preds = gp_predict(fit_gp, X_pool)
            for formula, (mu, sigma) in zip(valid_formulas, preds):
                gp_scores[formula] = acq_func(mu, sigma, best_y) if acquisition != "ucb" else acq_func(mu, sigma)
        else:
            gp_scores = {f: 0.0 for f in valid_formulas}

        # TPE
        fit_tpe = tpe_fit(observed)
        if fit_tpe is not None:
            tpe_raw = tpe_acquisition(fit_tpe, X_pool)
            tpe_scores_map = {f: s for f, s in zip(valid_formulas, tpe_raw)}
        else:
            tpe_scores_map = {f: 0.0 for f in valid_formulas}

        # 标准化后取 max
        def normalize(d):
            if not d:
                return {}
            vals = list(d.values())
            mx, mn = max(vals), min(vals)
            if mx - mn < 1e-9:
                return {k: 0.5 for k in d}
            return {k: (v - mn) / (mx - mn) for k, v in d.items()}

        gp_norm = normalize(gp_scores)
        tpe_norm = normalize(tpe_scores_map)
        for f in valid_formulas:
            scores[f] = max(gp_norm.get(f, 0), tpe_norm.get(f, 0))

    else:
        raise ValueError(f"未知算法: {algorithm}")

    # 4. 排序 + 取 top-N
    sorted_formulas = sorted(scores.keys(), key=lambda f: scores[f], reverse=True)
    top_formulas = sorted_formulas[:n_suggest]

    # 找回 pool 中对应的对象
    next_batch = []
    for c, f in zip(valid_pool, valid_formulas):
        if f in top_formulas:
            next_batch.append(c)
            # 只取前 n_suggest
            if len(next_batch) >= n_suggest:
                break

    # 5. 状态 + 收敛估计
    best_so_far = max(observed, key=lambda o: o.score) if observed else None
    convergence_estimate = _estimate_convergence(observed, scores)

    if convergence_estimate >= CONVERGENCE_THRESHOLD:
        status = "converged"
    elif len(observed) >= 10:
        status = "converging"
    else:
        status = "searching"

    return BayesianOutput(
        next_batch=next_batch,
        acquisition_scores={f: scores[f] for f in top_formulas},
        algorithm_used=algorithm,
        status=status,
        convergence_estimate=convergence_estimate,
        best_so_far=best_so_far,
        n_observed=len(observed),
        n_pool=len(valid_pool),
        n_suggest=len(next_batch),
    )


# ============================================================================
# 收敛估计
# ============================================================================


def _estimate_convergence(observed: list[ObservedPoint], acq_scores: dict[str, float]) -> float:
    """估计收敛度 0-1

    启发式:
    - 历史 score 方差小 → 高
    - acquisition score 最大值小 → 高(说明没什么好挑的了)
    - 样本越多 → 越高
    """
    if len(observed) < 2:
        return 0.0

    scores = [o.score for o in observed]
    score_mean = sum(scores) / len(scores)
    score_var = sum((s - score_mean) ** 2 for s in scores) / len(scores)

    # 历史方差越小 → 收敛(假设分数在 [-5, 0],var < 0.5 → 高)
    var_factor = max(0.0, 1.0 - score_var / 2.0)

    # acquisition 最大值越小 → 收敛(说明模型对所有候选都不确定 / 都不看好)
    if acq_scores:
        max_acq = max(acq_scores.values())
        # 标准化: EI 通常 0-1,>1 表示还有大改进
        acq_factor = max(0.0, 1.0 - min(max_acq, 1.0))
    else:
        acq_factor = 1.0

    # 样本量饱和
    sample_factor = min(1.0, len(observed) / 30.0)

    # 加权(各 1/3)
    return (var_factor + acq_factor + sample_factor) / 3.0


# ============================================================================
# 便利函数:从 SimCandidate 列表构造 ObservedPoint 列表
# ============================================================================


def make_observed_from_simulated(
    simulated: list[Any],
    score_field: str = "score",
) -> list[ObservedPoint]:
    """从 SimCandidate 列表构造 ObservedPoint 列表

    Args:
        simulated: List[SimCandidate] 或 dict
        score_field: 取分字段(默认 score;其他 relaxed_energy 转 -score)

    Returns:
        List[ObservedPoint]
    """
    observed = []
    for c in simulated:
        if isinstance(c, dict):
            formula = c.get("formula", "")
            relaxed_energy = c.get("relaxed_energy")
            stability = c.get("stability", "")
            # score 推导:energy 越负 → score 越高
            if relaxed_energy is not None:
                score = -relaxed_energy
            else:
                score = c.get(score_field, 0.0)
        elif hasattr(c, "formula"):
            formula = c.formula
            relaxed_energy = getattr(c, "relaxed_energy", None)
            stability = getattr(c, "stability", "")
            if relaxed_energy is not None:
                score = -relaxed_energy
            else:
                score = getattr(c, score_field, 0.0)
        else:
            continue

        if not formula:
            continue

        observed.append(
            ObservedPoint(
                formula=formula,
                features=formula_to_features(formula),
                score=score,
                relaxed_energy=relaxed_energy,
                stability=stability,
            )
        )

    return observed


# ============================================================================
# 主接口 alias(给 mat_bayesian_agent.py 用)
# ============================================================================


def run_bayesian_optimization(
    observed: list[ObservedPoint],
    pool: list[Any],
    n_suggest: int = 5,
    algorithm: str = "auto",
    acquisition: str = "ei",
    forbidden: list[str] | None = None,
) -> BayesianOutput:
    """主接口 alias = suggest_next_batch(语义更明确)"""
    return suggest_next_batch(
        observed=observed,
        pool=pool,
        n_suggest=n_suggest,
        algorithm=algorithm,
        acquisition=acquisition,
        forbidden=forbidden,
    )


__all__ = [
    "ELEMENT_INDEX",
    "ELEMENT_POOL",
    "AcquisitionResult",
    "BayesianOutput",
    "ObservedPoint",
    "acquisition_ei",
    "acquisition_pi",
    "acquisition_ucb",
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