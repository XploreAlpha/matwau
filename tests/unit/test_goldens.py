"""Goldens 测试集单元测试

任务 2 验收:
1. ✅ Goldens.load() 正确解析 mat-gen.yaml 50 个 case
2. ✅ GoldenMatcher 正确判定 7 类约束(must_contain / must_not / num / energy)
3. ✅ EvalHarness.run_full_eval() 出 pass_rate + category_breakdown
4. ✅ Goldens.expand() 反向扩充失败 case
5. ✅ 边界:缺字段 / 空数据 / 重复 ID
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from tests.goldens.goldens_runner import (  # noqa: E402
    EvalHarness,
    GoldenCase,
    GoldenMatcher,
    Goldens,
)


GOLDENS_PATH = PROJECT_ROOT / "tests" / "goldens" / "mat-gen.yaml"


# ============================================================================
# 1. Goldens.load() YAML 解析
# ============================================================================


def test_goldens_load_mat_gen_50_cases():
    """任务 2 主验收:mat-gen.yaml 含 50 个 case"""
    g = Goldens(str(GOLDENS_PATH))
    cases = g.load()

    assert len(cases) == 50
    assert all(isinstance(c, GoldenCase) for c in cases)


def test_goldens_case_structure():
    """case 字段齐全"""
    g = Goldens(str(GOLDENS_PATH))
    case = g.get_by_id("G001")

    assert case is not None
    assert case.id == "G001"
    assert case.category == "Li-ion cathode"
    assert "Li" in case.intent or "Li-ion" in case.intent
    assert "formula_must_contain" in case.expected
    assert case.expected["formula_must_contain"] == "Li"
    assert case.must_pass_sim is True


def test_goldens_categories():
    """类别统计(8 大类)"""
    g = Goldens(str(GOLDENS_PATH))

    categories = {c.category for c in g.load()}
    assert "Li-ion cathode" in categories
    assert "Solid electrolyte" in categories
    assert "Catalyst" in categories
    assert "Solar cell" in categories


def test_goldens_get_by_category():
    """按类别筛选"""
    g = Goldens(str(GOLDENS_PATH))
    se_cases = g.get_by_category("Solid electrolyte")

    assert len(se_cases) == 15
    assert all(c.category == "Solid electrolyte" for c in se_cases)


def test_goldens_get_by_id_not_found():
    """找不到返回 None"""
    g = Goldens(str(GOLDENS_PATH))
    assert g.get_by_id("G999") is None


# ============================================================================
# 2. GoldenMatcher 7 类约束判定
# ============================================================================


def test_match_formula_must_contain_pass():
    """含必需元素 → pass"""
    case = GoldenCase(
        id="test1",
        category="test",
        intent="test",
        expected={"formula_must_contain": "Li"},
    )
    actual = {"formulas": ["LiCoO2", "LiFePO4"], "num_candidates": 2}
    result = GoldenMatcher.match(case, actual)

    assert result.passed
    assert result.reasons == []


def test_match_formula_must_contain_fail():
    """缺必需元素 → fail"""
    case = GoldenCase(
        id="test2",
        category="test",
        intent="test",
        expected={"formula_must_contain": "Li"},
    )
    actual = {"formulas": ["NaCoO2", "KFePO4"], "num_candidates": 2}
    result = GoldenMatcher.match(case, actual)

    assert not result.passed
    assert "missing required element" in result.reasons[0]


def test_match_must_contain_any_pass():
    """含任一元素 → pass"""
    case = GoldenCase(
        id="test3",
        category="test",
        intent="test",
        expected={"formula_must_contain_any": ["Li", "Na", "Mg"]},
    )
    actual = {"formulas": ["Na3Zr2Si2PO12"]}
    result = GoldenMatcher.match(case, actual)

    assert result.passed


def test_match_must_contain_all_pass():
    """含全部元素 → pass"""
    case = GoldenCase(
        id="test4",
        category="test",
        intent="test",
        expected={"formula_must_contain_all": ["Li", "Fe", "P", "O"]},
    )
    actual = {"formulas": ["LiFePO4", "NaCoO2"]}
    result = GoldenMatcher.match(case, actual)

    assert result.passed


def test_match_must_not_contain_fail():
    """含禁止元素 → fail"""
    case = GoldenCase(
        id="test5",
        category="test",
        intent="test",
        expected={"formula_must_not_contain": "Co"},
    )
    actual = {"formulas": ["LiCoO2"]}
    result = GoldenMatcher.match(case, actual)

    assert not result.passed
    assert "forbidden element" in result.reasons[0]


def test_match_must_not_contain_any_fail():
    """含禁止任一元素 → fail"""
    case = GoldenCase(
        id="test6",
        category="test",
        intent="test",
        expected={"formula_must_not_contain_any": ["Co", "Ni", "Pt"]},
    )
    actual = {"formulas": ["LiNiO2"]}
    result = GoldenMatcher.match(case, actual)

    assert not result.passed


def test_match_num_candidates_pass():
    """候选数 >= 阈值 → pass"""
    case = GoldenCase(
        id="test7",
        category="test",
        intent="test",
        expected={"num_candidates": ">= 10"},
    )
    actual = {"formulas": ["f" + str(i) for i in range(15)], "num_candidates": 15}
    result = GoldenMatcher.match(case, actual)

    assert result.passed


def test_match_num_candidates_fail():
    """候选数 < 阈值 → fail"""
    case = GoldenCase(
        id="test8",
        category="test",
        intent="test",
        expected={"num_candidates": ">= 20"},
    )
    actual = {"formulas": ["f1", "f2"], "num_candidates": 2}
    result = GoldenMatcher.match(case, actual)

    assert not result.passed
    assert "too few candidates" in result.reasons[0]


def test_match_top_5_energy_below_pass():
    """top 5 形成能 < 阈值 → pass"""
    case = GoldenCase(
        id="test9",
        category="test",
        intent="test",
        expected={"top_5_energy_below": -3.0},
    )
    actual = {
        "formulas": ["f" + str(i) for i in range(10)],
        "top_5_energies": [-3.5, -3.8, -4.0, -4.2, -3.1],
    }
    result = GoldenMatcher.match(case, actual)

    assert result.passed


def test_match_top_5_energy_below_fail():
    """top 5 形成能 >= 阈值 → fail"""
    case = GoldenCase(
        id="test10",
        category="test",
        intent="test",
        expected={"top_5_energy_below": -3.0},
    )
    actual = {
        "formulas": ["f" + str(i) for i in range(10)],
        "top_5_energies": [-2.5, -3.5, -3.8, -4.0, -2.9],
    }
    result = GoldenMatcher.match(case, actual)

    assert not result.passed


# ============================================================================
# 3. EvalHarness.run_full_eval()
# ============================================================================


def test_eval_harness_perfect_agent():
    """完美的 agent → pass_rate 100%(完美 mock 直接读 case.expected 构造满足约束的输出)"""
    g = Goldens(str(GOLDENS_PATH))
    eh = EvalHarness(g)
    cases_by_intent = {c.intent: c for c in g.load()}

    def perfect_agent(intent: str) -> dict:
        """完美 mock:读 case.expected,直接构造满足约束的输出"""
        case = cases_by_intent[intent]
        exp = case.expected

        must_contain_all: list = exp.get("formula_must_contain_all", [])
        must_contain_any: list = exp.get("formula_must_contain_any", [])
        must_contain_single: str = exp.get("formula_must_contain", "")

        must_not: set = set()
        if "formula_must_not_contain" in exp:
            must_not.add(exp["formula_must_not_contain"])
        if "formula_must_not_contain_any" in exp:
            must_not.update(exp["formula_must_not_contain_any"])

        safe_pool = ["Li", "Na", "Mg", "Ca", "K", "Ba", "Ti", "V", "Mn", "Fe"]
        safe_pool += ["Ni", "Cu", "Zn", "Zr", "Si", "P", "S", "Cl", "Br", "I"]
        safe_pool += ["O", "N", "C", "H", "B", "F", "Mo", "W", "Y", "La"]
        safe_pool = [e for e in safe_pool if e not in must_not]

        formulas: list = []

        # 必须 1 个公式含全部元素(must_contain_all)
        if must_contain_all:
            formulas.append("".join(must_contain_all) + safe_pool[0])

        # must_contain_any:至少 1 个候选含其中任一
        if must_contain_any:
            formulas.append(must_contain_any[0] + safe_pool[1] + safe_pool[2])

        # must_contain_single:至少 1 个候选含该元素
        if must_contain_single:
            formulas.append(must_contain_single + safe_pool[0] + safe_pool[1])

        # 必须满足 num_candidates
        target_count = 50
        if "num_candidates" in exp:
            threshold = int(exp["num_candidates"].replace(">=", "").strip())
            target_count = max(target_count, threshold + 5)

        while len(formulas) < target_count:
            formulas.append(safe_pool[len(formulas) % len(safe_pool)] * 2)

        return {
            "formulas": list(dict.fromkeys(formulas)),
            "num_candidates": len(formulas),
            "top_5_energies": [-3.5, -3.8, -4.0, -4.2, -3.1],
        }

    result = eh.run_full_eval(perfect_agent, agent_name="perfect-mock")

    assert result["total"] == 50
    assert result["passed"] == 50, (
        f"failed: {[(r.case_id, r.reasons) for r in result['failed']][:5]}"
    )
    assert result["pass_rate"] == 1.0
    assert result["agent"] == "perfect-mock"


def test_eval_harness_zero_agent():
    """零 agent → pass_rate 0%"""
    g = Goldens(str(GOLDENS_PATH))
    eh = EvalHarness(g)

    def zero_agent(intent: str) -> dict:
        return {"formulas": [], "num_candidates": 0}

    result = eh.run_full_eval(zero_agent, agent_name="zero-mock")

    assert result["total"] == 50
    assert result["passed"] == 0
    assert result["pass_rate"] == 0.0


def test_eval_harness_category_breakdown():
    """按类别统计"""
    g = Goldens(str(GOLDENS_PATH))
    eh = EvalHarness(g)

    def zero_agent(intent: str) -> dict:
        return {"formulas": [], "num_candidates": 0}

    result = eh.run_full_eval(zero_agent)
    cb = result["category_breakdown"]

    # 8 大类(每个 case 都属于一个 category)
    assert "Li-ion cathode" in cb
    assert "Solid electrolyte" in cb
    assert cb["Li-ion cathode"]["total"] == 15
    assert cb["Solid electrolyte"]["total"] == 15


# ============================================================================
# 4. Goldens.expand()(Outer Loop 反向扩充)
# ============================================================================


def test_goldens_expand_mined_failures(tmp_path):
    """把失败 case 反向扩充进测试集"""
    # 写 1 个临时 Goldens 文件
    goldens_file = tmp_path / "test.yaml"
    goldens_file.write_text(
        """- id: G001
  category: test
  intent: 'test case 1'
  expected:
    formula_must_contain: Li
""",
        encoding="utf-8",
    )

    g = Goldens(str(goldens_file))
    assert len(g.load()) == 1

    # 加 2 个失败 case
    added = g.expand(
        [
            {
                "run_id": "run-fail-001",
                "input_message": "设计 Li-ion cathode",
                "expected_output": {"formula_must_contain": "Li"},
            },
            {
                "run_id": "run-fail-002",
                "input_message": "找固态电解质",
                "expected_output": {"formula_must_not_contain": "Co"},
            },
        ]
    )

    assert added == 2
    cases = g.load()
    assert len(cases) == 3
    auto_ids = [c.id for c in cases if c.id.startswith("auto-")]
    assert len(auto_ids) == 2


def test_goldens_expavoids_duplicate_id(tmp_path):
    """重复 ID 不重复加"""
    goldens_file = tmp_path / "test.yaml"
    goldens_file.write_text(
        """- id: G001
  category: test
  intent: 'test'
  expected: {}
- id: auto-run-fail-001
  category: auto-mined
  intent: 'already exists'
  expected: {}
""",
        encoding="utf-8",
    )

    g = Goldens(str(goldens_file))
    added = g.expand(
        [{"run_id": "run-fail-001", "input_message": "x", "expected_output": {}}]
    )

    assert added == 0  # 已存在,不重复加
    assert len(g.load()) == 2


# ============================================================================
# 5. 边界 + 错误处理
# ============================================================================


def test_goldens_missing_file():
    """文件不存在 → FileNotFoundError"""
    with pytest.raises(FileNotFoundError):
        Goldens("/nonexistent/path/goldens.yaml")


def test_goldens_invalid_yaml_format(tmp_path):
    """YAML 格式错误(不是 list)→ ValueError"""
    goldens_file = tmp_path / "bad.yaml"
    goldens_file.write_text("not_a_list: just_a_dict", encoding="utf-8")

    with pytest.raises(ValueError, match="必须是 list"):
        Goldens(str(goldens_file))


def test_eval_harness_partial_pass():
    """部分通过 — 用无 Co/Ni 公式避免 must_not_contain 干扰,验证一半一半比例"""
    g = Goldens(str(GOLDENS_PATH))
    eh = EvalHarness(g)

    call_count = [0]

    def half_agent(intent: str) -> dict:
        call_count[0] += 1
        if call_count[0] % 2 == 0:
            # 偶数次:50 个候选,无 Co/Ni
            return {
                "formulas": ["LiFePO4"] + [f"LiB{i}" for i in range(49)],
                "num_candidates": 50,
                "top_5_energies": [-3.5, -3.8, -4.0, -4.2, -3.1],
            }
        return {"formulas": [], "num_candidates": 0}

    result = eh.run_full_eval(half_agent)

    # 偶数次 ~25 个通过(部分 must_contain: Pt/Au 等仍 fail),实际 25-35%
    assert 0.2 < result["pass_rate"] < 0.5


def test_eval_harness_failure_collection():
    """失败 case 列表收集"""
    g = Goldens(str(GOLDENS_PATH))
    eh = EvalHarness(g)

    def zero_agent(intent: str) -> dict:
        return {"formulas": [], "num_candidates": 0}

    result = eh.run_full_eval(zero_agent)
    failed = result["failed"]

    assert len(failed) == 50
    assert all(not r.passed for r in failed)
    # 至少每条都有 reason
    assert all(len(r.reasons) > 0 for r in failed)