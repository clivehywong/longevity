"""
Tests for script/compute_seed_connectivity_xcpd.py.

Uses real sub-033/ses-01/fc XCP-D data.  Tests that need to load the 4-D BOLD
volume (~150 MB) are moderately slow; they are isolated so lighter tests can run
quickly.

Run:
    cd /home/clivewong/proj/longevity
    python -m pytest tests/test_compute_seed_connectivity_xcpd.py -v
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
BIDS_ROOT = REPO_ROOT
sys.path.insert(0, str(REPO_ROOT / "script"))
sys.path.insert(0, str(REPO_ROOT / "neuconn_app"))

from compute_seed_connectivity_xcpd import run, _parse_seed_spec, _seed_output_id  # noqa: E402
from utils.xcpd_outputs import XcpdDiscovery  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUBJECT = "sub-033"
SESSION = "ses-01"
PIPELINE = "fc"
TR = 0.8

# Use only two atlases in tests to stay fast
TEST_ATLASES = ["4S256Parcels"]

# MNI coords of PCC (posterior cingulate cortex)
PCC_COORDS = (0, -52, 26)
PCC_RADIUS = 6.0

# ---------------------------------------------------------------------------
# Module-level fixtures (real data checks)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def xcpd_out():
    disc = XcpdDiscovery(BIDS_ROOT, PIPELINE)
    out = disc.get(SUBJECT, SESSION, PIPELINE)
    if out.denoised_smoothed_bold is None or not out.denoised_smoothed_bold.exists():
        pytest.skip("XCP-D BOLD data not available for sub-033/ses-01/fc")
    return out


@pytest.fixture(scope="module")
def bold_path(xcpd_out):
    return xcpd_out.denoised_smoothed_bold


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_seed(seed_spec: str, measures: list[str], tmp_path: Path,
              bold_variant: str = "denoisedSmoothed",
              atlases: list[str] = None, force: bool = False) -> Path:
    """Call run() and return out_root."""
    out_root = tmp_path / "connectivity"
    run(
        bids_root=BIDS_ROOT,
        subject=SUBJECT,
        session=SESSION,
        pipeline=PIPELINE,
        seed_specs=[seed_spec],
        measures=measures,
        bold_variant=bold_variant,
        out_root=out_root,
        tr=TR,
        force=force,
        atlases=atlases if atlases else TEST_ATLASES,
    )
    return out_root


def _seed_dir(out_root: Path, seed_id: str) -> Path:
    return out_root / PIPELINE / SUBJECT / SESSION / "seed" / seed_id


# ---------------------------------------------------------------------------
# Test 1: Atlas-parcel seed — TSV shape, column labels, no NaN
# ---------------------------------------------------------------------------


def test_atlas_parcel_tsv_shape_and_columns(tmp_path, xcpd_out):
    """TSV for atlas-parcel seed has shape (1, N_parcels) with correct columns."""
    spec = "atlas-4S256Parcels:LH_Vis_1"
    out_root = _run_seed(spec, ["pearson"], tmp_path)

    seed_id = _seed_output_id(_parse_seed_spec(spec))
    seed_dir = _seed_dir(out_root, seed_id)
    tsv_files = sorted(seed_dir.glob("*measure-pearson*seed-to-parcel.tsv"))
    assert tsv_files, "No seed-to-parcel TSV found"

    tsv = tsv_files[0]
    df = pd.read_csv(tsv, sep="\t")

    # Shape: 1 row (the seed), N_parcels columns
    assert df.shape[0] == 1
    expected_labels = xcpd_out.parcel_labels("4S256Parcels")
    assert list(df.columns) == expected_labels, "Parcel columns do not match atlas labels"


def test_atlas_parcel_no_nan(tmp_path, xcpd_out):
    """Seed-to-parcel TSV must contain no NaN values for pearson measure."""
    spec = "atlas-4S256Parcels:LH_Vis_1"
    out_root = _run_seed(spec, ["pearson"], tmp_path)

    seed_id = _seed_output_id(_parse_seed_spec(spec))
    seed_dir = _seed_dir(out_root, seed_id)
    tsv = sorted(seed_dir.glob("*measure-pearson*seed-to-parcel.tsv"))[0]
    df = pd.read_csv(tsv, sep="\t")

    assert not df.isnull().any().any(), "TSV contains NaN values"


def test_atlas_parcel_self_correlation_high(tmp_path, xcpd_out):
    """Self-parcel (LH_Vis_1 vs LH_Vis_1) should yield a high Fisher-z value."""
    spec = "atlas-4S256Parcels:LH_Vis_1"
    out_root = _run_seed(spec, ["pearson"], tmp_path)

    seed_id = _seed_output_id(_parse_seed_spec(spec))
    seed_dir = _seed_dir(out_root, seed_id)
    tsv = sorted(seed_dir.glob("*measure-pearson*seed-to-parcel.tsv"))[0]
    df = pd.read_csv(tsv, sep="\t")

    # pearson + fisher_z of self = arctanh(1 - 1e-7) ≈ 8.06
    self_z = float(df["LH_Vis_1"].iloc[0])
    assert self_z > 7.0, f"Self-correlation Fisher-z too low: {self_z}"


# ---------------------------------------------------------------------------
# Test 2: Seed-to-voxel NIfTI — affine and shape match BOLD
# ---------------------------------------------------------------------------


def test_seed_to_voxel_nifti_affine_and_shape(tmp_path, xcpd_out, bold_path):
    """Seed-to-voxel z-map must have the same spatial shape and affine as the BOLD."""
    spec = "atlas-4S256Parcels:LH_Vis_1"
    out_root = _run_seed(spec, ["pearson"], tmp_path)

    seed_id = _seed_output_id(_parse_seed_spec(spec))
    seed_dir = _seed_dir(out_root, seed_id)
    zmap_files = sorted(seed_dir.glob("*seed-to-voxel_zmap.nii.gz"))
    assert zmap_files, "No seed-to-voxel z-map found"

    zmap_img = nib.load(str(zmap_files[0]))
    bold_img = nib.load(str(bold_path))

    # Spatial shape must match (3-D)
    assert zmap_img.shape == bold_img.shape[:3], (
        f"Z-map shape {zmap_img.shape} != BOLD shape {bold_img.shape[:3]}"
    )
    # Affine must match
    np.testing.assert_allclose(
        zmap_img.affine, bold_img.affine,
        rtol=1e-5, err_msg="Z-map affine does not match BOLD affine"
    )


# ---------------------------------------------------------------------------
# Test 3: Sphere seed — TSV produced, correct shape
# ---------------------------------------------------------------------------


def test_sphere_seed_tsv(tmp_path, xcpd_out):
    """Sphere seed at PCC coords produces a valid seed-to-parcel TSV."""
    spec = f"sphere:{PCC_COORDS[0]},{PCC_COORDS[1]},{PCC_COORDS[2]},r={int(PCC_RADIUS)},name=PCC"
    out_root = _run_seed(spec, ["pearson"], tmp_path)

    seed_id = _seed_output_id(_parse_seed_spec(spec))
    seed_dir = _seed_dir(out_root, seed_id)
    tsv_files = sorted(seed_dir.glob("*measure-pearson*seed-to-parcel.tsv"))
    assert tsv_files, f"No TSV found in {seed_dir}"

    df = pd.read_csv(tsv_files[0], sep="\t")
    assert df.shape[0] == 1
    expected_labels = xcpd_out.parcel_labels("4S256Parcels")
    assert list(df.columns) == expected_labels
    assert not df.isnull().any().any()


# ---------------------------------------------------------------------------
# Test 4: Custom NIfTI seed — small synthetic ROI in BOLD space
# ---------------------------------------------------------------------------


def test_custom_nifti_seed(tmp_path, xcpd_out, bold_path):
    """Custom NIfTI ROI seed (small synthetic mask) runs successfully."""
    # Build a tiny ROI NIfTI in the same space as the BOLD
    bold_img = nib.load(str(bold_path))
    affine = bold_img.affine
    shape3d = bold_img.shape[:3]

    # Place a 3-voxel radius sphere around PCC voxel
    inv_affine = np.linalg.inv(affine)
    cx, cy, cz, _ = inv_affine @ np.array([*PCC_COORDS, 1.0])
    mask = np.zeros(shape3d, dtype=np.float32)
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            for dz in range(-3, 4):
                if dx**2 + dy**2 + dz**2 <= 9:
                    xi, yi, zi = int(cx) + dx, int(cy) + dy, int(cz) + dz
                    if (0 <= xi < shape3d[0] and 0 <= yi < shape3d[1]
                            and 0 <= zi < shape3d[2]):
                        mask[xi, yi, zi] = 1.0

    roi_path = tmp_path / "pcc_roi.nii.gz"
    nib.save(nib.Nifti1Image(mask, affine), str(roi_path))

    spec = f"nifti:{roi_path},name=PCC_custom"
    out_root = _run_seed(spec, ["pearson"], tmp_path)

    seed_id = _seed_output_id(_parse_seed_spec(spec))
    seed_dir = _seed_dir(out_root, seed_id)
    tsv_files = sorted(seed_dir.glob("*measure-pearson*seed-to-parcel.tsv"))
    assert tsv_files, f"No TSV found in {seed_dir}"

    df = pd.read_csv(tsv_files[0], sep="\t")
    assert df.shape[0] == 1
    assert not df.isnull().any().any()
    # Also check the meta.json exists
    meta_files = sorted(seed_dir.glob("*_meta.json"))
    assert meta_files, "Meta JSON not found"
    import json
    meta = json.loads(meta_files[0].read_text())
    assert meta["pipeline"] == PIPELINE
    assert meta["bold_variant"] == "denoisedSmoothed"


# ---------------------------------------------------------------------------
# Test 5: PLV measure dispatch
# ---------------------------------------------------------------------------


def test_plv_measure(tmp_path, xcpd_out):
    """PLV measure runs and produces a TSV with values in [0, 1] (no fisher_z)."""
    spec = "atlas-4S256Parcels:LH_Vis_1"
    out_root = _run_seed(spec, ["plv"], tmp_path)

    seed_id = _seed_output_id(_parse_seed_spec(spec))
    seed_dir = _seed_dir(out_root, seed_id)
    tsv_files = sorted(seed_dir.glob("*measure-plv*seed-to-parcel.tsv"))
    assert tsv_files, "No PLV TSV found"

    df = pd.read_csv(tsv_files[0], sep="\t")
    assert df.shape[0] == 1
    vals = df.iloc[0].to_numpy(dtype=np.float64)
    assert not np.isnan(vals).any(), "PLV TSV has NaN"
    # PLV values are in [0, 1]
    assert vals.min() >= -0.01, f"PLV below 0: {vals.min()}"
    assert vals.max() <= 1.01, f"PLV above 1: {vals.max()}"


# ---------------------------------------------------------------------------
# Test 6: Idempotency — second run with same args is a no-op
# ---------------------------------------------------------------------------


def test_idempotency(tmp_path, xcpd_out):
    """Running twice without --force must not overwrite any output file."""
    spec = "atlas-4S256Parcels:LH_Vis_1"

    # First run
    out_root = _run_seed(spec, ["pearson"], tmp_path)

    seed_id = _seed_output_id(_parse_seed_spec(spec))
    seed_dir = _seed_dir(out_root, seed_id)

    # Collect all output paths and their mtimes
    all_outputs = list(seed_dir.glob("*"))
    assert all_outputs, "First run produced no outputs"
    mtimes_before = {p: p.stat().st_mtime for p in all_outputs}

    # Small sleep to ensure a mtime difference would be detectable
    time.sleep(0.05)

    # Second run (same args, no force)
    _run_seed(spec, ["pearson"], tmp_path, force=False)

    # Check mtimes unchanged
    for path, mtime_before in mtimes_before.items():
        mtime_after = path.stat().st_mtime
        assert mtime_after == mtime_before, (
            f"File was overwritten on second run: {path.name}"
        )


# ---------------------------------------------------------------------------
# Test 7: Parse seed specs round-trip
# ---------------------------------------------------------------------------


def test_parse_seed_spec_atlas():
    seed = _parse_seed_spec("atlas-4S256Parcels:LH_Vis_1")
    assert seed.source == "xcpd_atlas_parcel"
    assert seed.atlas == "4S256Parcels"
    assert seed.parcel_label == "LH_Vis_1"
    assert seed.id == "atlas-4S256Parcels_parcel-LH_Vis_1"


def test_parse_seed_spec_sphere():
    seed = _parse_seed_spec("sphere:0,-52,26,r=6,name=PCC")
    assert seed.source == "sphere"
    assert seed.coords_mm == (0.0, -52.0, 26.0)
    assert seed.radius_mm == 6.0
    assert seed.name == "PCC"


def test_parse_seed_spec_nifti(tmp_path):
    fake = tmp_path / "roi.nii.gz"
    fake.touch()
    seed = _parse_seed_spec(f"nifti:{fake},name=DLPFC")
    assert seed.source == "custom_nifti_roi"
    assert seed.name == "DLPFC"
    assert seed.id == "custom_nifti-DLPFC"
