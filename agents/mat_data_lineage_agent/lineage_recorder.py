"""lineage_recorder.py — W32 LineageRecorder(高级 record API)

LineageRecorder 是 LineageStore 的薄封装,提供:
1. **`record(...)`** — 1 行调用,自动 hash + summary + store + backend 写
2. **`record_critic_verdict(...)`** — critic-specific:吃 CriticVerdict + L4 cross_robot
3. **`record_chemist_report(...)`** — chemist-specific:吃 ChemistReport + per-robot results
4. **`record_workflow_result(...)`** — orchestrator-specific:吃 WorkflowResult / BatchWorkflowResult
5. **`record_experiment_result(...)`** — single experiment record

设计原则:
- 不引入新存储,只包 LineageStore(per user-confirmed 不动 core)
- 失败吞掉(per MatWAU-Harness-Loop 心法)— lineage 失败不应阻断业务
- 全局单例(get_global_recorder) + 工厂(get_recorder(store))

per W32 plan §E
"""
from __future__ import annotations

import logging
import threading
from dataclasses import asdict, is_dataclass
from typing import Any

from .lineage_engine import (
    LineageRecord,
    LineageStore,
    get_global_store,
    reset_global_store,
)

logger = logging.getLogger(__name__)


# ============================================================================
# helpers — dataclass / object → dict
# ============================================================================


def _to_dict(obj: Any) -> dict[str, Any]:
    """安全把 dataclass / dict / 对象转 dict

    - dataclass → asdict (recursively)
    - dict → 自身(深 copy)
    - 其它对象 → 尝试 vars() / __dict__ / 字符串
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if is_dataclass(obj):
        try:
            return asdict(obj)
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return {k: _to_dict(v) for k, v in vars(obj).items() if not k.startswith("_")}
    # 兜底
    return {"_repr": str(obj)[:200]}


def _summarize_critic_verdict(verdict: Any) -> dict[str, Any]:
    """CriticVerdict → lineage summary(verdict / scores / rules)

    CriticVerdict / CriticOutput 字段抽取(安全 try-import):
    - verdict: pass/warn/fail
    - overall_score / l1_score / l2_score / l3_score / l4_cross_robot_score
    - rules_passed / rules_failed(从 cross_robot 抽)
    - failures[]: list of {code, severity, ...}
    - top_suggestions[]: list of str
    """
    summary: dict[str, Any] = {"_type": "critic_verdict"}

    if verdict is None:
        return summary

    # verdict 字符串
    for attr in ("verdict",):
        if hasattr(verdict, attr):
            v = getattr(verdict, attr)
            if isinstance(v, str):
                summary["verdict"] = v
                break

    # 4 路 scores
    scores = {}
    for score_name in ("overall_score", "l1_score", "l2_score", "l3_score", "l4_cross_robot_score"):
        if hasattr(verdict, score_name):
            v = getattr(verdict, score_name)
            if isinstance(v, (int, float)):
                scores[score_name] = round(float(v), 4)
    if scores:
        summary["scores"] = scores

    # cross_robot 规则
    if hasattr(verdict, "cross_robot") and verdict.cross_robot is not None:
        cr = verdict.cross_robot
        if hasattr(cr, "consistent"):
            summary["l4_consistent"] = bool(cr.consistent)
        if hasattr(cr, "score"):
            summary["l4_score"] = round(float(cr.score), 4)
        if hasattr(cr, "rules_passed") and isinstance(cr.rules_passed, list):
            summary["rules_passed"] = list(cr.rules_passed)
        if hasattr(cr, "rules_failed") and isinstance(cr.rules_failed, list):
            summary["rules_failed"] = list(cr.rules_failed)

    # failures
    if hasattr(verdict, "failures"):
        failures = verdict.failures
        if isinstance(failures, list):
            summary["n_failures"] = len(failures)
            summary["failures"] = [
                {"code": getattr(f, "code", "?"), "severity": getattr(f, "severity", "?")}
                for f in failures[:5]  # 限 5 条避免爆
            ]

    return summary


def _summarize_chemist_report(report: Any) -> dict[str, Any]:
    """ChemistReport → lineage summary(success / cost / robot steps)"""
    summary: dict[str, Any] = {"_type": "chemist_report"}

    if report is None:
        return summary

    for attr in ("target_sample", "domain"):
        if hasattr(report, attr):
            v = getattr(report, attr)
            if v:
                summary[attr] = str(v)

    # robot_steps / robot_results
    for attr in ("robot_results",):
        if hasattr(report, attr):
            rs = getattr(report, attr)
            if isinstance(rs, list):
                summary["n_robot_steps"] = len(rs)
                summary["robot_step_types"] = [
                    getattr(r, "robot_type", "?") for r in rs[:5]
                ]
                summary["robot_step_success"] = [
                    bool(getattr(r, "success", False)) for r in rs[:5]
                ]

    if hasattr(report, "overall_success"):
        summary["overall_success"] = bool(report.overall_success)
    if hasattr(report, "summary"):
        s = report.summary
        if isinstance(s, str) and s:
            summary["summary_excerpt"] = s[:100]

    return summary


# ============================================================================
# LineageRecorder class
# ============================================================================


class LineageRecorder:
    """Lineage 高级 recorder(W32)

    用法:
        recorder = LineageRecorder()
        # 或 recorder = LineageRecorder(store=my_store)

        # 通用 record
        rec = recorder.record(
            run_id="exp-1-chemist",
            agent_name="mat-chemist-agent",
            input_artifacts={"task": task_dict},
            output_artifacts={"report": report_dict},
            duration_seconds=1.23,
            cost=120.0,
            metadata={"target_sample": "Inconel 718"},
        )

        # critic specific
        rec = recorder.record_critic_verdict(
            experiment_id="exp-1",
            target_sample="Inconel 718",
            critic_verdict=verdict,
            cost=50.0,
            duration_seconds=0.5,
        )

        # workflow specific
        rec = recorder.record_workflow_result(
            workflow_name="experiment_planning",
            subclass="experiment_planning",
            result=workflow_result,
        )
    """

    def __init__(self, store: LineageStore | None = None) -> None:
        self.store = store  # None → 懒加载 get_global_store()

    def _get_store(self) -> LineageStore:
        if self.store is None:
            self.store = get_global_store()
        return self.store

    # ----------------------------------------------------------------
    # 通用 record — 最底层接口
    # ----------------------------------------------------------------
    def record(
        self,
        run_id: str,
        agent_name: str,
        *,
        input_artifacts: dict[str, Any] | None = None,
        output_artifacts: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
        duration_seconds: float = 0.0,
        cost: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> LineageRecord | None:
        """打 1 条 lineage 记录(失败吞掉,返回 None)

        Returns:
            LineageRecord if 成功;None if store 不可用 / 失败
        """
        try:
            store = self._get_store()
            return store.add(
                run_id=run_id,
                agent_name=agent_name,
                input_artifacts=input_artifacts or {},
                output_artifacts=output_artifacts or {},
                parent_run_id=parent_run_id,
                duration_seconds=duration_seconds,
                cost=cost,
                metadata=metadata or {},
            )
        except Exception as e:
            logger.warning("[LineageRecorder] record 失败: %s", e)
            return None

    # ----------------------------------------------------------------
    # Critic-specific
    # ----------------------------------------------------------------
    def record_critic_verdict(
        self,
        experiment_id: str,
        target_sample: str,
        critic_verdict: Any,
        *,
        cost: float = 0.0,
        duration_seconds: float = 0.0,
        user_intent: str = "",
        parent_run_id: str | None = None,
    ) -> LineageRecord | None:
        """W32 — 记录 critic 跑 1 次的结果

        run_id: f"{experiment_id}-critic"
        parent_run_id: f"{experiment_id}-chemist"(默认)
        metadata: target_sample + user_intent + summary
        output_artifacts: critic verdict summary
        """
        summary = _summarize_critic_verdict(critic_verdict)
        summary.get("verdict", "unknown")

        metadata = {
            "target_sample": target_sample,
            "user_intent_excerpt": user_intent[:100] if user_intent else "",
            "summary": summary,
            "kind": "critic",
        }

        return self.record(
            run_id=f"{experiment_id}-critic",
            agent_name="mat-critic-agent",
            input_artifacts={"experiment_id": experiment_id, "target_sample": target_sample},
            output_artifacts={"critic_verdict": summary},
            parent_run_id=parent_run_id or f"{experiment_id}-chemist",
            duration_seconds=duration_seconds,
            cost=cost,
            metadata=metadata,
        )

    # ----------------------------------------------------------------
    # Chemist-specific
    # ----------------------------------------------------------------
    def record_chemist_report(
        self,
        experiment_id: str,
        task: Any,
        report: Any,
        *,
        cost: float = 0.0,
        duration_seconds: float = 0.0,
    ) -> LineageRecord | None:
        """W32 — 记录 chemist 跑 1 个 task 的结果"""
        summary = _summarize_chemist_report(report)

        metadata = {
            "target_sample": getattr(task, "target_sample", "<unknown>"),
            "domain": getattr(task, "domain", "<unknown>"),
            "summary": summary,
            "kind": "chemist",
        }

        return self.record(
            run_id=f"{experiment_id}-chemist",
            agent_name="mat-chemist-agent",
            input_artifacts={"task": _to_dict(task)},
            output_artifacts={"report": summary},
            duration_seconds=duration_seconds,
            cost=cost,
            metadata=metadata,
        )

    # ----------------------------------------------------------------
    # Orchestrator-specific:WorkflowResult
    # ----------------------------------------------------------------
    def record_workflow_result(
        self,
        workflow_name: str,
        subclass: str,
        result: Any,
        *,
        parent_run_id: str | None = None,
    ) -> LineageRecord | None:
        """W32 — 记录 orchestrator run() 完整 workflow 结果"""
        success = bool(getattr(result, "success", False))
        duration = float(getattr(result, "total_duration_seconds", 0.0))
        error = getattr(result, "error", None)
        node_results = getattr(result, "node_results", [])
        final_outputs = getattr(result, "final_outputs", {})

        metadata = {
            "workflow_name": workflow_name,
            "subclass": subclass,
            "success": success,
            "n_nodes": len(node_results) if isinstance(node_results, list) else 0,
            "n_nodes_success": sum(1 for nr in node_results if getattr(nr, "success", False)) if isinstance(node_results, list) else 0,
            "kind": "workflow",
        }
        if error:
            metadata["error"] = str(error)[:200]

        # 节点摘要
        if isinstance(node_results, list):
            metadata["nodes"] = [
                {
                    "node_id": getattr(nr, "node_id", "?"),
                    "agent_name": getattr(nr, "agent_name", "?"),
                    "success": bool(getattr(nr, "success", False)),
                    "duration": round(float(getattr(nr, "duration_seconds", 0.0)), 3),
                }
                for nr in node_results
            ]

        return self.record(
            run_id=f"workflow-{workflow_name}-{subclass}",
            agent_name="mat-orchestrator",
            input_artifacts={"subclass": subclass},
            output_artifacts={
                "final_outputs_keys": list(final_outputs.keys()) if isinstance(final_outputs, dict) else [],
                "n_nodes": metadata["n_nodes"],
            },
            parent_run_id=parent_run_id,
            duration_seconds=duration,
            metadata=metadata,
        )

    # ----------------------------------------------------------------
    # Orchestrator-specific:ExperimentResult / BatchWorkflowResult
    # ----------------------------------------------------------------
    def record_experiment_result(
        self,
        experiment_result: Any,
        *,
        parent_run_id: str | None = None,
    ) -> LineageRecord | None:
        """W32 — 记录 run_batch() 中 1 个 experiment 的结果(chemist + critic 双结果)

        run_id: experiment_result.experiment_id
        output_artifacts: verdict + cost + duration + target_sample + critic summary
        """
        exp_id = getattr(experiment_result, "experiment_id", "<unknown>")
        target = getattr(experiment_result, "target_sample", "<unknown>")
        verdict = getattr(experiment_result, "verdict", "fail")
        cost = float(getattr(experiment_result, "cost_cny", 0.0))
        duration = float(getattr(experiment_result, "duration_seconds", 0.0))
        error = getattr(experiment_result, "error", None)
        blocked = bool(getattr(experiment_result, "blocked", False))
        critic_verdict = getattr(experiment_result, "critic_verdict", None)
        chemist_report = getattr(experiment_result, "chemist_report", None)

        metadata = {
            "target_sample": target,
            "verdict": verdict,
            "blocked": blocked,
            "kind": "experiment",
        }
        if error:
            metadata["error"] = str(error)[:200]
        if chemist_report is not None:
            metadata["chemist_summary"] = _summarize_chemist_report(chemist_report)
        if critic_verdict is not None:
            metadata["critic_summary"] = _summarize_critic_verdict(critic_verdict)

        return self.record(
            run_id=exp_id,
            agent_name="mat-orchestrator-experiment",
            input_artifacts={"target_sample": target},
            output_artifacts={
                "verdict": verdict,
                "cost_cny": cost,
                "duration_seconds": duration,
                "blocked": blocked,
            },
            parent_run_id=parent_run_id,
            duration_seconds=duration,
            cost=cost,
            metadata=metadata,
        )

    def record_batch_workflow_result(
        self,
        batch_result: Any,
    ) -> LineageRecord | None:
        """W32 — 记录 run_batch() 的 BatchWorkflowResult 总览"""
        n_total = int(getattr(batch_result, "n_total", 0))
        n_passed = int(getattr(batch_result, "n_passed", 0))
        n_warned = int(getattr(batch_result, "n_warned", 0))
        n_failed = int(getattr(batch_result, "n_failed", 0))
        n_blocked = int(getattr(batch_result, "n_blocked", 0))
        overall_verdict = str(getattr(batch_result, "overall_verdict", "fail"))
        total_cost = float(getattr(batch_result, "total_cost_cny", 0.0))
        total_duration = float(getattr(batch_result, "total_duration_seconds", 0.0))
        parallel = bool(getattr(batch_result, "parallel", True))
        max_workers = int(getattr(batch_result, "max_workers", 4))

        metadata = {
            "workflow_name": getattr(batch_result, "workflow_name", "multi_experiment_characterization"),
            "n_total": n_total,
            "n_passed": n_passed,
            "n_warned": n_warned,
            "n_failed": n_failed,
            "n_blocked": n_blocked,
            "overall_verdict": overall_verdict,
            "parallel": parallel,
            "max_workers": max_workers,
            "kind": "batch_workflow",
        }

        # 失败样本名
        failed_samples_attr = getattr(batch_result, "experiment_results", [])
        if isinstance(failed_samples_attr, list):
            metadata["passed_samples"] = [
                getattr(r, "target_sample", "?")
                for r in failed_samples_attr
                if getattr(r, "verdict", None) == "pass"
            ][:10]
            metadata["failed_samples"] = [
                getattr(r, "target_sample", "?")
                for r in failed_samples_attr
                if getattr(r, "verdict", None) == "fail"
            ][:10]

        return self.record(
            run_id=f"batch-{metadata['workflow_name']}-{n_total}",
            agent_name="mat-orchestrator-batch",
            input_artifacts={"n_total": n_total, "max_workers": max_workers},
            output_artifacts={
                "overall_verdict": overall_verdict,
                "total_cost_cny": total_cost,
                "total_duration_seconds": total_duration,
            },
            duration_seconds=total_duration,
            cost=total_cost,
            metadata=metadata,
        )


# ============================================================================
# 全局 recorder(单例)
# ============================================================================


_global_recorder: LineageRecorder | None = None
_recorder_lock = threading.Lock()


def get_global_recorder() -> LineageRecorder:
    """获取全局 LineageRecorder(W32 单例)"""
    global _global_recorder
    if _global_recorder is None:
        with _recorder_lock:
            if _global_recorder is None:
                _global_recorder = LineageRecorder()
    return _global_recorder


def get_recorder(store: LineageStore | None = None) -> LineageRecorder:
    """工厂函数 — 给定 store 造 1 个 LineageRecorder(测试用显式注入)

    store=None → 全局单例
    store=LineageStore → 新 recorder 包这个 store
    """
    if store is None:
        return get_global_recorder()
    return LineageRecorder(store=store)


def reset_global_recorder() -> None:
    """重置全局 recorder + store(测试用)"""
    global _global_recorder
    with _recorder_lock:
        _global_recorder = None
    reset_global_store()


__all__ = [
    "LineageRecorder",
    "get_global_recorder",
    "get_recorder",
    "reset_global_recorder",
]