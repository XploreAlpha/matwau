# MatWAU — 材料科学 AI Agent 矩阵 (Material Science AI Universal)

> 🏛️ **学院版捐赠项目** | 由 **XploreAlpha** 捐赠给母校 | Apache 2.0 双署名

| 维度 | 内容 |
|---|---|
| **主署名** | XploreAlpha(开发方 / 维护方)|
| **子署名** | 母校(学术部署合作方)|
| **License** | [Apache License 2.0](./LICENSE) |
| **数据归属** | **学校**(详见 LICENSE §"DATA OWNERSHIP")|
| **部署** | 完全在学校自有 / 指定服务器(详见 LICENSE §"DEPLOYMENT")|
| **维护** | XploreAlpha 团队长期支持(详见 [MAINTENANCE.md](./MAINTENANCE.md))|

| 文档 | 链接 |
|---|---|
| **捐赠与法律说明** | [LICENSE](./LICENSE) |
| **维护说明** | [MAINTENANCE.md](./MAINTENANCE.md) |
| **贡献者与子项目列表** | [NOTICE](./NOTICE) |
| **给学院的"项目说明书"** | [docs/donation_proposal.md](./docs/donation_proposal.md) |

---

## 一、一句话定位

**MatWAU = 材料科学 17 agent 矩阵 + 灵魂 3 件套 + 高效 3 件套,跑在 WAU v1.0.0 上,35 周 MVP,Stage 3 钢铁侠 JARVIS 雏形 + 可解释性 100% 收口。**

类比:**MatWAU = 材料科学领域的 nginx** — 不露脸,但所有应用都离不开。

---

## 二、学院版价值(给决策者看的 1 段)

学院版价值三件套:
- 🎓 **教学** — 8 周实验课,本科生 4 小时看懂,2 天跑通
- 🔬 **科研** — 30+ 开箱即用 material agent,覆盖金属/聚合物/陶瓷 3 域
- 🏭 **示范** — Stage 3 JARVIS 雏形(从会跑到可观测到可解释),直接对接真仪器只需换 SDK

---

## 三、目录结构

```
matwau/                              ← 项目根(无头后端)
├── README.md                        ← 本文件(项目入口)
├── LICENSE                          ← ⭐ Apache 2.0 + 捐赠声明(W37.0)
├── NOTICE                           ← ⭐ 双署名 + 17 子项目清单(W37.0)
├── MAINTENANCE.md                   ← ⭐ 维护范围 + SLA(W37.0)
├── agents/                          ← 17 agent 代码(纯后端)
│   ├── mat-lit-agent/               ← 图书管理员(论文检索 + RAG)
│   ├── mat-gen-agent/               ← 造物主(晶体结构生成)
│   ├── mat-sim-agent/               ← 快速试菜员(MLIP 预筛)
│   ├── mat-hpc-agent/               ← 超算对接员(VASP + Slurm)
│   ├── mat-exp-agent/               ← 实验老师 + XRD 解谱
│   ├── mat-intent-agent/            ← 翻译官(5 类意图)
│   ├── mat-orchestrator/            ← DAG + 多实验并行
│   ├── mat-critic-agent/            ← 4 路交叉验证 + LLM 复核
│   ├── mat-bayesian/                ← 主动学习(Optuna)
│   ├── mat-cost/                    ← 成本估算
│   ├── mat-data-lineage/            ← 血缘记录
│   ├── mat-chemist-agent/           ← 化学师协调器(W26)
│   ├── mat_robot_synth/             ← OT-2 mock SDK(W19)
│   ├── mat_robot_xrd/               ← Bruker .brml mock(W20)
│   ├── mat_robot_em/                ← Zeiss SmartSEM mock(W21)
│   ├── mat_robot_dsc/               ← TA Trios mock(W22)
│   └── material_domain_router/      ← 3 材料域路由(W15)
├── matwau/                          ← 核心库
│   ├── core/                        ← MatWAUAgentBase + 类型
│   ├── harness/                     ← 5 大 Harness 职责
│   ├── outer_loop/                  ← Outer Loop 自愈
│   └── configs/                     ← matwau_settings 工厂
├── configs/                         ← 配置文件
├── workflows/                       ← workflow 模板
├── tests/                           ← 测试(35 周累计)
│   ├── unit/                        ← 单元测试
│   ├── integration/                 ← 集成测试
│   └── goldens/                     ← Goldens 测试集
├── docs/                            ← 用户 + 运维文档
│   ├── donation_proposal.md         ← ⭐ 学院版说明书(W37.0)
│   ├── user-manual.md
│   ├── deploy.md
│   └── ...
├── examples/                        ← 演示脚本
│   ├── multi_experiment_demo.py    ← W31 Stage 3 雏形
│   └── ...
├── scripts/                         ← 部署 + 维护脚本
├── deploy/                          ← Docker Compose + k8s manifest
└── requirements.txt
```

❌ MatWAU **不会**有的目录(无头架构):
- `ui/` / `frontend/` / `mobile/` / `web/` — **0 行 UI 代码**

---

## 四、3 层架构

```
╔════════════════════════════════════════════════════════════╗
║  顶层 — 17 agent(11 核心 + 4 robot + 1 router + 1 chemist)║
╠════════════════════════════════════════════════════════════╣
║  中层 — 每 agent 内部 Harness + Inner Loop 4 步            ║
╠════════════════════════════════════════════════════════════╣
║  底层 — WAU OS 层 Harness 中间件(共享)                    ║
╚════════════════════════════════════════════════════════════╝
```

---

## 五、当前状态(W33 末 / W37 启动)

### 5.1 35 周 MVP 全部完成 ✅

| 阶段 | 周次 | 内容 | 状态 |
|---|---|---|---|
| **Phase 1** | W1-W10 | 11 agent 上线 | ✅ |
| **Phase 2** | W11-W16 | arXiv 真接 + SQLite + Lineage | ✅ |
| **Phase 3** | W17-W23 | 4 机器人全家福 + Postgres | ✅ |
| **Phase 4** | W24-W29 | 4 真 SDK + 化学师 + k8s | ✅ |
| **Stage 3 可观测** | W30-W32 | critic L4 + 多实验并行 + LineageStore 自动接线 | ✅ |
| **Stage 3 可解释** | W33 | LLM 二次复核(DeepSeek + fail-soft) | ✅ |
| **学院版** | W37.0 | **Apache 2.0 + 双署名 + 法律框架**(本次)| ✅ |

### 5.2 测试覆盖

| 维度 | 数量 |
|---|---|
| **全量测试** | 1298 PASSED, 1 skipped, ~181s |
| **代码模块** | 17 agent + 1 router + 1 chemist + 5 harness + 1 lineage |
| **Goldens case** | 100+ 个 case,平均 90%+ |
| **集成测试** | 35+ 件 |
| **端到端** | Stage 3 JARVIS 雏形(Inconel 718 / PMMA / TiO2 多实验并行)|

### 5.3 学院版适配(W37.0 起)

- ✅ Apache 2.0 LICENSE
- ✅ 双署名 NOTICE
- ✅ 维护承诺 MAINTENANCE.md
- ✅ W37.0 — 学院版捐赠法律框架
- ✅ W37.2 — 8 周教学手册(1201 行 + 4 demo 脚本)
- ✅ W37.3 — 学院版 Release v1.0-Academic
- ✅ W37.4 — Docker Compose 单机包(833 行 + 8 端点 HTTP API)
- ✅ W37.5 — 招生宣传样板(11 维对比表 + 1 分钟脚本)
- ✅ W37.6 — 8 周课堂 PPT(1154 行 + 51 PPT 页 + 13 Mermaid 图)
- ✅ W37.8 — 学院版 Release v1.1-Academic(本次)

### 5.1 未来演进(高 level)

| 版本 | 时间 | 定位 | 详细 |
|---|---|---|---|
| **v1.1-Academic** | 2026-07 | ✅ 教学 + 部署 + 宣传配套 | [RELEASE_NOTES_v1.1-Academic.md](./RELEASE_NOTES_v1.1-Academic.md) |
| **v1.2-Academic** | 2027 Q1 | 真仪器接入 + i18n 英文版 + Q&A 反馈 | [docs/v1.2-roadmap.md](./docs/v1.2-roadmap.md) |
| **v2.0-Academic** | 2027 Q3+ | **WAU 网络 OS + App 生态 + Siri 入口**(学院版接入生态)| [docs/v2.0-vision.md](./docs/v2.0-vision.md) |

> v2.0 愿景:把 wau-core-kernel 部署到云端作为**网络版 iOS**,MatWAU / 企业 agent / 其他学院 agent 作为**各类 App** 部署到各本机(数据归属各本机),HomeRail 作为**Siri 入口**。云端不存数据,各本机数据不出本机。

---

## 六、快速开始(学院版)

### 6.1 部署(给学院 IT)

```bash
# 1. clone
git clone https://github.com/XploreAlpha/matwau.git
cd matwau

# 2. 装依赖
pip install -r requirements.txt

# 3. 跑通示例(mock 模式,无需任何外部 SDK / LLM)
python3 examples/multi_experiment_demo.py
# 期望:3 实验并行 + L4 复核 + BatchWorkflowResult

# 4. (可选)启用 LLM 复核
export MATWAU_LLM_API_KEY="<由学院 IT 配置>"
export MATWAU_LLM_BASE_URL="https://api.deepseek.com"
export MATWAU_LLM_MODEL="deepseek-v4-flash"
export MATWAU_LLM_ENABLED="1"
```

### 6.2 跑单元测试

```bash
cd /path/to/matwau
pytest tests/ -v
# 1298 passed, 1 skipped, ~181s
```

### 6.3 写 1 个 MatWAU agent(3 步)

```python
from matwau.core.agent_base import MatWAUAgentBase, AgentRequest, AgentResponse

class MyAgent(MatWAUAgentBase):
    name = "my-agent"

    def system_prompt(self) -> str:
        return "你是材料科学 X agent,..."

    def act(self, ctx, tools):
        return AgentResponse(reply="ok", artifacts={}, confidence=0.9, cost=0.1)

agent = MyAgent()
req = AgentRequest(run_id="run-001", message="...", artifacts={}, context={})
response = agent.run(req)
print(response.reply)
```

---

## 七、协议与边界(per memory 记录)

| 组件 | 放哪 | 跟 WAU 关系 |
|---|---|---|
| **`MatWAUAgentBase` 基类** | `matwau/core/agent_base.py` | **不**放 WAU 仓,跟 wau-python-sdk 平级 |
| **Goldens 测试集** | `tests/goldens/*.yaml` | 完全 MatWAU 自有 |
| **17 agent** | `agents/` | MatWAU 自有,调用 WAU 中间件 |
| **5 Harness 部件** | `matwau/harness/` | MatWAU 自有 |
| **WAU 中间件** | 21 仓(共享基础设施)| MatWAU 显式调用 |

**关键原则**:Harness 部件 MatWAU 自有,WAU 提供共享中间件。

---

## 八、致谢

感谢母校给这次捐赠机会。XploreAlpha 团队承诺长期维护,Apache 2.0 允许学院独立 fork 继续演进。

---

**end of MatWAU README**

> 主维护:XploreAlpha 团队
> 反馈:GitHub Issues https://github.com/XploreAlpha/matwau/issues
> 最后更新:2026-07-26(W37.0 学院版法律框架落地)