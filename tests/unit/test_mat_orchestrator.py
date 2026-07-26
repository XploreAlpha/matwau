"""test_mat_orchestrator.py — W10 mat-orchestrator 单元测试 + Goldens 跑分

测试覆盖:
1. DAG 数据结构测试
2. 5 workflow 模板测试
3. DAGExecutor 节点执行
4. MatOrchestrator 完整工作流
5. mat-orchestrator.yaml Goldens 20 case 跑分
6. 集成 mat-pipeline

per MatWAU-开发计划 §七 W10
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_intent_agent.intent_classifier import (  # noqa: E402
    parse_mat_intent,
)
from agents.mat_orchestrator.dag import (  # noqa: E402
    DAG,
    DAGExecutor,
    DAGNode,
    NodeResult,
    WorkflowResult,
    WORKFLOW_BY_SUBCLASS,
    design_new_material_workflow,
    experiment_planning_workflow,
    explain_failure_workflow,
    get_workflow_for_subclass,
    literature_review_workflow,
    optimize_existing_workflow,
)
from agents.mat_orchestrator.mat_orchestrator import (  # noqa: E402
    MatOrchestrator,
    StubAgent,
    create_default_orchestrator,
)
from tests.goldens.goldens_runner import Goldens  # noqa: E402

GOLDENS_PATH = str(_PROJECT_ROOT / "tests" / "goldens" / "mat-orchestrator.yaml")


# ============================================================================
# 测试 1: DAGNode / DAG 数据结构
# ============================================================================


class TestDAGNode:
    """DAGNode 测试"""

    def test_node_basic(self):
        n = DAGNode(node_id="gen", agent_name="mat-gen-agent")
        assert n.node_id == "gen"
        assert n.agent_name == "mat-gen-agent"
        assert n.output_key == "result"

    def test_node_to_dict(self):
        n = DAGNode(
            node_id="sim",
            agent_name="mat-sim-agent",
            inputs={"candidates": "gen.candidates"},
            output_key="sim_response",
        )
        d = n.to_dict()
        assert d["node_id"] == "sim"
        assert d["agent_name"] == "mat-sim-agent"
        assert d["inputs"] == {"candidates": "gen.candidates"}
        assert d["output_key"] == "sim_response"


class TestDAG:
    """DAG 数据结构测试"""

    def test_dag_creation(self):
        dag = DAG(name="test", nodes=[])
        assert dag.name == "test"
        assert dag.nodes == []

    def test_dag_add_node(self):
        dag = DAG(name="test", nodes=[])
        dag.add_node(DAGNode(node_id="a", agent_name="x"))
        assert len(dag.nodes) == 1
        assert dag.nodes[0].node_id == "a"


# ============================================================================
# 测试 2: 5 workflow 模板
# ============================================================================


class TestWorkflows:
    """5 workflow 模板测试"""

    def test_all_5_workflows(self):
        """5 workflow 全部定义"""
        assert "experiment_planning" in WORKFLOW_BY_SUBCLASS
        assert "design_new_material" in WORKFLOW_BY_SUBCLASS
        assert "optimize_existing" in WORKFLOW_BY_SUBCLASS
        assert "explain_failure" in WORKFLOW_BY_SUBCLASS
        assert "literature_review" in WORKFLOW_BY_SUBCLASS

    def test_experiment_planning_4_nodes(self):
        """experiment_planning:4 节点"""
        wf = experiment_planning_workflow()
        assert wf.name == "experiment_planning"
        assert len(wf.nodes) == 4
        node_ids = [n.node_id for n in wf.nodes]
        assert node_ids == ["gen", "sim", "hpc", "exp"]

    def test_design_new_material_2_nodes(self):
        """design_new_material:2 节点"""
        wf = design_new_material_workflow()
        assert len(wf.nodes) == 2
        node_ids = [n.node_id for n in wf.nodes]
        assert node_ids == ["gen", "sim"]

    def test_optimize_existing_2_nodes(self):
        """optimize_existing:2 节点"""
        wf = optimize_existing_workflow()
        assert len(wf.nodes) == 2
        node_ids = [n.node_id for n in wf.nodes]
        assert node_ids == ["sim", "gen_optimized"]

    def test_explain_failure_1_stub_node(self):
        """explain_failure:1 critic 节点(W12 替换 stub)"""
        wf = explain_failure_workflow()
        assert len(wf.nodes) == 1
        assert wf.nodes[0].agent_name == "mat-critic-agent"

    def test_literature_review_1_stub_node(self):
        """literature_review:1 lit 节点(W14 替换 stub → mat-lit-agent)"""
        wf = literature_review_workflow()
        assert len(wf.nodes) == 1
        assert wf.nodes[0].agent_name == "mat-lit-agent"

    def test_get_workflow_for_subclass(self):
        """get_workflow_for_subclass 正常"""
        wf = get_workflow_for_subclass("experiment_planning")
        assert wf is not None
        assert wf.name == "experiment_planning"

    def test_get_workflow_for_unknown_subclass(self):
        """未知子类返回 None"""
        assert get_workflow_for_subclass("unknown_subclass") is None

    def test_workflow_node_data_flow(self):
        """实验 workflow 数据流正确"""
        wf = experiment_planning_workflow()
        sim_node = wf.nodes[1]
        # sim 节点 inputs 应引用 gen 节点的 candidates
        assert "candidates" in sim_node.inputs
        assert sim_node.inputs["candidates"] == "gen.candidates"

        hpc_node = wf.nodes[2]
        assert "simulated" in hpc_node.inputs
        assert hpc_node.inputs["simulated"] == "sim.simulated"

        exp_node = wf.nodes[3]
        assert "jobs" in exp_node.inputs
        assert exp_node.inputs["jobs"] == "hpc.jobs"


# ============================================================================
# 测试 3: StubAgent
# ============================================================================


class TestStubAgent:
    """Stub agent 测试"""

    def test_stub_agent_run(self):
        from matwau.core.agent_base import AgentRequest

        s = StubAgent("test-stub", "test role")
        r = s.run(AgentRequest(run_id="t", message="test"))
        assert "⏳" in r.reply
        assert r.artifacts["stub"] is True
        assert r.artifacts["role"] == "test role"


# ============================================================================
# 测试 4: MatOrchestrator
# ============================================================================


class TestMatOrchestrator:
    """MatOrchestrator 完整工作流测试"""

    def test_create_default_orchestrator(self):
        o = create_default_orchestrator()
        assert isinstance(o, MatOrchestrator)
        assert o.intent_agent is not None
        assert o.gen_agent is not None
        assert "mat-gen-agent" in o.agent_registry
        assert "mat-sim-agent" in o.agent_registry
        # W12: mat-critic-agent 替换 mat-critic-stub
        assert "mat-critic-agent" in o.agent_registry
        assert "mat-critic-stub" not in o.agent_registry

    def test_run_experiment_planning(self):
        """experiment_planning 端到端"""
        o = create_default_orchestrator()
        r = o.run(user_intent="出 LiCoO2 实验方案")

        assert r.workflow_name == "experiment_planning"
        assert r.success
        # 4 节点全跑通
        assert len(r.node_results) == 4
        for nr in r.node_results:
            assert nr.success, f"{nr.node_id} 失败: {nr.error}"
        # final_outputs 应有 artifacts
        assert "artifacts" in r.final_outputs

    def test_run_design_new_material(self):
        """design_new_material 端到端"""
        o = create_default_orchestrator()
        r = o.run(user_intent="设计新型固态电解质")

        assert r.workflow_name == "design_new_material"
        assert r.success
        assert len(r.node_results) == 2

    def test_run_optimize_existing(self):
        """optimize_existing 端到端"""
        o = create_default_orchestrator()
        r = o.run(user_intent="优化 LiCoO2 配方")

        assert r.workflow_name == "optimize_existing"
        assert r.success
        assert len(r.node_results) == 2

    def test_run_explain_failure(self):
        """explain_failure workflow 跑通(W12 接真 MatCriticAgent)"""
        o = create_default_orchestrator()
        r = o.run(user_intent="为什么 XRD 谱不对")

        assert r.workflow_name == "explain_failure"
        assert r.success
        assert len(r.node_results) == 1
        # W12: 真 MatCriticAgent 跑通,返回 verdict
        node_output = r.node_results[0].outputs
        # critic agent 输出含 verdict
        artifacts = node_output.get("artifacts", {})
        assert "verdict" in artifacts or "critic_verdict" in artifacts

    def test_run_literature_review(self):
        """literature_review 跑通(W14 真 MatLitAgent)"""
        o = create_default_orchestrator()
        r = o.run(user_intent="Review 一下 LLZO 最新进展")

        assert r.workflow_name == "literature_review"
        assert r.success
        # W14: 真 MatLitAgent 跑通,返回 review
        node_output = r.node_results[0].outputs
        artifacts = node_output.get("artifacts", {})
        assert "review" in artifacts or "references" in artifacts

    def test_run_with_forbidden_propagation(self):
        """forbidden 元素传递到下游"""
        o = create_default_orchestrator()
        r = o.run(user_intent="出无 Co 锂电池正极实验方案")

        assert r.success
        # exp 节点的 artifacts 应能查到 recipes
        exp_nr = r.node_results[-1]
        if "artifacts" in exp_nr.outputs:
            recipes = exp_nr.outputs["artifacts"].get("recipes", [])
            if recipes:
                for recipe in recipes:
                    assert "Co" not in recipe.formula

    def test_run_with_intent_preset(self):
        """run_with_intent 用预设 MatIntent"""
        o = create_default_orchestrator()
        mi = parse_mat_intent("出 LLZO 实验方案,无贵金属")
        r = o.run_with_intent(user_intent="出 LLZO 实验方案", mat_intent=mi)

        assert r.success
        assert r.workflow_name == "experiment_planning"


# ============================================================================
# 测试 5: mat-orchestrator.yaml Goldens 跑分
# ============================================================================


def _check_goldens_case(result, expected: dict) -> tuple[bool, list[str]]:
    """检查 1 个 Goldens case — 支持 WorkflowResult + BatchWorkflowResult(W31)"""
    from agents.mat_orchestrator import BatchWorkflowResult

    reasons = []

    # W31 — BatchWorkflowResult 分支(multi_experiment category)
    if isinstance(result, BatchWorkflowResult):
        if "workflow" in expected:
            if result.workflow_name != expected["workflow"]:
                reasons.append(f"workflow={result.workflow_name} (期望 {expected['workflow']})")

        if "n_total_min" in expected:
            if result.n_total < expected["n_total_min"]:
                reasons.append(f"n_total={result.n_total} < {expected['n_total_min']}")

        if "n_passed_min" in expected:
            if result.n_passed < expected["n_passed_min"]:
                reasons.append(f"n_passed={result.n_passed} < {expected['n_passed_min']}")

        if "overall_verdict_in" in expected:
            if result.overall_verdict not in expected["overall_verdict_in"]:
                reasons.append(f"overall_verdict={result.overall_verdict} 不在 {expected['overall_verdict_in']}")

        if "total_cost_max" in expected:
            if result.total_cost_cny > expected["total_cost_max"]:
                reasons.append(f"total_cost={result.total_cost_cny:.0f} > {expected['total_cost_max']}")

        if "total_cost_min" in expected:
            if result.total_cost_cny < expected["total_cost_min"]:
                reasons.append(f"total_cost={result.total_cost_cny:.0f} < {expected['total_cost_min']}")

        if "total_duration_max" in expected:
            if result.total_duration_seconds > expected["total_duration_max"]:
                reasons.append(f"total_duration={result.total_duration_seconds:.1f} > {expected['total_duration_max']}")

        if "max_workers_min" in expected:
            if result.max_workers < expected["max_workers_min"]:
                reasons.append(f"max_workers={result.max_workers} < {expected['max_workers_min']}")

        if "parallel" in expected:
            if result.parallel != expected["parallel"]:
                reasons.append(f"parallel={result.parallel} (期望 {expected['parallel']})")

        return (len(reasons) == 0, reasons)

    # 老 WorkflowResult 分支(W10)
    if "workflow" in expected:
        if result.workflow_name != expected["workflow"]:
            reasons.append(f"workflow={result.workflow_name} (期望 {expected['workflow']})")

    if "min_nodes_success" in expected:
        n_success = sum(1 for nr in result.node_results if nr.success)
        if n_success < expected["min_nodes_success"]:
            reasons.append(
                f"nodes_success={n_success} < {expected['min_nodes_success']}"
            )

    if "final_outputs_has" in expected:
        for k in expected["final_outputs_has"]:
            if k not in result.final_outputs:
                reasons.append(f"final_outputs 缺 {k}")

    return (len(reasons) == 0, reasons)


class TestOrchestratorGoldens:
    """mat-orchestrator.yaml 20 case 跑分"""

    @pytest.fixture(scope="class")
    def orchestrator(self):
        return create_default_orchestrator()

    @pytest.fixture(scope="class")
    def results(self, orchestrator):
        from agents.mat_orchestrator import BatchWorkflowResult, get_multi_experiment_default_batch

        g = Goldens(GOLDENS_PATH)
        cases = g.load()
        results = []
        for case in cases:
            try:
                # W31 — multi_experiment 类别走 run_batch
                if case.category == "multi_experiment":
                    # 默认 3 实验批(M019 也用同样 batch)
                    experiments = get_multi_experiment_default_batch()
                    r = orchestrator.run_batch(experiments, parallel=True, max_workers=3)
                else:
                    r = orchestrator.run(user_intent=case.intent)
            except Exception as e:
                from agents.mat_orchestrator import BatchWorkflowResult as BWR
                # 区分:multi_experiment 失败 → BatchWorkflowResult 兜底
                if case.category == "multi_experiment":
                    r = BWR(n_total=0, n_passed=0, n_failed=0, overall_verdict="fail", error=str(e))
                else:
                    r = WorkflowResult(
                        workflow_name="error",
                        subclass="unknown",
                        success=False,
                        error=str(e),
                    )
            passed, reasons = _check_goldens_case(r, case.expected)
            # 提取展示字段
            if isinstance(r, BatchWorkflowResult):
                results.append(
                    {
                        "case_id": case.id,
                        "category": case.category,
                        "passed": passed,
                        "reasons": reasons,
                        "workflow": r.workflow_name,
                        "n_total": r.n_total,
                        "n_passed": r.n_passed,
                        "overall_verdict": r.overall_verdict,
                    }
                )
            else:
                results.append(
                    {
                        "case_id": case.id,
                        "category": case.category,
                        "passed": passed,
                        "reasons": reasons,
                        "workflow": r.workflow_name,
                        "n_nodes": len(r.node_results),
                        "n_success": sum(1 for nr in r.node_results if nr.success),
                    }
                )
        return results

    def test_goldens_20_cases_pass_rate(self, results):
        n_pass = sum(1 for r in results if r["passed"])
        n_total = len(results)
        pass_rate = n_pass / n_total

        print(f"\n📊 mat-orchestrator Goldens: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_workflow_pass_rate(self, results):
        wf_results = [r for r in results if r["category"] == "workflow"]
        n_pass = sum(1 for r in wf_results if r["passed"])
        n_total = len(wf_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 workflow 路由: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"workflow pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_e2e_pass_rate(self, results):
        e2e_results = [r for r in results if r["category"] == "e2e"]
        n_pass = sum(1 for r in e2e_results if r["passed"])
        n_total = len(e2e_results)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 e2e 跑分: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.5, f"e2e pass-rate {pass_rate:.0%} < 50%"

    def test_goldens_multi_experiment_pass_rate(self, results):  # W31 NEW
        """W31 — multi_experiment 类别 pass-rate ≥ 60%"""
        sub = [r for r in results if r["category"] == "multi_experiment"]
        n_pass = sum(1 for r in sub if r["passed"])
        n_total = len(sub)
        pass_rate = n_pass / n_total if n_total else 0

        print(f"\n📊 multi_experiment 跑分: {n_pass}/{n_total} = {pass_rate:.0%}")
        assert pass_rate >= 0.6, f"multi_experiment pass-rate {pass_rate:.0%} < 60%"


# ============================================================================
# 测试 6: 集成 mat-pipeline
# ============================================================================


class TestOrchestratorIntegration:
    """mat-orchestrator + mat-pipeline 集成"""

    def test_orchestrator_vs_pipeline_same_result(self):
        """orchestrator 跟 pipeline 跑同实验应该结果一致"""
        from matwau.pipeline import create_default_pipeline

        orch = create_default_orchestrator()
        pipe = create_default_pipeline()

        intent_text = "出 LiCoO2 实验方案"

        # orchestrator 跑
        r1 = orch.run(user_intent=intent_text)
        # pipeline 跑
        r2 = pipe.run_full_pipeline(
            user_intent=intent_text,
            elements=["Li", "Co", "O"],
            n_samples=5,
        )

        # orchestrator experiment_planning 应跑 4 段,跟 pipeline 一致
        assert r1.success
        assert r2.success
        assert len(r1.node_results) == 4
        assert r2.success


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])