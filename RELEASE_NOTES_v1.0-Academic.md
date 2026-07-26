# MatWAU v1.0-Academic Release Notes

> **发布日期**: 2026-07-26
> **版本类型**: 学院版首发(LTS 起)
> **License**: Apache 2.0
> **主署名**: XploreAlpha
> **部署目标**: 学院自有 / 学院指定服务器
> **数据归属**: 学院(详见 LICENSE)

---

## 一、一句话总结

**MatWAU v1.0-Academic = 35 周研发成果(1298 PASSED, 17 agent, 3 材料域)+ Apache 2.0 + XploreAlpha 主署名 + 学院版双署名 + 4 大法律声明 + 4 级 SLA 维护承诺。**

---

## 二、版本号语义

| 段 | 含义 |
|---|---|
| **v1** | MatWAU 第一个 stable 版本(从 v0.9.x → v1.0)|
| **.0** | 主版本号(学院版首发)|
| **-Academic** | 版本后缀,表示这是**学院版**(与未来商业版区分)|

未来版本路线图:

| 版本 | 计划时间 | 内容 |
|---|---|---|
| v1.0-Academic | 2026-07-26 | **学院版首发**(本次)|
| v1.1-Academic | 2026 Q4 | 8 周教学手册 + 课堂 PPT |
| v1.2-Academic | 2027 Q1 | 真仪器接入样板(等学院决定)|
| v2.0-Academic | 2027 Q3 | 产学研合作入口 |

---

## 三、新增(What is new)

### 3.1 学院版法律框架(W37.0)

| 项 | 内容 |
|---|---|
| **`LICENSE`** | Apache 2.0 + 捐赠声明 + 数据归属 + 部署 + 维护 4 大法律声明 |
| **`NOTICE`** | XploreAlpha 主署名 + 母校子署名 + 17 子项目清单 + 第三方依赖 |
| **`MAINTENANCE.md`** | 4 级 SLA(P0/P1/P2/P3)+ 维护范围 + 退路(Apache 永久授权)|
| **`README.md`** | 整体重写,顶部学院版声明 + 5 维表(主署名 / 子署名 / License / 数据归属 / 部署 / 维护)|
| **`docs/donation_proposal.md`** | 给院长的 3 页项目说明书 |

### 3.2 Stage 3 钢铁侠 JARVIS 雏形(W30-W33 累计)

- ✅ **W30 critic L4 跨机器人 5 规则 + 4 路打分**(L1 物理 + L2 合成 + L3 安全 + L4 跨机器人)
- ✅ **W31 多实验并行**(ThreadPoolExecutor + 异常隔离 + 3 demo)
- ✅ **W32 LineageStore 自动接线**(Postgres + SQLite + GIN 索引 + context manager)
- ✅ **W33 LLM 二次复核**(DeepSeek + deepseek-v4-flash + OpenAI 兼容 SDK + fail-soft)

---

## 四、核心能力清单(学院版适用)

### 4.1 17 agent(全部就绪)

```
核心 11:
  mat-gen-agent          造物主(晶体结构生成,3 材料域)
  mat-sim-agent          快速试菜员(MLIP CHGNet mock)
  mat-hpc-agent          超算对接员(VASP + Slurm mock)
  mat-exp-agent          实验老师(XRD Bragg 解谱 + DSC 分类)
  mat-intent-agent       翻译官(5 类意图 + 11 material_system)
  mat-orchestrator       DAG + ThreadPoolExecutor 多实验并行
  mat-critic-agent       L1+L2+L3+L4 + 可选 LLM 复核
  mat-bayesian           主动学习(GP + TPE + EI/UCB/PI)
  mat-cost               工作流预算守卫
  mat-data-lineage       Postgres + SQLite 自动接线
  mat-lit                arXiv API + RAG

高级 / 支撑 6:
  mat-chemist-agent      多机器人协调(W26)
  mat-robot-synth        OT-2 mock(W19)
  mat-robot-xrd          Bruker .brml mock(W20)
  mat-robot-em           Zeiss SmartSEM mock(W21)
  mat-robot-dsc          TA Trios mock(W22)
  MaterialDomainRouter   3 材料域路由(W15)
```

### 4.2 关键能力

| 维度 | 学院版可用 |
|---|---|
| 教学演示 | ✅ 一键跑通 3 demo(Inconel 718 / PMMA / TiO2)|
| 课堂 PPT | 📋 v1.1-Academic 计划 |
| 8 周实验课 | 📋 v1.1-Academic 计划 |
| 真仪器接入 | 📋 v1.2-Academic 计划(等学院决定)|
| LLM 复核 | ✅ 可选(DeepSeek + deepseek-v4-flash)|
| 真硬件(OT-2 等)| 🔒 W34 RESERVED |
| 商业化 API(Stripe)| ❌ 不做(学院版范围外)|

---

## 五、兼容性矩阵

| 维度 | v1.0-Academic |
|---|---|
| **Python** | 3.11+ |
| **操作系统** | Linux (Ubuntu 22.04+ 推荐) / macOS |
| **数据库** | SQLite(内置)+ PostgreSQL 14+(可选)|
| **内存** | 最小 4 GB,推荐 16 GB(教学场景)|
| **磁盘** | 最小 20 GB,推荐 100 GB(血缘 + 文献缓存)|
| **网络** | 离线完全可用(走 mock);可选外网(LLM 复核)|
| **依赖** | 见 `requirements.txt`(numpy / scipy / pyyaml / pytest / openai≥1.0 / psycopg / python-dotenv)|

---

## 六、升级与回退

### 6.1 升级到 v1.0-Academic

```bash
# 1. clone v1.0-Academic
git clone https://github.com/XploreAlpha/matwau.git
cd matwau
git checkout v1.0-Academic

# 2. 装新依赖
pip install -r requirements.txt

# 3. 跑回归测试(学院 IT 自检)
pytest tests/ -q
# 期望:1298 passed, 1 skipped
```

### 6.2 回退路径

如需回到 v0.x 系列:

```bash
git checkout v0.7.1  # 或更早版本
pip install -r requirements.txt
```

> v1.0-Academic 与 v0.x 系列数据兼容(LineageStore schema 保持 JSONB)。

---

## 七、已知问题与限制

### 7.1 已知限制

| 项 | 限制 | 解决时间 |
|---|---|---|
| 8 周教学手册 | v1.0-Academic 未含 | v1.1-Academic |
| 课堂 PPT | v1.0-Academic 未含 | v1.1-Academic |
| Docker Compose 单机包 | v1.0-Academic 未含 | v1.1-Academic |
| 真仪器接入样板 | v1.0-Academic 未含 | v1.2-Academic |

### 7.2 已知 trade-off

| 决策 | 取舍 |
|---|---|
| 5 个机器人 SDK 全 mock | 优点:学院版不依赖任何特定厂商;缺点:不接真仪器 |
| 默认 enable_llm_review=False | 优点:测试确定性 + 学院可不配 key;缺点:LLM 复核需显式 enable |
| LineageStore 默认 SQLite | 优点:零部署成本;缺点:大规模并发建议 Postgres |

---

## 八、鸣谢

35 周研发从 W1(2026-07-24)到 W33 + W37(2026-07-26),共 **17 agent + 1298 测试 + 35 周**。感谢母校给这次捐赠机会,XploreAlpha 团队承诺长期维护。

---

## 九、下载与文档

| 项 | 链接 |
|---|---|
| **GitHub Tag** | `v1.0-Academic`(本地,未 push)|
| **GitHub Release Notes** | 本文件 |
| **README** | [README.md](./README.md) |
| **LICENSE** | [LICENSE](./LICENSE) |
| **NOTICE** | [NOTICE](./NOTICE) |
| **MAINTENANCE** | [MAINTENANCE.md](./MAINTENANCE.md) |
| **学院说明书** | [docs/donation_proposal.md](./docs/donation_proposal.md) |
| **变更日志** | [CHANGELOG.md](./CHANGELOG.md) |

---

**end of RELEASE_NOTES_v1.0-Academic.md**

> 发布者:XploreAlpha 团队
> 日期:2026-07-26
> 本地 tag(未 push):`v1.0-Academic`
> 协议合规:0 push / 0 systemd / 0 PR / 全本地