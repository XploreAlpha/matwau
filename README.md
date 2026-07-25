# MatWAU — 材料科学 11 件套 AI Agent 矩阵

> **项目**:MatWAU — 基于 WAU-core-kernel v1.0.0 的材料科学超级智能体
> **架构**:无头(Headless)后端服务,11 个独立 agent + 灵魂 3 件套 + 高效 3 件套
> **核心哲学**:每 agent **独立 Harness** + 共用 **Inner Loop 基类** + WAU OS 共享中间件
> **状态**:**W1 起点**(Phase 0 阶段,2026-07-24 拍板)
> **基于**:
> - [`~/WAU-develop/develop-log/MatWAU/MatWAU-项目展示.md`](https://WAU-develop/develop-log/MatWAU/MatWAU-项目展示.md) — 项目总览
> - [`~/WAU-develop/develop-log/MatWAU/MatWAU-开发计划.md`](https://WAU-develop/develop-log/MatWAU/MatWAU-开发计划.md) — 12-15 周 MVP 路线图
> - [`~/WAU-develop/develop-log/MatWAU/MatWAU-Harness-Loop-工程心法实践.md`](https://WAU-develop/develop-log/MatWAU/MatWAU-Harness-Loop-工程心法实践.md) — 工程心法实践

---

## 一、一句话定位

**MatWAU = 材料科学 11 agent 矩阵 + 灵魂 3 件套 + 高效 3 件套,跑在 WAU v1.0.0 上,15 周 MVP,3 年商业化。**

类比:**MatWAU = 材料科学领域的 nginx** — 不露脸,但所有应用都离不开。

---

## 二、目录结构

```
matwau/                              ← 项目根(无头后端)
├── README.md                        ← 本文件(项目入口)
├── agents/                          ← 11 agent 代码(纯后端,每个 agent 1 子目录)
│   ├── mat-lit-agent/               ← 图书管理员(论文检索 + RAG)
│   ├── mat-gen-agent/               ← 造物主(晶体结构生成)
│   ├── mat-sim-agent/               ← 快速试菜员(MLIP 预筛)
│   ├── mat-hpc-agent/               ← 超算对接员(VASP + Slurm)
│   ├── mat-exp-agent/               ← 实验老师 + 结果分析
│   ├── mat-intent-agent/            ← 听人话的翻译官(5 类意图)
│   ├── mat-orchestrator-agent/      ← DAG 调度
│   ├── mat-critic-agent/            ← 3 路交叉验证
│   ├── mat-bayesian-agent/          ← 主动学习(Optuna)
│   ├── mat-cost-estimator-agent/    ← 成本估算
│   └── mat-data-lineage-agent/      ← 血缘记录
├── matwau/                          ← 核心库
│   ├── core/                        ← 基类 + 共享类型
│   │   └── agent_base.py            ← ⭐ MatWAU-AgentBase 基类
│   ├── harness/                     ← 5 大 Harness 职责
│   │   ├── context_manager.py       ← §5.1
│   │   ├── tool_registry.py         ← §5.2
│   │   ├── state_store.py           ← §5.3
│   │   ├── safety_guard.py          ← §5.4
│   │   └── eval_harness.py          ← §5.5
│   └── outer_loop/                  ← Outer Loop 自愈
│       └── failure_miner.py         ← §6
├── configs/                         ← 配置文件
│   ├── mat-intent.yaml
│   ├── mat-orchestrator.yaml
│   └── ...
├── workflows/                       ← workflow 模板
│   ├── design_new_material.yaml
│   ├── optimize_existing.yaml
│   └── ...
├── tests/                           ← 测试
│   ├── unit/                        ← 单元测试
│   ├── goldens/                     ← Goldens 测试集(每个 agent 50+ case)
│   └── e2e/                         ← 端到端测试
├── docs/                            ← 用户 + 运维文档
│   ├── user-manual.md
│   ├── deploy.md
│   └── ...
└── scripts/                         ← 部署 + 维护脚本
    ├── deploy.sh
    └── ...
```

❌ MatWAU **不会**有的目录(因为是无头架构):
- `ui/` / `frontend/` / `mobile/` / `web/` — **0 行 UI 代码**

---

## 三、3 层架构(per Harness-Loop doc §3)

```
╔════════════════════════════════════════════════════════════╗
║  顶层 — 11 个独立 agent(mat-lit/gen/sim/hpc/exp/intent/   ║
║                    orch/critic/bayesian/cost/lineage)      ║
╠════════════════════════════════════════════════════════════╣
║  中层 — 每 agent 内部 Harness(Context+Tools+State+         ║
║                    Safety+Eval)+ Inner Loop 4 步           ║
╠════════════════════════════════════════════════════════════╣
║  底层 — WAU OS 层 Harness 中间件(11 agent 共享)            ║
║           wau-llm-router / wau-store / wau-circuit         ║
║           wau-trust / wau-scheduler / wau-registry        ║
╚════════════════════════════════════════════════════════════╝
```

**关键**:**WAU 不是某个 agent 的 Harness,而是 11 个 agent 共享的 OS 层 Harness 中间件**。

---

## 四、Phase 0 进度(W1-W2,2 周)

| W | 任务 | 状态 |
|---|---|---|
| **W1** | 设计 `MatWAU-AgentBase` 基类(Inner Loop 4 步)| ✅ **本次拍板(2026-07-24)** |
| **W1** | Goldens 测试集 50 case(mat-gen)| 📋 待启动 |
| **W2** | `mat-context-manager`(Stage 1 简版)| 📋 待启动 |
| **W2** | `mat-safety-guard`(Stage 1 简版)| 📋 待启动 |
| **W2** | 部署 WAU 8 服务 + 1 个 mat-lit 跑通 | 📋 待启动 |

**W1-W2 总工作量**:4.5 天(原本 W1 满)+ 1 天(原 W2 满)= 总 +0 天

---

## 五、快速开始

### 5.1 安装依赖

```bash
# Python 3.11+
pip install pytest  # 单元测试
# 后续:W1 末装 wau-python-sdk v1.3.3+
```

### 5.2 跑单元测试

```bash
cd /home/inamoto888/project/matwau
pytest tests/unit/ -v
```

### 5.3 写 1 个 MatWAU agent(3 步)

```python
# 1. 继承 MatWAU-AgentBase
from matwau.core.agent_base import MatWAUAgentBase, AgentRequest, AgentResponse

class MyAgent(MatWAUAgentBase):
    name = "my-agent"
    
    def system_prompt(self) -> str:
        return "你是材料科学 X agent,..."
    
    def act(self, ctx, tools):
        return AgentResponse(reply="ok", artifacts={}, confidence=0.9, cost=0.1)

# 2. 注入 Harness 部件(后续 W2 完成)
agent = MyAgent(
    context_manager=...,
    tool_registry=...,
    state_store=...,
    safety_guard=...,
    eval_harness=...,
)

# 3. 跑
req = AgentRequest(run_id="run-001", message="...", artifacts={}, context={})
response = agent.run(req)
print(response.reply)
```

---

## 六、跟 WAU 的边界(per project-matwau-os-boundary-2026-07-23)

| 组件 | 放哪 | 跟 WAU 关系 |
|---|---|---|
| **`MatWAU-AgentBase` 基类** | `matwau/core/agent_base.py` | **不放 WAU 仓**,跟 wau-python-sdk 平级 |
| **Goldens 测试集** | `tests/goldens/*.yaml` | 完全 MatWAU 自有 |
| **`mat-context-manager`** | `matwau/harness/` | MatWAU 自有,调用 wau-llm-router 选最便宜 LLM |
| **`mat-safety-guard`** | `matwau/harness/` | MatWAU 自有,跟 wau-trust JWT 互补 |
| **WAU 中间件** | 21 仓 | 共享基础设施,MatWAU agent 显式调用 |

**关键原则**:**Harness 部件 MatWAU 自有,WAU 提供共享中间件**。

---

## 七、当前进度(W1 Day 1)

- ✅ 项目目录骨架建好(per 开发计划 §十二)
- ✅ README.md 写好
- ✅ **`MatWAU-AgentBase` 基类** — 即将完成
- ✅ 单元测试 — 即将完成
- 📋 提交 user review 后进入 W1 Day 2(Goldens 测试集)

---

**end of MatWAU README**

> 维护者:Claude + MatWAU 项目组
> 反馈:发邮件或开 GitHub issue