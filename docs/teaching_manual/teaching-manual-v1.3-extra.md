# MatWAU v1.3-Academic 教学手册增量 (teaching-manual-v1.3-extra)

> **本文件**:v1.3-Academic 学院版相对 v1.0-Academic 教学手册的增量章节
> **配套版本**:MatWAU v1.3-Academic(2026-08-04)
> **适用读者**:已熟悉 v1.0-Academic 教学手册的老师 / 学生(v1.3 新功能增量)
> **关联文件**:
> - 旧教学手册:`README.md` + `01_overview.md` + `02_8week_curriculum.md` + `04_grading_rubric.md`
> - 新增 demo:`03_demo_scripts/W4_critic_L1L5.py` + `W4.5_cross_source_validation.py` + `W5_orchestrator_4platforms.py`

---

## 一句话总结

**v1.3-Academic 在原 4 路 critic(L1 物理 + L2 合成 + L3 安全 + L4 跨机器人)基础上加入第 5 路 L5 跨数据源一致性,并接入 4 个开源材料数据平台(OQMD / COD / NOMAD / JARVIS),让 critic 能交叉验证候选物相的 DFT 形成能、带隙、晶系是否一致。**

---

## 一、新功能概览(per MatWAU v1.3-Academic)

| 类别 | 内容 | 教学关联 |
|---|---|---|
| **4 个数据客户端** | OQMD + COD + NOMAD + JARVIS(共 ~3000 行)| 演示跨源一致率 |
| **CanonicalKey 跨源对齐** | reduced_formula + pearson_symbol + spacegroup_number 联合去重 | 演示物相对齐 |
| **mat-critic L5 规则** | R6 consensus_rate / R7 formation_energy / R8 band_gap | 5-way 加权 |
| **2 个新 intent subclass** | external_db_query + cross_source_validation | W1 demo 加 2 类别 |
| **2 个新 orchestrator workflow** | cross_source_lookup + cross_source_property | W5 demo 4 库并行 |
| **4 个新 env vars** | MATWAU_NOMAD_API_BASE/TOKEN + MATWAU_JARVIS_API_BASE/TOKEN | IT 部署文档 |
| **测试基线** | 1297 → 1545 passed(+248,0 回归)| QA 文档 |

---

## 二、Critic 5 路打分(原 L1-L4 → L1-L5)

### 2.1 加权对比

| 路 | 名称 | 旧 v1.1 权重 | 新 v1.3 权重 | Δ |
|---|---|---|---|---|
| L1 | 物理合理性 | 0.30 | **0.27** | -0.03 |
| L2 | 合成可行性 | 0.30 | **0.27** | -0.03 |
| L3 | 化学安全 | 0.20 | **0.18** | -0.02 |
| L4 | 跨机器人一致性 | 0.20 | **0.18** | -0.02 |
| **L5** | **跨数据源一致性** | — | **0.10** | **+0.10** |

**L5 引入原理**:5 个数据平台可能给同一物相不同 DFT 形成能 / 带隙估计。L5 用 R6/R7/R8 3 个规则评估一致性,加权 0.10 后,L1+L2 仍占主导(54%),不破坏原有 critic 行为。

### 2.2 L5 3 个规则

| 规则 | 阈值(默认)| 失败码 | 含义 |
|---|---|---|---|
| **R6 consensus_rate** | ≥ 0.5 | `cross_source_low_consensus` | 至少 50% 库命中同一 CanonicalKey |
| **R7 formation_energy** | 偏差 ≤ 0.5 eV | `cross_source_energy_mismatch` | DFT 形成能跨库偏差 |
| **R8 band_gap** | 偏差 ≤ 0.3 eV | `cross_source_band_gap_mismatch` | 带隙跨库偏差 |

阈值在 `agents/mat_critic_agent/critic_engine.py` 顶部常量:

```python
DEFAULT_CONSENSUS_RATE_THRESHOLD = 0.5
DEFAULT_ENERGY_MISMATCH_THRESHOLD = 0.5  # eV/atom
DEFAULT_BAND_GAP_MISMATCH_THRESHOLD = 0.3  # eV
```

(v1.4 起暴露到 `MatWAUSettings`,v1.3 暂硬编码)

### 2.3 API 扩展

**`evaluate_cross_source_consistency(recs_by_platform)`**

```python
from agents.mat_critic_agent.critic_engine import (
    evaluate_cross_source_consistency, CrossSourceScore
)
from agents.oqmd_client import OqmdReference
from agents.cod_client import CodReference
from agents.nomad_client import NomadReference
from agents.jarvis_client import JarvReference

recs = {
    "OQMD": [OqmdReference(oqmd_id="o1", formula="Si", spacegroup="Fd-3m",
                          formation_energy_per_atom=-1.5)],
    "COD": [CodReference(cod_id="c1", formula="Si",
                          spacegroup_h_m="Fd-3m", spacegroup_number=227)],
    "NOMAD": [NomadReference(entry_id="n1", formula="Si",
                              spacegroup_symbol="Fd-3m", spacegroup_number=227,
                              formation_energy_per_atom_eV=-1.5, band_gap_eV=1.11)],
    "JARVIS": [JarvReference(jid="j1", formula="Si",
                              spacegroup_symbol="Fd-3m", spacegroup_number=227,
                              formation_energy_per_atom_eV=-1.5, band_gap_eV=1.11)],
}

cs: CrossSourceScore = evaluate_cross_source_consistency(recs)
# cs.score = 1.0(全过 R6/R7/R8)
# cs.consensus_rate = 1.0(4 库全命中)
# cs.n_clusters = 1(1 个 CanonicalKey 簇)
```

**`evaluate_with_cross_source(candidates, cross_source_records, user_intent)` — 5-way 加权入口**

```python
from agents.mat_critic_agent.critic_engine import evaluate_with_cross_source

verdict = evaluate_with_cross_source(
    candidates=[{"formula": "Si", "energy": -1.5}],
    cross_source_records=recs,
    user_intent="Si 候选评估",
)
# verdict.overall_score:5-way 加权总分
# verdict.cross_source.score:L5 单路分
# verdict.cross_source.consensus_rate:跨源一致率
```

**向后兼容**:
- `evaluate_candidates()`(3-way 旧入口)行为不变,L5 默认不参与
- `CriticOutput` 加 3 个 L5 字段(default=0.0),旧调用方不感知
- `CriticVerdict.cross_source` 字段默认 None,3-way 路径不填

---

## 三、4 个数据平台详解

### 3.1 OQMD (Open Quantum Materials Database)

| 维度 | 详情 |
|---|---|
| **覆盖** | DFT 形成能 + 相图(~100 万化合物)|
| **API 端点** | `https://oqmd.org/oqmdapi` |
| **认证** | 公开 |
| **客户端** | `agents/oqmd_client.py` (~870 行) |
| **WRAPPER** | `agents/mat_oqmd_agent.py` |
| **典型查询** | `OqmdClient.get_formation_energy(formula="LiCoO2")` |
| **缓存** | LRU maxsize=256,~5 MB |

### 3.2 COD (Crystallography Open Database)

| 维度 | 详情 |
|---|---|
| **覆盖** | 实验晶体结构(~50 万条目)|
| **API 端点** | `https://www.crystallography.net/cod/result` |
| **认证** | 公开 |
| **客户端** | `agents/cod_client.py` (~620 行) |
| **WRAPPER** | `agents/mat_cod_agent.py` |
| **典型查询** | `CodClient.search(formula="Si", spacegroup_number=227)` |
| **缓存** | LRU maxsize=256,~3 MB |

### 3.3 NOMAD (Novel Materials Discovery Laboratory)

| 维度 | 详情 |
|---|---|
| **覆盖** | 实验 + 计算全谱学,metainfo 35 映射路径 |
| **API 端点** | `https://nomad-lab.eu/prod/v1/api`(国内服务器可达性差)|
| **认证** | Token 可选,公开数据无需 |
| **客户端** | `agents/nomad_client.py` (~720 行) |
| **WRAPPER** | `agents/mat_nomad_agent.py` |
| **典型查询** | `NomadClient.get_entry(entry_id="NPDcV...")` |
| **缓存** | LRU maxsize=128,~12 MB(每条 metainfo ~100 KB)|
| **v1.3.1 计划** | metainfo 路径 35 → 60 |

### 3.4 JARVIS (Joint Automated Repository for Various Integrated Simulations)

| 维度 | 详情 |
|---|---|
| **覆盖** | DFT 标准化属性(~7 万化合物)|
| **API 端点** | `https://jarvis.nist.gov/rest` |
| **认证** | Token 可选,公开数据无需 |
| **客户端** | `agents/jarvis_client.py` (~830 行) |
| **WRAPPER** | `agents/mat_jarvis_agent.py` |
| **典型查询** | `JarvClient.get_property(jid="JVASP-1002", prop="formation_energy")` |
| **缓存** | LRU maxsize=128,~4 MB |
| **国内服务器** | 可达性差,默认走 mock,学院 IT 配 VPN 才能真接 |

### 3.5 网络策略

**默认**:`在线优先 + LRU cache + fail-soft`

```python
from agents.oqmd_client import OqmdClient
client = OqmdClient(enable_network=True)  # 默认

# 正常调用
records = client.search(formula="LiCoO2")

# 网络挂掉时
try:
    records = client.search(formula="LiCoO2")
except NetworkError:
    # 客户端内部已 LRU cache hit,返回旧值
    # cache 也无 → 返回空 list,不抛异常(fail-soft)
    pass
```

**学院 IT 国内服务器建议**:
```bash
# 配 MATWAU_NOMAD_API_BASE 镜像(国内有机构镜像)
MATWAU_NOMAD_API_BASE=https://mirror.example.cn/nomad/api

# JARVIS 国内可达性差,默认走 mock
# 真接需要配 VPN
```

---

## 四、W4.5 跨数据源验证周(可选新增周)

### 4.1 课时

- 1 学时(讲)+ 1 学时(上机)= 共 2 学时
- 可作为 W4-W5 之间插入的选修周

### 4.2 教学目标

- 理解跨数据源一致性问题(同一物相在不同库可能不同 DFT 估计)
- 看 cross_source_resolver 怎么聚类 + 检测冲突
- 看 critic L5 怎么用 3 规则评估一致性

### 4.3 Demo 演示

```bash
cd /path/to/matwau
python3 docs/teaching_manual/03_demo_scripts/W4.5_cross_source_validation.py
```

输出包含 4 部分:
1. `cross_source_lookup_workflow` DAG 结构(5 节点)
2. 7 subclass intent 路由(external_db_query + cross_source_validation)
3. `evaluate_with_cross_source` 5-way 加权评分
4. fail-soft 网络失败兜底演示

### 4.4 上机作业

```
作业 W4.5: 跨数据源验证入门
1. 跑 W4.5 demo,理解 4 个数据平台的差异
2. 改 demo 中 Si 的 cross_source_records,让 4 库全部不一致(不同晶系)
3. 看 L5 score 怎么降(应该 R6 fail → score < 0.5)
4. 解释为什么 L5 是 v1.3 最重要的 critic 新增
   (参考答案:L5 是数据集成独有维度,L1-L4 都是单数据评估)
```

### 4.5 评分点

| 维度 | 分值 |
|---|---|
| 跑通 demo + 改 cross_source_records | 40 分 |
| 解释 L5 3 个规则 | 30 分 |
| 解释 fail-soft + 国内可达性 | 20 分 |
| 思考:什么样的物相跨源差异会大 | 10 分 |

---

## 五、W5 多实验编排升级(per v1.3-Academic)

### 5.1 原 W5 升级点

| 升级前(v1.1) | 升级后(v1.3)|
|---|---|
| 5 个 workflow | **7 个 workflow**(+cross_source_lookup + cross_source_property) |
| critic L1-L4 | **critic L1-L5**(5-way 加权) |
| lineage 记录单库 | **lineage 跨 4 库追踪** |
| 不接外部数据源 | **接 4 平台**(在线优先 + LRU cache) |

### 5.2 新 Demo

```bash
cd /path/to/matwau
python3 docs/teaching_manual/03_demo_scripts/W5_orchestrator_4platforms.py
```

输出包含 6 部分:
1. WORKFLOW_BY_SUBCLASS 注册表(7 个)
2. intent 路由(external_db_query + cross_source_validation)
3. cross_source_lookup_workflow DAG 结构
4. cross_source_property_workflow DAG 结构
5. DAGExecutor outputs.X 解析(M3 新能力)
6. lineage_store 自动记录

### 5.3 上机作业

```
作业 W5(v1.3 升级): 多实验 + 4 平台编排
1. 跑 W5 demo,看 7 workflow 注册
2. 用 MatOrchestrator 跑 1 个 cross_source_lookup e2e:
   from agents.mat_orchestrator import MatOrchestrator
   from matwau.core.agent_base import AgentRequest
   orch = MatOrchestrator()
   req = AgentRequest(run_id="w5", message="查 Si 已知结构")
   result = orch.run(req, user_intent="查 Si 已知结构")
   print(result.artifacts["workflow_name"])  # cross_source_lookup
3. 看 lineage.db 有几条新记录
   sqlite3 ~/.matwau/lineage.db "SELECT count(*) FROM lineage_records;"
4. 解释为什么 lineage 跨库追踪很重要(数据归学校 + 可复现)
```

---

## 六、教学日历建议

| 周 | 主题 | 旧(v1.1) | 新(v1.3)|
|---|---|---|---|
| W1 | mat-intent-agent 入门 | 5 subclass + 11 material_system + 8 target_props | **+2 subclass + W1 demo 加 2 类别** |
| W2 | mat-sim-agent + mat-exp-agent | 不变 | 不变 |
| W3 | mat-bayesian-agent | 不变 | 不变 |
| W4 | mat-critic-agent | L1-L4 | **L1-L5(W4_critic_L1L5.py)** |
| **W4.5** | **跨数据源验证(可选)** | — | **新增 2 学时(W4.5 demo)** |
| W5 | mat-orchestrator run_batch | 5 workflow | **7 workflow(W5 demo + 4 库 e2e)** |
| W6 | mat-data-lineage | 不变 | **+ 跨 4 库 lineage 追踪** |
| W7 | LLM 二次复核 | 不变 | 不变 |
| W8 | 期末项目 | 自选 | **鼓励选跨数据源相关题目** |

---

## 七、与 v1.0-Academic 教学手册的兼容性

✅ **完全向后兼容**:
- 旧 demo `W4_critic_L1L4.py` 仍可用(行为不变,L5 默认 None)
- 旧 5 subclass 仍可用(行为不变)
- 旧 5 workflow 仍可用(行为不变)
- 旧 critic L1-L4 评估仍可用(L5 默认 0.0,旧权重回归)
- 学生从 v1.0 升级到 v1.3:**只需** 多读本文件 + 跑 2 个新 demo(W4_critic_L1L5.py + W4.5_cross_source_validation.py)

⚠️ **破坏性变更**:
- 无(0 破坏性变更,per `CHANGELOG.md v1.3-Academic`)

---

## 八、老师备课 checklist

- [ ] 看 `MatWAU-v1.3-Academic-RELEASE-NOTES.md` 一遍(发版说明)
- [ ] 跑 3 个新 demo(W4_critic_L1L5 / W4.5 / W5)确认输出符合预期
- [ ] 决定是否在 W4-W5 之间插入 W4.5(2 学时)
- [ ] 给学生发本文件作为 v1.3 增量材料
- [ ] 学院 IT 是否配 MATWAU_NOMAD_TOKEN / MATWAU_JARVIS_TOKEN(可选)
- [ ] W8 期末项目选题:鼓励选跨数据源相关(如"对比 OQMD + JARVIS 对 LiCoO2 形成能的差异")

---

## 九、学生学习 checklist

- [ ] 读本文件(增量章节,~20 分钟)
- [ ] 跑 `W4_critic_L1L5.py`,看 5-way 加权
- [ ] 跑 `W4.5_cross_source_validation.py`,看 4 库并行
- [ ] 跑 `W5_orchestrator_4platforms.py`,看 7 workflow
- [ ] 解释 L5 3 个规则 R6/R7/R8
- [ ] 解释 CanonicalKey 3 字段(reduced_formula + pearson_symbol + spacegroup_number)
- [ ] W8 期末项目:跨数据源验证题目(优先)

---

**end of teaching-manual-v1.3-extra.md**

> 编写日期:2026-08-04
> 配套版本:MatWAU v1.3-Academic
> License:Apache 2.0(同 MatWAU 主 license)
> canonical doc:`~/WAU-develop/develop-log/MatWAU/v1.3/MatWAU-v1.3-Academic-RELEASE-NOTES.md`