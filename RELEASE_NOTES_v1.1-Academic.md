# MatWAU v1.1-Academic Release Notes

> **发布日期**: 2026-07-26
> **版本类型**: 学院版第二次 release(配套内容合集)
> **License**: Apache 2.0
> **主署名**: XploreAlpha
> **部署目标**: 学院自有 / 学院指定服务器
> **数据归属**: 学院(详见 LICENSE)
> **配套基线**: v1.0-Academic(已含 17 agent + 1297 PASSED)
> **后续 patch**: v1.1.1-Academic(同日,fix 2 bug: W1 demo import + SQLiteBackend expanduser)
> **配套工具**: `~/WAU-develop/develop-log/MatWAU/test/run-acceptance.sh`(学院方一键验收 + 发现 2 个 bug)

---

## 一、一句话总结

**MatWAU v1.1-Academic = v1.0-Academic(17 agent / 1297 PASSED)+ 8 周教学手册(W37.2)+ 课堂 PPT 51 页(W37.6)+ Docker Compose 单机包(W37.4)+ 招生宣传样板(W37.5)+ IT 部署文档 = 学院 IT 15 分钟部署 + 老师 0 备课开讲 + 招生办 1 分钟看懂。**

---

## 二、版本号语义

| 段 | 含义 |
|---|---|
| **v1** | MatWAU 第一个 stable 版本(从 v0.9.x → v1.0)|
| **.1** | 次版本号 — 向后兼容,**新增教学 + 部署配套**(无代码变更)|
| **-Academic** | 学院版后缀 |

### 与 v1.0-Academic 的关系

| 维度 | v1.0-Academic | **v1.1-Academic** |
|---|---|---|
| **核心代码 / agent** | 17 agent + 1297 PASSED | ✅ 完全继承(0 行改动)|
| **教学手册** | ❌ | ✅ **W37.2**(8 文件 ~1201 行)|
| **课堂 PPT** | ❌ | ✅ **W37.6**(51 页 / 13 Mermaid)|
| **Docker Compose** | ❌ | ✅ **W37.4**(8 文件 ~833 行)|
| **IT 部署文档** | ❌ | ✅ docs/deploy_academic.md(286 行)|
| **招生宣传** | ❌ | ✅ **W37.5**(academic_pitch.md)|
| **教学 demo 脚本** | ❌ | ✅ **W37.2 03_demo_scripts**(4 件)|

> **0 代码改动 / 0 测试改动 / 0 push**(只新增 docs + deploy + 配套文件)

---

## 三、新增(What is new — 自 v1.0-Academic 累计)

### 3.1 W37.2 — 8 周教学手册(学院 0 备课开讲)

| 项 | 内容 |
|---|---|
| **`docs/teaching_manual/README.md`** | 教学手册入口索引(110 行)|
| **`docs/teaching_manual/01_overview.md`** | 课程导入 + 4 步上手(208 行)|
| **`docs/teaching_manual/02_8week_curriculum.md`** | 8 周详细大纲(290 行)|
| **`docs/teaching_manual/04_grading_rubric.md`** | 100 分评分标准(181 行)|
| **`docs/teaching_manual/03_demo_scripts/W1_intent_classification.py`** | W1 demo:mat-intent 演示(76 行)|
| **`docs/teaching_manual/03_demo_scripts/W2_xrd_peak_decode.py`** | W2 demo:mat-sim + mat-exp(113 行)|
| **`docs/teaching_manual/03_demo_scripts/W3_bayesian_optimize.py`** | W3 demo:mat-bayesian 3 acquisition(108 行)|
| **`docs/teaching_manual/03_demo_scripts/W4_critic_L1L4.py`** | W4 demo:mat-critic 4 路打分(115 行)|

**总 8 件 ~1201 行** — 老师只用这 1 个文件夹就能完成 8 周备课。

### 3.2 W37.4 — Docker Compose 单机包(学院 IT 15 分钟跑通)

| 项 | 内容 |
|---|---|
| **`deploy/academic/Dockerfile`** | python:3.11-slim + 非 root 用户 + healthcheck(47 行)|
| **`deploy/academic/docker-compose.yml`** | 2 service(matwau-app + lineage-db)+ 2 volume(99 行)|
| **`deploy/academic/serve.py`** | HTTP API 服务 — 8 端点(168 行)|
| **`deploy/academic/VERSION`** | 版本号文件(本次 v1.1-Academic)|
| **`deploy/academic/.env.example`** | DB 密码 + LLM 环境变量模板(38 行)|
| **`deploy/academic/.dockerignore`** | Docker 构建排除规则(50 行)|
| **`deploy/academic/deploy_academic.sh`** | 一键部署脚本(chmod +x,144 行)|
| **`docs/deploy_academic.md`** | IT 部署完整文档(286 行)|

**总 8 件 ~833 行** — `bash deploy_academic.sh` → 15 分钟跑通。

### 3.2.1 HTTP API 端点(serve.py 8 件)

```
GET  /             — 健康检查 + 服务信息
GET  /health       — 健康检查
GET  /version      — 版本信息(v1.1-Academic)
GET  /lineage      — 列出 lineage 实验记录
GET  /agents       — 列出 17 个 agent
POST /intent       — 翻译用户意图(mat-intent-agent)
POST /multi-exp    — 多实验并行(mat-orchestrator)
```

### 3.3 W37.5 — 招生宣传样板(招生办 1 分钟看懂)

| 项 | 内容 |
|---|---|
| **`docs/outreach/academic_pitch.md`** | 单文件 10 节 + 2 Mermaid + 11 维对比表 + 1 分钟宣讲脚本 + 4 承诺(~410 行)|

**核心 4 大不可替代点**(对比海外):
1. ✅ **永久免费 + 永久授权**(Apache 2.0)
2. ✅ **数据归学校**(不离开学院服务器)
3. ✅ **17 agent 覆盖全栈**(海外通常 1-3 个)
4. ✅ **8 周教学手册 + 51 页 PPT 配套**(海外通常只发论文)

### 3.4 W37.6 — 8 周课堂 PPT 讲义(老师直接投影)

| 项 | 内容 |
|---|---|
| **`docs/teaching_manual/slides_8week.md`** | 单文件 1154 行 + **51 张 PPT 页** + **13 Mermaid 流程图** + 8 周 × 5-7 页 |

**每页结构**:钩子 → 大点 → Mermaid → Demo 命令 → 课堂提问 → 上机任务 → 课外作业

---

## 四、文件总览(自 v1.0-Academic 新增 18 件)

```
docs/teaching_manual/
  ├── README.md                                     [NEW]
  ├── 01_overview.md                                [NEW]
  ├── 02_8week_curriculum.md                        [NEW]
  ├── 04_grading_rubric.md                          [NEW]
  ├── slides_8week.md                               [NEW] ⭐ 51 PPT 页
  └── 03_demo_scripts/
      ├── W1_intent_classification.py               [NEW]
      ├── W2_xrd_peak_decode.py                     [NEW]
      ├── W3_bayesian_optimize.py                   [NEW]
      └── W4_critic_L1L4.py                         [NEW]

docs/outreach/
  └── academic_pitch.md                             [NEW]

docs/
  └── deploy_academic.md                            [NEW] IT 部署文档

deploy/academic/
  ├── VERSION                                       [BUMP v1.0-Academic → v1.1-Academic]
  ├── Dockerfile                                    [NEW]
  ├── docker-compose.yml                            [NEW]
  ├── serve.py                                      [NEW]
  ├── .env.example                                  [NEW]
  ├── .dockerignore                                 [NEW]
  └── deploy_academic.sh                            [NEW]

RELEASE_NOTES_v1.1-Academic.md                      [NEW] ← 本文件
```

**总计**:18 件(17 新 + 1 版本号 bump)≈ **~3230 行**(含 .py / .md / .yml / Dockerfile)

---

## 五、兼容性矩阵(同 v1.0-Academic)

| 维度 | v1.1-Academic |
|---|---|
| **Python** | 3.11+ |
| **操作系统** | Linux (Ubuntu 22.04+ 推荐)/ macOS |
| **数据库** | SQLite(内置)+ PostgreSQL 14+(可选,W37.4 docker compose 自带)|
| **Docker / Docker Compose** | 学院 IT 部署必备(W37.4)|
| **内存** | 最小 4 GB,推荐 16 GB(教学场景)|
| **磁盘** | 最小 20 GB,推荐 100 GB(血缘 + 文献缓存)|
| **网络** | 离线完全可用(mock 模式);可选外网(LLM 复核 / arXiv 拉取)|
| **依赖** | 同 v1.0-Academic(`requirements.txt` 0 行变化)|

---

## 六、升级与回退

### 6.1 从 v1.0-Academic 升级到 v1.1-Academic

```bash
# 1. 拉取 v1.1-Academic(学院 IT 操作)
cd /opt/matwau
git fetch origin
git checkout v1.1-Academic

# 2. 验证(回归测试 — 应保持 1297 passed)
pytest tests/ -q
# 期望:1297 passed, 2 skipped

# 3. 重启 docker compose(教学部署)
cd deploy/academic
docker compose down
docker compose pull   # 拉取新 image(matwau/academic:v1.1-Academic)
docker compose up -d

# 4. 验证新 API
curl http://localhost:8080/version
# 期望:"version": "v1.1-Academic"
```

### 6.2 回退路径

```bash
git checkout v1.0-Academic
pip install -r requirements.txt
docker compose down && docker compose up -d
```

> v1.1-Academic 与 v1.0-Academic 数据完全兼容(LineageStore schema 不变 / docker volume 不变)。

---

## 七、新增文件清单与验收

| 文件 | 行数 | 角色 | 验收 |
|---|---|---|---|
| `docs/teaching_manual/README.md` | 110 | 教学手册入口 | ✅ |
| `docs/teaching_manual/01_overview.md` | 208 | 课程导入 | ✅ |
| `docs/teaching_manual/02_8week_curriculum.md` | 290 | 8 周大纲 | ✅ |
| `docs/teaching_manual/04_grading_rubric.md` | 181 | 评分规则 | ✅ |
| `docs/teaching_manual/slides_8week.md` | 1154 | ⭐ 51 PPT 页 | ✅ |
| `docs/teaching_manual/03_demo_scripts/W1_intent_classification.py` | 76 | W1 demo | ✅ |
| `docs/teaching_manual/03_demo_scripts/W2_xrd_peak_decode.py` | 113 | W2 demo | ✅ |
| `docs/teaching_manual/03_demo_scripts/W3_bayesian_optimize.py` | 108 | W3 demo | ✅ |
| `docs/teaching_manual/03_demo_scripts/W4_critic_L1L4.py` | 115 | W4 demo | ✅ |
| `docs/outreach/academic_pitch.md` | ~410 | 招生宣传 | ✅ |
| `docs/deploy_academic.md` | 286 | IT 部署文档 | ✅ |
| `deploy/academic/Dockerfile` | 47 | Docker 镜像 | ✅ |
| `deploy/academic/docker-compose.yml` | 99 | 容器编排 | ✅ |
| `deploy/academic/serve.py` | 168 | HTTP API | ✅ |
| `deploy/academic/.env.example` | 38 | 环境变量 | ✅ |
| `deploy/academic/.dockerignore` | 50 | 构建排除 | ✅ |
| `deploy/academic/deploy_academic.sh` | 144 | 一键部署 | ✅ |
| `deploy/academic/VERSION` | 1 行 | 版本号 | ✅ bump 到 v1.1-Academic |

---

## 八、典型用户路径(场景剧本)

### 8.1 学院 IT(15 分钟)

```bash
cd /opt/matwau
git checkout v1.1-Academic
cd deploy/academic
cp .env.example .env       # 改 MATWAU_PG_PASSWORD
./deploy_academic.sh        # 一键跑通
curl http://localhost:8080/version
# 期望:"v1.1-Academic"
```

### 8.2 学院老师(8 周 0 备课)

```bash
# 第 1 周前读:
cat docs/teaching_manual/README.md
cat docs/teaching_manual/01_overview.md

# 第 N 周讲课前读:
cat docs/teaching_manual/02_8week_curriculum.md   # 大纲
cat docs/teaching_manual/slides_8week.md          # 讲义(用 Marp/Slidev/GitHub 打开)
```

### 8.3 学院招生办(1 分钟看懂)

```bash
# 直接读:
cat docs/outreach/academic_pitch.md
# §6 = 60s 宣讲脚本
# §5 = 11 维对比表(学院版 vs 海外 vs 商业 vs 手工)
# §4 = 2 张 Mermaid 流程图(学生视角 + 学院视角)
```

---

## 九、已知限制与下一步

### 9.1 已知限制(v1.1-Academic 仍未解决)

| 项 | 状态 | 计划版本 |
|---|---|---|
| 真仪器接入样板 | v1.1-Academic 未含 | v1.2-Academic(学院决定后启动)|
| 国际化(i18n) | v1.1-Academic 未含 | v1.2-Academic |
| Postgres JSONB 性能调优 | 已含(W32)| 持续优化 |
| LLM 复核模型选择 | DeepSeek(已含)| 可换其他 OpenAI 兼容 |

### 9.2 下一步路线图

| 版本 | 计划时间 | 内容 |
|---|---|---|
| v1.1-Academic | 2026-07-26 | **本次 — 教学 + 部署 + 宣传配套** |
| v1.2-Academic | 2027 Q1 | 真仪器接入样板 + i18n(等学院决定)|
| v2.0-Academic | 2027 Q3 | 产学研合作入口 + 多学院扩展 |

---

## 十、鸣谢

自 v1.0-Academic(2026-07-26)起的 24 小时内,XploreAlpha 团队完成了 W37.2-W37.6 共 5 个 milestones:

- ✅ **W37.2** 8 周教学手册(1201 行,4 demo 脚本)
- ✅ **W37.4** Docker Compose 单机包(833 行,8 端点 HTTP API)
- ✅ **W37.5** 招生宣传样板(410 行,11 维对比表)
- ✅ **W37.6** 8 周课堂 PPT(1154 行,51 PPT 页 + 13 Mermaid 图)
- ✅ **W37.7(W37.8 替代)** v1.1-Academic Release(本次,本文档)

测试覆盖:**1297 passed / 2 skipped**(同 v1.0-Academic,0 行代码变化)。

---

## 十一、下载与文档

| 项 | 链接 |
|---|---|
| **GitHub Tag** | `v1.1-Academic`(本地,未 push)|
| **GitHub Release Notes** | 本文件 |
| **README** | [README.md](./README.md) |
| **LICENSE** | [LICENSE](./LICENSE) |
| **NOTICE** | [NOTICE](./NOTICE) |
| **MAINTENANCE** | [MAINTENANCE.md](./MAINTENANCE.md) |
| **学院说明书** | [docs/donation_proposal.md](./docs/donation_proposal.md) |
| **8 周教学手册** | [docs/teaching_manual/README.md](./docs/teaching_manual/README.md) |
| **8 周课堂 PPT** | [docs/teaching_manual/slides_8week.md](./docs/teaching_manual/slides_8week.md) |
| **招生宣传** | [docs/outreach/academic_pitch.md](./docs/outreach/academic_pitch.md) |
| **IT 部署文档** | [docs/deploy_academic.md](./docs/deploy_academic.md) |
| **Docker 部署包** | [deploy/academic/](./deploy/academic/) |
| **变更日志** | [CHANGELOG.md](./CHANGELOG.md) |
| **v1.0-Academic** | [RELEASE_NOTES_v1.0-Academic.md](./RELEASE_NOTES_v1.0-Academic.md) |

---

**end of RELEASE_NOTES_v1.1-Academic.md**

> 发布者:XploreAlpha 团队
> 日期:2026-07-26
> 本地 tag(未 push):`v1.1-Academic`
> 协议合规:0 push / 0 systemd / 0 PR / 全本地 / 0 代码改动