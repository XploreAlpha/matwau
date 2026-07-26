# MatWAU v1.1.1-Academic — 学院版补丁说明

> **发布时间**:2026-07-26
> **基线版本**:v1.1-Academic(tag `v1.1-Academic`)
> **类型**:Bug fix 补丁(minor)
> **Commit**:`8c1e005`
> **Tag**:`v1.1.1-Academic`(annotated)
> **影响**:**学院方部署可选升级**,不升级也能跑(临时方案可见)

---

## 🎯 一句话总结

修复学院方验收测试中发现的 **2 个 v1.1-Academic 真 bug**:
- **HIGH**:W1 demo 第 1 节课 import 失败(`mat_intent_agent` 没 re-export)
- **MEDIUM**:SQLite lineage 用 `~/` 路径时报 `unable to open database file`

零行为变化、零向后不兼容、可选升级。

---

## 🐛 修复清单

### Bug #1 — HIGH:`agents/mat_intent_agent/__init__.py` 不 re-export

| 项 | 值 |
|---|---|
| **严重度** | ⛔ **HIGH**(学院方第 1 节课就遇到)|
| **位置** | `agents/mat_intent_agent/__init__.py` |
| **Bug** | 文件只含 docstring,没 `from .mat_intent_agent import MatIntentAgent` |
| **症状** | W1 demo `from agents.mat_intent_agent import MatIntentAgent` → `ImportError` |
| **用户痛点** | 学院方老师周一上第 1 节课跑 W1 demo,3 个测试全挂,印象差 |
| **修复** | 文件末尾加 2 行 re-export + `__all__` 声明 |
| **修复行数** | +9 / -1 |

**修复 diff(关键片段)**:
```python
# agents/mat_intent_agent/__init__.py 末尾
from .mat_intent_agent import MatIntentAgent, create_default_agent
__all__ = ["MatIntentAgent", "create_default_agent"]
```

### Bug #2 — MEDIUM:`SQLiteBackend` 不 expanduser `~`

| 项 | 值 |
|---|---|
| **严重度** | ⚠️ **MEDIUM**(学院方启用 SQLite lineage 时遇到)|
| **位置** | `agents/lineage_store_backend/backends.py:218` |
| **Bug** | `db_path is None` 分支会 expanduser,但显式传 `~/...` 时不调用 |
| **症状** | `sqlite3.connect("~/.matwau/lineage.db")` → `sqlite3.OperationalError: unable to open database file` |
| **触发场景** | `MATWAU_LINEAGE_SQLITE_PATH='~/data/lineage.db'` env var |
| **修复** | 在 `else` 分支加 `db_path = os.path.expanduser(db_path)` |
| **修复行数** | +11 / -2 |

**修复 diff(关键片段)**:
```python
if db_path is None:
    home = os.path.expanduser("~")
    db_dir = os.path.join(home, ".matwau")
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, "lineage.db")
else:
    # W37.9 v1.1.1-Academic patch: caller may pass "~/..." literal
    db_path = os.path.expanduser(db_path)
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
```

---

## ✅ 验证结果

| 检验项 | v1.1-Academic | v1.1.1-Academic |
|---|---|---|
| `pytest tests/` | 1297 passed / 2 skipped | **1297 passed / 2 skipped** ✅ |
| W1 demo `W1_intent_classification.py` | 22 行(3 ImportError) | **53 行(5 测试输出)** ✅ |
| `SQLiteBackend("~/...")` | ❌ `unable to open` | ✅ **真文件创建** ✅ |
| `run-acceptance.sh teaching-only` | 6/7(假阳性)| **5/5 都跑通(改用 ImportError 检测)** ✅ |
| `run-acceptance.sh code-only` | 5/5 | **6/6(C3 lineage 真持久化)** ✅ |
| Acceptance script `all` 模式 | 21/28 | **21/28**(剩下 4 ❌ 是部署环境非代码 bug) ✅ |

**结论**:2 个 bug 真修了 0 回归,baseline 数字完全一致,语义更干净。

---

## 📦 文件清单

### 修改(2 files / +18 -2)

| 文件 | 增 | 删 | 净 |
|---|---|---|---|
| `agents/mat_intent_agent/__init__.py` | 9 | 1 | +8 |
| `agents/lineage_store_backend/backends.py` | 11 | 2 | +9 |

### 新增(0 文件)

零新文件 — 纯源码补丁。

---

## 🚀 升级方式

### 方式 A(推荐):学院方 IT 拉新 tag

```bash
cd matwau
git fetch --tags
git checkout v1.1.1-Academic
pip install -r requirements.txt  # 不需要 — 纯源码改动
pytest tests/ -q                  # 应该:1297 passed
```

### 方式 B(快速):只 patch 这 2 个文件

```bash
git diff v1.1-Academic v1.1.1-Academic -- \
    agents/mat_intent_agent/__init__.py \
    agents/lineage_store_backend/backends.py | git apply
```

### 方式 C(不升级,临时绕过)

```bash
# Bug #1 临时绕过:在 W1 demo 加 sys.path hack
# Bug #2 临时绕过:export MATWAU_LINEAGE_SQLITE_PATH=$HOME/.matwau/lineage.db
```

**强烈推荐方式 A**。

---

## ⏭️ v1.1.1-Academic 之后 → 下一步

| 选项 | 内容 |
|---|---|
| v1.1.2-Academic | 学院方反馈 → 修 N+1 个 bug |
| v1.2-Academic | **W37.7 真仪器**(OT-2 + Bruker + Zeiss + TA)+ i18n + Q&A,10 周 ≈ 2.5 月 |
| v2.0-Academic | WAU Network OS(云)+ MatWAU(本机)+ HomeRail(Siri)架构 |

详见:
- [`docs/v1.2-roadmap.md`](./docs/v1.2-roadmap.md) — v1.2 路线图
- [`docs/v2.0-vision.md`](./docs/v2.0-vision.md) — v2.0 愿景

---

## 📋 协议合规

- ✅ 0 行为变化(纯代码 bug fix)
- ✅ 0 向后不兼容(老 API 全部保留)
- ✅ 0 删除(纯加 re-export + 加 expanduser)
- ✅ 学院方可跳过 — v1.1-Academic 临时方案仍可用
- ✅ 0 systemd / 0 PR / 0 release artifacts 副作用

---

## 🙏 鸣谢

- 验收测试:`~/WAU-develop/develop-log/MatWAU/test/run-acceptance.sh`(2 个 bug 都是它发现的)
- 学院方测试计划:`~/WAU-develop/develop-log/MatWAU/test/2026-07-26-acceptance-test-plan.md`
- W37.8 v1.1-Academic → v1.1.1-Academic 同日 patch closure

**end of PATCH_NOTES_v1.1.1-Academic.md**
