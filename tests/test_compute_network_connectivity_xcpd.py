"""
tests/test_compute_network_connectivity_xcpd.py

Tests for script/compute_network_connectivity_xcpd.py

Real subject: sub-033, ses-01, pipeline fc
Atlases tested: 4S256Parcels (full-size), Tian (50 parcels — fast)
Measures tested: pearson, plv (fast subset for integration tests)

Test inventory
--------------
1. test_load_timeseries          — shape, labels, dtype
2. test_load_relmat              — shape, labels, diagonal==1
3. test_pearson_sanity_vs_xcpd   — recomputed Pearson ≈ XCP-D relmat within 1e-3
4. test_output_tsv_shape         — run CLI for Tian/pearson; check (50, 50) matrix
5. test_output_labels_match      — row/col labels match atlas parcel labels
6. test_fisher_z_suffix          — pearson output file has _relmat-z.tsv suffix
7. test_non_correlation_suffix   — plv output file has _relmat.tsv (no -z) suffix
8. test_idempotency              — second run with same args skips (no --force)
9. test_force_overwrite          — --force regenerates existing output
10. test_meta_json_fields        — meta JSON contains expected keys & sane values
"""

from __future__ import annotations

import json
import sys
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# -------------------------------------------------------------------------
# Allow imports from script/ and repo root
# -------------------------------------------------------------------------
_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "script"
sys.path.insert(0, str(_SCRIPT))
sys.path.insert(0, str(_REPO))

from compute_network_connectivity_xcpd import (
    load_timeseries,
    load_relmat,
    process_atlas,
    _all_outputs_exist,
    _out_filename,
    run,
)
import connectivity_measures as cm
from neuconn_app.utils.xcpd_outputs import XcpdDiscovery

# -------------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------------
BIDS_ROOT = _REPO
SUBJECT = "sub-033"
SESSION = "ses-01"
PIPELINE = "fc"
ATLAS_LARGE = "4S256Parcels"   # 256 parcels
ATLAS_SMALL = "Tian"           # 50 parcels — fast
ATLAS_SMALL_N = 50
ATLAS_LARGE_N = 256
TR = 0.8


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------

@pytest.fixture(scope="module")
def discovery():
    return XcpdDiscovery(BIDS_ROOT, pipeline=PIPELINE)


@pytest.fixture(scope="module")
def xcpd_outputs(discovery):
    return discovery.get(SUBJECT, SESSION, PIPELINE)


@pytest.fixture(scope="module")
def tian_ts_path(xcpd_outputs):
    path = xcpd_outputs.mean_timeseries.get(ATLAS_SMALL)
    if path is None:
        pytest.skip(f"Atlas {ATLAS_SMALL} mean_timeseries not available")
    return path


@pytest.fixture(scope="module")
def tian_relmat_path(xcpd_outputs):
    path = xcpd_outputs.pearson_relmat.get(ATLAS_SMALL)
    if path is None:
        pytest.skip(f"Atlas {ATLAS_SMALL} pearson_relmat not available")
    return path


@pytest.fixture(scope="module")
def large_ts_path(xcpd_outputs):
    path = xcpd_outputs.mean_timeseries.get(ATLAS_LARGE)
    if path is None:
        pytest.skip(f"Atlas {ATLAS_LARGE} mean_timeseries not available")
    return path


@pytest.fixture(scope="module")
def large_relmat_path(xcpd_outputs):
    path = xcpd_outputs.pearson_relmat.get(ATLAS_LARGE)
    if path is None:
        pytest.skip(f"Atlas {ATLAS_LARGE} pearson_relmat not available")
    return path


@pytest.fixture(scope="module")
def tian_ts(tian_ts_path):
    return load_timeseries(tian_ts_path)


@pytest.fixture(scope="module")
def tian_relmat(tian_relmat_path):
    return load_relmat(tian_relmat_path)


@pytest.fixture(scope="session")
def out_root(tmp_path_factory):
    """Temporary output root shared across module-scope tests."""
    return tmp_path_factory.mktemp("connectivity")


@pytest.fixture(scope="module")
def tian_out_dir(tmp_path_factory, xcpd_outputs):
    """Run pearson + plv for Tian and return the output directory."""
    out_root = tmp_path_factory.mktemp("tian_connectivity")
    run(
        bids_root=BIDS_ROOT,
        subject=SUBJECT,
        session=SESSION,
        pipeline=PIPELINE,
        atlases=[ATLAS_SMALL],
        measures=["pearson", "plv"],
        out_root=out_root,
        tr=TR,
        force=False,
    )
    return (
        out_root / PIPELINE / SUBJECT / SESSION / "network" / f"atlas-{ATLAS_SMALL}"
    )


# -------------------------------------------------------------------------
# Test 1 — load_timeseries
# -------------------------------------------------------------------------

def test_load_timeseries_shape_and_labels(tian_ts):
    ts, labels = tian_ts
    assert ts.ndim == 2, "timeseries must be 2-D"
    assert ts.shape[1] == ATLAS_SMALL_N, f"Expected {ATLAS_SMALL_N} parcels, got {ts.shape[1]}"
    assert len(labels) == ATLAS_SMALL_N, "label count must equal parcel count"
    assert ts.dtype == np.float64, "timeseries dtype must be float64"


# -------------------------------------------------------------------------
# Test 2 — load_relmat
# -------------------------------------------------------------------------

def test_load_relmat_shape_and_diagonal(tian_relmat):
    mat, labels = tian_relmat
    n = ATLAS_SMALL_N
    assert mat.shape == (n, n), f"Expected ({n},{n}), got {mat.shape}"
    assert len(labels) == n
    np.testing.assert_allclose(
        np.diag(mat), np.ones(n), atol=1e-6,
        err_msg="XCP-D relmat diagonal should be 1",
    )


# -------------------------------------------------------------------------
# Test 3 — Pearson sanity check vs XCP-D (BEFORE Fisher-Z)
# -------------------------------------------------------------------------

def test_pearson_sanity_vs_xcpd(tian_ts, tian_relmat):
    ts, _ = tian_ts
    xcpd_mat, _ = tian_relmat
    our_pearson = cm.pearson(ts)
    diff = np.abs(our_pearson - xcpd_mat)
    mean_diff = float(np.mean(diff))
    max_diff = float(np.max(diff))
    assert mean_diff <= 1e-3, (
        f"Mean abs diff between recomputed Pearson and XCP-D relmat: {mean_diff:.2e} > 1e-3"
    )
    assert max_diff <= 1e-3, (
        f"Max abs diff between recomputed Pearson and XCP-D relmat: {max_diff:.2e} > 1e-3"
    )


# -------------------------------------------------------------------------
# Test 4 — Output TSV shape (n_parcels × n_parcels)
# -------------------------------------------------------------------------

def test_output_tsv_shape(tian_out_dir):
    n = ATLAS_SMALL_N
    pearson_file = tian_out_dir / _out_filename(
        SUBJECT, SESSION, ATLAS_SMALL, "pearson", "relmat-z"
    )
    assert pearson_file.exists(), f"Expected output not found: {pearson_file}"
    df = pd.read_csv(pearson_file, sep="\t", index_col=0)
    assert df.shape == (n, n), f"Expected ({n},{n}), got {df.shape}"


# -------------------------------------------------------------------------
# Test 5 — Output labels match atlas parcel labels
# -------------------------------------------------------------------------

def test_output_labels_match_atlas(tian_out_dir, tian_ts):
    _, expected_labels = tian_ts
    pearson_file = tian_out_dir / _out_filename(
        SUBJECT, SESSION, ATLAS_SMALL, "pearson", "relmat-z"
    )
    df = pd.read_csv(pearson_file, sep="\t", index_col=0)
    assert list(df.index) == expected_labels, "Row labels mismatch"
    assert list(df.columns) == expected_labels, "Column labels mismatch"


# -------------------------------------------------------------------------
# Test 6 — Fisher-Z measures get _relmat-z.tsv suffix
# -------------------------------------------------------------------------

def test_fisher_z_suffix(tian_out_dir):
    for measure in cm.CORRELATION_TYPE:
        # Only pearson was requested in the fixture; check the one we computed
        if measure == "pearson":
            fname = _out_filename(SUBJECT, SESSION, ATLAS_SMALL, measure, "relmat-z")
            assert (tian_out_dir / fname).exists(), f"Expected {fname}"


# -------------------------------------------------------------------------
# Test 7 — Non-correlation measures get _relmat.tsv suffix (no -z)
# -------------------------------------------------------------------------

def test_non_correlation_suffix(tian_out_dir):
    fname = _out_filename(SUBJECT, SESSION, ATLAS_SMALL, "plv", "relmat")
    assert (tian_out_dir / fname).exists(), f"Expected {fname}"
    # Make sure the -z variant does NOT exist for plv
    fname_z = _out_filename(SUBJECT, SESSION, ATLAS_SMALL, "plv", "relmat-z")
    assert not (tian_out_dir / fname_z).exists(), f"Unexpected file: {fname_z}"


# -------------------------------------------------------------------------
# Test 8 — Idempotency (skip existing outputs without --force)
# -------------------------------------------------------------------------

def test_idempotency(tian_out_dir, tmp_path_factory, xcpd_outputs):
    out_root2 = tmp_path_factory.mktemp("idempotency")
    # First run
    run(
        bids_root=BIDS_ROOT,
        subject=SUBJECT,
        session=SESSION,
        pipeline=PIPELINE,
        atlases=[ATLAS_SMALL],
        measures=["pearson"],
        out_root=out_root2,
        tr=TR,
        force=False,
    )
    out_dir = out_root2 / PIPELINE / SUBJECT / SESSION / "network" / f"atlas-{ATLAS_SMALL}"
    fname = _out_filename(SUBJECT, SESSION, ATLAS_SMALL, "pearson", "relmat-z")
    first_mtime = (out_dir / fname).stat().st_mtime

    # Second run (no --force) — should not rewrite
    run(
        bids_root=BIDS_ROOT,
        subject=SUBJECT,
        session=SESSION,
        pipeline=PIPELINE,
        atlases=[ATLAS_SMALL],
        measures=["pearson"],
        out_root=out_root2,
        tr=TR,
        force=False,
    )
    second_mtime = (out_dir / fname).stat().st_mtime
    assert first_mtime == second_mtime, (
        "File was overwritten without --force (idempotency violated)"
    )


# -------------------------------------------------------------------------
# Test 9 — --force overwrites existing output
# -------------------------------------------------------------------------

def test_force_overwrite(tmp_path_factory):
    out_root3 = tmp_path_factory.mktemp("force_test")
    kwargs = dict(
        bids_root=BIDS_ROOT,
        subject=SUBJECT,
        session=SESSION,
        pipeline=PIPELINE,
        atlases=[ATLAS_SMALL],
        measures=["pearson"],
        out_root=out_root3,
        tr=TR,
    )
    # First run
    run(**kwargs, force=False)
    out_dir = out_root3 / PIPELINE / SUBJECT / SESSION / "network" / f"atlas-{ATLAS_SMALL}"
    fname = _out_filename(SUBJECT, SESSION, ATLAS_SMALL, "pearson", "relmat-z")
    first_mtime = (out_dir / fname).stat().st_mtime

    import time as _time
    _time.sleep(0.05)

    # Second run WITH --force
    run(**kwargs, force=True)
    second_mtime = (out_dir / fname).stat().st_mtime
    assert second_mtime > first_mtime, (
        "--force should regenerate output (mtime should increase)"
    )


# -------------------------------------------------------------------------
# Test 10 — Meta JSON contains expected keys and sane values
# -------------------------------------------------------------------------

def test_meta_json_fields(tian_out_dir):
    meta_file = tian_out_dir / f"{SUBJECT}_{SESSION}_atlas-{ATLAS_SMALL}_meta.json"
    assert meta_file.exists(), f"Meta JSON not found: {meta_file}"
    with meta_file.open() as fh:
        meta = json.load(fh)

    required_keys = [
        "subject", "session", "pipeline", "atlas",
        "n_parcels", "n_timepoints", "tr_seconds",
        "measures", "fisher_z_applied",
        "sanity_check_vs_xcpd_pearson",
        "runtime_seconds", "software",
    ]
    for key in required_keys:
        assert key in meta, f"Meta JSON missing key: {key!r}"

    assert meta["subject"] == SUBJECT
    assert meta["session"] == SESSION
    assert meta["pipeline"] == PIPELINE
    assert meta["atlas"] == ATLAS_SMALL
    assert meta["n_parcels"] == ATLAS_SMALL_N
    assert meta["n_timepoints"] > 0
    assert meta["tr_seconds"] == TR
    assert "pearson" in meta["fisher_z_applied"]
    assert "plv" not in meta["fisher_z_applied"]
    assert meta["runtime_seconds"] > 0

    # Sanity check values must be near-zero
    sc = meta["sanity_check_vs_xcpd_pearson"]
    assert "xcpd_pearson_mean_abs_diff" in sc
    assert sc["xcpd_pearson_mean_abs_diff"] <= 1e-3, (
        f"Pearson sanity check failed in meta: mean_diff={sc['xcpd_pearson_mean_abs_diff']:.2e}"
    )
