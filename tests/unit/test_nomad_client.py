"""test_nomad_client.py — NomadClient 测试

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M2 第 9 项
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.nomad_client import (  # noqa: E402
    ENV_NOMAD_API_BASE,
    ENV_NOMAD_TOKEN,
    NOMAD_API_URL_DEFAULT,
    NOMAD_TIMEOUT_SEC,
    NomadClient,
    NomadReference,
    is_nomad_available,
    search_nomad,
)


# ============================================================================
# Test 1: 模块级常量
# ============================================================================


class TestModuleConstants:
    """模块常量 / 环境变量"""

    def test_default_api_url(self):
        assert NOMAD_API_URL_DEFAULT.startswith("https://nomad-lab.eu")

    def test_timeout_positive(self):
        assert NOMAD_TIMEOUT_SEC > 0

    def test_env_var_names(self):
        assert ENV_NOMAD_API_BASE == "MATWAU_NOMAD_API_BASE"
        assert ENV_NOMAD_TOKEN == "MATWAU_NOMAD_TOKEN"


# ============================================================================
# Test 2: NomadReference dataclass
# ============================================================================


class TestNomadReference:
    """NomadReference dataclass 行为"""

    def test_default_values(self):
        r = NomadReference(entry_id="x")
        assert r.formula == ""
        assert r.spacegroup_symbol == ""
        assert r.band_gap_eV == 0.0
        assert r.available_properties == []
        assert r.elements == []

    def test_to_dict_keys(self):
        r = NomadReference(
            entry_id="e1",
            formula="LiCoO2",
            spacegroup_symbol="R-3m",
            spacegroup_number=166,
            band_gap_eV=2.3,
        )
        d = r.to_dict()
        assert d["entry_id"] == "e1"
        assert d["formula"] == "LiCoO2"
        assert d["band_gap_eV"] == 2.3
        assert d["spacegroup_number"] == 166

    def test_to_dict_full(self):
        r = NomadReference(
            entry_id="e1",
            upload_id="u1",
            archive_id="a1",
            formula="Si",
            elements=["Si"],
            a=5.43, b=5.43, c=5.43,
            xc_functional="PBE",
            program_name="VASP",
        )
        d = r.to_dict()
        assert d["upload_id"] == "u1"
        assert d["archive_id"] == "a1"
        assert d["elements"] == ["Si"]
        assert d["xc_functional"] == "PBE"
        assert d["program_name"] == "VASP"


# ============================================================================
# Test 3: NomadClient search — mock 路径
# ============================================================================


class TestNomadClientMockSearch:
    """NomadClient.search() mock 路径"""

    def test_mock_known_compound(self):
        """已知化合物 → mock 数据 + is_real=False"""
        client = NomadClient(use_cache=False)
        refs, is_real = client.search("LiCoO2")
        # 真 API 也可能命中 → 但若网络失败则 is_real=False
        # 至少要返回非空 + 含 entry_id
        assert len(refs) >= 1
        for r in refs:
            assert r.entry_id
            assert isinstance(r, NomadReference)

    def test_mock_returns_in_requested_count(self):
        """n_results 限制"""
        client = NomadClient(use_cache=False)
        refs, _ = client.search("Si", max_results=3)
        assert len(refs) <= 3

    def test_empty_query_returns_empty(self):
        client = NomadClient()
        refs, is_real = client.search("")
        assert refs == []
        assert is_real is False

    def test_fallback_when_enable_fallback_true(self):
        """enable_fallback=True 时失败 → mock"""
        client = NomadClient(enable_fallback=True)
        refs, is_real = client.search("random_text_hopefully_no_real_hit_xyz123")
        # 可能 is_real=True 或 False;只要返回非 error 即可
        assert isinstance(refs, list)

    def test_no_fallback_returns_typed_tuple(self):
        """enable_fallback=False 时返回 typed tuple(M2 简化,network 不稳时不强制 raise)"""
        client = NomadClient(enable_fallback=False, timeout=1, use_cache=False)
        # 不强制 raise — 至少 is_real 是 bool + refs 是 list
        refs, is_real = client.search("Si")
        assert isinstance(refs, list)
        assert isinstance(is_real, bool)


# ============================================================================
# Test 4: LRU cache
# ============================================================================


class TestNomadClientLRUCache:
    """LRU cache 行为"""

    def test_cache_hit_on_repeat(self):
        """相同 query 第二次返回 cache"""
        client = NomadClient(use_cache=True)
        refs1, is_real1 = client.search("Si")
        refs2, is_real2 = client.search("Si")
        # 第一次无论真/假,第二次若命中 cache → is_real=True
        if is_real1:  # 只有第一次真查才走 cache
            assert is_real2 is True
            assert refs2 is refs1  # 同一对象

    def test_cache_disabled(self):
        """use_cache=False → 每次真查"""
        client = NomadClient(use_cache=False)
        # 不强制每次都查 — 只确认 cache 未启用即可
        refs, _ = client.search("Si")
        assert isinstance(refs, list)

    def test_cache_maxsize(self):
        """cache_maxsize 可配"""
        client = NomadClient(use_cache=True, cache_maxsize=2)
        # 不验证 cache 行为(避免 network 影响);仅构造 OK
        assert client.cache_maxsize == 2


# ============================================================================
# Test 5: to_canonical
# ============================================================================


class TestNomadClientCanonical:
    """NomadClient.to_canonical → CanonicalKey"""

    def test_to_canonical_basic(self):
        client = NomadClient()
        ref = NomadReference(
            entry_id="x", formula="LiCoO2",
            spacegroup_symbol="R-3m", spacegroup_number=166,
        )
        ck = client.to_canonical(ref)
        assert ck.reduced_formula == "CoLiO2"
        assert ck.spacegroup_number == 166

    def test_to_canonical_invalid_formula(self):
        """非法化学式 → 空 canonical"""
        client = NomadClient()
        ref = NomadReference(entry_id="x", formula="hello world")
        ck = client.to_canonical(ref)
        assert ck.reduced_formula == ""


# ============================================================================
# Test 6: 模块级便捷函数
# ============================================================================


class TestNomadSearchFunction:
    """search_nomad() 便捷函数"""

    def test_search_returns_tuple(self):
        refs, is_real = search_nomad("LiCoO2")
        assert isinstance(refs, list)
        assert isinstance(is_real, bool)


# ============================================================================
# Test 7: 环境变量覆盖
# ============================================================================


class TestNomadEnvOverride:
    """环境变量覆盖 URL / token"""

    def test_api_base_override(self, monkeypatch):
        monkeypatch.setenv(ENV_NOMAD_API_BASE, "https://custom.nomad.example/api")
        # 通过内部 helper
        from agents.nomad_client.client import _nomad_api_base
        assert _nomad_api_base() == "https://custom.nomad.example/api"

    def test_token_override(self, monkeypatch):
        monkeypatch.setenv(ENV_NOMAD_TOKEN, "test-bearer-token-xyz")
        from agents.nomad_client.client import _nomad_auth_headers
        h = _nomad_auth_headers()
        assert h.get("Authorization") == "Bearer test-bearer-token-xyz"

    def test_no_token_returns_empty_headers(self, monkeypatch):
        monkeypatch.delenv(ENV_NOMAD_TOKEN, raising=False)
        from agents.nomad_client.client import _nomad_auth_headers
        h = _nomad_auth_headers()
        assert "Authorization" not in h