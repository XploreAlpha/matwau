# MatWAU 变更日志 (CHANGELOG)

> 所有 MatWAU 版本的重大变更记录。
> 学院版 v1.0-Academic 起,本文件按 **Keep a Changelog 1.1** 规范记录。

---

## [v1.4-Academic] - 2026-08-08 — MINOR: widget 协议层(M2 homerail voice cockpit)

### 概述

为 homerail voice cockpit 生成式 UI(v0.3-matwau-genui 同日 tag)接入 widget 协议层。
matwau 后端返回 `/wau/dispatch` 时附带 `widgets[]` / `spoken_text` / `structured_data`,
homerail 前端用这 3 字段在中央画布渲染卡片(论文列表 / 实验方案)。

### 新增

- **`agents/widget_schema.py`** (~125 行):
  - `WidgetType` enum:M2 暴露 2 种 widget(`matwau_paper_list` + `matwau_recipe_card`),M3 扩到 8 种
  - `WidgetLayout` enum:card_grid / list / table
  - `WidgetAction` enum:open_url / copy_doi / expand_abstract / expand_steps / show_sources / view_hit
  - `Widget` Pydantic model(`extra="ignore"` 向后兼容老 caller,`use_enum_values=False` 保持 enum 对象)
  - `M2_SUPPORTED_TYPES: frozenset[str]` 强断言只 2 个,防止 regression 偷偷加 widget
  - `widget_to_dict()` 工具函数:返回 JSON-safe dict
- **`agents/widget_helpers.py`** (~250 行):
  - `summarize_for_voice()`:TTS 专用短摘要,硬约束 ≤200 字符 + 严禁含 title/arxiv:/doi:/http(s)://
  - `assert_spoken_text_safe()`:硬断言 TTS 安全约束,失败即抛(给单测用)
  - `summarize_natural()` / `summarize_recipe_natural()`:自然语言摘要(给 reply 用)
  - `make_paper_list_widget()` / `make_recipe_card_widget()`:构造 widget,默认 fallback_text
  - `attach_widget_protocol()`:给 AgentResponse 加 3 字段(spoken_text / structured_data / widgets)
- **`AgentResponse` 新增 3 个 optional 字段**(`matwau/core/agent_base.py`):
  - `spoken_text: str | None = None`
  - `structured_data: dict[str, Any] | None = None`
  - `widgets: list[Any] = field(default_factory=list)`
  - 全 optional 默认值,**老调用方 0 改动**也能跑

### 修改

- **`WorkflowResult` 新增 1 个 optional 字段**(`agents/mat_orchestrator/dag.py`):
  - `final_response: Any = None`
  - `DAGExecutor.execute()` 表面最后节点的 AgentResponse 给 dispatch handler 透传 widgets
- **`MatOrchestrator._run_cross_source_parallel()`** 加 `final_response=critic_resp`
- **`serve.py` /wau/dispatch handler** 抽 widget 协议从 final_response:
  - 返回 JSON 加 `reply` / `spoken_text` / `structured_data` / `widgets` 4 字段
  - 老 workflow 走 fallback 路径,空 widgets 数组
- **`MatArxivAgent._results_to_response()`** 自动 attach paper_list widget(records 非空时)
- **`MatExpAgent.act()`** 自动 attach recipe_card widget(recipes 非空时)

### 性能

- widget 构造开销:< 1ms / call(纯 Pydantic + dict 操作)
- serve.py response size 增长:< 5KB / response(论文 5 篇 + widget)

### 兼容性

- ✅ 老 caller 0 改动:AgentResponse 3 字段全 optional,WorkflowResult 1 字段 optional
- ✅ 老 acceptance.sh 22 场景 0 回归(4 新增 widget 场景 T14-T17)
- ✅ homerail v0.3-matwau-genui 同日 tag,可立即消费 widgets 字段

### 测试

- 新增 `tests/unit/test_widget_schema.py`(5 单测)
- 新增 `tests/unit/test_widget_helpers.py`(12 单测)
- `tests/unit/test_mat_arxiv_agent.py` 追加 15 v14_* 单测
- `tests/unit/test_mat_exp_agent.py` 追加 12 v14_* 单测
- 共 39 M2 widget 单测,所有 PASS
- 老 pytest 回归:217 passed in M2-touched 文件(M2 widget schema/helpers + arxiv/exp agent + agent_base + serve + orchestrator + dag)
- 4 pre-existing baseline fail 不属 M2 范围(critic cross_source + nomad typed tuple,本 commit 前已存在)

---

## [v1.3.4-Academic] - 2026-08-06 — MINOR: paper PDF parse + semantic search

### 概述

把 v1.3.3 拿到的"论文摘要(abstract)"扩展到"全文段落(paragraphs)" + "跨论文语义搜索",让学院方能做更细粒度的文献调研。

### 新增

- **`agents/pdf_parser/`** (~480 行):
  - `PdfParserClient`(对齐 `ArxivClient` 模板):pdfplumber 真解析 → `PdfDocument` + `PdfParagraph[]`
  - 三种入口:`parse_pdf`(本地路径)/ `parse_pdf_from_url`(HTTP 下载)/ `parse_pdf_from_bytes`(上传)
  - LRU cache(默认 32)+ `__bool__ → True`(防空 cache `if cache:` 误判)
  - 防御性 limit:`max_pages=50` + `min_paragraph_chars=20`
  - 扫描版 PDF 检测(`parse_succeeded=false`,graceful 失败)
  - 模块级 `parse_pdf` / `parse_pdf_from_url` / `parse_pdf_from_bytes` 便利函数
  - `is_pdfplumber_available()` availability check
- **`agents/mat_pdf_agent/`** (~330 行):
  - `MatPdfAgent(MatWAUAgentBase)`:业务 wrapper,3 入口 + artifacts 透传
  - `PdfAgentConfig` dataclass(`cache_size` / `max_pages` / `download_timeout` / `paper_id`)
- **`agents/semantic_search/`** (~330 行):
  - `SemanticSearchClient`:sklearn TF-IDF + cosine similarity,纯本地
  - `SearchHit`(paper_id + paragraph_no + page_no + text + relevance)
  - LRU query cache(默认 100)+ `__bool__ → True`
  - 模块级 `search()` 便利函数 + `search_client` 全局 singleton(serve.py 用)
  - `is_sklearn_available()` availability check
- **`serve.py` 扩展**:
  - `/literature` 加 `parse_full_text: bool = False` + `top_k: int = 3` 参数
  - `/literature` 返回加 `full_text_sections[]` + `semantic_hits[]` + `parse_full_text_succeeded`
  - 新端点 `POST /papers/upload`(multipart/form-data + JSON 两种入口)
  - 新端点 `POST /papers/search`(JSON,query + top_k)
  - 模块级 `_do_parse_full_text(references, message, top_k)` helper(arxiv /abs/ URL → /pdf/ 自动转)

### 性能

- PDF 解析:< 5s(20 页标准论文)
- TF-IDF 索引构建:< 1s(100 篇 × 50 段)
- 语义搜索:< 200ms
- LRU cache 命中:< 1ms

### 兼容性

- ✅ v1.3.3 `/literature` 老调用者 0 改动(`parse_full_text` 默认 False)
- ✅ 老 acceptance.sh 22 场景 0 回归
- ✅ sklearn / pdfplumber 缺失 graceful 失败(返空 list,不抛异常)

### Bug 修复(本次实施期间踩到)

- **`_LruCache.__bool__` 修复**:空 cache 时 `bool(cache) = False`(因 `__len__ = 0`),`if cache: cache.put(...)` 永远不进 put 分支。修复:`__bool__ → return True`(模板从 v1.3.2 `ArxivClient._LruCache` 复制就有这 bug,本次顺手修了)。
- **v1.3.3 `LitConfig` 默认值漏改**:commit `d138ba4` 改 `lit_engine.py` 但漏改 `mat_lit_agent.py:66/74`,学院服务器部署后 `/literature` `sources_queried` 还是老列表。已 hotfix `b217125` 修复。教训:defaults 改动必须 cross-check 所有 caller + 强断言。

### 依赖

新增 2 个:
- `pdfplumber>=0.10.0`(pure Python / MIT / ~5MB)
- `scikit-learn>=1.3.0`(BSD-3-Clause / ~30MB)

### 配套 dev-plan

- `~/WAU-develop/develop-log/MatWAU/v1.3.4/MatWAU-v1.3.4-Academic-requirements-20260806.md` 需求
- `~/WAU-develop/develop-log/MatWAU/v1.3.4/MatWAU-v1.3.4-Academic-dev-plan-20260806.md` 开发 plan
- `closure-2026-08-06.md`(本批完成后写)

### 测试

- `tests/unit/test_pdf_parser_client.py`:32 测试
- `tests/unit/test_mat_pdf_agent.py`:19 测试
- `tests/unit/test_semantic_search_client.py`:22 测试
- `tests/unit/test_serve_papers_endpoint.py`:13 测试
- **新测试总计:86**(全 PASS)
- 老测试(`test_mat_lit_agent.py` + `test_serve_literature_endpoint.py`):60 PASS,0 回归
- 总:**146 测试全 PASS,0 回归**

### Docker / 部署

- image tag:`v1.3.3-Academic` → `v1.3.4-Academic`
- Dockerfile 自动装 pdfplumber + scikit-learn(per requirements.txt)
- 学院服务器:`docker compose build --no-cache && up -d`(image 增 ~35MB)

---

## [v1.3.3-Academic] - 2026-08-06 — MINOR: PubChem + CrossRef + /literature 端点

per v2.0 JARVIS 计划阶段 1 的第 2 步,与 v1.3.2 同一节奏。学院方/Homerail 一行 curl 查文献。
配套 dev-plan:`~/WAU-develop/develop-log/MatWAU/v1.3.3/MatWAU-v1.3.3-Academic-dev-plan-20260806.md`

### Added(新增)

- **PubChem client + wrapper agent(`agents/pubchem_client/` + `agents/mat_pubchem_agent/`)** — 复用 v1.3.2 arxiv 模板(~500 行)
  - `PubChemClient`:LRU cache + gzip + 硬上限 20(per v1.3.2 模板)
  - 真查 PubChem REST API(无需 API key,NIH 公共数据,CC-BY 4.0)
  - 查询字段:CID / MolecularFormula / MolecularWeight / IUPACName / CanonicalSMILES / IsomericSMILES / InChI / InChIKey
  - 速率 5 req/sec(per PubChem docs)— LRU cache 复用
  - `MatPubChemAgent` wrapper agent(对齐 mat_arxiv_agent 模式)
  - confidence 启发式:0→0.3, 1→0.6, ≥2→0.8
- **CrossRef client + wrapper agent(`agents/crossref_client/` + `agents/mat_crossref_agent/`)** — 复用模板(~500 行)
  - `CrossRefClient`:`mailto=` query param 标识礼貌使用(per CrossRef etiquette)
  - 真查 CrossRef works API(公共元数据,无需 API key)
  - 查询字段:DOI / title / authors / journal / year / volume / issue / pages / publisher / type / citations_count / abstract(JATS XML stripped)
  - `MatCrossRefAgent` wrapper agent(对齐模式)
- **`POST /literature` 专用端点(`deploy/academic/serve.py`)** — v1.3.3 核心
  - 学院方/Homerail 一行 curl 调 MatLitAgent
  - 入参:`{message, n_results, domain}`
  - 出参:`reply / is_real_query / n_results / sources_queried / references / background / state_of_art / gaps / suggestions / cost`
  - 缺 message → 400;agent 抛错 → 500

### Changed(变更)

- **`mat_lit_agent.sources_queried`**:arXiv(per v1.3.2)+ **PubChem** + **CrossRef**(v1.3.3)
  - Materials Project / ICSD 字符串占位保留(W17/M17-C 没真接)
- **`serve.py` 默认 version**:v1.3.2-Academic → v1.3.3-Academic
- **`deploy_academic.sh` MATWAU_VERSION**:同步

### Tests(测试)

- 新增 `tests/unit/test_pubchem_client.py` — 37 测试(LRU + gzip + fallback + cache + JATS + author + year)
- 新增 `tests/unit/test_mat_pubchem_agent.py` — 23 测试(wrapper + confidence + safety)
- 新增 `tests/unit/test_crossref_client.py` — 37 测试(LRU + gzip + fallback + cache + JATS strip)
- 新增 `tests/unit/test_mat_crossref_agent.py` — 18 测试(wrapper + confidence + safety)
- 新增 `tests/unit/test_serve_literature_endpoint.py` — 11 测试(端点 200/400/500/n_results/domain/sources_queried)

总计:**126 个新测试项**,全 PASS

### Compatibility(兼容性)

- 公开 API 不变:`ArxivClient` / `MatLitAgent` / 4 平台 wrapper 不动
- `mat_lit_agent(use_real_arxiv=False)` 仍可用
- `/intent` / `/multi-exp` / `/wau/dispatch` 不破坏

### Documentation(文档)

- `~/WAU-develop/develop-log/MatWAU/v1.3.3/` 新建:
  - `MatWAU-v1.3.3-Academic-requirements-20260806.md` 需求
  - `MatWAU-v1.3.3-Academic-dev-plan-20260806.md` 开发 plan
  - `closure-2026-08-06.md`(本批完成后写)
- Docker image tag:`v1.3.2-Academic` → `v1.3.3-Academic`
- `serve.py` 默认 version 同步
- `deploy_academic.sh` MATWAU_VERSION 同步

### Performance(性能)

- PubChem 单查询:< 8s(timeout)
- CrossRef 单查询:< 10s(timeout)
- LRU cache 命中:< 1ms
- Fallback 路径:< 100ms(本地 mock)

### Risk(风险与缓解)

- **学院网络封 PubChem/CrossRef**:默认 `enable_fallback=True`,acceptance.sh 场景 24/25 改 WARN 不 FAIL
- **PubChem 5 req/s 限流**:LRU cache 复用 + 默认 n=5
- **CrossRef `X-Rate-Limit-*`**:User-Agent + mailto(礼貌使用)
- **CI 无外网**:unit 测试全 monkeypatch,真查只在学院服务器 acceptance 跑

### Hotfix(v1.3.3-Academic post-GA,2026-08-06)

**Bug**:`LitConfig` 默认 `sources=["arXiv", "Materials Project", "ICSD", "PubChem"]` 覆盖了 `lit_engine.py` v1.3.3 改的 `["arXiv", "PubChem", "CrossRef"]`。**所有走 MatLitAgent 的调用都拿老列表**(`/literature` 端点 `sources_queried` 字段返回 `["arXiv", "MP", "ICSD", "PubChem"]`,与 lit_engine 真接 3 源不符)。

**根因**:v1.3.3 commit `d138ba4` 改了 `lit_engine.py:608/722/916` 三处默认值,**漏改** `mat_lit_agent.py:66/74` 的 `LitConfig.__post_init__` 和 `from_dict`。原 unit test `test_default` 只断言 `"arXiv" in cfg.sources` — 真假都过,漏抓。

**Fix**:
- `agents/mat_lit_agent/mat_lit_agent.py` 两处默认值同步 → `["arXiv", "PubChem", "CrossRef"]`
- `system_prompt` + Stage 1 注释同步
- 新增 5 个 regression test(`TestLitConfig.test_default_sources_match_v133` / `test_from_dict_default_sources_match_v133` / `test_from_dict_explicit_sources` + `test_literature_endpoint_real_agent_sources_v133`)
- 测试结果:60 PASS(45 mat_lit_agent + 11 serve + 4 新),0 回归

**影响**:v1.3.3-Academic 第一次 push 后立刻发现;**用户需 `--force-with-lease` 重推**(tag 不变 `v1.3.3-Academic`)

---

## [v1.3.2-Academic] - 2026-08-06 — PATCH: arxiv 真 API 默认启用

per v2.0 JARVIS 计划阶段 1(M4 + 1 个月)的第 1 步,小步快跑节奏下的 v1.3 系列 patch。
配套 dev-plan:`~/WAU-develop/develop-log/MatWAU/v1.3.2/MatWAU-v1.3.2-Academic-dev-plan-20260806.md`

### Added(新增)

- **新 wrapper agent `agents/mat_arxiv_agent/`** — 对齐 OQMD/COD/NOMAD/JARVIS 4 平台模式(~300 行)
  - 继承 `MatWAUAgentBase`,有 `system_prompt` / `act` / `perceive` / `_empty_response` / `_error_response`
  - 包装 `ArxivClient.search` → 标准 `AgentResponse`(records + is_real_query + confidence + cost)
  - `ArxivAgentConfig` dataclass + `from_dict` 工厂;`max_results_hard_cap=20` 截断保护
  - confidence 启发式:0→0.3, 1-2→0.6, ≥3→0.8
  - 默认 `use_real_arxiv=True`,失败 fallback mock(W14 向后兼容)
  - SafetyGuard 集成(per mat_oqmd_agent 模式)

- **`agents/arxiv_client/` LRU cache** — 复用 nomad_client 模式
  - `_LruCache` 类,OrderedDict + move_to_end,默认容量 128
  - `ArxivClient` 加 `cache_size` / `enable_cache` 字段,`__post_init__` 初始化
  - `clear_cache()` 方法(测试 / 显式 invalidate 用)
  - 同 query < 1ms 命中(LRU hit 标记 `is_real_query=True`)
  - capacity 必须 ≥ 1(`ValueError` 保护)

- **`agents/arxiv_client/` gzip 压缩支持** — 仿 arxiv 文档建议
  - `enable_gzip=True`(默认)发 `Accept-Encoding: gzip`
  - 响应头 `Content-Encoding: gzip` 时 `gzip.decompress()` 解压
  - 解压失败时 graceful fallback(用 raw bytes decode)
  - 大响应省 70% 流量(per arxiv API 文档建议)

- **`agents/mat_lit_agent/` 默认 `use_real_arxiv=True`** — 主开关打开
  - `lit_engine.py:review_literature` / `search_literature_with_real_sources` 默认参数 False → True
  - `mat_lit_agent.py:MatLitAgent.__init__` 默认参数 False → True
  - 向后兼容:`use_real_arxiv=False` 仍可用(走 W14 mock DB)

- **`hard_max_results=20` 硬上限保护** — `ArxivClient` 默认
  - 防滥用 max_results 拉巨大响应

### Tests(测试)

- 新增 `tests/unit/test_arxiv_client.py` — 33 测试(LRU/gzip/fallback/cache 命中)
- 新增 `tests/unit/test_mat_arxiv_agent.py` — 24 测试(wrapper/confidence/safety)
- `tests/unit/test_mat_lit_agent.py` 加 4 测试(`TestUseRealArxivDefault` 类)
  - 验证 `MatLitAgent().use_real_arxiv is True`
  - 验证 `review_literature()` 默认参数 `use_real_arxiv=True`
  - 验证 `use_real_arxiv=False` 向后兼容

总计:**57 个新测试 + 4 个更新测试 = 61 测试项**,全 PASS

### Compatibility(兼容性)

- 公开 API 不变:`ArxivClient().search()` / `MatLitAgent()` 签名兼容
- 默认行为变化:`use_real_arxiv` 默认 True(W16 已支持,但默认 False)— 学院方升级后所有 literature_review workflow 自动走真 arXiv
- 数据归属不变,无版权问题(只 metadata + abstract,不下载 PDF)

### Documentation(文档)

- `~/WAU-develop/develop-log/MatWAU/v1.3.2/` 新建:
  - `MatWAU-v1.3.2-Academic-requirements-20260806.md` 需求
  - `MatWAU-v1.3.2-Academic-dev-plan-20260806.md` 开发 plan
  - `closure-2026-08-06.md`(本批完成后写)
- Docker image tag:`v1.3.1-Academic` → `v1.3.2-Academic`
- `serve.py` 默认 version 同步
- `deploy_academic.sh` MATWAU_VERSION 同步

### Performance(性能)

- 单次 arxiv 真查:< 8s(per `ARXIV_TIMEOUT_SEC=8`)
- LRU cache 命中:< 1ms
- Fallback 路径:< 100ms(本地 mock)

### Risk(风险与缓解)

- **学院网络封 arxiv.org**:默认 `enable_fallback=True`,fallback mock 不报错
- **CI 无外网**:unit 测试全 monkeypatch,真查只在学院服务器 acceptance 跑
- **真查延迟 8s+**:LRU cache 复用 + 默认 n_results=5 + 可调小

---

## [v1.3.1-Academic] - 2026-08-05 — PATCH: 4 P0/P1 + 1 P2 + 1 隐含 + Bug #5 收口

per homerail 团队通过前端实测反馈的 6 个 bug(分 2 批收口)。

### Fixed(修复)

- **Bug #2 experiment_placking confidence 兑底** — `agents/mat_exp_agent/mat_exp_agent.py`
  - `_empty_response` confidence 0.1 → 0.5,加 `is_template_fallback=True` 标记 + 默认烧结/XRD 参数
  - 原因:链路本身正常(mat-gen→sim→hpc→exp 全通),问题在 exp 无上游时硬编 conf=0.1 让前端误以为是 bug

- **Bug #3 cross_source 50.9s 超时** — `agents/mat_orchestrator/mat_orchestrator.py`
  - per-client timeout 20s → 10s(刚好覆盖内层 client timeout 10-12s)
  - timeout 时改返 `success=True + outputs={"records": []}`,critic L5 仍能跑
  - 实测 50.9s → 8.36s,提速 6×

- **Bug #4 consensus_rate=0 修** — `agents/data_canonical/canonical_key.py` + `cross_source_resolver.py`
  - `CanonicalKey.from_record` + `_extract_energy` / `_extract_band_gap` 加 `_get()` helper,同时支持 dict 和 dataclass
  - 原因:4 client agent 用 `r.to_dict()` 转 plain dict,旧版 `getattr(dict, "formula")` 返回 None,12 record 全 drop

- **Bug #5 outer consensus_rate 字段映射错** — `agents/mat_orchestrator/mat_orchestrator.py`
  - `_run_cross_source_parallel` 改从 `critic_output` 对象直接读 `.l5_cross_source_consensus_rate` / `.verdict` / `.overall_score`,不再用 `artifacts.get("consensus_rate")`(路径错)
  - 修复:`final_outputs.consensus_rate` 0.0 → 1.0,verdict 从 CriticOutput repr 变 "warn" 字符串

- **P2 版本不一致** — `agents/wau_protocol_adapter/dispatch_handler.py`
  - GET `/wau/dispatch` 改读 VERSION 文件 + 加 `last_fix_at` + `fix_summary`
  - 修前:硬编 "v1.1.1-Academic",但 VERSION = v1.3-Academic

- **隐含 bug orch.run(req) TypeError** — `agents/wau_protocol_adapter/dispatch_handler.py`
  - `MatOrchestrator.run(*, user_intent)` 是 keyword-only,旧代码 `orch.run(req)` 会 TypeError
  - 改成 `orch.run(user_intent=intent)` + 返回 `wf_result` 字段对齐 serve.py

### Added(新增)

- **docs/MATWAU-CROSS-SOURCE-TIMEOUT.md** (88 行)
  - cross_source workflow timeout 配置 SoT
  - 客户端 timeout 建议:CLI ≥ 60s,DAG node ≥ 60s,reverse proxy ≥ 30s
  - homerail 团队配套升级清单(60s → 120s 等)

### Test

- `tests/unit/test_cross_source_resolver.py::test_single_source_only` 期望更新
  - 单源 consensus_rate: 0.0 → 1.0(per Bug #4 新语义)
- `test_mat_orchestrator_cross_source.py` 12/12 PASS
- 全仓 145/145 PASS,0 回归

---

## [v1.3-Academic] - 2026-08-04 — 4 平台数据接入 + critic L5 跨源验证

### Added(新增)

- **M1 — OQMD + COD 客户端(M1 + W24-W26)**:
  - `agents/oqmd_client.py` (~870 行) — DFT 形成能 + 相图查询,LRU cache
  - `agents/cod_client.py` (~620 行) — 实验晶体结构查询,LRU cache
  - `agents/mat_oqmd_agent.py` + `agents/mat_cod_agent.py` — 2 个 wrapper agent
  - `agents/data_canonical/canonical_key.py` — CanonicalKey 跨源物相对齐(reduced_formula + pearson_symbol + spacegroup_number)
  - `tests/unit/test_oqmd_client.py` + `test_cod_client.py` + `test_canonical_key.py` + `test_mat_oqmd_agent.py` + `test_mat_cod_agent.py` — 89 unit tests
  - 累计测试:1297 → **1386**(+89)
- **M2 — NOMAD + JARVIS 客户端(M2 + W27-W29)**:
  - `agents/nomad_client.py` (~720 行) — NOMAD metainfo,~35 映射路径,LRU cache,Token 可选
  - `agents/jarvis_client.py` (~830 行) — JARVIS REST + jarvis-tools Python 包双驱动,LRU cache
  - `agents/mat_nomad_agent.py` + `agents/mat_jarvis_agent.py` — 2 个 wrapper agent
  - `tests/unit/test_nomad_client.py` + `test_jarvis_client.py` + `test_mat_nomad_agent.py` + `test_mat_jarvis_agent.py` — 93 unit tests
  - 累计测试:1386 → **1479**(+93)
- **M3 — cross_source_resolver + critic L5 + orchestrator workflow(M3 + W30-W33)**:
  - `agents/data_canonical/cross_source_resolver.py` (388 行) — 4 record → ConsensusReport + consensus_rate + Conflict 列表
  - `mat_critic_agent/critic_engine.py` — 新增 `CrossSourceScore` dataclass + `evaluate_cross_source_consistency()` + `evaluate_with_cross_source()` 5-way 加权入口
  - 3 个新规则:R6 cross_source_consensus_rate / R7 formation_energy_consistency / R8 band_gap_consistency
  - `mat_intent_agent/intent_classifier.py` — SUBCLASSES 5→7,新增 `external_db_query` + `cross_source_validation`
  - `mat_orchestrator/dag.py` — 新增 `cross_source_lookup_workflow` + `cross_source_property_workflow`(各 5 节点)+ DAGExecutor 支持 `outputs.X` src_key 解析
  - `matwau/configs/matwau_settings.py` — 新增 4 env vars(`MATWAU_NOMAD_API_BASE` / `MATWAU_NOMAD_TOKEN` / `MATWAU_JARVIS_API_BASE` / `MATWAU_JARVIS_TOKEN`)
  - `tests/unit/test_cross_source_resolver.py` + `test_mat_critic_cross_source.py` + `test_mat_orchestrator_cross_source.py` + `test_mat_intent_agent_external_db.py` + `test_matwau_settings_cross_source.py` + `test_dag_outputs_x_resolution.py` — 66 unit tests
  - 累计测试:1479 → **1545**(+66)
- **M4 — 发版 + 教学 + 验收**:
  - `~/WAU-develop/develop-log/MatWAU/v1.3/MatWAU-v1.3-Academic-RELEASE-NOTES.md` (本节配套)
  - `docs/teaching_manual/teaching-manual-v1.3-extra.md` — W4 demo L1-L5 升级 + W4.5 新周(跨数据源验证)
  - `~/WAU-develop/develop-log/MatWAU/test/run-acceptance.sh` `--mode=v1.3-academic` — 4 库 + L5 + cross_source e2e 验收
  - `~/WAU-develop/develop-log/MatWAU/v1.3/acceptance/` — 3 件 M4 closure doc

### Changed(变更)

- **`mat_intent_agent.SUBCLASSES`**:5 → 7(新增 `external_db_query` + `cross_source_validation`)
- **`mat_critic_agent.CriticOutput`**:加 3 个 L5 字段(向后兼容,默认 0.0)
- **`mat_critic_agent.CriticVerdict`**:加 `cross_source` 字段(向后兼容,3 路入口默认 None)
- **`mat_orchestrator.MatOrchestrator.__init__`**:接受 4 个新可选 kwarg — `oqmd_agent` / `cod_agent` / `nomad_agent` / `jarvis_agent`(测试可注入 stub)
- **`mat_orchestrator.dag.DAGExecutor.execute()`**:新增 `outputs.X` src_key 解析路径(优先级最高,先于 node_id 解析)
- **`VERSION` 文件**:`v1.1.3-Academic` → **v1.3-Academic**
- **5-way critic 加权**:`L1(0.27) + L2(0.27) + L3(0.18) + L4(0.18) + L5(0.10)` — 旧 3-way 加权 `L1(0.30) + L2(0.30) + L3(0.20)` 仍保留向后兼容

### Deprecated(弃用)

- 无

### Removed(移除)

- 无(完全向后兼容 v1.1.3-Academic)

### Fixed(修复)

- 无(M1+M2+M3 均为新功能,0 bug 修复)

### Security(安全)

- API key / token 走 `~/.matwau/secrets.env` chmod 600(per `feedback-api-key-leak-2026-07-30.md`)
- NOMAD / JARVIS token 默认不读,公开数据无需
- `MATWAU_NOMAD_TOKEN` / `MATWAU_JARVIS_TOKEN` 仅在显式设置时启用

### Stats

- **3 commits**(per 学院版 commit history):`1656eed`(M1) + `a475f22`(M2) + `d674f83`(M3)+ 待补 `VERSION` bump commit
- **测试基线**:1297 → **1545 passed**(累计 +248,0 回归,2 skipped)
- **新文件 ~30**:4 client + 4 wrapper + canonical_key + cross_source_resolver + 9 test files + 2 goldens + 4 doc
- **修改文件 ~10**:mat_intent_agent / mat_critic_agent / mat_orchestrator / matwau_settings / VERSION / CHANGELOG / dag.py / __init__.py 等
- **总代码行 +5,791**(46,069 → 51,860)
- **本地 git tag**:`v1.3-Academic`(annotated,2026-08-04 待打)
- **学院方验收**:`bash ~/WAU-develop/develop-log/MatWAU/test/run-acceptance.sh --mode=v1.3-academic`(M4 新增 mode)

### 完整发版说明

- `~/WAU-develop/develop-log/MatWAU/v1.3/MatWAU-v1.3-Academic-RELEASE-NOTES.md` (~470 行,12 章)
- 需求分析:`~/WAU-develop/develop-log/MatWAU/v1.3/MatWAU-v1.3-Academic-requirements-20260804.md` (~494 行)
- 开发计划:`~/WAU-develop/develop-log/MatWAU/v1.3/MatWAU-v1.3-Academic-dev-plan-20260804.md` (~425 行)

### 已知非阻塞问题

- **KB-2026-08-04-01**:NOMAD 国内可达性差,学院 IT 需镜像或 VPN(中,网络)— v1.3.1 patch
- **KB-2026-08-04-02**:JARVIS 国内可达性差,默认 mock(低)— v1.3.1 patch
- **KB-2026-08-04-03**:L5 阈值(consensus_rate / energy / band_gap)硬编码(低)— v1.4 暴露 settings
- **KB-2026-08-04-04**:cross_source_records 4 库并行未启用 asyncio(低,~3-5s)— v1.4 异步化
- **KB-2026-08-04-05**:NOMAD metainfo 35 路径,缺失路径走默认空(中,数据完整度)— v1.3.1 扩到 60

---

## [v1.1.3-Academic] - 2026-07-29 — /wau/dispatch 适配 WorkflowResult 真实字段

### Fixed(修复)

- **HIGH: `agents/wau_protocol_adapter/wau_client.py`** — 适配 `WorkflowResult` 真实字段(无 `reply` / `cost` / `artifacts`)。修复前 `/wau/dispatch` 调用 `MatOrchestrator.run()` 后访问不存在的字段 → KeyError → 500。

### Stats

- **1 file / +13 / -7**
- **Commit**:`99cc8d3`
- **Patch notes**:`~/WAU-develop/develop-log/MatWAU/20260729/MatWAU-20260729-homerail-dispatch-closure.md`
- **Tag**:`v1.1.3-Academic`(annotated)

---

## [v1.1.2-Academic] - 2026-07-29 — /wau/dispatch 修复 MatOrchestrator.run() 调用错误

### Fixed(修复)

- **HIGH: `agents/wau_protocol_adapter/wau_client.py`** — 修复 `MatOrchestrator.run()` 调用错误(应传 keyword-only arg `user_intent=`)。修复前 `/wau/dispatch` 调用 → TypeError → 500。

### Stats

- **1 file / +5 / -2**
- **Commit**:`d047fa0`

---

## [Unreleased] — 7 个服务器部署 bug 修复(2026-07-28)→ 已并入 v1.1.3-Academic

> **本段已并入 v1.1.3-Academic**(2026-07-29 `/wau/dispatch` 修复发布后,这些服务器部署 bug fix 与 `/wau/dispatch` 适配合为同一发版线 v1.1.3-Academic)
> 完整 closure doc:[~/WAU-develop/develop-log/MatWAU/20260728/MatWAU-20260728-server-deployment-closure.md](~/WAU-develop/develop-log/MatWAU/20260728/MatWAU-20260728-server-deployment-closure.md)

### Fixed(修复 7 个真实 bug)

- **HIGH: `deploy/academic/VERSION`** — 创建 VERSION 文件,内容 `v1.1.1-Academic`。修复前 `/health` 永远 fallback 到 `v1.0-Academic`,跟 image tag 错位。
- **HIGH: `deploy/academic/docker-compose.yml`** — image tag `v1.1-Academic` → `v1.1.1-Academic`,跟 VERSION 对齐。
- **HIGH: `deploy/academic/docker-compose.yml`** — environment 加 `WAU_JWT_SHARED_SECRET` / `WAU_TENANT_ID` / `WAU_REGISTRY_URL` 3 个 env vars(W37.12 V1 接公网必须)。
- **CRITICAL: `deploy/academic/serve.py` + `agents/wau_protocol_adapter/wau_client.py` + `agents/wau_protocol_adapter/__init__.py`** — **拆分 `MATWAU_HOST` 为 `MATWAU_BIND_HOST` + `MATWAU_PUBLIC_HOST`**。`MATWAU_HOST` 语义冲突(serve.py 当 bind 地址 / wau_client 当 agent card url),学院 IT 填公网 IP → `OSError: Cannot assign requested address` → 容器 restart loop。修复后 `MATWAU_BIND_HOST` 默认 `0.0.0.0`(socket bind 用),`MATWAU_PUBLIC_HOST` 默认 `localhost`(agent card url 字段用,学院 IT 填公网 IP)。
- **MEDIUM: `deploy/academic/Dockerfile`** — 加清华 apt + pip 源(国内服务器 build 提速 5-10 倍,5-15 分钟 → 1-3 分钟)。
- **LOW: `deploy/academic/.env.example`** — 加 V1 3 env vars + MATWAU_BIND/PUBLIC 注释。

### Changed(变更)

- `agents/wau_protocol_adapter/wau_client.py` 默认 agent card url 从 `localhost` → `localhost`(向后兼容,行为不变)
- `deploy/academic/.env.example` 末尾追加 17 行注释段

### Deprecated(弃用)

- **`MATWAU_HOST` 已废用** — 不再读(向后兼容保留 .env.example 中的注释行,serve.py 默认 `0.0.0.0`)。学院 IT 升级时请改名 `MATWAU_PUBLIC_HOST`(填公网 IP)。

### Stats

- **6 files / +33 / -9**(本次会话累计)
- **7 commit**:`bd8dfab` / `36d988d` / `baca802` / `4359cc9` / `2eb4b5b` / `a011bff` / `7fe60a0`
- **完整报告**:`~/WAU-develop/develop-log/MatWAU/20260728/MatWAU-20260728-server-deployment-closure.md`
- **Memory**:`~/.claude/projects/.../memory/project-matwau-server-deployment-v1-2026-07-28.md`

### 已知非阻塞问题

- **`a011bff` commit 已废但保留在 git 历史**(避免 force push)— 7fe60a0 已彻底修复其 bug。下次 rebase 可 squash。
- **学院 IT 部署必须 `docker compose down + up -d`,不能用 `restart`**(restart 不读 .env)— 已在 doc 中标注。

---

## [v1.1.1-Academic] - 2026-07-26 — 学院版 patch (W1 demo import + SQLiteBackend expanduser)

### Fixed(修复)
- **HIGH: `agents/mat_intent_agent/__init__.py`** — 加 `from .mat_intent_agent import MatIntentAgent, create_default_agent`,让 W1 demo `from agents.mat_intent_agent import MatIntentAgent` 在学院方第 1 节课能 import。修复前 W1 demo 3 个测试全 ImportError(22 行 → 53 行)。
- **MEDIUM: `agents/lineage_store_backend/backends.py:205-230`** — `SQLiteBackend.__init__` 显式 db_path 分支加 `os.path.expanduser(db_path)`,让 `MATWAU_LINEAGE_SQLITE_PATH='~/...'` env var 场景下 SQLite 能真打开文件。

### Changed(变更)
- **零行为变化**:纯 bug fix,baseline 1297 passed / 2 skipped 不变。

### Stats
- **2 files / +18 / -2**
- **Commit**:`8c1e005`
- **Tag**:`v1.1.1-Academic`(annotated)
- **Patch notes**:[`PATCH_NOTES_v1.1.1-Academic.md`](./PATCH_NOTES_v1.1.1-Academic.md)
- **学院方验收脚本**:`~/WAU-develop/develop-log/MatWAU/test/run-acceptance.sh`(发现这 2 个 bug 的工具)

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