"""mat-bayesian-agent — 材料科学主动学习研究员(per dev plan §七 W13)

Stage 1 / Phase 1:纯规则 + 纯 NumPy(无 sklearn / scipy 依赖)
Stage 2(WAU v1.0.0 GA 后):接 optuna / hyperopt / BoTorch

业务流程(per act() 实现):
1. 从 req.artifacts 抽 observed(已观测点)+ pool(候选池)
2. 跑 bayesian_engine.suggest_next_batch(默认 algorithm="auto")
3. 返回 BayesianOutput + 自然语言总结

用法:
    from agents.mat_bayesian_agent.mat_bayesian_agent import MatBayesianAgent
    from matwau.core.agent_base import AgentRequest

    # 准备 observed(mat-sim 给的)
    observed = [ObservedPoint(...), ...]
    # 准备 pool(mat-gen 给的)
    pool = [{'formula': 'Li2O'}, ...]

    agent = MatBayesianAgent()
    req = AgentRequest(
        run_id="bayes-001",
        message="推荐下一批 5 个候选",
        artifacts={"observed": observed, "pool": pool},
    )
    response = agent.run(req)
    print(response.artifacts["next_batch"])  # List[GenCandidate]
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# 允许直接 python3 -m 运行本文件
_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.core.agent_base import (  # noqa: E402
    AgentRequest,
    AgentResponse,
    MatWAUAgentBase,
)
from matwau.harness.context_manager import ContextManager  # noqa: E402
from matwau.harness.safety_guard import SafetyGuard  # noqa: E402

from .bayesian_engine import (  # noqa: E402
    BayesianOutput,
    ObservedPoint,
    extract_elements,
    make_observed_from_simulated,
    run_bayesian_optimization,
)


# ============================================================================
# 数据结构(对外暴露)
# ============================================================================


@dataclass
class BayesianConfig:
    """用户配置(per AgentRequest.context)"""

    algorithm: str = "auto"           # "gp" / "tpe" / "ensemble" / "auto"
    acquisition: str = "ei"            # "ei" / "ucb" / "pi"
    n_suggest: int = 5
    forbidden: List[str] = None        # 禁止元素

    def __post_init__(self) -> None:
        if self.forbidden is None:
            self.forbidden = []

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "BayesianConfig":
        if not d:
            return cls()
        return cls(
            algorithm=d.get("algorithm", "auto"),
            acquisition=d.get("acquisition", "ei"),
            n_suggest=d.get("n_suggest", 5),
            forbidden=d.get("forbidden", []),
        )


def _bayesian_to_config_dict(output: BayesianOutput) -> Dict[str, Any]:
    """BayesianOutput → dict(给 caller 看)"""
    return {
        "next_batch": [
            getattr(c, "formula", c.get("formula", "?")) if not isinstance(c, str) else c
            for c in output.next_batch
        ],
        "next_batch_full": output.next_batch,  # 完整对象
        "acquisition_scores": output.acquisition_scores,
        "algorithm_used": output.algorithm_used,
        "status": output.status,
        "convergence_estimate": round(output.convergence_estimate, 3),
        "best_so_far": output.best_so_far.to_dict() if output.best_so_far else None,
        "n_observed": output.n_observed,
        "n_pool": output.n_pool,
        "n_suggest": output.n_suggest,
    }


# ============================================================================
# MatBayesianAgent 主体
# ============================================================================


class MatBayesianAgent(MatWAUAgentBase):
    """mat-bayesian-agent — 材料科学主动学习研究员

    业务流程:
    1. 抽取 observed + pool(支持 dict / SimCandidate / GenCandidate / ObservedPoint)
    2. 跑 bayesian_engine.suggest_next_batch
    3. 返回 BayesianOutput(给 mat-gen / mat-sim 喂下一批)
    """

    name = "mat-bayesian-agent"

    def __init__(
        self,
        *,
        default_algorithm: str = "auto",
        default_acquisition: str = "ei",
        default_n_suggest: int = 5,
        cost_per_call: float = 0.02,        # ¥/次(NumPy 计算几乎免费)
        **kwargs,
    ) -> None:
        """构造

        Args:
            default_algorithm: 默认算法(auto / gp / tpe / ensemble)
            default_acquisition: 默认 acquisition(ei / ucb / pi)
            default_n_suggest: 默认建议数
            cost_per_call: 单次调用估算成本 ¥
        """
        super().__init__(**kwargs)
        self.default_algorithm = default_algorithm
        self.default_acquisition = default_acquisition
        self.default_n_suggest = default_n_suggest
        self.cost_per_call = cost_per_call

        # 默认注入 harness 部件
        if self.context_manager is None:
            self.context_manager = ContextManager(max_tokens=4000)
        if self.safety_guard is None:
            self.safety_guard = SafetyGuard(budget_limit=500.0)

    def system_prompt(self) -> str:
        return """你是材料科学主动学习研究员 agent(mat-bayesian-agent),用 GP / TPE 算法选下一批候选。

能力:
1. 接收 observed(已实测候选 + score)+ pool(未测候选库)
2. 用 Gaussian Process(GP)或 Tree-structured Parzen Estimator(TPE)选下一批
3. 默认 algorithm="auto":样本 < 10 用 TPE / >= 10 用 GP
4. acquisition:"ei"(Expected Improvement)/ "ucb"(Upper Confidence Bound)/ "pi"(Prob. of Improvement)
5. 输出:next_batch + acquisition_scores + algorithm_used + status + convergence_estimate

3 档状态:
- searching:样本 < 10 OR convergence < 0.7
- converging:样本 >= 10 AND 0.7 <= convergence < 0.95
- converged:样本 >= 30 OR convergence >= 0.95

适用场景:
- mat-gen → 候选 pool → mat-sim → score → mat-bayesian → next_batch
- 主动学习循环:用最少实验次数找最优配方

约束:
- 0 行 UI 代码(无头架构)
- 1 次调用 = 1 次 Goldens 跑分(mat-bayesian.yaml,pass-rate > 50% Stage 1 / > 80% Stage 2)
"""

    def act(self, ctx: Dict[str, Any], tools: List[str]) -> AgentResponse:
        """Inner Loop 第 3 步:执行 — mat-bayesian 特有业务逻辑

        1. 从 ctx 抽 observed + pool + config
        2. 跑 suggest_next_batch
        3. 构造 reply + BayesianOutput dict
        4. SafetyGuard 检查
        5. 返回 AgentResponse
        """
        observed: List[ObservedPoint] = ctx.get("_input_observed") or []
        pool: List[Any] = ctx.get("_input_pool") or []
        config: BayesianConfig = ctx.get("_input_config") or BayesianConfig()

        # fallback: 从 artifacts
        if not observed:
            artifacts = ctx.get("_input_artifacts") or {}
            observed_raw = artifacts.get("observed") or []
            observed = self._coerce_observed(observed_raw)

        if not pool:
            artifacts = ctx.get("_input_artifacts") or {}
            pool = artifacts.get("pool") or artifacts.get("candidates") or []

        # 1. 跑 BO
        try:
            output = run_bayesian_optimization(
                observed=observed,
                pool=pool,
                n_suggest=config.n_suggest,
                algorithm=config.algorithm,
                acquisition=config.acquisition,
                forbidden=config.forbidden,
            )
        except Exception as e:
            return self._error_response(f"mat-bayesian 失败: {e}")

        # 2. 转 dict
        output_dict = _bayesian_to_config_dict(output)

        # 3. 自然语言 reply
        reply = self._format_reply(output, config)

        # 4. 置信度
        confidence = (
            0.95 if output.status == "converged" else
            0.85 if output.status == "converging" else
            0.7
        )

        response = AgentResponse(
            reply=reply,
            artifacts={
                "next_batch": output.next_batch,           # 完整对象(给 mat-gen)
                "next_batch_formulas": output_dict["next_batch"],
                "acquisition_scores": output.acquisition_scores,
                "algorithm_used": output.algorithm_used,
                "status": output.status,
                "convergence_estimate": output.convergence_estimate,
                "best_so_far": output.best_so_far.to_dict() if output.best_so_far else None,
                "n_observed": output.n_observed,
                "n_pool": output.n_pool,
                "n_suggest": output.n_suggest,
                "input_count": {"observed": len(observed), "pool": len(pool)},
            },
            confidence=confidence,
            cost=self.cost_per_call,
        )

        # 5. SafetyGuard
        if self.safety_guard:
            try:
                if not self.safety_guard.check(response):
                    response.reply = f"[BLOCKED by SafetyGuard] {response.reply}"
            except Exception:
                pass

        return response

    def perceive(self, req: AgentRequest) -> Dict[str, Any]:
        """步骤 1 重写:抽取 observed + pool + config

        支持 3 种输入格式:
        - artifacts.observed: List[ObservedPoint / dict / SimCandidate]
        - artifacts.pool: List[GenCandidate / dict / formula str]
        - context.config: BayesianConfig dict
        """
        ctx = super().perceive(req)
        artifacts = req.artifacts or {}

        # 1. observed:List[ObservedPoint / dict / SimCandidate / GenCandidate]
        observed_raw = artifacts.get("observed", [])
        observed = self._coerce_observed(observed_raw)

        # 2. pool
        pool = artifacts.get("pool") or artifacts.get("candidates") or []

        # 3. config(从 context)
        config_dict = req.context.get("config") or req.context
        config = BayesianConfig.from_dict(config_dict) if isinstance(config_dict, dict) else BayesianConfig()

        ctx["_input_observed"] = observed
        ctx["_input_pool"] = pool
        ctx["_input_config"] = config
        ctx["user_message"] = req.message
        ctx["_input_artifacts"] = artifacts

        return ctx

    # ========================================================================
    # 内部 helper
    # ========================================================================

    def _coerce_observed(self, raw: List[Any]) -> List[ObservedPoint]:
        """把任意 list 转 List[ObservedPoint]

        支持:
        - ObservedPoint(直接保留)
        - dict:需要 formula + score / relaxed_energy
        - SimCandidate / GenCandidate(用 dataclass 属性)
        """
        observed = []
        for c in raw:
            if isinstance(c, ObservedPoint):
                observed.append(c)
            elif isinstance(c, dict):
                # 已经是 dict 形式
                if "formula" not in c:
                    continue
                features = c.get("features") or []  # 缺省时 __post_init__ 会算
                observed.append(
                    ObservedPoint(
                        formula=c["formula"],
                        features=features,
                        score=c.get("score", 0.0),
                        relaxed_energy=c.get("relaxed_energy"),
                        stability=c.get("stability", ""),
                    )
                )
            else:
                # dataclass(SimCandidate / GenCandidate)
                formula = getattr(c, "formula", None)
                if not formula:
                    continue
                relaxed_energy = getattr(c, "relaxed_energy", None)
                # score 推导
                if relaxed_energy is not None:
                    score = -relaxed_energy
                else:
                    estimated_energy = getattr(c, "estimated_energy", None)
                    if estimated_energy is not None:
                        score = -estimated_energy
                    else:
                        score = 0.0
                observed.append(
                    ObservedPoint(
                        formula=formula,
                        score=score,
                        relaxed_energy=relaxed_energy,
                        stability=getattr(c, "stability", ""),
                    )
                )
        return observed

    def _format_reply(self, output: BayesianOutput, config: BayesianConfig) -> str:
        """生成自然语言 reply"""
        formulas = [
            getattr(c, "formula", c.get("formula", "?") if isinstance(c, dict) else str(c))
            for c in output.next_batch
        ]

        lines = [
            f"🎯 mat-bayesian 推荐下一批 {output.n_suggest} 个候选",
            f"   算法: {output.algorithm_used} | 状态: {output.status} | 收敛度: {output.convergence_estimate:.2f}",
        ]

        if output.best_so_far:
            lines.append(
                f"   当前最佳: {output.best_so_far.formula}(score={output.best_so_far.score:.2f})"
            )

        lines.append(
            f"   观测: {output.n_observed} 个 | 候选池: {output.n_pool} 个"
        )

        lines.append(f"\n📋 下一批候选:")
        for f, score in output.acquisition_scores.items():
            lines.append(f"   {f} → acquisition={score:.4f}")

        return "\n".join(lines)

    def _empty_response(self, reason: str) -> AgentResponse:
        """空响应"""
        return AgentResponse(
            reply=f"⚠️ mat-bayesian: {reason}",
            artifacts={"next_batch": [], "status": "searching", "convergence_estimate": 0.0},
            confidence=0.3,
        )

    def _error_response(self, error: str) -> AgentResponse:
        """错误响应"""
        return AgentResponse(
            reply=f"❌ mat-bayesian 错误: {error}",
            artifacts={"next_batch": [], "status": "failed", "convergence_estimate": 0.0},
            confidence=0.0,
            error=error,
        )


def create_default_agent() -> MatBayesianAgent:
    """便利函数:创建带默认 Harness 的 MatBayesianAgent"""
    return MatBayesianAgent(
        default_algorithm="auto",
        default_acquisition="ei",
        default_n_suggest=5,
        cost_per_call=0.02,
    )


# ============================================================================
# CLI 入口
# ============================================================================


if __name__ == "__main__":
    print("🚀 MatBayesianAgent Demo")
    print("=" * 60)

    agent = create_default_agent()
    print(f"   {agent}")
    print(f"   algorithm={agent.default_algorithm}, acquisition={agent.default_acquisition}")

    # Demo 1: mat-gen → mat-sim → mat-bayesian 闭环
    print("\n📦 Step 1: 模拟 5 个观测点")
    observed = [
        ObservedPoint(formula="Li2O", score=2.0, relaxed_energy=-2.0),
        ObservedPoint(formula="LiCoO2", score=3.5, relaxed_energy=-3.5),
        ObservedPoint(formula="LiFePO4", score=3.2, relaxed_energy=-3.2),
        ObservedPoint(formula="NaCl", score=2.5, relaxed_energy=-2.5),
        ObservedPoint(formula="Fe2O3", score=3.0, relaxed_energy=-3.0),
    ]
    for o in observed:
        print(f"   {o.formula}: score={o.score}, energy={o.relaxed_energy}")

    print("\n🎯 Step 2: 候选池 8 个")
    pool = [
        {"formula": "LiCoO2"},      # 已观测,跳过
        {"formula": "LiNiO2"},
        {"formula": "LiMnO2"},
        {"formula": "Na2O"},
        {"formula": "K2O"},
        {"formula": "Li2SiO3"},
        {"formula": "Li5La3Zr2O12"},
        {"formula": "LiAlO2"},
    ]

    print("\n🚀 Step 3: mat-bayesian 推荐下一批")
    req = AgentRequest(
        run_id="bayes-demo-1",
        message="推荐下一批 3 个候选",
        artifacts={"observed": observed, "pool": pool},
        context={"config": {"n_suggest": 3, "algorithm": "auto"}},
    )
    response = agent.run(req)
    print(response.reply)

    # Demo 2: forbidden
    print("\n\n🚀 Demo 4: 用户禁止 Co")
    req2 = AgentRequest(
        run_id="bayes-demo-2",
        message="推荐下一批 3 个候选,无 Co",
        artifacts={"observed": observed, "pool": pool},
        context={"config": {"n_suggest": 3, "forbidden": ["Co"]}},
    )
    response2 = agent.run(req2)
    print(response2.reply)


__all__ = [
    "MatBayesianAgent",
    "BayesianConfig",
    "create_default_agent",
]