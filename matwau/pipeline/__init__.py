"""matwau.pipeline — 端到端工作流编排器(W7 拍板)

4 段管线:mat-gen → mat-sim → mat-hpc → mat-exp
每段是独立 agent,通过 pipeline 把数据流串起来
Stage 1 mock / Stage 2 接真模型

用法:
    from matwau.pipeline import MatPipeline, PipelineDemo
    p = MatPipeline()
    report = p.run_full_pipeline(
        user_intent="出 LiCoO2 实验方案",
        elements=["Li", "Co", "O"],
        forbidden=["Co"],  # 可选
        budget=500.0,
    )
    print(report)
"""
from .mat_pipeline import (
    MatPipeline,
    PipelineReport,
    StageResult,
    create_default_pipeline,
)
from .pipeline_demos import (
    PipelineDemo,
    DEMO_CASES,
)

__all__ = [
    "MatPipeline",
    "PipelineReport",
    "StageResult",
    "create_default_pipeline",
    "PipelineDemo",
    "DEMO_CASES",
]