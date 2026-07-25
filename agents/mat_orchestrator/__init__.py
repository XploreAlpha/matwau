"""mat-orchestrator — DAG 调度器(per W10)

接 mat-intent 解析结果,根据 5 子类选 workflow 模板,执行 DAG。

Stage 1 mock:所有 workflow 跑现有 agent(mat-gen/sim/hpc/exp/intent)
Stage 2 接 mat-lit / mat-critic(W12/W14 写)

5 workflow 模板:
- experiment_planning:4 段(mat-gen → sim → hpc → exp)
- design_new_material:2 段(mat-gen → sim)+ top-N
- optimize_existing:mat-sim 迭代 + 用户反馈
- explain_failure:mat-critic(W12 stub)
- literature_review:mat-lit(W14 stub)
"""