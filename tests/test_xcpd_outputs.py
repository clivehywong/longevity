"""Tests for neuconn_app/utils/xcpd_outputs.py.

Run with:
    cd /home/clivewong/proj/longevity && python -m pytest tests/test_xcpd_outputs.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

# Allow importing from neuconn_app without an installed package
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "neuconn_app"))

from utils.xcpd_outputs import XcpdDiscovery, XcpdOutputs, KNOWN_ATLASES

BIDS_ROOT = REPO_ROOT  # project root contains derivatives/preprocessing/xcpd/


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def discovery():
    return XcpdDiscovery(BIDS_ROOT, pipeline="fc")


@pytest.fixture(scope="module")
def sub033_ses01_fc(discovery):
    return discovery.get("sub-033", "ses-01", "fc")


# ---------------------------------------------------------------------------
# Pipeline / subject / session listing
# ---------------------------------------------------------------------------

def test_list_pipelines(discovery):
    pipelines = discovery.list_pipelines()
    assert set(pipelines) >= {"fc", "fc_gsr", "ec"}


def test_list_subjects_fc(discovery):
    subjects = discovery.list_subjects("fc")
    assert "sub-033" in subjects
    assert all(s.startswith("sub-") for s in subjects)


def test_list_sessions_sub033(discovery):
    sessions = discovery.list_sessions("sub-033", "fc")
    assert "ses-01" in sessions


def test_sub033_ses01_in_all_three_pipelines():
    """sub-033/ses-01 must be discoverable in all three pipelines."""
    for pl in ("fc", "fc_gsr", "ec"):
        d = XcpdDiscovery(BIDS_ROOT, pipeline=pl)
        subs = d.list_subjects(pl)
        assert "sub-033" in subs, f"sub-033 not found in pipeline {pl}"
        sessions = d.list_sessions("sub-033", pl)
        assert "ses-01" in sessions, f"ses-01 not found for sub-033 in pipeline {pl}"


# ---------------------------------------------------------------------------
# File existence for sub-033/ses-01/fc
# ---------------------------------------------------------------------------

def test_alff_map_exists(sub033_ses01_fc):
    assert sub033_ses01_fc.alff_map is not None
    assert sub033_ses01_fc.alff_map.exists()
    assert sub033_ses01_fc.alff_map.suffix == ".gz"


def test_reho_map_exists(sub033_ses01_fc):
    assert sub033_ses01_fc.reho_map is not None
    assert sub033_ses01_fc.reho_map.exists()


def test_has_local_measures(sub033_ses01_fc):
    assert sub033_ses01_fc.has_local_measures()


def test_denoised_bold_exists(sub033_ses01_fc):
    assert sub033_ses01_fc.denoised_bold is not None
    assert sub033_ses01_fc.denoised_bold.exists()


def test_denoised_smoothed_bold_exists(sub033_ses01_fc):
    assert sub033_ses01_fc.denoised_smoothed_bold is not None
    assert sub033_ses01_fc.denoised_smoothed_bold.exists()


def test_motion_tsv_exists(sub033_ses01_fc):
    assert sub033_ses01_fc.motion_tsv is not None
    assert sub033_ses01_fc.motion_tsv.exists()


def test_outliers_tsv_exists(sub033_ses01_fc):
    assert sub033_ses01_fc.outliers_tsv is not None
    assert sub033_ses01_fc.outliers_tsv.exists()


def test_design_tsv_exists(sub033_ses01_fc):
    assert sub033_ses01_fc.design_tsv is not None
    assert sub033_ses01_fc.design_tsv.exists()


def test_figures_dir_exists(sub033_ses01_fc):
    assert sub033_ses01_fc.figures_dir.exists()
    assert sub033_ses01_fc.figures_dir.is_dir()


# ---------------------------------------------------------------------------
# Atlas-keyed outputs
# ---------------------------------------------------------------------------

def test_list_atlases_returns_five(sub033_ses01_fc):
    atlases = sub033_ses01_fc.list_atlases()
    assert set(atlases) == set(KNOWN_ATLASES), (
        f"Expected {sorted(KNOWN_ATLASES)}, got {sorted(atlases)}"
    )


def test_alff_parcel_has_five_atlases(sub033_ses01_fc):
    assert set(sub033_ses01_fc.alff_parcel.keys()) == set(KNOWN_ATLASES)


def test_reho_parcel_has_five_atlases(sub033_ses01_fc):
    assert set(sub033_ses01_fc.reho_parcel.keys()) == set(KNOWN_ATLASES)


def test_coverage_parcel_has_five_atlases(sub033_ses01_fc):
    assert set(sub033_ses01_fc.coverage_parcel.keys()) == set(KNOWN_ATLASES)


def test_pearson_relmat_has_five_atlases(sub033_ses01_fc):
    assert set(sub033_ses01_fc.pearson_relmat.keys()) == set(KNOWN_ATLASES)


# ---------------------------------------------------------------------------
# parcel_labels
# ---------------------------------------------------------------------------

def test_parcel_labels_4s256(sub033_ses01_fc):
    labels = sub033_ses01_fc.parcel_labels("4S256Parcels")
    assert len(labels) == 256
    assert labels[0] == "LH_Vis_1"


def test_parcel_labels_bad_atlas_raises(sub033_ses01_fc):
    with pytest.raises(KeyError):
        sub033_ses01_fc.parcel_labels("NonExistentAtlas")


# ---------------------------------------------------------------------------
# coverage_table
# ---------------------------------------------------------------------------

def test_coverage_table_structure(discovery):
    df = discovery.coverage_table("fc")
    assert isinstance(df, pd.DataFrame)
    expected_cols = {"alff_map", "reho_map", "denoised", "motion_tsv", "atlases_present"}
    assert expected_cols <= set(df.columns)
    # Index is (subject, session)
    assert df.index.names == ["subject", "session"]


def test_coverage_table_sub033_present(discovery):
    df = discovery.coverage_table("fc")
    assert ("sub-033", "ses-01") in df.index


def test_coverage_table_bool_cols(discovery):
    df = discovery.coverage_table("fc")
    assert df.loc[("sub-033", "ses-01"), "alff_map"] == True
    assert df.loc[("sub-033", "ses-01"), "reho_map"] == True


# ---------------------------------------------------------------------------
# Graceful handling for missing data
# ---------------------------------------------------------------------------

def test_missing_pipeline_returns_empty_subjects(discovery):
    d = XcpdDiscovery(BIDS_ROOT, pipeline="nonexistent")
    assert d.list_subjects("nonexistent") == []


def test_missing_subject_returns_empty_sessions(discovery):
    sessions = discovery.list_sessions("sub-999", "fc")
    assert sessions == []


def test_get_missing_returns_nones():
    d = XcpdDiscovery(BIDS_ROOT, pipeline="fc")
    out = d.get("sub-999", "ses-99", "fc")
    assert isinstance(out, XcpdOutputs)
    assert out.alff_map is None
    assert out.reho_map is None
    assert out.denoised_bold is None
    assert out.alff_parcel == {}
    assert out.list_atlases() == []
    assert not out.has_local_measures()


def test_coverage_table_nonexistent_pipeline(discovery):
    df = discovery.coverage_table("nonexistent")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0


def test_get_uses_default_pipeline():
    d = XcpdDiscovery(BIDS_ROOT, pipeline="fc")
    out = d.get("sub-033", "ses-01")  # no explicit pipeline
    assert out.pipeline == "fc"
    assert out.alff_map is not None
