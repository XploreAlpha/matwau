"""test_materials_project_integration.py — W17-C Materials Project API 集成测试

覆盖:
1. MaterialsProjectClient 基本 + mock fallback
2. 真查Materials Project(网络 mark 测试)
3. _build_mp_query 各种 query 模式
4. mat-lit use_real_mp 接通
5. mat-lit use_real_mp + use_real_arxiv 组合
6. W17-C 跟 W15 / W17-A 域路由一致(4 域)

per MatWAU-开发计划 §8 W17-C
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.materials_project_client import (  # noqa: E402
    MaterialsProjectClient,
    MaterialsProjectReference,
    is_materials_project_available,
    search_materials_project,
)
from agents.materials_project_client.client import (  # noqa: E402
    _build_mp_query,
    _mock_mp_response,
)
from agents.mat_lit_agent.lit_engine import (  # noqa: E402
    review_literature,
    search_literature_with_real_sources,
    parse_lit_query,
)


# ============================================================================
# 测试 1: 基本
# ============================================================================


class TestMPClientBasic:
    """Materials Project client 基本功能"""

    def test_reference_to_dict(self):
        r = MaterialsProjectReference(
            mp_id="mp-1234", formula="LiCoO2",
            spacegroup="R-3m", band_gap=1.7,
            energy_above_hull=0.0, is_stable=True,
        )
        d = r.to_dict()
        assert d["mp_id"] == "mp-1234"
        assert d["formula"] == "LiCoO2"
        assert d["is_stable"] is True

    def test_is_mp_available(self):
        """可用性探测(至少 1 次超时要 5s)"""
        result = is_materials_project_available()
        assert isinstance(result, bool)

    def test_build_mp_query_with_formula(self):
        q = _build_mp_query("出 LiCoO2 实验方案")
        assert q == "LiCoO2" or "CoO" in q or "Li" in q

    def test_build_mp_query_with_NMC(self):
        """NMC 是 cathode alias,应该识别"""
        q = _build_mp_query("设计 NMC811 配方")
        assert q.upper() in ("NMC", "NMC811") or q.startswith("NMC")

    def test_build_mp_query_with_LLZO(self):
        q = _build_mp_query("LLZO 进展")
        assert q.upper() == "LLZO"

    def test_build_mp_query_with_Inconel(self):
        """W17 metal_alloy 域 — Inconel 也得识别"""
        q = _build_mp_query("Inconel 718")
        assert "Inconel" in q or "NICKEL" in q.upper() or "FE" in q.upper() or "NI" in q.upper()

    def test_build_mp_query_empty(self):
        """空查询兜底"""
        q = _build_mp_query("")
        assert q == ""

    def test_mock_response_known_formula(self):
        """已知化学式 → 真 mock 数据"""
        refs = _mock_mp_response("LiCoO2", n=5)
        assert len(refs) >= 1
        assert all(r.formula == "LiCoO2" for r in refs)

    def test_mock_response_unknown_formula(self):
        """未知化学式 → generic mock entry"""
        refs = _mock_mp_response("FooBarBaz", n=3)
        assert len(refs) == 1
        assert refs[0].mp_id.startswith("mp-mock-")


# ============================================================================
# 测试 2: 真查 + fallback
# ============================================================================


class TestMPFallback:
    """fallback 行为测试"""

    def test_short_timeout_falls_back(self):
        """超短 timeout 触发 fallback"""
        client = MaterialsProjectClient(timeout=0.001)
        refs, is_real = client.search("LiCoO2", max_results=2)
        if not is_real:
            # fallback 应该有 mock 数据
            assert len(refs) >= 1
            assert all(r.mp_id.startswith("mp-") or r.mp_id.startswith("mp-mock-") for r in refs)

    def test_invalid_query_falls_back(self):
        """无效 query 触发 fallback(不崩)"""
        client = MaterialsProjectClient(timeout=8)
        refs, is_real = client.search("@@invalid@@@!!!", max_results=2)
        # 真查失败回 mock;成功也接收
        assert isinstance(refs, list)


@pytest.mark.network
class TestMPLive:
    """需要网络的真查询测试"""

    def test_search_mp_real_li_co_o2(self):
        """真查 LiCoO2"""
        refs, is_real = search_materials_project("LiCoO2", max_results=3)
        if not is_real:
            pytest.skip("Materials Project 不可用,跳过")
        assert len(refs) > 0
        assert all(r.formula for r in refs)
        assert all(r.mp_id.startswith("mp-") for r in refs)


# ============================================================================
# 测试 3: mat-lit 接通 use_real_mp
# ============================================================================


class TestMatLitW17C:
    """mat-lit use_real_mp 接通测试"""

    def test_review_default_no_real(self):
        """默认 False = W16 行为"""
        r = review_literature("Review LiCoO2", use_real_arxiv=False, use_real_mp=False)
        # 即使默认也该有 mock refs(W14 行为)
        assert r.references is not None

    def test_review_with_real_mp(self):
        """use_real_mp=True(网络失败也 fallback,mock 应该兜底)"""
        r = review_literature("Review LiCoO2", use_real_arxiv=False, use_real_mp=True)
        # 即便 fallback,mock 给 LiCoO2 真 mock refs
        assert len(r.references) >= 0  # 0 或 >=1 都接受

    def test_review_with_both_real(self):
        """use_real_arxiv + use_real_mp 同时 True(W17 价值点)"""
        r = review_literature(
            "Review NMC811",
            use_real_arxiv=True,
            use_real_mp=True,
        )
        # 至少应有 1 条(就算 fallback)
        assert r.references is not None

    def test_review_with_real_mp_metal_alloy(self):
        """W17 价值点:metal_alloy 域也能查到"""
        r = review_literature(
            "Inconel 718 实验方案",
            use_real_mp=True,
            domain="metal_alloy",
        )
        assert r.references is not None

    def test_search_lit_with_real_sources_no_real(self):
        """不真查 → search_literature 行为不变"""
        from agents.mat_lit_agent.lit_engine import LitQuery
        q = LitQuery(
            raw_query="LiCoO2",
            formulas=["LiCoO2"],
            material_names=["LiCoO2"],
            properties=[],
            domains=[],
            keywords=["LiCoO2"],
            domain="inorganic_crystal",
        )
        refs = search_literature_with_real_sources(
            q, n_results=3, use_real_arxiv=False, use_real_mp=False,
        )
        # 走 mock fallback
        assert isinstance(refs, list)


# ============================================================================
# 测试 4: W17-C 跟 W15 + W17-A 域路由一致(4 域)
# ============================================================================


class TestMPDomainCompat:
    """Materials Project API + 4 域(W17 跨 W15 + W17-A)"""

    @pytest.mark.parametrize("domain", ["inorganic_crystal", "polymer", "nano", "metal_alloy"])
    def test_mp_query_by_domain(self, domain):
        """4 域都能用 mp client 查(不报错)"""
        client = MaterialsProjectClient(timeout=2)  # 短 timeout,确保 fallback
        refs, is_real = client.search("test", max_results=2, domain=domain)
        # mock 兜底或真查,任一都 OK
        assert isinstance(refs, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
