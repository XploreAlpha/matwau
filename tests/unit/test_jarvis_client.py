"""test_jarvis_client.py — JarvClient 测试

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2 第 10 项
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.jarvis_client import (  # noqa: E402
    ENV_JARVIS_API_BASE,
    ENV_JARVIS_TOKEN,
    JARVIS_API_URL_DEFAULT,
    JARVIS_TIMEOUT_SEC,
    JarvClient,
    JarvReference,
    is_jarvis_available,
    is_jarvis_tools_available,
    search_jarvis,
)


# ============================================================================
# Test 1: 模块级常量
# ============================================================================


class TestJarvModuleConstants:
    def test_default_api_url(self):
        assert JARVIS_API_URL_DEFAULT.startswith("https://jarvis.nist.gov")

    def test_timeout_positive(self):
        assert JARVIS_TIMEOUT_SEC > 0

    def test_env_var_names(self):
        assert ENV_JARVIS_API_BASE == "MATWAU_JARVIS_API_BASE"
        assert ENV_JARVIS_TOKEN == "MATWAU_JARVIS_TOKEN"


# ============================================================================
# Test 2: JarvReference dataclass
# ============================================================================


class TestJarvReference:
    def test_default_values(self):
        r = JarvReference(jid="x")
        assert r.formula == ""
        assert r.is_2d is False
        assert r.dimensionality == "3D"
        assert r.xc_functional == "PBE"

    def test_2d_marker(self):
        r = JarvReference(jid="x", is_2d=True, dimensionality="2D")
        assert r.is_2d is True
        assert r.dimensionality == "2D"

    def test_to_dict(self):
        r = JarvReference(
            jid="JVASP-1", formula="MoS2",
            spacegroup_symbol="P63/mmc", spacegroup_number=194,
            band_gap_eV=1.68,
            bulk_modulus_GPa=120.0,
            is_2d=True, dimensionality="2D",
            xc_functional="PBE",
        )
        d = r.to_dict()
        assert d["jid"] == "JVASP-1"
        assert d["is_2d"] is True
        assert d["dimensionality"] == "2D"
        assert d["band_gap_eV"] == 1.68
        assert d["spacegroup_number"] == 194


# ============================================================================
# Test 3: JarvClient search
# ============================================================================


class TestJarvClientSearch:
    def test_mock_known_compound(self):
        """MoS2 mock → is_2d=True"""
        client = JarvClient(use_cache=False)
        refs, _ = client.search("MoS2", max_results=5)
        assert len(refs) >= 1
        # MoS2 在 mock 字典里
        found_2d = any(r.is_2d and "Mo" in r.elements for r in refs)
        assert found_2d, f"MoS2 mock should have 2D entry, got: {refs}"

    def test_mock_3d_compound(self):
        """GaN mock → 3D"""
        client = JarvClient(use_cache=False)
        refs, _ = client.search("GaN", max_results=5)
        assert len(refs) >= 1
        # GaN mock 是 3D
        for r in refs:
            if r.formula == "GaN":
                assert r.is_2d is False
                assert r.dimensionality == "3D"

    def test_n_results_limit(self):
        client = JarvClient(use_cache=False)
        refs, _ = client.search("Si", max_results=2)
        assert len(refs) <= 2

    def test_empty_query_returns_empty(self):
        client = JarvClient()
        refs, is_real = client.search("")
        assert refs == []
        assert is_real is False


# ============================================================================
# Test 4: to_canonical
# ============================================================================


class TestJarvClientCanonical:
    def test_to_canonical_basic(self):
        client = JarvClient()
        ref = JarvReference(jid="x", formula="MoS2", spacegroup_symbol="P63/mmc")
        ck = client.to_canonical(ref)
        assert ck.reduced_formula == "MoS2"
        assert ck.pearson_symbol == "hP2"

    def test_to_canonical_invalid(self):
        client = JarvClient()
        ref = JarvReference(jid="x", formula="not a formula")
        ck = client.to_canonical(ref)
        assert ck.reduced_formula == ""


# ============================================================================
# Test 5: jarvis-tools 包探测
# ============================================================================


class TestJarvisToolsDetection:
    def test_is_jarvis_tools_available_returns_bool(self):
        """探测函数返回 bool"""
        result = is_jarvis_tools_available()
        assert isinstance(result, bool)


# ============================================================================
# Test 6: LRU cache
# ============================================================================


class TestJarvClientLRUCache:
    def test_cache_hit_on_repeat(self):
        client = JarvClient(use_cache=True)
        refs1, is_real1 = client.search("Si")
        refs2, is_real2 = client.search("Si")
        if is_real1:
            assert is_real2 is True
            assert refs2 is refs1

    def test_cache_disabled(self):
        client = JarvClient(use_cache=False)
        refs, _ = client.search("Si")
        assert isinstance(refs, list)


# ============================================================================
# Test 7: 环境变量覆盖
# ============================================================================


class TestJarvEnvOverride:
    def test_api_base_override(self, monkeypatch):
        monkeypatch.setenv(ENV_JARVIS_API_BASE, "https://custom.jarvis.example/api")
        from agents.jarvis_client.client import _jarvis_api_base
        assert _jarvis_api_base() == "https://custom.jarvis.example/api"

    def test_token_override(self, monkeypatch):
        monkeypatch.setenv(ENV_JARVIS_TOKEN, "test-jarvis-token")
        from agents.jarvis_client.client import _jarvis_auth_headers
        h = _jarvis_auth_headers()
        assert h.get("Authorization") == "Bearer test-jarvis-token"


# ============================================================================
# Test 8: 模块级便捷函数
# ============================================================================


class TestJarvSearchFunction:
    def test_search_returns_tuple(self):
        refs, is_real = search_jarvis("MoS2")
        assert isinstance(refs, list)
        assert isinstance(is_real, bool)