"""
Tests for the unified XCP-D seed catalog (seed_catalog.py refactor).

Covers:
  - 5 atlases discovered from real XCP-D probe data
  - Correct parcel counts per atlas
  - Network inference for Schaefer-style, Gordon, and Tian labels
  - Deterministic seed IDs
  - Custom NIfTI ROI loading from roi_config.json
  - Sphere factory (Seed.sphere) and SeedCatalog.add_sphere
  - Query / atlas / network filters
  - Graceful degradation when bids_root is missing
  - group_by_network grouping
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from neuconn_app.utils.seed_catalog import Seed, SeedCatalog

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_catalog() -> SeedCatalog:
    """Catalog loaded from the actual repo's XCP-D derivatives."""
    return SeedCatalog(REPO_ROOT)


@pytest.fixture()
def roi_catalog(tmp_path: Path) -> SeedCatalog:
    """Catalog backed by a temp directory with a synthetic roi_config.json."""
    (tmp_path / "neuconn_app").mkdir()
    roi_entries = [
        {
            "id": "motor_L",
            "name": "Left Motor Cortex",
            "nifti_path": "rois/motor_L.nii.gz",
        },
        {
            "id": "hippocampus",
            "name": "Hippocampus",
            "nifti_path": "rois/hipp.nii.gz",
        },
        {
            # Entry without nifti_path — should be skipped
            "id": "no_nifti",
            "name": "No NIfTI",
        },
    ]
    (tmp_path / "neuconn_app" / "roi_config.json").write_text(
        json.dumps({"rois": roi_entries})
    )
    return SeedCatalog(tmp_path)


# ---------------------------------------------------------------------------
# Atlas discovery
# ---------------------------------------------------------------------------

def test_five_atlases_discovered(real_catalog: SeedCatalog) -> None:
    atlases = set(real_catalog.list_atlases())
    expected = {"4S256Parcels", "4S456Parcels", "Glasser", "Gordon", "Tian"}
    assert expected.issubset(atlases), f"Missing atlases: {expected - atlases}"


def test_4s256_parcel_count(real_catalog: SeedCatalog) -> None:
    assert len(real_catalog.get_seeds(atlas="4S256Parcels")) == 256


def test_4s456_parcel_count(real_catalog: SeedCatalog) -> None:
    assert len(real_catalog.get_seeds(atlas="4S456Parcels")) == 456


def test_glasser_parcel_count(real_catalog: SeedCatalog) -> None:
    assert len(real_catalog.get_seeds(atlas="Glasser")) == 360


def test_gordon_parcel_count(real_catalog: SeedCatalog) -> None:
    assert len(real_catalog.get_seeds(atlas="Gordon")) == 333


def test_tian_parcel_count(real_catalog: SeedCatalog) -> None:
    assert len(real_catalog.get_seeds(atlas="Tian")) >= 16


# ---------------------------------------------------------------------------
# Network inference
# ---------------------------------------------------------------------------

def test_network_inference_4s256_vis(real_catalog: SeedCatalog) -> None:
    vis_seeds = [
        s for s in real_catalog.get_seeds(atlas="4S256Parcels")
        if s.parcel_label and s.parcel_label.startswith("LH_Vis_")
    ]
    assert vis_seeds, "Expected Vis seeds in 4S256Parcels"
    assert all(s.network == "Vis" for s in vis_seeds)


def test_network_inference_gordon_default(real_catalog: SeedCatalog) -> None:
    default_seeds = real_catalog.get_seeds(atlas="Gordon", network="Default")
    assert default_seeds, "Expected Default-network seeds in Gordon"


def test_network_inference_tian_hip(real_catalog: SeedCatalog) -> None:
    hip_seeds = real_catalog.get_seeds(atlas="Tian", network="HIP")
    assert hip_seeds, "Expected HIP seeds in Tian atlas"


def test_glasser_network_none(real_catalog: SeedCatalog) -> None:
    glasser_seeds = real_catalog.get_seeds(atlas="Glasser")
    # Glasser labels carry no network info → all should be None
    assert all(s.network is None for s in glasser_seeds)


# ---------------------------------------------------------------------------
# Deterministic seed IDs
# ---------------------------------------------------------------------------

def test_seed_id_format(real_catalog: SeedCatalog) -> None:
    seed = real_catalog.get_seed("atlas-4S256Parcels_parcel-LH_Vis_1")
    assert seed.atlas == "4S256Parcels"
    assert seed.parcel_label == "LH_Vis_1"
    assert seed.parcel_index == 0  # first column


def test_seed_id_stable_across_lookups(real_catalog: SeedCatalog) -> None:
    sid = "atlas-Gordon_parcel-L_Default_1"
    seed = real_catalog.get_seed(sid)
    assert seed.id == sid
    assert seed.source == "xcpd_atlas_parcel"


# ---------------------------------------------------------------------------
# Custom NIfTI ROIs
# ---------------------------------------------------------------------------

def test_custom_nifti_count(roi_catalog: SeedCatalog) -> None:
    seeds = roi_catalog.get_seeds(source="custom_nifti_roi")
    # Only entries with nifti_path are loaded (2 out of 3)
    assert len(seeds) == 2


def test_custom_nifti_roi_source(roi_catalog: SeedCatalog) -> None:
    seed = roi_catalog.get_seed("custom_nifti-motor_L")
    assert seed.source == "custom_nifti_roi"
    assert seed.name == "Left Motor Cortex"
    assert seed.nifti_path is not None


def test_custom_nifti_relative_path_resolved(roi_catalog: SeedCatalog) -> None:
    seed = roi_catalog.get_seed("custom_nifti-hippocampus")
    # Relative path should be resolved against bids_root
    assert seed.nifti_path is not None
    assert seed.nifti_path.is_absolute()


# ---------------------------------------------------------------------------
# Sphere factory
# ---------------------------------------------------------------------------

def test_sphere_static_factory() -> None:
    s = Seed.sphere("PCC", -6, -52, 26, radius_mm=8)
    assert s.source == "sphere"
    assert s.coords_mm == (-6.0, -52.0, 26.0)
    assert s.radius_mm == 8.0
    assert "PCC" in s.id


def test_sphere_default_radius() -> None:
    s = Seed.sphere("mPFC", 0, 52, -6)
    assert s.radius_mm == 6.0


def test_add_sphere_to_catalog() -> None:
    cat = SeedCatalog(Path("/nonexistent/path"))
    seed = cat.add_sphere("mPFC", 0, 52, -6)
    assert cat.get_seed(seed.id) is seed
    sphere_seeds = cat.get_seeds(source="sphere")
    assert len(sphere_seeds) == 1


def test_add_sphere_idempotent() -> None:
    cat = SeedCatalog(Path("/nonexistent/path"))
    s1 = cat.add_sphere("PCC", -6, -52, 26)
    s2 = cat.add_sphere("PCC", -6, -52, 26)
    assert s1 is s2
    assert len(cat.get_seeds(source="sphere")) == 1


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def test_query_filter(real_catalog: SeedCatalog) -> None:
    results = real_catalog.get_seeds(query="LH_Vis")
    assert results
    assert all("Vis" in (s.parcel_label or "") for s in results)


def test_atlas_filter_exclusive(real_catalog: SeedCatalog) -> None:
    seeds = real_catalog.get_seeds(atlas="Gordon")
    assert all(s.atlas == "Gordon" for s in seeds)


def test_network_filter(real_catalog: SeedCatalog) -> None:
    seeds = real_catalog.get_seeds(atlas="4S256Parcels", network="Vis")
    assert seeds
    assert all(s.network == "Vis" for s in seeds)


def test_nonexistent_atlas_returns_empty(real_catalog: SeedCatalog) -> None:
    assert real_catalog.get_seeds(atlas="NonexistentAtlas") == []


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

def test_missing_bids_root_empty_catalog() -> None:
    cat = SeedCatalog(Path("/this/path/does/not/exist"))
    assert cat.get_seeds() == []
    assert cat.list_atlases() == []
    assert cat.list_sources() == []


# ---------------------------------------------------------------------------
# group_by_network
# ---------------------------------------------------------------------------

def test_group_by_network_4s256(real_catalog: SeedCatalog) -> None:
    grouped = real_catalog.group_by_network("4S256Parcels")
    assert "Vis" in grouped
    assert any("Som" in k for k in grouped), f"No SomMot-like network in {list(grouped)}"
    assert all(len(v) > 0 for v in grouped.values())


def test_group_by_network_tian(real_catalog: SeedCatalog) -> None:
    grouped = real_catalog.group_by_network("Tian")
    assert "HIP" in grouped
    assert "THA" in grouped


def test_list_networks_gordon(real_catalog: SeedCatalog) -> None:
    networks = real_catalog.list_networks("Gordon")
    assert "Default" in networks
    assert isinstance(networks, list)
    assert networks == sorted(networks)
