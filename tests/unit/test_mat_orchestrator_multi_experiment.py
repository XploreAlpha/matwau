"""test_mat_orchestrator_multi_experiment.py — W31 mat-orchestrator 多实验并行单元测试

覆盖(W31 拍板 40 测试):
- TestBatchDataClasses          6 — ExperimentResult / BatchWorkflowResult dataclass 行为
- TestParallelBatchRunner       8 — fan-out + 异常隔离 + 顺序保持 + 串行兜底
- TestMatOrchestratorRunBatch   10 — 默认 3 实验 + custom + parallel=False + 空 list + n_passed 计数
- TestChemistCriticHandoff      8 — chemist 暴露完整 ChemistReport + critic L4 触发
- TestMultiExperimentWorkflow   4 — workflow 模板 + WORKFLOW_BY_SUBCLASS 注册
- TestGoldens                   4 — BatchWorkflowResult.to_dict() goldens-friendly
"""
from __future__ import annotations

import sys
from pathlib import Path

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

import pytest

from matwau.core.agent_base import AgentRequest

from agents.mat_orchestrator import (
    BatchWorkflowResult,
    ExperimentResult,
    MatOrchestrator,
    ParallelBatchRunner,
    WORKFLOW_BY_SUBCLASS,
    get_multi_experiment_default_batch,
    multi_experiment_characterization_workflow,
)
from agents.mat_chemist_agent import (
    ChemistTask,
    RobotStep,
    MatChemistAgent,
    get_default_pmma_workflow,
)
from agents.mat_critic_agent import MatCriticAgent


# ============================================================================
# TestBatchDataClasses — ExperimentResult / BatchWorkflowResult dataclass (6 tests)
# ============================================================================


class TestBatchDataClasses:
    """W31 dataclass 行为测试"""

    def test_experiment_result_to_dict(self):
        """ExperimentResult.to_dict() 含全部字段"""
        er = ExperimentResult(
            experiment_id="exp-0-abc",
            target_sample="Inconel 718",
            chemist_report=None,
            critic_verdict=None,
            cost_cny=500.0,
            duration_seconds=1.5,
            verdict="pass",
        )
        d = er.to_dict()
        assert d["experiment_id"] == "exp-0-abc"
        assert d["target_sample"] == "Inconel 718"
        assert d["verdict"] == "pass"
        assert d["cost_cny"] == 500.0
        assert d["duration_seconds"] == 1.5
        assert d["has_chemist_report"] is False
        assert d["has_critic_verdict"] is False

    def test_experiment_result_with_error(self):
        """ExperimentResult 含 error 字段"""
        er = ExperimentResult(
            experiment_id="err-0",
            target_sample="<unknown>",
            chemist_report=None,
            critic_verdict=None,
            cost_cny=0.0,
            duration_seconds=0.0,
            verdict="fail",
            error="ValueError: bad input",
        )
        assert er.error == "ValueError: bad input"
        assert er.verdict == "fail"

    def test_batch_workflow_result_to_dict(self):
        """BatchWorkflowResult.to_dict() 含 summary + experiment_results"""
        er = ExperimentResult(
            experiment_id="exp-0",
            target_sample="TiO2",
            chemist_report=None,
            critic_verdict=None,
            cost_cny=200.0,
            duration_seconds=0.5,
            verdict="pass",
        )
        batch = BatchWorkflowResult(
            n_total=1, n_passed=1, n_warned=0, n_failed=0,
            experiment_results=[er],
            total_cost_cny=200.0,
            total_duration_seconds=0.5,
            overall_verdict="pass",
        )
        d = batch.to_dict()
        assert d["n_total"] == 1
        assert d["overall_verdict"] == "pass"
        assert len(d["experiment_results"]) == 1

    def test_batch_workflow_result_all_passed_true(self):
        """all_passed() — 全部 pass 返回 True"""
        batch = BatchWorkflowResult(
            n_total=3, n_passed=3, n_warned=0, n_failed=0,
        )
        assert batch.all_passed() is True

    def test_batch_workflow_result_all_passed_empty(self):
        """all_passed() — 空批次返回 False"""
        batch = BatchWorkflowResult(n_total=0)
        assert batch.all_passed() is False

    def test_batch_workflow_result_failed_samples(self):
        """failed_samples() 返回 verdict=fail 的 sample 名"""
        results = [
            ExperimentResult(experiment_id="1", target_sample="Inconel 718",
                             chemist_report=None, critic_verdict=None,
                             cost_cny=0.0, duration_seconds=0.0, verdict="pass"),
            ExperimentResult(experiment_id="2", target_sample="PMMA",
                             chemist_report=None, critic_verdict=None,
                             cost_cny=0.0, duration_seconds=0.0, verdict="fail"),
            ExperimentResult(experiment_id="3", target_sample="TiO2",
                             chemist_report=None, critic_verdict=None,
                             cost_cny=0.0, duration_seconds=0.0, verdict="warn"),
        ]
        batch = BatchWorkflowResult(
            n_total=3, n_passed=1, n_warned=1, n_failed=1,
            experiment_results=results,
        )
        assert batch.failed_samples() == ["PMMA"]


# ============================================================================
# TestParallelBatchRunner — ThreadPoolExecutor (8 tests)
# ============================================================================


class TestParallelBatchRunner:
    """ParallelBatchRunner 行为测试"""

    def test_empty_list(self):
        """空 list → 空结果"""
        runner = ParallelBatchRunner(max_workers=4)
        assert runner.run_all([]) == []

    def test_serial_fallback_max_workers_1(self):
        """max_workers=1 → 串行执行"""
        runner = ParallelBatchRunner(max_workers=1)
        results = runner.run_all([
            lambda: ExperimentResult(experiment_id="0", target_sample="A",
                                      chemist_report=None, critic_verdict=None,
                                      cost_cny=0.0, duration_seconds=0.0, verdict="pass"),
            lambda: ExperimentResult(experiment_id="1", target_sample="B",
                                      chemist_report=None, critic_verdict=None,
                                      cost_cny=0.0, duration_seconds=0.0, verdict="pass"),
        ])
        assert len(results) == 2
        assert results[0].target_sample == "A"
        assert results[1].target_sample == "B"

    def test_single_callable_serial_path(self):
        """N=1 → 走串行兜底路径"""
        runner = ParallelBatchRunner(max_workers=4)
        results = runner.run_all([
            lambda: ExperimentResult(experiment_id="solo", target_sample="X",
                                      chemist_report=None, critic_verdict=None,
                                      cost_cny=0.0, duration_seconds=0.0, verdict="pass"),
        ])
        assert len(results) == 1
        assert results[0].experiment_id == "solo"

    def test_order_preservation_parallel(self):
        """并行执行也保持输入顺序"""
        runner = ParallelBatchRunner(max_workers=4)
        results = runner.run_all([
            lambda i=i: ExperimentResult(
                experiment_id=f"exp-{i}", target_sample=f"S{i}",
                chemist_report=None, critic_verdict=None,
                cost_cny=0.0, duration_seconds=0.0, verdict="pass",
            )
            for i in range(5)
        ])
        for i, r in enumerate(results):
            assert r.target_sample == f"S{i}"

    def test_exception_isolation(self):
        """单个 callable 抛异常不破坏其他"""
        runner = ParallelBatchRunner(max_workers=4)

        def good():
            return ExperimentResult(experiment_id="0", target_sample="A",
                                    chemist_report=None, critic_verdict=None,
                                    cost_cny=0.0, duration_seconds=0.0, verdict="pass")

        def bad():
            raise ValueError("test error")

        def good2():
            return ExperimentResult(experiment_id="2", target_sample="C",
                                    chemist_report=None, critic_verdict=None,
                                    cost_cny=0.0, duration_seconds=0.0, verdict="pass")

        results = runner.run_all([good, bad, good2])
        assert results[0].verdict == "pass"
        assert results[1].verdict == "fail"
        assert results[1].error is not None
        assert "ValueError" in results[1].error
        assert results[2].verdict == "pass"

    def test_max_workers_validation(self):
        """max_workers < 1 → ValueError"""
        with pytest.raises(ValueError):
            ParallelBatchRunner(max_workers=0)

    def test_max_workers_default_4(self):
        """默认 max_workers=4"""
        runner = ParallelBatchRunner()
        assert runner.max_workers == 4

    def test_exception_isolation_serial(self):
        """串行模式也异常隔离"""
        runner = ParallelBatchRunner(max_workers=1)

        def good():
            return ExperimentResult(experiment_id="0", target_sample="A",
                                    chemist_report=None, critic_verdict=None,
                                    cost_cny=0.0, duration_seconds=0.0, verdict="pass")

        def bad():
            raise RuntimeError("serial fail")

        results = runner.run_all([good, bad])
        assert results[0].verdict == "pass"
        assert results[1].verdict == "fail"
        assert "RuntimeError" in results[1].error


# ============================================================================
# TestMatOrchestratorRunBatch — MatOrchestrator.run_batch (10 tests)
# ============================================================================


class TestMatOrchestratorRunBatch:
    """run_batch API 端到端测试"""

    def test_run_batch_default_3_experiments(self):
        """默认 3 实验 → batch 含 3 result"""
        orch = MatOrchestrator()
        experiments = get_multi_experiment_default_batch()
        batch = orch.run_batch(experiments, parallel=True, max_workers=3)

        assert batch.n_total == 3
        assert len(batch.experiment_results) == 3
        # 顺序保持
        assert batch.experiment_results[0].target_sample == "Inconel 718"
        assert batch.experiment_results[1].target_sample == "PMMA"
        assert batch.experiment_results[2].target_sample == "TiO2"

    def test_run_batch_parallel_false(self):
        """parallel=False → 串行"""
        orch = MatOrchestrator()
        experiments = get_multi_experiment_default_batch()
        batch = orch.run_batch(experiments, parallel=False, max_workers=1)
        assert batch.parallel is False
        assert batch.max_workers == 1
        assert batch.n_total == 3

    def test_run_batch_empty_list(self):
        """空 list → 兜底 batch"""
        orch = MatOrchestrator()
        batch = orch.run_batch([], parallel=True, max_workers=4)
        assert batch.n_total == 0
        assert batch.overall_verdict == "fail"
        assert batch.all_passed() is False

    def test_run_batch_single_experiment(self):
        """单 experiment → batch.n_total=1"""
        orch = MatOrchestrator()
        task = get_default_pmma_workflow()
        batch = orch.run_batch([task], parallel=True, max_workers=4)
        assert batch.n_total == 1
        assert batch.experiment_results[0].target_sample == "PMMA"

    def test_run_batch_n_passed_count(self):
        """n_passed 计数正确"""
        orch = MatOrchestrator()
        experiments = get_multi_experiment_default_batch()
        batch = orch.run_batch(experiments, parallel=True, max_workers=3)
        n_pass = sum(1 for r in batch.experiment_results if r.verdict == "pass")
        assert batch.n_passed == n_pass

    def test_run_batch_overall_verdict_pass(self):
        """全 pass → overall_verdict=pass"""
        orch = MatOrchestrator()
        experiments = get_multi_experiment_default_batch()
        batch = orch.run_batch(experiments, parallel=True, max_workers=3)
        # mock 默认数据应该都 pass
        if batch.n_passed == batch.n_total:
            assert batch.overall_verdict == "pass"

    def test_run_batch_custom_task(self):
        """自定义 ChemistTask list"""
        orch = MatOrchestrator()
        task = ChemistTask(
            target_sample="Si",
            domain="ceramic",
            goal="Si 单晶表征",
            robot_steps=[
                RobotStep(robot_type="xrd", description="XRD Si", estimated_cost_cny=100.0),
            ],
            budget_cny=1000.0,
        )
        batch = orch.run_batch([task], parallel=True, max_workers=4)
        assert batch.n_total == 1
        assert batch.experiment_results[0].target_sample == "Si"

    def test_run_batch_failed_samples_helper(self):
        """failed_samples() 返回 fail 的 sample"""
        orch = MatOrchestrator()
        batch = orch.run_batch([], parallel=True, max_workers=4)
        assert batch.failed_samples() == []

    def test_run_batch_total_cost(self):
        """total_cost_cny = sum(per-experiment cost)"""
        orch = MatOrchestrator()
        experiments = get_multi_experiment_default_batch()
        batch = orch.run_batch(experiments, parallel=True, max_workers=3)
        assert batch.total_cost_cny == pytest.approx(
            sum(r.cost_cny for r in batch.experiment_results), abs=1e-6
        )

    def test_run_batch_uses_critic_agent(self):
        """run_batch 用 critic_agent 跑 critic(per experiment)"""
        orch = MatOrchestrator()
        experiments = get_multi_experiment_default_batch()
        batch = orch.run_batch(experiments, parallel=True, max_workers=3)
        # 每个 experiment 都有 critic_verdict(默认用 orch.critic_agent)
        for r in batch.experiment_results:
            assert r.critic_verdict is not None


# ============================================================================
# TestChemistCriticHandoff — MatChemistAgent → MatCriticAgent (8 tests)
# ============================================================================


class TestChemistCriticHandoff:
    """chemist 暴露完整 ChemistReport → critic mode 1 触发 L4"""

    def test_chemist_exposes_report_object(self):
        """MatChemistAgent.act() 返回 artifacts["report"] 是 ChemistReport"""
        from agents.mat_chemist_agent import ChemistReport

        agent = MatChemistAgent()
        task = get_default_pmma_workflow()
        req = AgentRequest(
            run_id="handoff-1",
            message="PMMA",
            artifacts={"task": task},
        )
        resp = agent.run(req)
        report = resp.artifacts.get("report")
        assert report is not None
        assert isinstance(report, ChemistReport)

    def test_chemist_exposes_robot_results_full(self):
        """artifacts["robot_results_full"] 是 List[RobotStepResult]"""
        from agents.mat_chemist_agent import RobotStepResult

        agent = MatChemistAgent()
        task = get_default_pmma_workflow()
        req = AgentRequest(
            run_id="handoff-2",
            message="PMMA",
            artifacts={"task": task},
        )
        resp = agent.run(req)
        full = resp.artifacts.get("robot_results_full")
        assert full is not None
        assert isinstance(full, list)
        assert all(isinstance(r, RobotStepResult) for r in full)

    def test_back_compat_simplified_robot_results(self):
        """back-compat:简化 robot_results dict 还在"""
        agent = MatChemistAgent()
        task = get_default_pmma_workflow()
        req = AgentRequest(
            run_id="handoff-3",
            message="PMMA",
            artifacts={"task": task},
        )
        resp = agent.run(req)
        simple = resp.artifacts.get("robot_results")
        assert simple is not None
        assert isinstance(simple, list)
        assert "robot_type" in simple[0]
        assert "success" in simple[0]

    def test_critic_mode1_triggered_by_report(self):
        """critic 收到 report key → 走 L4 cross_robot"""
        agent = MatChemistAgent()
        task = get_default_pmma_workflow()
        chem_req = AgentRequest(
            run_id="handoff-4-chemist",
            message="PMMA",
            artifacts={"task": task},
        )
        chem_resp = agent.run(chem_req)
        report = chem_resp.artifacts.get("report")

        critic = MatCriticAgent()
        critic_req = AgentRequest(
            run_id="handoff-4-critic",
            message="PMMA 表征复核",
            artifacts={"report": report},
        )
        critic_resp = critic.run(critic_req)
        verdict = critic_resp.artifacts.get("critic_verdict")
        assert verdict is not None
        # cross_robot 应有 score(可能 0.7 因数据 mock)
        assert verdict.cross_robot.score >= 0.0

    def test_critic_mode2_robot_results_full(self):
        """critic 也支持 robot_results 列表(W30 mode 2 兜底)"""
        agent = MatChemistAgent()
        task = get_default_pmma_workflow()
        chem_req = AgentRequest(
            run_id="handoff-5-chemist",
            message="PMMA",
            artifacts={"task": task},
        )
        chem_resp = agent.run(chem_req)
        full = chem_resp.artifacts.get("robot_results_full")

        critic = MatCriticAgent()
        critic_req = AgentRequest(
            run_id="handoff-5-critic",
            message="PMMA",
            artifacts={"robot_results": full},
        )
        critic_resp = critic.run(critic_req)
        verdict = critic_resp.artifacts.get("critic_verdict")
        assert verdict is not None

    def test_back_compat_old_artifacts_unchanged(self):
        """老 artifacts 字段(back-compat)全部还在"""
        agent = MatChemistAgent()
        task = get_default_pmma_workflow()
        req = AgentRequest(
            run_id="handoff-6",
            message="PMMA",
            artifacts={"task": task},
        )
        resp = agent.run(req)
        # 老字段(W26 拍板)
        assert "task_id" in resp.artifacts
        assert "target_sample" in resp.artifacts
        assert "n_successful" in resp.artifacts
        assert "n_blocked" in resp.artifacts
        assert "n_robot_steps" in resp.artifacts
        assert "total_cost_cny" in resp.artifacts
        assert "total_duration_seconds" in resp.artifacts
        assert "cross_validation" in resp.artifacts
        assert "summary" in resp.artifacts
        assert "warnings" in resp.artifacts

    def test_end_to_end_pmma_workflow(self):
        """端到端:PMMA chemist → critic L4 verdict pass"""
        agent = MatChemistAgent()
        task = get_default_pmma_workflow()
        req = AgentRequest(
            run_id="handoff-7",
            message="PMMA",
            artifacts={"task": task},
        )
        chem_resp = agent.run(req)

        critic = MatCriticAgent()
        critic_req = AgentRequest(
            run_id="handoff-7-critic",
            message="PMMA 复核",
            artifacts={"report": chem_resp.artifacts["report"]},
        )
        critic_resp = critic.run(critic_req)
        verdict_obj = critic_resp.artifacts.get("verdict")
        assert verdict_obj is not None
        # PMMA 数据干净 → verdict 应该是 pass 或 warn(不会 fail)
        assert verdict_obj.verdict in ("pass", "warn")

    def test_chemist_report_has_robot_results_list(self):
        """ChemistReport.robot_results 是 List[RobotStepResult]"""
        from agents.mat_chemist_agent import RobotStepResult

        agent = MatChemistAgent()
        task = get_default_pmma_workflow()
        req = AgentRequest(
            run_id="handoff-8",
            message="PMMA",
            artifacts={"task": task},
        )
        resp = agent.run(req)
        report = resp.artifacts["report"]
        assert isinstance(report.robot_results, list)
        assert len(report.robot_results) >= 1
        assert all(isinstance(r, RobotStepResult) for r in report.robot_results)


# ============================================================================
# TestMultiExperimentWorkflow — workflow 模板 (4 tests)
# ============================================================================


class TestMultiExperimentWorkflow:
    """W31 第 6 个 workflow 模板"""

    def test_workflow_returns_dag(self):
        """multi_experiment_characterization_workflow() 返回 DAG"""
        dag = multi_experiment_characterization_workflow()
        assert dag.name == "multi_experiment_characterization"
        assert len(dag.nodes) >= 1

    def test_workflow_registered_in_workflow_by_subclass(self):
        """WORKFLOW_BY_SUBCLASS 注册了 multi_experiment_characterization"""
        assert "multi_experiment_characterization" in WORKFLOW_BY_SUBCLASS

    def test_default_batch_returns_3_experiments(self):
        """get_multi_experiment_default_batch() 返回 3 实验"""
        batch = get_multi_experiment_default_batch()
        assert len(batch) == 3
        assert batch[0].target_sample == "Inconel 718"
        assert batch[1].target_sample == "PMMA"
        assert batch[2].target_sample == "TiO2"

    def test_default_batch_covers_3_domains(self):
        """默认 3 实验覆盖 3 个 material domain(metal/polymer/ceramic)"""
        batch = get_multi_experiment_default_batch()
        domains = {t.domain for t in batch}
        assert "metal_alloy" in domains
        assert "polymer" in domains
        assert "ceramic" in domains


# ============================================================================
# TestGoldens — goldens-friendly 序列化 (4 tests)
# ============================================================================


class TestGoldens:
    """BatchWorkflowResult.to_dict() goldens-friendly"""

    def test_to_dict_keys(self):
        """to_dict() 含 goldens 期望的全部 keys"""
        batch = BatchWorkflowResult(
            n_total=3, n_passed=3, n_warned=0, n_failed=0,
            total_cost_cny=1000.0,
            total_duration_seconds=1.0,
            overall_verdict="pass",
        )
        d = batch.to_dict()
        expected_keys = {"workflow_name", "n_total", "n_passed", "n_warned",
                         "n_failed", "n_blocked", "overall_verdict",
                         "total_cost_cny", "total_duration_seconds",
                         "parallel", "max_workers", "experiment_results"}
        assert expected_keys <= set(d.keys())

    def test_to_dict_experiment_results_serializable(self):
        """experiment_results 列表每项可独立 to_dict"""
        er = ExperimentResult(
            experiment_id="0", target_sample="Inconel 718",
            chemist_report=None, critic_verdict=None,
            cost_cny=500.0, duration_seconds=1.0, verdict="pass",
        )
        batch = BatchWorkflowResult(
            n_total=1, n_passed=1,
            experiment_results=[er],
            overall_verdict="pass",
        )
        d = batch.to_dict()
        assert isinstance(d["experiment_results"], list)
        assert len(d["experiment_results"]) == 1
        er_dict = d["experiment_results"][0]
        assert er_dict["target_sample"] == "Inconel 718"

    def test_to_dict_cost_rounded(self):
        """cost 字段保留 2 位小数"""
        er = ExperimentResult(
            experiment_id="0", target_sample="X",
            chemist_report=None, critic_verdict=None,
            cost_cny=123.4567, duration_seconds=0.1234, verdict="pass",
        )
        d = er.to_dict()
        assert d["cost_cny"] == 123.46
        assert d["duration_seconds"] == 0.12

    def test_to_dict_empty_experiment_results(self):
        """空 experiment_results → to_dict() 含空 list"""
        batch = BatchWorkflowResult(n_total=0)
        d = batch.to_dict()
        assert d["experiment_results"] == []
        assert d["n_total"] == 0