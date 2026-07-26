"""parallel_runner.py — W31 ThreadPoolExecutor 批 runner

设计要点:
- I/O-bound 工作:4 robot agent + 1 critic rule engine(无 CPU 密集)
- ThreadPoolExecutor(stdlib,0 新依赖)
- max_workers 默认 4(= 4 robot 类型上限),可配 1 兜底串行
- 异常隔离:per-experiment try/except → ExperimentResult(verdict='fail')
- as_completed 提供进度可见性(后续 W32 lineage 可挂)
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional


class ParallelBatchRunner:
    """批 runner:fan-out N 个 experiment,fan-in 聚合 List[ExperimentResult]

    设计原则:
    - 顺序保持:results[i] 对应 callables[i](不依赖 as_completed 完成顺序)
    - 异常隔离:per-callable try/except → ExperimentResult(verdict='fail')
    - 串行兜底:max_workers <= 1 或 N == 1 → 不开线程
    - 类型宽容:fn 返回值 duck-typing ExperimentResult(to_dict / verdict / target_sample)
    """

    def __init__(self, max_workers: int = 4):
        if max_workers < 1:
            raise ValueError(f"max_workers 必须 >= 1,got {max_workers}")
        self.max_workers = max_workers

    def run_all(
        self,
        callables: List[Callable[[], "ExperimentResultLike"]],
    ) -> List["ExperimentResultLike"]:
        """fan-out N 个 callable,异常隔离,顺序返回结果列表

        Args:
            callables: List[() -> ExperimentResultLike]
                每项应是 callable,返回 ExperimentResult 或 duck-typing 类似对象

        Returns:
            List[ExperimentResultLike] — 与 callables 同顺序
        """
        results: List[Optional["ExperimentResultLike"]] = [None] * len(callables)

        if not callables:
            return []

        # 串行兜底(max_workers=1 或 N=1)
        if self.max_workers <= 1 or len(callables) <= 1:
            for idx, fn in enumerate(callables):
                results[idx] = self._safe_run(fn, idx)
            return [r for r in results if r is not None]  # type: ignore

        # 并行(线程池)
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_idx = {
                ex.submit(self._safe_run, fn, idx): idx
                for idx, fn in enumerate(callables)
            }
            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                results[idx] = fut.result()

        # type: ignore — None 已用 _safe_run 兜底
        return results  # type: ignore

    @staticmethod
    def _safe_run(fn, idx: int):
        """包 try/except,异常包装成 fail ExperimentResult"""
        from agents.mat_orchestrator.dag import ExperimentResult

        try:
            return fn()
        except Exception as e:
            return ExperimentResult(
                experiment_id=f"err-{idx}",
                target_sample="<unknown>",
                chemist_report=None,
                critic_verdict=None,
                cost_cny=0.0,
                duration_seconds=0.0,
                verdict="fail",
                blocked=False,
                error=f"{type(e).__name__}: {e}",
            )


# 类型别名 — duck typing 兼容任何有 verdict/target_sample/cost_cny 字段的对象
ExperimentResultLike = "ExperimentResult"


__all__ = ["ParallelBatchRunner"]