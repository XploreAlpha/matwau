# MatWAU 学院版 — 概览与 4 步上手(01_overview)

> **目标**: 4 小时看懂 MatWAU,2 天跑通第 1 个实验
> **读者**: 学院本科生 / 研究生 / 老师(零基础友好)
> **配套版本**: MatWAU v1.0-Academic

---

## 一、MatWAU 是什么?(大白话)

**MatWAU 是一套"AI 实验室小工坊"**,你可以把它想成材料科学版的"乐高积木":
- 🧱 **17 个 agent**(造物主 / 试菜员 / 老师 / 翻译官 / 裁决者 / 调度器 ...)
- 🔌 **可拼装** — 像乐高一样,把不同 agent 组合起来做事
- 📚 **可教学** — 每个 agent 都"教"你一类材料科学/AI 知识
- 🔒 **可审计** — 学院服务器本地运行,数据归学校

---

## 二、17 个 agent 一览(10 分钟读懂)

```
mat-intent-agent       ← 翻译官(听懂你说的 5 类意图)
mat-gen-agent          ← 造物主(凭空生成晶体结构)
mat-sim-agent          ← 试菜员(MLIP 快速预测能量)
mat-hpc-agent          ← 超算员(对接 VASP + Slurm)
mat-exp-agent          ← 实验老师(读 XRD / DSC 数据)
mat-critic-agent       ← 裁决者(打分 + 解释)
mat-bayesian           ← 主动学习(找最优配方)
mat-cost               ← 成本守门员(别超预算)
mat-data-lineage       ← 记录员(每步留痕)
mat-lit                ← 图书管理员(查论文)
mat-chemist-agent      ← 化学师协调器(调度多机器人)
mat-robot-synth        ← OT-2 mock(合成机器人)
mat-robot-xrd          ← XRD mock(晶体表征)
mat-robot-em           ← SEM mock(显微观察)
mat-robot-dsc          ← DSC mock(热学表征)
mat-orchestrator       ← 调度器(DAG + 多实验并行)
MaterialDomainRouter   ← 路由(无机 / 聚合物 / 纳米)
```

---

## 三、典型工作流(以"造 1 个新材料"为例)

```
你说:"帮我造 1 个能耐高温的 LiCoO2 替代品"
        ↓
mat-intent-agent     翻译成 5 类意图里的 "design_new_material"
        ↓
mat-orchestrator     编排 4 个 agent 跑:gen → sim → critic → critic
        ↓
mat-gen-agent        生成 10 个候选晶体结构
        ↓
mat-sim-agent        算每个候选的能量(MLIP 模拟)
        ↓
mat-critic-agent     打分:哪个最稳定 + 哪个成本最低
        ↓
mat-data-lineage     记录全过程(谁 → 哪个 → 用了什么)
        ↓
回报:Top 3 候选 + 完整 lineage
```

---

## 四、4 步上手(复制粘贴就能跑)

### Step 1 — 装环境(5 分钟)

```bash
# 系统要求
python3 --version    # 需要 3.11+
# Linux / macOS / WSL2 都行

# clone 代码(假设学院 IT 已部署)
git clone https://github.com/XploreAlpha/matwau.git
cd matwau

# 装依赖(全部开源,无需密钥)
pip install -r requirements.txt
```

### Step 2 — 跑通官方示例(2 分钟)

```bash
# 跑 3 个实验并行(Inconel 718 + PMMA + TiO2)
python3 examples/multi_experiment_demo.py
```

**期望输出**(节选):
```
🚀 MatWAU W31 Stage 3 JARVIS Demo — 3 实验并行
📋 默认批次:['Inconel 718', 'PMMA', 'TiO2']
📊 BatchWorkflowResult
  N = 3, passed = 3, overall_verdict: PASS
  Total cost: ¥4500
```

### Step 3 — 跑回归测试(可选,5 分钟)

```bash
# 学院 IT 已部署可跳过
python3 -m pytest tests/ -q
# 期望:1298 passed, 1 skipped, ~3 分钟
```

### Step 4 — 写第 1 个 MatWAU agent(15 分钟)

```python
# 文件:my_first_agent.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

from matwau.core.agent_base import MatWAUAgentBase, AgentRequest, AgentResponse


class HelloMatWAUAgent(MatWAUAgentBase):
    name = "hello-matwau"

    def system_prompt(self) -> str:
        return "你是材料科学新生入门导师,只回答 1 个材料科学问题。"

    def act(self, ctx, tools):
        msg = ctx.message
        if "钢" in msg:
            reply = "钢是铁碳合金,含碳 0.02%-2.14%。分类:低碳钢/中碳钢/高碳钢。"
        elif "陶瓷" in msg:
            reply = "陶瓷是无机非金属材料,常见有氧化物/氮化物/碳化物三大类。"
        else:
            reply = f"我看到你说:{msg}。我是材料新生导师,问钢/陶瓷/聚合物都行。"

        return AgentResponse(
            reply=reply,
            artifacts={"echo": msg},
            confidence=0.85,
            cost=0.001,
        )


if __name__ == "__main__":
    agent = HelloMatWAUAgent()
    req = AgentRequest(run_id="tutor-001", message="讲讲钢", artifacts={}, context={})
    resp = agent.run(req)
    print("🤖:", resp.reply)
```

跑一下:

```bash
python3 my_first_agent.py
# 期望输出:🤖: 钢是铁碳合金,含碳 0.02%-2.14%。分类:低碳钢/中碳钢/高碳钢。
```

**恭喜!你已经写了第 1 个 MatWAU agent!**

---

## 五、4 个关键概念(理解后就能上手其他 agent)

| 概念 | 含义 | 在 MatWAU 里的体现 |
|---|---|---|
| **agent** | 一个能"听懂 + 做事 + 解释"的小 AI | 17 agent 每个都做 1 件事 |
| **inner loop** | agent 内部 4 步:思考→用工具→检查→输出 | 所有 agent 都跑这 4 步 |
| **artifact** | agent 输出里带"结果数据"的部分 | `AgentResponse.artifacts` 是 dict |
| **lineage** | 谁 → 哪个 → 用了什么,全过程记录 | mat-data-lineage 自动记录 |

---

## 六、常见问题(FAQ)

### Q1: 我需要 GPU 吗?

**不需要**。所有 demo 默认跑 mock(模拟器),单机 CPU 即可跑通。LLM 复核可选,即使开也只用 API,不消耗本地算力。

### Q2: 我需要装 Docker 吗?

**不需要**(v1.0-Academic 不强求)。学院 IT 部署时可以选 Docker Compose 单机包(v1.1-Academic 计划),但学生直接 `pip install` 就够用。

### Q3: 我需要 API key 吗?

**默认不需要**。学院版默认全 mock,无网络依赖。需要 LLM 二次复核时,学院 IT 统一配 1 个 DeepSeek key,学生用 `.env` 引用即可(API key 不进对话)。

### Q4: 我能把 MatWAU 装到自己电脑上吗?

**可以**。Apache 2.0 允许任意 fork 与本地部署。建议跟学院 IT 同步装一份,以便使用 LineageStore 持久化。

### Q5: 学院版 v1.0-Academic 跟未来版本有什么差别?

学院版 LTS 18 个月,后续 v1.1-Academic 加教学手册 + PPT,v1.2-Academic 加真仪器样板。学院版永远 Apache 2.0 + 双署名 + 数据归学校。

---

## 七、下一步去哪?

| 你想... | 看哪 |
|---|---|
| 看 8 周课程详细大纲 | [02_8week_curriculum.md](./02_8week_curriculum.md) |
| 拷贝课堂演示脚本 | [03_demo_scripts/](./03_demo_scripts/) |
| 看评分标准 | [04_grading_rubric.md](./04_grading_rubric.md) |
| 跑多实验并行 demo | [../../examples/multi_experiment_demo.py](../../examples/multi_experiment_demo.py) |
| 查 17 agent API | [../../agents/](../../agents/) 每个子目录有 README |

---

**end of 01_overview.md**

> 编写日期:2026-07-26
> 配套版本:MatWAU v1.0-Academic
> License:Apache 2.0