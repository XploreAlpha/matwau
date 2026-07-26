# MatWAU 变更日志 (CHANGELOG)

> 所有 MatWAU 版本的重大变更记录。
> 学院版 v1.0-Academic 起,本文件按 **Keep a Changelog 1.1** 规范记录。

---

## [v1.1-Academic] - 2026-07-26 — 教学 + 部署 + 宣传配套合集

### Added(新增)
- **W37.2 — 8 周教学手册**(8 件 ~1201 行):
  - `docs/teaching_manual/README.md` — 教学手册入口索引
  - `docs/teaching_manual/01_overview.md` — 课程导入 + 4 步上手
  - `docs/teaching_manual/02_8week_curriculum.md` — 8 周详细大纲
  - `docs/teaching_manual/04_grading_rubric.md` — 100 分评分标准
  - `docs/teaching_manual/03_demo_scripts/W1_intent_classification.py` — W1 demo
  - `docs/teaching_manual/03_demo_scripts/W2_xrd_peak_decode.py` — W2 demo
  - `docs/teaching_manual/03_demo_scripts/W3_bayesian_optimize.py` — W3 demo
  - `docs/teaching_manual/03_demo_scripts/W4_critic_L1L4.py` — W4 demo
- **W37.4 — Docker Compose 单机包**(8 件 ~833 行):
  - `deploy/academic/Dockerfile` — python:3.11-slim + 非 root + healthcheck
  - `deploy/academic/docker-compose.yml` — 2 service + 2 volume
  - `deploy/academic/serve.py` — HTTP API 8 端点
  - `deploy/academic/.env.example` — DB 密码 + LLM env 模板
  - `deploy/academic/.dockerignore` — 构建排除规则
  - `deploy/academic/deploy_academic.sh` — 一键部署脚本
  - `docs/deploy_academic.md` — IT 部署完整文档
- **W37.5 — 招生宣传样板**:
  - `docs/outreach/academic_pitch.md` — 10 节 + 2 Mermaid + 11 维对比表 + 1 分钟脚本
- **W37.6 — 8 周课堂 PPT 讲义**:
  - `docs/teaching_manual/slides_8week.md` — 1154 行 + 51 PPT 页 + 13 Mermaid 流程图
- **`RELEASE_NOTES_v1.1-Academic.md`** — 本次发版说明(本文档配套)

### Changed(变更)
- `deploy/academic/VERSION` 从 `v1.0-Academic` → **`v1.1-Academic`**
- `deploy/academic/serve.py` `/version` 端点反映 v1.1-Academic

### Deprecated(即将弃用)
- 无

### Removed(移除)
- 无(完全向后兼容)

### Fixed(修复)
- 无(0 代码改动)

### Security(安全)
- API key 走 `.env` 文件,**绝不进对话 + 不进 git**(W37.4 模板)

---

## [v1.0-Academic] - 2026-07-26 — 学院版首发

### Added(新增)
- **学院版法律框架**(W37.0):
  - `LICENSE` — Apache 2.0 + 捐赠 / 数据归属 / 部署 / 维护 4 大声明
  - `NOTICE` — XploreAlpha 主署名 + 母校子署名 + 17 子项目清单 + 第三方依赖
  - `MAINTENANCE.md` — 4 级 SLA(P0/P1/P2/P3)+ 维护范围 + 退路
  - `README.md` 整体重写(顶部学院版声明)
  - `docs/donation_proposal.md` — 给院长的 3 页项目说明书
  - `RELEASE_NOTES_v1.0-Academic.md` — 本次发版说明
  - `CHANGELOG.md` — 本文件
- **Stage 3 JARVIS 雏形**(W30-W33):
  - W30 critic L4 跨机器人 5 规则 + 4 路打分
  - W31 多实验并行(ThreadPoolExecutor + 异常隔离)
  - W32 LineageStore 自动接线(Postgres + SQLite + GIN + context manager)
  - W33 LLM 二次复核(DeepSeek + deepseek-v4-flash + fail-soft)

### Changed(变更)
- `README.md` 从 W1 起步版(2026-07-24)整体重写,反映 35 周进展 + 学院版身份
- 顶部加学院版捐赠声明 + 5 维表

### Deprecated(即将弃用)
- 无

### Removed(移除)
- 无(完全向后兼容)

### Fixed(修复)
- LineageStore PostgresBackend schema 从 TEXT → JSONB(W32)
- LineageStore 加 GIN 索引(W32)
- MatOrchestrator 3 hook 点接入 LineageRecorder(W32)
- LLMReviewer fail-soft 兜底矩阵(W33)

### Security(安全)
- API key 走环境变量,绝不入对话(W33)
- 数据归属学校,MatWAU 不收集不触碰(W37.0)

---

## [历史版本] — v0.x 系列(W1-W29)

> v0.x 系列为学院版之前的快速迭代版本,2026-07-24 → 2026-07-25 共 5 周。

### [v0.9.x] - 2026-07-25 — W17-W23 累计

- ✅ **W17** metal_alloy 域 + PostgresBackend + Materials Project 真接
- ✅ **W18** mat-robot-synth + mat-robot-xrd 真 SDK
- ✅ **W19** OpentronsRealSDK OT-2 .py 真接
- ✅ **W20** BrukerRealSDK .brml XML 真接
- ✅ **W21** mat-robot-em(Zeiss SmartSEM .sxml)
- ✅ **W22** mat-robot-dsc(TA Trios .csv)
- ✅ **W23** 4 机器人全家福 + Postgres 部署
- 测试覆盖:**722/722 PASSED**

### [v0.8.x] - 2026-07-25 — W14-W16 累计

- ✅ **W14** mat-lit 替换最后 stub(85%) + mat-cost(100%) + mat-data-lineage(83%)
- ✅ **W15** MaterialDomainRouter 重铺地基(3 材料域路由)
- ✅ **W16** arXiv API 真接入 + SQLite 持久化
- 测试覆盖:**615/615 PASSED**

### [v0.7.x] - 2026-07-24 — W11-W13 累计

- ✅ **W11** mat-bayesian 主动学习(纯 NumPy GP + TPE + 3 acquisition)
- ✅ **W12** mat-critic 3 路交叉验证(L1 物理 + L2 合成 + L3 安全)
- ✅ **W13** mat-orchestrator DAG 调度器(5 workflow 模板)
- 测试覆盖:**524/524 PASSED**

### [v0.6.x] - 2026-07-24 — W8-W10 累计

- ✅ **W8** 测试 + 优化(Goldens 100%)
- ✅ **W9** mat-intent-agent 业务层意图解析
- ✅ **W10** mat-orchestrator DAG 调度器
- 测试覆盖:**326/326 PASSED**

### [v0.5.x] - 2026-07-24 — W1-W7 累计

- ✅ **W1** MatWAUAgentBase 基类 + Harness 心法
- ✅ **W3** mat-gen-agent 造物主
- ✅ **W4** mat-sim-agent 快速试菜员
- ✅ **W5** mat-hpc-agent 超算对接员
- ✅ **W6** mat-exp-agent 实验规划老师
- ✅ **W7** 端到端工作流整合
- 测试覆盖:**218/218 PASSED**

---

## 版本号规则(从 v1.0-Academic 起)

| 段 | 含义 | 示例 |
|---|---|---|
| **Major** | 不兼容变更 | v1 → v2 |
| **Minor** | 向后兼容新功能 | v1.0 → v1.1 |
| **Patch** | 向后兼容 bug 修复 | v1.0.0 → v1.0.1 |
| **Suffix** | 版本后缀 | `-Academic`(学院版)/ `-commercial`(未来)/ `-rc1`(候选)|

学院版 LTS:**18 个月安全更新**。学院版首发 v1.0-Academic → 下次学院版 v1.1-Academic(2026 Q4)。

---

## 升级路径

| 从 | 到 | 路径 |
|---|---|---|
| v0.9.x | v1.0-Academic | `git checkout v1.0-Academic` + `pip install -r requirements.txt` |
| v1.0-Academic | v1.1-Academic | 学院 IT 升级(2026 Q4)|
| v1.0-Academic | v1.2-Academic | 学院 IT 升级(2027 Q1)|

---

## 协议合规

- ✅ 0 push / 0 systemd / 0 PR / 全本地
- ✅ docs 全留本地(`docs/` + `~/WAU-develop/develop-log/MatWAU/`)
- ✅ 学院版独立 release 命名(`-Academic` 后缀)
- ✅ Apache 2.0 + 双署名 + 数据归学校 + 学校服务器 + XploreAlpha 长期维护

---

**end of CHANGELOG.md**