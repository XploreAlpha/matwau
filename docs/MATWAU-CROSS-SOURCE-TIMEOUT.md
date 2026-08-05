# MatWAU cross_source_validation Timeout 配置

> **版本**:v1.3-Academic patch (2026-08-05)
> **给谁看**:homerail CLI / DAG orchestrator 维护方 + 学院 IT
> **适用范围**:`cross_source_lookup` + `cross_source_property` workflow

---

## 1. 当前默认耗时(实测,学院服务器)

| 阶段 | 耗时 | 备注 |
|---|---|---|
| 4 client 并行(OQMD/COD/NOMAD/JARVIS) | ≤ 10s | per-client hard timeout 10s |
| mat-critic L5 cross_source 复核 | 1-3s | 计算一致率 + LLM 复核(可关) |
| **总耗时** | **8-12s** | 95% case |

**对比修前**:50.9s(60-120s timeout),12 条 record 仍全在;**现在**:8-12s。

---

## 2. 客户端 timeout 建议

| 部署位置 | 建议 timeout | 理由 |
|---|---|---|
| **homerail CLI**(用户发请求) | **≥ 60s** | 4 client + critic + 序列化 + 安全裕度 |
| **DAG orchestrator node** | **≥ 60s** | 同上 + retry + lineage store 写入 |
| **wau-edge reverse proxy** | **≥ 30s** | 仅做 pass-through,不重计算 |
| **学院 IT 防火墙白名单** | **≤ 60s** | 4 平台 client timeout 各自 10-12s,内层先断 |

⚠️ **不要低于 30s**:学院版 firewall/IT 路由可能让首次 connect 多耗 5-10s。

---

## 3. 超时 fallback 行为(2026-08-05 bug #3 fix)

**新行为**(per `mat_orchestrator.py:_run_cross_source_parallel`):

- 单 client 超时 → **不返 error,返 empty fallback record**
  - `cross_source_records[platform] = []`(空 list)
  - 该 node 标 `success=True, error="timeout (fallback)"`
  - critic L5 仍能算 consensus(只是缺这一源)
- 4 client 全超时 → consensus_rate = 0,verdict = warn,failures 含 `cross_source_no_data`

**对比修前**:单 client 超时 → 整个 workflow fail + 所有 caller 看到 500。

---

## 4. 单 client timeout 实测

| 平台 | 修前 timeout | 修后 timeout | 内层 timeout |
|---|---|---|---|
| OQMD | 20s(orchestrator)+ 10s(client) | **10s**(orchestrator)+ 10s(client) | `OQMD_TIMEOUT_SEC=10` |
| COD | 20s + 10s | **10s** + 10s | `COD_TIMEOUT_SEC=10` |
| NOMAD | 20s + 12s | **10s** + 12s | `NOMAD_TIMEOUT_SEC=12` |
| JARVIS | 20s + 10s | **10s** + 10s | `JARVIS_TIMEOUT_SEC=10` |

每 client 真正的硬上限 = `min(orchestrator timeout, client timeout)` = 10s。

---

## 5. 升级 homerail timeout 配套

homerail 团队需配合升级:

```yaml
# wau-edge config 或 homerail CLI 默认
timeout:
  client_request_ms: 120000     # 60s → 120s(学院版 4 库并行 + LLM 复核)
  dag_node_ms: 180000          # 90s → 180s
  reverse_proxy_ms: 60000      # 30s → 60s
```

不升级 → 12s 内的请求 100% 通,但 LLM 复核等额外耗时会被截断。

---

## 6. 长期优化(中期 / 长期,本 patch 未做)

| 项 | 优先级 | 工作量 | 备注 |
|---|---|---|---|
| asyncio.gather 替代 ThreadPoolExecutor | P2 | 1 周 | 解决 GIL 锁竞争,真并行 |
| streaming 化(边收边算) | P3 | 2 周 | 第一个 client 完成即开始 critic |
| LRU cache(per formula) | P3 | 1 周 | 二次查询 < 100ms |
| 学院 IT 加 OQMD/COD/JARVIS 防火墙白名单 | P1 | 1-2 周 | NOMAD 已通,其余 3 库真连 |

详见 `feedback-matwau-cross-source-long-term.md`(未来单独 doc)。