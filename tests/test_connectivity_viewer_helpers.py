"""Tests for neuconn_app/utils/connectivity_viewer.py helpers.

Run with:
    cd /home/clivewong/proj/longevity && python -m pytest tests/test_connectivity_viewer_helpers.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "neuconn_app"))

from utils.connectivity_viewer import (
    KNOWN_MEASURES,
    CORRELATION_TYPE,
    DEFAULT_PIPELINE,
    KNOWN_PIPELINES,
    connectivity_dir,
    network_dir,
    seed_dir,
    relmat_filename,
    relmat_path,
    load_relmat,
    load_seed_to_parcel,
    list_available_seeds,
    list_available_atlases_network,
    list_available_measures,
    list_available_measures_seed,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_known_measures_count():
    """There should be exactly 8 known measures."""
    assert len(KNOWN_MEASURES) == 8


def test_correlation_type_subset():
    """CORRELATION_TYPE must be a subset of KNOWN_MEASURES."""
    assert CORRELATION_TYPE.issubset(set(KNOWN_MEASURES))


def test_default_pipeline():
    """Default pipeline is 'fc'."""
    assert DEFAULT_PIPELINE == "fc"


def test_known_pipelines():
    """Three pipelines defined."""
    assert set(KNOWN_PIPELINES) == {"fc", "fc_gsr", "ec"}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def test_relmat_filename_pearson():
    fn = relmat_filename("sub-033", "ses-01", "4S256Parcels", "pearson")
    assert fn == "sub-033_ses-01_atlas-4S256Parcels_measure-pearson_relmat-z.tsv"


def test_relmat_filename_non_correlation():
    fn = relmat_filename("sub-033", "ses-01", "Gordon", "plv")
    assert fn == "sub-033_ses-01_atlas-Gordon_measure-plv_relmat.tsv"
    assert "-z" not in fn


def test_relmat_path_structure(tmp_path: Path):
    """relmat_path points into derivatives/connectivity/{pipeline}/sub/ses/network/atlas-*/."""
    p = relmat_path(tmp_path, "fc", "sub-033", "ses-01", "4S256Parcels", "pearson")
    assert "derivatives/connectivity" in str(p)
    assert "fc/sub-033/ses-01/network/atlas-4S256Parcels" in str(p)


def test_seed_dir_structure(tmp_path: Path):
    """seed_dir points into derivatives/connectivity/{pipeline}/sub/ses/seed/{seed_id}/."""
    p = seed_dir(tmp_path, "fc", "sub-033", "ses-01", "atlas-Gordon_parcel-L_VIS_1")
    assert "seed/atlas-Gordon_parcel-L_VIS_1" in str(p)


# ---------------------------------------------------------------------------
# load_relmat — missing file returns (None, None)
# ---------------------------------------------------------------------------

def test_load_relmat_missing_returns_none():
    mat, labels = load_relmat(
        str(REPO_ROOT), "fc", "sub-999", "ses-99", "4S256Parcels", "pearson"
    )
    assert mat is None
    assert labels is None


def test_load_relmat_from_synthetic_tsv(tmp_path: Path):
    """load_relmat correctly parses a synthetic TSV."""
    atlas = "TestAtlas"
    measure = "plv"  # non-correlation → no -z
    sub, ses, pl = "sub-001", "ses-01", "fc"

    ndir = tmp_path / "derivatives" / "connectivity" / pl / sub / ses / "network" / f"atlas-{atlas}"
    ndir.mkdir(parents=True)
    fn = f"{sub}_{ses}_atlas-{atlas}_measure-{measure}_relmat.tsv"
    labels = ["A", "B", "C"]
    mat_data = pd.DataFrame([[1.0, 0.5, 0.3], [0.5, 1.0, 0.7], [0.3, 0.7, 1.0]], columns=labels, index=[0, 1, 2])
    (ndir / fn).write_text(mat_data.to_csv(sep="\t"))

    mat, out_labels = load_relmat(str(tmp_path), pl, sub, ses, atlas, measure)
    assert mat is not None
    assert out_labels == labels
    assert mat.shape == (3, 3)
    assert pytest.approx(mat[0, 1], abs=1e-6) == 0.5


def test_load_seed_to_parcel_from_synthetic(tmp_path: Path):
    """load_seed_to_parcel correctly parses a synthetic TSV."""
    sub, ses, pl = "sub-001", "ses-01", "fc"
    sid = "atlas-Gordon_parcel-L_Vis_1"
    atlas, measure = "Gordon", "pearson"

    sdir = tmp_path / "derivatives" / "connectivity" / pl / sub / ses / "seed" / sid
    sdir.mkdir(parents=True)
    fn = f"{sub}_{ses}_seed-{sid}_atlas-{atlas}_measure-{measure}_seed-to-parcel.tsv"
    parcel_df = pd.DataFrame({"L_Vis_2": [0.8], "L_Vis_3": [0.6]})
    (sdir / fn).write_text(parcel_df.to_csv(sep="\t", index=False))

    df = load_seed_to_parcel(str(tmp_path), pl, sub, ses, sid, atlas, measure)
    assert df is not None
    assert "L_Vis_2" in df.columns
    assert float(df["L_Vis_2"].iloc[0]) == pytest.approx(0.8)


def test_load_seed_to_parcel_missing_returns_none():
    df = load_seed_to_parcel(
        str(REPO_ROOT), "fc", "sub-999", "ses-99", "no_such_seed", "Gordon", "pearson"
    )
    assert df is None


# ---------------------------------------------------------------------------
# list_available_seeds
# ---------------------------------------------------------------------------

def test_list_available_seeds_empty_dir(tmp_path: Path):
    seeds = list_available_seeds(tmp_path, "fc", "sub-033", "ses-01")
    assert seeds == []


def test_list_available_seeds_populated(tmp_path: Path):
    sub, ses, pl = "sub-033", "ses-01", "fc"
    seed_root = tmp_path / "derivatives" / "connectivity" / pl / sub / ses / "seed"
    (seed_root / "seed_A").mkdir(parents=True)
    (seed_root / "seed_B").mkdir(parents=True)
    seeds = list_available_seeds(tmp_path, pl, sub, ses)
    assert set(seeds) == {"seed_A", "seed_B"}


# ---------------------------------------------------------------------------
# list_available_measures
# ---------------------------------------------------------------------------

def test_list_available_measures_empty(tmp_path: Path):
    measures = list_available_measures(tmp_path, "fc", "sub-033", "ses-01", "Gordon")
    assert measures == []


def test_list_available_measures_detects_existing(tmp_path: Path):
    sub, ses, pl, atlas = "sub-033", "ses-01", "fc", "Gordon"
    ndir = tmp_path / "derivatives" / "connectivity" / pl / sub / ses / "network" / f"atlas-{atlas}"
    ndir.mkdir(parents=True)
    # Create a pearson relmat file (correlation → -z suffix)
    (ndir / f"{sub}_{ses}_atlas-{atlas}_measure-pearson_relmat-z.tsv").write_text("idx\tA\tB\n")
    # Create a plv relmat file
    (ndir / f"{sub}_{ses}_atlas-{atlas}_measure-plv_relmat.tsv").write_text("idx\tA\tB\n")

    measures = list_available_measures(tmp_path, pl, sub, ses, atlas)
    assert "pearson" in measures
    assert "plv" in measures
    assert "spearman" not in measures


# ---------------------------------------------------------------------------
# pipeline_picker default (no Streamlit runtime — test helper logic only)
# ---------------------------------------------------------------------------

def test_pipeline_picker_default_value():
    """DEFAULT_PIPELINE should be 'fc' — the expected picker default."""
    assert DEFAULT_PIPELINE == "fc"
    assert DEFAULT_PIPELINE in KNOWN_PIPELINES
