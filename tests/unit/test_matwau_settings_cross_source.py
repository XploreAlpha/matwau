"""test_matwau_settings_cross_source.py — matwau_settings M3 4 个 env var 测试

per MatWAU-v1.3-Academic-dev-plan-20260804.md §五 M3 第 7 项
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from matwau.configs.matwau_settings import (  # noqa: E402
    DEFAULT_JARVIS_API_BASE,
    DEFAULT_JARVIS_TOKEN,
    DEFAULT_NOMAD_API_BASE,
    DEFAULT_NOMAD_TOKEN,
    get_default_settings,
    reset_settings_cache,
)


# ============================================================================
# Test 1: 默认值
# ============================================================================


class TestDefaults:
    def test_default_nomad_api_base(self):
        assert DEFAULT_NOMAD_API_BASE.startswith("https://nomad-lab.eu")

    def test_default_jarvis_api_base(self):
        assert DEFAULT_JARVIS_API_BASE.startswith("https://jarvis.nist.gov")

    def test_default_tokens_empty(self):
        assert DEFAULT_NOMAD_TOKEN == ""
        assert DEFAULT_JARVIS_TOKEN == ""


# ============================================================================
# Test 2: env var 覆盖
# ============================================================================


class TestEnvVarOverride:
    def teardown_method(self):
        reset_settings_cache()

    def test_nomad_api_base_override(self, monkeypatch):
        monkeypatch.setenv("MATWAU_NOMAD_API_BASE", "https://custom.nomad/api")
        reset_settings_cache()
        s = get_default_settings()
        assert s.nomad_api_base == "https://custom.nomad/api"

    def test_nomad_token_override(self, monkeypatch):
        monkeypatch.setenv("MATWAU_NOMAD_TOKEN", "test-bearer-xyz")
        reset_settings_cache()
        s = get_default_settings()
        assert s.nomad_token == "test-bearer-xyz"

    def test_jarvis_api_base_override(self, monkeypatch):
        monkeypatch.setenv("MATWAU_JARVIS_API_BASE", "https://custom.jarvis/api")
        reset_settings_cache()
        s = get_default_settings()
        assert s.jarvis_api_base == "https://custom.jarvis/api"

    def test_jarvis_token_override(self, monkeypatch):
        monkeypatch.setenv("MATWAU_JARVIS_TOKEN", "test-jarvis-token")
        reset_settings_cache()
        s = get_default_settings()
        assert s.jarvis_token == "test-jarvis-token"

    def test_all_4_overrides(self, monkeypatch):
        monkeypatch.setenv("MATWAU_NOMAD_API_BASE", "https://a")
        monkeypatch.setenv("MATWAU_NOMAD_TOKEN", "tok-a")
        monkeypatch.setenv("MATWAU_JARVIS_API_BASE", "https://b")
        monkeypatch.setenv("MATWAU_JARVIS_TOKEN", "tok-b")
        reset_settings_cache()
        s = get_default_settings()
        assert s.nomad_api_base == "https://a"
        assert s.nomad_token == "tok-a"
        assert s.jarvis_api_base == "https://b"
        assert s.jarvis_token == "tok-b"


# ============================================================================
# Test 3: M3 字段存在
# ============================================================================


class TestFieldsExist:
    def test_settings_has_4_m3_fields(self):
        s = get_default_settings()
        for field in [
            "nomad_api_base", "nomad_token",
            "jarvis_api_base", "jarvis_token",
        ]:
            assert hasattr(s, field)