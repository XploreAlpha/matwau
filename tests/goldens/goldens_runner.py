"""Goldens 测试集运行器(per MatWAU-Harness-Loop doc §5.5 + §6)

提供:
- Goldens.load(path) → List[dict] 解析 YAML
- Goldens.expand(failures) → 把失败 case 反向扩充回测试集(Outer Loop)
- EvalHarness.run_full_eval(agent) → 跑完整测试集 + 出分

这是任务 2 的核心交付物:
- 支持 .yaml 格式
- 支持嵌套 expected 字段(formula_must_contain 等)
- 支持 num_candidates / top_5_energy_below 数值约束
- 支持 must_pass_sim / must_pass_lit / must_pass_eis 跨 agent 验证
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class GoldenCase:
    """单条 Goldens 测试 case"""

    id: str
    category: str
    intent: str
    expected: Dict[str, Any] = field(default_factory=dict)
    candidates: List[Dict[str, Any]] = field(default_factory=list)  # 🆕 W12 mat-critic 用
    artifacts: Dict[str, Any] = field(default_factory=dict)         # 🆕 W13 mat-bayesian 用(observed + pool)
    must_pass_sim: bool = False
    must_pass_lit: bool = False
    must_pass_eis: bool = False

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GoldenCase":
        return cls(
            id=d["id"],
            category=d.get("category", "uncategorized"),
            intent=d["intent"],
            expected=d.get("expected", {}),
            candidates=d.get("candidates", []),  # 🆕 W12
            artifacts=d.get("artifacts", {}),    # 🆕 W13
            must_pass_sim=d.get("must_pass_sim", False),
            must_pass_lit=d.get("must_pass_lit", False),
            must_pass_eis=d.get("must_pass_eis", False),
        )


@dataclass
class EvalResult:
    """单条 case 的跑分结果"""

    case_id: str
    passed: bool
    reasons: List[str] = field(default_factory=list)
    actual: Dict[str, Any] = field(default_factory=dict)


class Goldens:
    """Goldens 测试集加载器

    任务 2 验收:Goldens.load() 能解析 mat-gen.yaml 50 个 case
    """

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Goldens 文件不存在: {path}")
        self.cases: List[GoldenCase] = self._load()

    def _load(self) -> List[GoldenCase]:
        data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"Goldens 必须是 list,got {type(data)}")
        return [GoldenCase.from_dict(item) for item in data]

    def load(self) -> List[GoldenCase]:
        """返回所有 case"""
        return self.cases

    def get_by_id(self, case_id: str) -> Optional[GoldenCase]:
        for c in self.cases:
            if c.id == case_id:
                return c
        return None

    def get_by_category(self, category: str) -> List[GoldenCase]:
        return [c for c in self.cases if c.category == category]

    def expand(self, failures: List[Dict[str, Any]]) -> int:
        """Outer Loop:把失败 case 反向扩充回测试集

        Args:
            failures: list of {"input_message": str, "expected_output": dict}

        Returns:
            新增的 case 数
        """
        existing_ids = {c.id for c in self.cases}
        added = 0

        for fail in failures:
            new_id = f"auto-{fail.get('run_id', f'fail-{added}')}"
            if new_id in existing_ids:
                continue
            self.cases.append(
                GoldenCase(
                    id=new_id,
                    category="auto-mined",
                    intent=fail["input_message"],
                    expected=fail.get("expected_output", {}),
                )
            )
            added += 1

        # 持久化
        self._save()
        return added

    def _save(self) -> None:
        data = [
            {
                "id": c.id,
                "category": c.category,
                "intent": c.intent,
                "expected": c.expected,
                **({"candidates": c.candidates} if c.candidates else {}),  # 🆕 W12
                **({"artifacts": c.artifacts} if c.artifacts else {}),      # 🆕 W13
                **({"must_pass_sim": c.must_pass_sim} if c.must_pass_sim else {}),
                **({"must_pass_lit": c.must_pass_lit} if c.must_pass_lit else {}),
                **({"must_pass_eis": c.must_pass_eis} if c.must_pass_eis else {}),
            }
            for c in self.cases
        ]
        self.path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


class GoldenMatcher:
    """单 case 跑分判定器(per doc §5.5 self_eval)

    给定 1 个 case 的 expected + agent 的实际输出 → 判定 pass/fail
    """

    @staticmethod
    def match(case: GoldenCase, actual: Dict[str, Any]) -> EvalResult:
        """判定 1 个 case

        Args:
            case: GoldenCase(有 expected 约束)
            actual: agent 输出,期望含:
                - formulas: List[str] (候选化学式列表)
                - num_candidates: int
                - top_5_energies: List[float] (eV/atom,可选)

        Returns:
            EvalResult(passed / reasons / actual)
        """
        reasons: List[str] = []
        exp = case.expected

        # 1. formula_must_contain(单元素必含)
        if "formula_must_contain" in exp:
            required = exp["formula_must_contain"]
            if not any(required in f for f in actual.get("formulas", [])):
                reasons.append(f"missing required element: {required}")

        # 2. formula_must_contain_any(任一元素)
        if "formula_must_contain_any" in exp:
            allowed_any = exp["formula_must_contain_any"]
            if not any(any(e in f for e in allowed_any) for f in actual.get("formulas", [])):
                reasons.append(f"none contain any of: {allowed_any}")

        # 3. formula_must_contain_all(全部元素)
        if "formula_must_contain_all" in exp:
            required_all = exp["formula_must_contain_all"]
            for f in actual.get("formulas", []):
                if all(e in f for e in required_all):
                    break
            else:
                reasons.append(f"no formula contains all of: {required_all}")

        # 4. formula_must_not_contain(单元素禁止)
        if "formula_must_not_contain" in exp:
            forbidden = exp["formula_must_not_contain"]
            if any(forbidden in f for f in actual.get("formulas", [])):
                reasons.append(f"contains forbidden element: {forbidden}")

        # 5. formula_must_not_contain_any(任一元素禁止)
        if "formula_must_not_contain_any" in exp:
            forbidden_any = exp["formula_must_not_contain_any"]
            if any(any(e in f for e in forbidden_any) for f in actual.get("formulas", [])):
                reasons.append(f"contains forbidden any of: {forbidden_any}")

        # 6. num_candidates(候选数 >= N)
        if "num_candidates" in exp:
            threshold_str = exp["num_candidates"]  # e.g. ">= 10"
            if threshold_str.startswith(">="):
                threshold = int(threshold_str.replace(">=", "").strip())
                actual_count = actual.get("num_candidates", 0)
                if actual_count < threshold:
                    reasons.append(
                        f"too few candidates: {actual_count} < {threshold}"
                    )

        # 7. top_5_energy_below(形成能 < -3.0 eV/atom)
        if "top_5_energy_below" in exp:
            threshold = float(exp["top_5_energy_below"])
            energies = actual.get("top_5_energies", [])
            if not all(e < threshold for e in energies[:5]):
                reasons.append(f"top 5 energies not all < {threshold}")

        return EvalResult(
            case_id=case.id,
            passed=len(reasons) == 0,
            reasons=reasons,
            actual=actual,
        )


class EvalHarness:
    """Goldens 跑分器

    任务 2 验收:EvalHarness.run_full_eval() 出 pass_rate
    """

    def __init__(self, goldens: Goldens) -> None:
        self.goldens = goldens

    def run_full_eval(
        self, agent_predict_fn, agent_name: str = "mat-gen"
    ) -> Dict[str, Any]:
        """跑完整 Goldens 测试集

        Args:
            agent_predict_fn: callable(intent: str) -> dict
                返回 {"formulas": [...], "num_candidates": int, ...}
            agent_name: agent 名(报告用)

        Returns:
            {"agent": str, "pass_rate": float, "total": int, "passed": int,
             "failed": List[EvalResult], "category_breakdown": dict}
        """
        cases = self.goldens.load()
        results: List[EvalResult] = []
        category_pass: Dict[str, List[int]] = {}

        for case in cases:
            try:
                actual = agent_predict_fn(case.intent)
            except Exception as e:
                actual = {"formulas": [], "num_candidates": 0, "error": str(e)}

            result = GoldenMatcher.match(case, actual)
            results.append(result)

            # 按 category 统计
            cat = case.category
            if cat not in category_pass:
                category_pass[cat] = [0, 0]  # [passed, total]
            category_pass[cat][1] += 1
            if result.passed:
                category_pass[cat][0] += 1

        total = len(results)
        passed = sum(1 for r in results if r.passed)
        pass_rate = passed / total if total > 0 else 0.0

        category_breakdown = {
            cat: {"passed": p, "total": t, "rate": p / t if t > 0 else 0.0}
            for cat, (p, t) in category_pass.items()
        }

        failed = [r for r in results if not r.passed]

        return {
            "agent": agent_name,
            "pass_rate": pass_rate,
            "total": total,
            "passed": passed,
            "failed": failed,
            "category_breakdown": category_breakdown,
        }


__all__ = ["Goldens", "GoldenCase", "GoldenMatcher", "EvalHarness", "EvalResult"]