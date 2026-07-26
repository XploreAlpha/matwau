# MatWAU 学院版 — 8 周教学手册

> **目标读者**: 学院老师 / 助教 / 本科生 / 研究生
> **课程时长**: 8 周(每周 3 学时,共 24 学时)
> **难度**: 入门(有 Python 基础即可,无需 AI/材料学背景)
> **配套代码**: MatWAU v1.0-Academic(17 agent, 1298 PASSED)
> **License**: Apache 2.0(配合 MatWAU 主 license)

---

## 一、本手册结构

| 文件 | 内容 | 建议用法 |
|---|---|---|
| **[01_overview.md](./01_overview.md)** | 概览 + 4 步上手 | 学生第 1 次课前阅读 |
| **[02_8week_curriculum.md](./02_8week_curriculum.md)** | 8 周详细大纲 + 每周作业 | 老师备课用 |
| **[03_demo_scripts/](./03_demo_scripts/)** | 4 个课堂演示脚本(可直接拷贝运行)| 课堂演示 + 学生上机 |
| **[04_grading_rubric.md](./04_grading_rubric.md)** | 评分标准 + 期末项目要求 | 老师评分用 |

---

## 二、8 周课程一览

| 周 | 主题 | Demo | 作业 |
|---|---|---|---|
| **W1** | 入门 + 单 agent | mat-intent-agent | 跑通 3 个 intent 类别 |
| **W2** | 模拟 + 实验 | mat-sim-agent + mat-exp-agent | 写 1 个 XRD 解谱脚本 |
| **W3** | 主动学习 | mat-bayesian | 跑 TPE 优化 1 个函数 |
| **W4** | 裁决与安全 | mat-critic-agent | 解释 critic L1-L4 |
| **W5** | 多实验编排 | mat-orchestrator run_batch | 编排 2 个并行实验 |
| **W6** | 血缘与可观测 | mat-data-lineage | 查 lineage + 写报告 |
| **W7** | LLM 二次复核(可选)| mat-critic-agent + LLM | 接入 DeepSeek 跑 1 个 case |
| **W8** | 期末项目 | 自选 | 设计 + 实现 + 答辩 |

---

## 三、4 步上手(给学生的速通)

```bash
# Step 1 — 装依赖
git clone https://github.com/XploreAlpha/matwau.git
cd matwau
pip install -r requirements.txt

# Step 2 — 跑通示例(mock 模式,无需任何外部 SDK/LLM)
python3 examples/multi_experiment_demo.py

# Step 3 — 跑回归(学院 IT 已部署可跳过)
python3 -m pytest tests/ -q

# Step 4 — 写你的第一个 MatWAU agent
# 见 docs/teaching_manual/01_overview.md §5
```

---

## 四、文件组织

```
teaching_manual/
├── README.md                  ← 本文件(入口)
├── 01_overview.md             ← 概览 + 4 步上手
├── 02_8week_curriculum.md     ← 8 周详细大纲
├── 03_demo_scripts/           ← 课堂演示脚本
│   ├── W1_intent_classification.py
│   ├── W2_xrd_peak_decode.py
│   ├── W3_bayesian_optimize.py
│   └── W4_critic_L1L4.py
└── 04_grading_rubric.md       ← 评分标准
```

---

## 五、配套资源

| 资源 | 链接 |
|---|---|
| **MatWAU 主 README** | [../../README.md](../../README.md) |
| **捐赠与法律** | [../../LICENSE](../../LICENSE) + [../../NOTICE](../../NOTICE) + [../../MAINTENANCE.md](../../MAINTENANCE.md) |
| **学院版说明书** | [../donation_proposal.md](../donation_proposal.md) |
| **示例代码** | [../../examples/](../../examples/) |
| **Goldens 测试**(教师参考) | [../../tests/goldens/](../../tests/goldens/) |

---

## 六、学时建议(本科学院选修课标准)

```
总学时 24 = 8 周 × 3 学时/周
理论:实验 = 1:2(每周 1 学时讲 + 2 学时上机)
课外作业:每周 3-5 小时
期末项目:8-12 小时
```

---

## 七、教辅角色

| 角色 | 责任 |
|---|---|
| **主讲老师** | 8 周理论 + 答疑 |
| **助教**(1-2 名)| 上机辅导 + 作业批改 + 答疑 |
| **学院 IT** | MatWAU 部署 + 服务器维护(0.1 FTE)|

---

**end of teaching_manual/README.md**

> 编写日期:2026-07-26
> 配套版本:MatWAU v1.0-Academic
> License:Apache 2.0(同 MatWAU 主 license)