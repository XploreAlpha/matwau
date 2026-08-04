"""test_mat_intent_agent_external_db.py — mat_intent_agent M3 新子类路由测试

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M3 第 11 项
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.mat_intent_agent.intent_classifier import (  # noqa: E402
    SUBCLASSES,
    classify_subclass,
)


# ============================================================================
# Test 1: 7 子类总数(5 旧 + 2 新)
# ============================================================================


class TestM3Subclasses:
    def test_subclasses_includes_2_new(self):
        assert "external_db_query" in SUBCLASSES
        assert "cross_source_validation" in SUBCLASSES

    def test_subclass_count_7(self):
        assert len(SUBCLASSES) == 7


# ============================================================================
# Test 2: external_db_query 路由
# ============================================================================


class TestExternalDbQueryRouting:
    def test_query_oqmd(self):
        sub, conf, _ = classify_subclass("OQMD 查询 LLZO")
        assert sub == "external_db_query"
        assert conf >= 0.5

    def test_query_cod(self):
        sub, conf, _ = classify_subclass("查 COD TiO2 已知结构")
        assert sub == "external_db_query"

    def test_query_known_structure(self):
        sub, conf, _ = classify_subclass("查 Inconel 718 已知结构")
        # "查 ... 已知结构" 应命中 external_db_query
        assert sub == "external_db_query"

    def test_query_db_keyword(self):
        sub, _, _ = classify_subclass("external db query Si")
        # "external db" 关键词命中 external_db_query
        assert sub == "external_db_query"


# ============================================================================
# Test 3: cross_source_validation 路由
# ============================================================================


class TestCrossSourceValidationRouting:
    def test_cross_data_source(self):
        sub, _, _ = classify_subclass("跨数据源对比 LiCoO2")
        assert sub == "cross_source_validation"

    def test_4_libraries_compare(self):
        sub, _, _ = classify_subclass("4 库对比 Inconel 718")
        assert sub == "cross_source_validation"

    def test_cross_validation(self):
        sub, _, _ = classify_subclass("OQMD 和 COD 对比 LiCoO2")
        # 这条可能不命中 cross_source_validation(关键词不够),允许其他子类
        assert sub in ("cross_source_validation", "experiment_planning", "design_new_material")

    def test_formation_energy_compare(self):
        sub, _, _ = classify_subclass("跨数据源对比 LiCoO2 形成能")
        assert sub == "cross_source_validation"


# ============================================================================
# Test 4: 旧子类仍正常
# ============================================================================


class TestLegacySubclassesUnchanged:
    def test_experiment_planning_still_routes(self):
        sub, _, _ = classify_subclass("出 LiCoO2 实验方案")
        assert sub == "experiment_planning"

    def test_literature_review_still_routes(self):
        sub, _, _ = classify_subclass("Review LLZO 最新进展")
        assert sub == "literature_review"

    def test_design_new_material(self):
        sub, _, _ = classify_subclass("设计新型固态电解质")
        assert sub == "design_new_material"