"""lineage_engine.py — mat-data-lineage 的数据血缘引擎

职责:
1. 给每次 agent run 记 1 条 LineageRecord(lineage_id + parent + data hash + 时间戳)
2. in-memory 存储 + 索引(run_id → [lineage_id])
3. 递归查询:ancestors(上游)/ descendants(下游)
4. 导出 JSON(给 wau-store 持久化或人工查看)

Stage 1 / Phase 1:纯 in-memory dict
Stage 2(WAU v1.0.0 GA 后):接 wau-store SDK(wau-lineage 仓 Go 服务)

per MatWAU-开发计划 §七 W14
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class LineageRecord:
    """1 条血缘记录"""

    lineage_id: str                       # UUID
    run_id: str                           # 业务 run_id(per mat agent)
    parent_run_id: str | None = None   # 上游 run_id(per DAG)
    agent_name: str = ""                  # 哪个 agent 跑的
    input_hash: str = ""                  # 输入数据 hash
    output_hash: str = ""                 # 输出数据 hash
    input_artifacts_summary: dict[str, Any] = field(default_factory=dict)  # 简化(只存 key + size)
    output_artifacts_summary: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""                   # ISO 8601
    duration_seconds: float = 0.0
    cost: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lineage_id": self.lineage_id,
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "agent_name": self.agent_name,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "input_artifacts_summary": self.input_artifacts_summary,
            "output_artifacts_summary": self.output_artifacts_summary,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
            "cost": self.cost,
            "metadata": self.metadata,
        }


# ============================================================================
# 哈希计算
# ============================================================================


def hash_data(data: Any) -> str:
    """算数据 hash(per JSON 序列化 + SHA256)

    简化:支持 dict / list / str / int / float
    """
    try:
        s = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        s = str(data)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]    # 16 字符(64 bit)


def summarize_artifacts(artifacts: dict[str, Any]) -> dict[str, Any]:
    """artifacts 摘要(只存 key + size,避免大对象)

    Args:
        artifacts: agent 输出 dict

    Returns:
        摘要 dict{key: {"type": "list"/"dict"/"str"/..., "size": int, "hash": str}}
    """
    summary = {}
    for k, v in artifacts.items():
        if isinstance(v, list):
            summary[k] = {"type": "list", "size": len(v), "hash": hash_data(v)}
        elif isinstance(v, dict):
            summary[k] = {"type": "dict", "size": len(v), "hash": hash_data(v)}
        elif isinstance(v, str):
            summary[k] = {"type": "str", "size": len(v), "hash": hash_data(v)}
        elif isinstance(v, (int, float)):
            summary[k] = {"type": "number", "value": v, "hash": hash_data(v)}
        else:
            summary[k] = {"type": type(v).__name__, "size": 0, "hash": hash_data(str(v))}
    return summary


# ============================================================================
# LineageStore(in-memory)
# ============================================================================


class LineageStore:
    """Lineage 存储(W16)

    Stage 1 默认 in-memory dict(W14 行为)
    Stage 2(W16):接受 backend 参数,可切 SQLite 真持久化
    注:LineageStore 仍维护自己的 in-memory cache(by_run / by_parent / ancestors),
       backend 是为了"持久化兜底"(关 Python 重开数据还在)
    """

    def __init__(self, backend: Any | None = None) -> None:
        """构造

        Args:
            backend: W16 LineageBackend 实例(None → W14 纯 in-memory 行为)
        """
        self.backend = backend  # W16: 可选 backend
        self.records: dict[str, LineageRecord] = {}
        self.by_run: dict[str, list[str]] = {}
        self.by_parent: dict[str, list[str]] = {}

        # W16: 如果 backend 已有数据(从磁盘恢复),加载到内存 cache
        if self.backend is not None:
            self._load_from_backend()

    def _load_from_backend(self) -> None:
        """W16: 从 backend 加载已有 records(用于 SQLite 重启场景)"""
        try:
            existing = self.backend.list()
        except Exception:
            return
        for rec_dto in existing:
            # DTO → LineageRecord(直接构造,跟 dataclass 同形)
            rec = LineageRecord(
                lineage_id=rec_dto.lineage_id,
                run_id=rec_dto.run_id,
                parent_run_id=rec_dto.parent_run_id,
                agent_name=rec_dto.agent_name,
                input_hash=rec_dto.input_hash,
                output_hash=rec_dto.output_hash,
                input_artifacts_summary=rec_dto.input_artifacts_summary,
                output_artifacts_summary=rec_dto.output_artifacts_summary,
                timestamp=rec_dto.timestamp,
                duration_seconds=rec_dto.duration_seconds,
                cost=rec_dto.cost,
                metadata=rec_dto.metadata,
            )
            self.records[rec.lineage_id] = rec
            self.by_run.setdefault(rec.run_id, []).append(rec.lineage_id)
            if rec.parent_run_id:
                self.by_parent.setdefault(rec.parent_run_id, []).append(rec.lineage_id)

    def add(
        self,
        run_id: str,
        agent_name: str,
        input_artifacts: dict[str, Any] | None = None,
        output_artifacts: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
        duration_seconds: float = 0.0,
        cost: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> LineageRecord:
        """加 1 条 record

        Args:
            run_id: 业务 run_id
            agent_name: agent 名
            input_artifacts: 输入数据(算 hash + summary)
            output_artifacts: 输出数据(算 hash + summary)
            parent_run_id: 上游 run_id
            duration_seconds: 耗时
            cost: 成本
            metadata: 自由字段

        Returns:
            LineageRecord
        """
        input_artifacts = input_artifacts or {}
        output_artifacts = output_artifacts or {}

        record = LineageRecord(
            lineage_id=str(uuid.uuid4()),
            run_id=run_id,
            parent_run_id=parent_run_id,
            agent_name=agent_name,
            input_hash=hash_data(input_artifacts),
            output_hash=hash_data(output_artifacts),
            input_artifacts_summary=summarize_artifacts(input_artifacts),
            output_artifacts_summary=summarize_artifacts(output_artifacts),
            timestamp=datetime.now().isoformat(),
            duration_seconds=duration_seconds,
            cost=cost,
            metadata=metadata or {},
        )

        self.records[record.lineage_id] = record
        self.by_run.setdefault(run_id, []).append(record.lineage_id)
        if parent_run_id:
            self.by_parent.setdefault(parent_run_id, []).append(record.lineage_id)

        # W16: 写 backend(SQLite 等真持久化)
        if self.backend is not None:
            try:
                from agents.lineage_store_backend import LineageRecordDTO
                dto = LineageRecordDTO(
                    lineage_id=record.lineage_id,
                    run_id=record.run_id,
                    parent_run_id=record.parent_run_id,
                    agent_name=record.agent_name,
                    input_hash=record.input_hash,
                    output_hash=record.output_hash,
                    timestamp=record.timestamp,
                    duration_seconds=record.duration_seconds,
                    cost=record.cost,
                    metadata=record.metadata,
                    input_artifacts_summary=record.input_artifacts_summary,
                    output_artifacts_summary=record.output_artifacts_summary,
                )
                self.backend.add(dto)
            except Exception:
                pass  # backend 写失败不阻断

        return record

    def get(self, lineage_id: str) -> LineageRecord | None:
        """按 lineage_id 查"""
        return self.records.get(lineage_id)

    def get_by_run(self, run_id: str) -> list[LineageRecord]:
        """按 run_id 查所有 record"""
        ids = self.by_run.get(run_id, [])
        return [self.records[i] for i in ids if i in self.records]

    def ancestors(self, run_id: str) -> list[LineageRecord]:
        """查 run_id 的所有上游(递归,不含 run_id 自身)"""
        result: list[LineageRecord] = []
        visited_run = set()

        def _walk(rid: str) -> None:
            for r in self.get_by_run(rid):
                if r.parent_run_id is None:
                    continue
                if r.parent_run_id in visited_run:
                    continue
                visited_run.add(r.parent_run_id)
                # 找 parent record(可能多条)
                parents = self.get_by_run(r.parent_run_id)
                for p in parents:
                    result.append(p)
                # 递归往上
                _walk(r.parent_run_id)

        _walk(run_id)
        return result

    def descendants(self, run_id: str) -> list[LineageRecord]:
        """查 run_id 的所有下游(递归,不含 run_id 自身)"""
        result: list[LineageRecord] = []
        visited = set()

        def _walk(rid: str) -> None:
            child_ids = self.by_parent.get(rid, [])
            for cid in child_ids:
                if cid in visited:
                    continue
                visited.add(cid)
                record = self.records.get(cid)
                if record:
                    result.append(record)
                    _walk(record.run_id)

        _walk(run_id)
        return result

    def to_json(self) -> str:
        """导出 JSON(给 wau-store 持久化 / 人工查看)"""
        return json.dumps(
            [r.to_dict() for r in self.records.values()],
            ensure_ascii=False,
            indent=2,
        )

    def to_list(self) -> list[dict[str, Any]]:
        """导出 list of dict"""
        return [r.to_dict() for r in self.records.values()]

    def size(self) -> int:
        return len(self.records)

    def clear(self) -> None:
        self.records.clear()
        self.by_run.clear()
        self.by_parent.clear()


# ============================================================================
# 全局 store(Stage 1 单例)
# ============================================================================


_global_store: LineageStore | None = None


def get_global_store() -> LineageStore:
    """获取全局 LineageStore(Stage 1 单例)"""
    global _global_store
    if _global_store is None:
        _global_store = LineageStore()
    return _global_store


def reset_global_store() -> None:
    """重置全局 store(测试用)"""
    global _global_store
    _global_store = None


# ============================================================================
# LineageTree(可视化辅助)
# ============================================================================


@dataclass
class LineageTree:
    """1 棵血缘树(以 1 个 run_id 为根)"""

    root_run_id: str
    root: LineageRecord | None
    ancestors_tree: dict[str, list[LineageRecord]]     # run_id → parents
    descendants_tree: dict[str, list[LineageRecord]]  # run_id → children
    depth: int                                         # 树深度(0 = 只有 root)
    total_nodes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_run_id": self.root_run_id,
            "root": self.root.to_dict() if self.root else None,
            "ancestors_tree": {k: [r.to_dict() for r in v] for k, v in self.ancestors_tree.items()},
            "descendants_tree": {k: [r.to_dict() for r in v] for k, v in self.descendants_tree.items()},
            "depth": self.depth,
            "total_nodes": self.total_nodes,
        }


def build_lineage_tree(
    store: LineageStore,
    root_run_id: str,
) -> LineageTree:
    """以 root_run_id 为根建 1 棵血缘树"""
    # 找根
    root_records = store.get_by_run(root_run_id)
    root = root_records[0] if root_records else None

    # 递归收集
    ancestors_tree: dict[str, list[LineageRecord]] = {}
    descendants_tree: dict[str, list[LineageRecord]] = {}

    def _walk_up(rid: str, depth: int) -> int:
        """返回 max depth"""
        max_d = depth
        for r in store.get_by_run(rid):
            ancestors_tree.setdefault(rid, []).append(r)
            if r.parent_run_id:
                max_d = max(max_d, _walk_up(r.parent_run_id, depth + 1))
        return max_d

    def _walk_down(rid: str, depth: int) -> int:
        max_d = depth
        for r in store.get_by_run(rid):
            # 找 children(以 r.run_id 为 parent_run_id 的 record)
            children = [c for c in store.get_by_run(r.run_id) if c.parent_run_id == r.run_id]
            if children:
                descendants_tree.setdefault(rid, []).extend(children)
                for c in children:
                    max_d = max(max_d, _walk_down(c.run_id, depth + 1))
        return max_d

    ancestors_depth = _walk_up(root_run_id, 0) if root_records else 0
    descendants_depth = _walk_down(root_run_id, 0) if root_records else 0

    depth = max(ancestors_depth, descendants_depth)
    total_nodes = len(store.records)

    return LineageTree(
        root_run_id=root_run_id,
        root=root,
        ancestors_tree=ancestors_tree,
        descendants_tree=descendants_tree,
        depth=depth,
        total_nodes=total_nodes,
    )


__all__ = [
    "LineageRecord",
    "LineageStore",
    "LineageTree",
    "build_lineage_tree",
    "get_global_store",
    "hash_data",
    "reset_global_store",
    "summarize_artifacts",
]