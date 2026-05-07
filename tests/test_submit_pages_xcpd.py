"""Smoke tests for the XCP-D-driven connectivity submit pages.

Tests:
- Each page module imports cleanly.
- Each defines render().
- Each uses the documented session-state prefix.
- Page 1 uses XcpdDiscovery.coverage_table.
- Pages 2/3/4 build commands via ConnectivityWorkflowManager.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parents[1] / "neuconn_app"
PAGES_DIR = APP_DIR / "pages_connectivity_submit"

PAGE_FILES = {
    "local_coverage": PAGES_DIR / "01_local_measures_coverage.py",
    "seed":           PAGES_DIR / "02_submit_seed_connectivity.py",
    "network":        PAGES_DIR / "03_submit_network_connectivity.py",
    "group":          PAGES_DIR / "04_submit_group_stats.py",
}

EXPECTED_PREFIXES = {
    "local_coverage": "submit_local_",
    "seed":           "submit_seed_",
    "network":        "submit_network_",
    "group":          "submit_group_",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_module(key: str):
    """Import a page module by file path, mocking streamlit if needed."""
    # Provide a stub for streamlit so the module can be imported without a
    # Streamlit server running.
    if "streamlit" not in sys.modules:
        import unittest.mock as mock
        st_mock = mock.MagicMock()
        st_mock.cache_data = lambda **kw: (lambda fn: fn)
        st_mock.cache_resource = lambda **kw: (lambda fn: fn)
        sys.modules["streamlit"] = st_mock

    path = PAGE_FILES[key]
    spec = importlib.util.spec_from_file_location(f"page_{key}", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ---------------------------------------------------------------------------
# T1 – All pages import cleanly
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", list(PAGE_FILES.keys()))
def test_page_imports_cleanly(key):
    """Each page module must import without raising."""
    mod = _load_module(key)
    assert mod is not None


# ---------------------------------------------------------------------------
# T2 – All pages define render()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", list(PAGE_FILES.keys()))
def test_page_defines_render(key):
    """Each page must expose a top-level render() function."""
    mod = _load_module(key)
    assert callable(getattr(mod, "render", None)), f"{key} does not define render()"


# ---------------------------------------------------------------------------
# T3 – Session-state prefixes are correct
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key,prefix", EXPECTED_PREFIXES.items())
def test_session_state_prefix(key, prefix):
    """Each page must reference its documented session-state prefix."""
    source = _load_source(PAGE_FILES[key])
    assert prefix in source, (
        f"{key} does not use session-state prefix '{prefix}'"
    )


# ---------------------------------------------------------------------------
# T4 – Page 1 uses XcpdDiscovery.coverage_table
# ---------------------------------------------------------------------------

def test_local_coverage_uses_xcpd_discovery():
    source = _load_source(PAGE_FILES["local_coverage"])
    assert "XcpdDiscovery" in source
    assert "coverage_table" in source


# ---------------------------------------------------------------------------
# T5 – Page 1 uses setdefault initialisation
# ---------------------------------------------------------------------------

def test_local_coverage_state_defaults():
    source = _load_source(PAGE_FILES["local_coverage"])
    assert "setdefault" in source


# ---------------------------------------------------------------------------
# T6 – Pages 2/3 use build_subject_level_command
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["seed", "network"])
def test_subject_level_pages_use_build_command(key):
    source = _load_source(PAGE_FILES[key])
    assert "build_subject_level_command" in source
    assert "ConnectivityWorkflowManager" in source


# ---------------------------------------------------------------------------
# T7 – Page 4 uses build_group_level_command
# ---------------------------------------------------------------------------

def test_group_page_uses_build_group_command():
    source = _load_source(PAGE_FILES["group"])
    assert "build_group_level_command" in source
    assert "ConnectivityWorkflowManager" in source


# ---------------------------------------------------------------------------
# T8 – Pages 2/3 import from connectivity_measures (MEASURES)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["seed", "network"])
def test_pages_reference_connectivity_measures(key):
    source = _load_source(PAGE_FILES[key])
    assert "connectivity_measures" in source or "ALL_MEASURES" in source


# ---------------------------------------------------------------------------
# T9 – Page 2 supports all three seed sources
# ---------------------------------------------------------------------------

def test_seed_page_supports_all_sources():
    source = _load_source(PAGE_FILES["seed"])
    for src in ("Atlas parcel", "Custom NIfTI ROI", "Sphere from coordinates"):
        assert src in source, f"Seed page missing source option: {src}"


# ---------------------------------------------------------------------------
# T10 – Page 4 has Voxel and Matrix branches
# ---------------------------------------------------------------------------

def test_group_page_has_both_kind_branches():
    source = _load_source(PAGE_FILES["group"])
    assert '"Voxel"' in source or "'Voxel'" in source
    assert '"Matrix"' in source or "'Matrix'" in source
    assert "voxel" in source.lower()
    assert "matrix" in source.lower()


# ---------------------------------------------------------------------------
# T11 – Page 4 has TFCE permutation count warning
# ---------------------------------------------------------------------------

def test_group_page_has_tfce_warning():
    source = _load_source(PAGE_FILES["group"])
    assert "TFCE" in source
    assert "1000" in source  # warns if < 1000 permutations


# ---------------------------------------------------------------------------
# T12 – Page 3 uses @st.cache_data with ttl
# ---------------------------------------------------------------------------

def test_network_page_uses_cache_data():
    source = _load_source(PAGE_FILES["network"])
    assert "cache_data" in source
    assert "ttl=60" in source


# ---------------------------------------------------------------------------
# T13 – All pages use STATE_PREFIX constant
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", list(PAGE_FILES.keys()))
def test_pages_use_state_prefix_constant(key):
    source = _load_source(PAGE_FILES[key])
    assert "STATE_PREFIX" in source
