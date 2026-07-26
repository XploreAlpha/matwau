# MatWAU 学院版 — 8 周详细课程大纲(02_8week_curriculum)

> **目标**: 8 周从"零基础"到"独立设计 1 个实验 pipeline"
> **节奏**: 每周 3 学时(1 讲 + 2 上机)+ 3-5 小时课外作业
> **配套版本**: MatWAU v1.0-Academic

---

## 总览

| 周 | 主题 | 核心 agent | Demo 脚本 | 作业 |
|---|---|---|---|---|
| **W1** | 入门 + 单 agent | mat-intent-agent | [W1_intent_classification.py](./03_demo_scripts/W1_intent_classification.py) | 跑通 3 类意图 |
| **W2** | 模拟 + 实验 | mat-sim-agent + mat-exp-agent | [W2_xrd_peak_decode.py](./03_demo_scripts/W2_xrd_peak_decode.py) | 写 1 个 XRD 解谱 |
| **W3** | 主动学习 | mat-bayesian | [W3_bayesian_optimize.py](./03_demo_scripts/W3_bayesian_optimize.py) | 跑 TPE 优化 1 函数 |
| **W4** | 裁决与安全 | mat-critic-agent | [W4_critic_L1L4.py](./03_demo_scripts/W4_critic_L1L4.py) | 解释 L1-L4 4 路 |
| **W5** | 多实验编排 | mat-orchestrator | (扩展 multi_experiment_demo.py)| 编排 2 并行 |
| **W6** | 血缘与可观测 | mat-data-lineage | (查 SQLite / Postgres) | 查 lineage + 写报告 |
| **W7** | LLM 二次复核(可选)| mat-critic-agent + LLM | (在 W4 demo 加 `enable_llm_review=True`)| 接入 DeepSeek |
| **W8** | 期末项目 | 自选 | 自选 | 设计 + 实现 + 答辩 |

---

## W1 — 入门 + 单 agent(翻译官)

### 教学目标
- 理解 MatWAU "agent" 的概念
- 跑通 1 个 agent:mat-intent-agent(翻译官)
- 写出第 1 个自己的 MatWAU agent

### 讲课内容(1 学时)
1. 什么是 agent?与"普通函数"区别在哪?
2. MatWAU 的"inner loop 4 步":思考 → 工具 → 检查 → 输出
3. 17 agent 总览(配 01_overview.md §2 的图)
4. **演示**:`mat-intent-agent` 跑 5 类意图

### 上机内容(2 学时)
- 跑 [W1 demo](./03_demo_scripts/W1_intent_classification.py)
- 改 prompt,看输出变化
- 写 1 个 `HelloMatWAUAgent`(参考 01_overview.md §4 Step 4)

### 课外作业(3 小时)
1. **跑通 3 类意图**:`design_new_material` / `optimize_existing` / `literature_review`
2. **改 prompt 实验**:把系统提示改成"只回答金属问题",验证 intent 分类变化
3. **写第 1 个 agent**:模仿 `HelloMatWAUAgent`,做 1 个"陶瓷百科"agent

### 评分标准
- 跑通 3 类意图:20 分
- 改 prompt 实验:30 分
- 写 1 个 agent:50 分

---

## W2 — 模拟 + 实验(快速试菜员 + 实验老师)

### 教学目标
- 理解"MLIP 预筛 + 真实验验证"的科研范式
- 用 mat-sim-agent 算能量
- 用 mat-exp-agent 读 XRD 数据

### 讲课内容(1 学时)
1. 材料表征实验流程:合成 → 表征 → 解谱 → 验证
2. MLIP(Machine Learning Interatomic Potential)原理
3. XRD 布拉格定律:`2d sinθ = nλ`
4. **演示**:`mat-sim-agent` 算 LiCoO2 能量 + `mat-exp-agent` 解 XRD

### 上机内容(2 学时)
- 跑 [W2 demo](./03_demo_scripts/W2_xrd_peak_decode.py)
- 看 Bragg 峰位置 → 反推晶格常数
- 改 `target_wavelength`(Cu Kα vs Mo Kα),看峰位移

### 课外作业(4 小时)
1. **写 1 个 XRD 解谱脚本**:输入 2θ 数组 → 输出晶格常数
2. **改 target_wavelength 实验**:从 Cu Kα 改 Mo Kα,解释峰位移原理
3. **跑 mat-sim-agent**:给 3 个不同结构,看能量排序

### 评分标准
- XRD 解谱脚本:40 分
- target_wavelength 实验报告:30 分
- mat-sim-agent 排序:30 分

---

## W3 — 主动学习(mat-bayesian)

### 教学目标
- 理解"主动学习"思想:用最少实验找最优
- 跑通 GP(Gaussian Process)+ TPE
- 比较 3 种 acquisition:EI / UCB / PI

### 讲课内容(1 学时)
1. 主动学习 vs 网格搜索 vs 随机搜索
2. GP / TPE 数学直觉(不讲推导)
3. EI / UCB / PI 适用场景
4. **演示**:`mat-bayesian` 优化 1 个 2D 函数

### 上机内容(2 学时)
- 跑 [W3 demo](./03_demo_scripts/W3_bayesian_optimize.py)
- 改 acquisition(EI → UCB → PI),看搜索路径
- 改 `n_trials`,看收敛速度

### 课外作业(4 小时)
1. **跑 TPE 优化 1 函数**:自定义 `f(x) = sin(x) + 0.1 * x`,跑 20 trials
2. **对比 3 acquisition**:EI / UCB / PI 各跑 10 次,统计 best 值
3. **写 1 段"为什么主动学习更省"** 的解释(300 字)

### 评分标准
- TPE 跑通:30 分
- 对比实验:40 分
- 解释文字:30 分

---

## W4 — 裁决与安全(mat-critic-agent)

### 教学目标
- 理解"4 路打分"模型:L1 物理 / L2 合成 / L3 安全 / L4 跨机器人
- 跑通 mat-critic-agent
- 解释 verdict 是怎么来的

### 讲课内容(1 学时)
1. 为什么需要 critic?("自动实验也可能错")
2. 4 路打分设计:每一路检查什么?
3. L1 物理(能量守恒 + 布拉格)+ L2 合成(可达性)+ L3 安全(Co / Be 限制)+ L4 跨机器人(一致性)
4. **演示**:`mat-critic-agent` 跑 1 个候选

### 上机内容(2 学时)
- 跑 [W4 demo](./03_demo_scripts/W4_critic_L1L4.py)
- 故意改 1 个 candidate 让 verdict = fail
- 看 `_run_one` 怎么串联 mat-chemist + mat-critic

### 课外作业(5 小时)
1. **解释 L1-L4 4 路打分**:每路写 200 字
2. **故意制造 fail 场景**:让 1 个含 Co 候选 fail
3. **改 critic 权重**:从 L1=0.3/L2=0.3/L3=0.2/L4=0.2 → 改 1 组,解释后果

### 评分标准
- L1-L4 解释:50 分
- fail 场景:30 分
- 权重实验:20 分

---

## W5 — 多实验编排(mat-orchestrator)

### 教学目标
- 理解"DAG"和"并行"
- 跑通 `run_batch()` 多实验并行
- 理解 ThreadPoolExecutor + 异常隔离

### 讲课内容(1 学时)
1. 单实验 vs 批实验(为什么需要并行)
2. DAG 模型 vs 简单 sequence
3. ThreadPoolExecutor + 异常隔离原理
4. **演示**:`examples/multi_experiment_demo.py`(3 实验并行)

### 上机内容(2 学时)
- 跑 `examples/multi_experiment_demo.py`
- 改 `parallel=False`,对比时长
- 故意让 1 个实验 fail,看 BatchWorkflowResult.overall_verdict

### 课外作业(5 小时)
1. **编排 2 个并行实验**:自定义 2 个 ChemistTask,跑通
2. **对比 parallel=True/False 时长**:测 5 次取平均
3. **改 max_workers=1/4/8**:看时长变化(画曲线)

### 评分标准
- 2 并行跑通:30 分
- 时长对比:30 分
- max_workers 曲线:40 分

---

## W6 — 血缘与可观测(mat-data-lineage)

### 教学目标
- 理解"为什么科研需要血缘记录"
- 查 LineageStore(SQLite / Postgres)
- 写 1 段 lineage 报告

### 讲课内容(1 学时)
1. "可复现"对科研的意义
2. LineageStore 数据模型:`experiment_id / agent / input / output / timestamp`
3. SQLite vs Postgres 差异
4. **演示**:查 LineageStore 看 1 个 experiment 的全链路

### 上机内容(2 学时)
- 查 LineageStore(默认 SQLite 在 `~/.matwau/lineage.db`)
- 跑 `examples/multi_experiment_demo.py` 后,看记录
- 用 SQL 查"谁 → 哪个 → 用了什么"

### 课外作业(4 小时)
1. **查 lineage**:跑 1 个 demo,导出 3 个 experiment 的 lineage JSON
2. **写 1 段 lineage 报告**(300 字):解释可复现性
3. **(可选)切到 Postgres**:按 `matwau/configs/matwau_settings.py` 配 `MATWAU_PG_DSN`

### 评分标准
- lineage 导出:50 分
- 报告:50 分

---

## W7 — LLM 二次复核(可选,mat-critic-agent + LLM)

### 教学目标
- 理解"LLM 辅助科研"边界
- 配置 DeepSeek API key
- 跑 `enable_llm_review=True`

### 讲课内容(1 学时)
1. LLM 在 critic 中的角色:"给建议,不决定 verdict"
2. fail-soft 设计:无 key / 无 pkg → 跳过 LLM,verdict 不变
3. **演示**:开 LLM 复核 + 关 LLM 复核对比

### 上机内容(2 学时)
- 配置 `MATWAU_LLM_API_KEY`(学院 IT 统一配)
- 在 W4 demo 上加 `enable_llm_review=True`
- 看 artifacts 里的 `llm_review` 字段

### 课外作业(4 小时)
1. **跑 1 个 case with LLM**:开 + 关各 1 次,对比输出
2. **解释 LLM 复核的价值**:200 字
3. **(可选)测 fail-soft**:故意配错 key,看 verdict 是否不变

### 评分标准
- LLM 跑通:50 分
- 价值解释:30 分
- fail-soft 实验:20 分

---

## W8 — 期末项目(自选 + 答辩)

### 选题方向(任选 1)

| 方向 | 难度 | 建议 |
|---|---|---|
| **新 agent** | ★★★ | 写 1 个 MatWAU 没覆盖的 agent(例:mat-tensile-agent)|
| **新 workflow** | ★★★ | 编排 1 个 multi-agent 流水线(例:聚变堆材料评估)|
| **新规则** | ★★ | 给 mat-critic-agent 加 1 条规则(例:相图自洽)|
| **新 demo** | ★★ | 写 1 个完整 demo(例:钙钛矿太阳能电池材料筛选)|
| **真仪器接入**(挑战)| ★★★★ | 替换 mock SDK 为真仪器(需学院硬件支持)|

### 项目要求

| 项 | 要求 |
|---|---|
| **代码** | 提交 PR 到学院内部 fork(不直接合 MatWAU 主仓)|
| **测试** | ≥ 5 个单元测试 + 1 个 demo |
| **文档** | 1 页 README + 5 分钟答辩 PPT |
| **时长** | 8-12 小时(1 周)|
| **答辩** | 10 分钟讲 + 5 分钟问 |

### 评分标准(详见 04_grading_rubric.md)

- 代码 + 测试:40 分
- 文档 + PPT:30 分
- 答辩:30 分

---

## 附录 A:每周作业提交清单

| 周 | 提交物 | 提交格式 |
|---|---|---|
| W1 | 3 类意图 + HelloAgent + 陶瓷百科 | .py + 截图 |
| W2 | XRD 解谱脚本 + 实验报告 | .py + .md |
| W3 | TPE 优化 + 对比 + 解释 | .py + 表格 + .md |
| W4 | L1-L4 解释 + fail 场景 + 权重 | .md + .py |
| W5 | 2 并行 + 时长对比 + 曲线 | .py + .csv + 图表 |
| W6 | lineage JSON + 报告 + (可选 Postgres)| .json + .md |
| W7 | LLM 跑通 + 价值 + fail-soft | .py + .md |
| W8 | 期末项目 | .py + 测试 + README + PPT |

---

## 附录 B:推荐阅读

| 资源 | 用途 |
|---|---|
| [01_overview.md §5 4 个关键概念](./01_overview.md#五4个关键概念理解后就能上手其他-agent) | 每周回顾 |
| MatWAU 主 README [../../README.md](../../README.md) | 17 agent 详细 API |
| [01_overview.md §6 FAQ](./01_overview.md#六常见问题faq) | 疑难解答 |

---

**end of 02_8week_curriculum.md**

> 编写日期:2026-07-26
> 配套版本:MatWAU v1.0-Academic
> License:Apache 2.0