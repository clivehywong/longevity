"""
Tests for script/group_voxel_stats_xcpd.py

Run with:
    cd /home/clivewong/proj/longevity && python -m pytest tests/test_group_voxel_stats_xcpd.py -v

Test plan
---------
1. test_fdr_paired          — FDR on synthetic ses-02_minus_ses-01 data
2. test_fdr_two_sample      — FDR on synthetic group-walking_minus_control data
3. test_fdr_correlation     — FDR on synthetic correlation_score data
4. test_grf_cli_args        — GRF mocks subprocess.run, asserts correct FSL cluster args
5. test_tfce_paired_cli     — TFCE mocks subprocess.run, asserts correct randomise args
6. test_tfce_two_sample_cli — TFCE two-sample mock, asserts design matrix is written
7. test_mask_derivation     — derive_mask builds valid mask from synthetic maps
8. test_output_files_fdr    — run_group_voxel_stats FDR creates all required output files
9. test_report_json_fields  — report.json contains expected keys
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple
from unittest.mock import MagicMock, patch

import nibabel as nib
import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Path setup — allow direct import from script/ and neuconn_app/
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "neuconn_app"))
sys.path.insert(0, str(REPO_ROOT / "script"))

import group_voxel_stats_xcpd as gvs  # noqa: E402

# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

SMALL_SHAPE = (8, 8, 8)   # tiny volume for speed
N_SUBJECTS = 5
RNG = np.random.default_rng(42)


def _make_nifti(data: np.ndarray, path: Path) -> Path:
    """Save a float32 NIfTI to *path* and return path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    affine = np.eye(4) * 2.0  # 2 mm isotropic
    affine[3, 3] = 1.0
    img = nib.Nifti1Image(data.astype(np.float32), affine)
    nib.save(img, str(path))
    return path


def _make_mask(shape: Tuple[int, int, int], path: Path) -> Path:
    """All-ones mask."""
    data = np.ones(shape, dtype=np.uint8)
    return _make_nifti(data.astype(np.float32), path)


def _synthetic_xcpd_tree(
    tmp_path: Path,
    pipeline: str = "fc",
    measure: str = "alff",
    n_subjects: int = N_SUBJECTS,
    sessions: Tuple[str, str] = ("ses-01", "ses-02"),
    group_labels: List[str] | None = None,
) -> Tuple[Path, pd.DataFrame]:
    """
    Build a synthetic XCP-D derivative tree with ALFF maps.

    Returns (bids_root, group_df).
    """
    bids_root = tmp_path / "bids"
    xcpd_root = bids_root / "derivatives" / "preprocessing" / "xcpd" / pipeline
    subjects = [f"sub-{100 + i:03d}" for i in range(n_subjects)]
    if group_labels is None:
        group_labels = ["Walking" if i % 2 == 0 else "Control" for i in range(n_subjects)]

    for i, sub in enumerate(subjects):
        for ses in sessions:
            func_dir = xcpd_root / sub / ses / "func"
            fname = (
                f"{sub}_{ses}_task-rest_space-MNI152NLin6Asym_res-2"
                f"_stat-{measure}_boldmap.nii.gz"
            )
            # ses-02 maps slightly higher than ses-01 to create a real effect
            offset = 0.5 if ses == sessions[1] else 0.0
            data = RNG.random(SMALL_SHAPE).astype(np.float32) + offset
            _make_nifti(data, func_dir / fname)

    group_df = pd.DataFrame({
        "participant_id": subjects,
        "Age": np.linspace(60, 68, n_subjects),
        "Gender": ["F" if i % 2 == 0 else "M" for i in range(n_subjects)],
        "group": group_labels,
    })
    return bids_root, group_df


# ---------------------------------------------------------------------------
# Test 1 — FDR paired (ses-02_minus_ses-01)
# ---------------------------------------------------------------------------

def test_fdr_paired(tmp_path):
    bids_root, group_df = _synthetic_xcpd_tree(tmp_path)
    participants_tsv = bids_root / "participants.tsv"
    group_df.to_csv(participants_tsv, sep="\t", index=False)
    out_dir = tmp_path / "out_fdr_paired"

    gvs.run_group_voxel_stats(
        bids_root=bids_root,
        pipeline="fc",
        measure="alff",
        contrast="ses-02_minus_ses-01",
        method="fdr",
        group_csv=participants_tsv,
        out_dir=out_dir,
        mask_path=None,
        n_permutations=0,
    )

    assert (out_dir / "tstat.nii.gz").exists()
    assert (out_dir / "zstat.nii.gz").exists()
    assert (out_dir / "pcorr.nii.gz").exists()
    assert (out_dir / "cluster_table.tsv").exists()

    # t-stats should be mostly positive (ses-02 > ses-01 by 0.5)
    tstat_data = nib.load(str(out_dir / "tstat.nii.gz")).get_fdata()
    assert tstat_data.mean() > 0, "Expected positive mean t-stat (ses-02 > ses-01)"


# ---------------------------------------------------------------------------
# Test 2 — FDR two-sample (group-walking_minus_control)
# ---------------------------------------------------------------------------

def test_fdr_two_sample(tmp_path):
    n = 6
    groups = ["Walking", "Walking", "Walking", "Control", "Control", "Control"]
    bids_root, group_df = _synthetic_xcpd_tree(
        tmp_path, n_subjects=n, group_labels=groups
    )
    participants_tsv = bids_root / "participants.tsv"
    group_df.to_csv(participants_tsv, sep="\t", index=False)
    out_dir = tmp_path / "out_fdr_group"

    gvs.run_group_voxel_stats(
        bids_root=bids_root,
        pipeline="fc",
        measure="alff",
        contrast="group-walking_minus_control",
        method="fdr",
        group_csv=participants_tsv,
        out_dir=out_dir,
    )

    pcorr = nib.load(str(out_dir / "pcorr.nii.gz")).get_fdata()
    assert pcorr.shape == SMALL_SHAPE
    assert np.all((pcorr >= 0) & (pcorr <= 1.0 + 1e-6)), "pcorr must be in [0, 1]"


# ---------------------------------------------------------------------------
# Test 3 — FDR correlation (correlation_score)
# ---------------------------------------------------------------------------

def test_fdr_correlation(tmp_path):
    n = 6
    bids_root, group_df = _synthetic_xcpd_tree(tmp_path, n_subjects=n)
    group_df["score"] = np.arange(n, dtype=float) * 10.0
    participants_tsv = bids_root / "participants.tsv"
    group_df.to_csv(participants_tsv, sep="\t", index=False)
    out_dir = tmp_path / "out_fdr_corr"

    gvs.run_group_voxel_stats(
        bids_root=bids_root,
        pipeline="fc",
        measure="alff",
        contrast="correlation_score",
        method="fdr",
        group_csv=participants_tsv,
        out_dir=out_dir,
    )

    zstat = nib.load(str(out_dir / "zstat.nii.gz")).get_fdata()
    assert np.isfinite(zstat).all(), "z-stat map should contain only finite values"


# ---------------------------------------------------------------------------
# Test 4 — GRF: assert correct FSL cluster CLI args
# ---------------------------------------------------------------------------

def test_grf_cli_args(tmp_path):
    """GRF method calls `cluster` with -t 3.1 -p 0.05 --mm."""
    bids_root, group_df = _synthetic_xcpd_tree(tmp_path)
    participants_tsv = bids_root / "participants.tsv"
    group_df.to_csv(participants_tsv, sep="\t", index=False)
    out_dir = tmp_path / "out_grf"

    def fake_run(cmd, **kwargs):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = (
            "Cluster Index\tVoxels\tP\t-log10(P)\tZ-MAX\t"
            "Z-MAX X (mm)\tZ-MAX Y (mm)\tZ-MAX Z (mm)\n"
            "1\t500\t0.001\t3.0\t4.2\t-30.0\t-20.0\t50.0\n"
        )
        mock.stderr = ""
        return mock

    with patch("group_voxel_stats_xcpd.run_cmd", side_effect=fake_run) as mock_run:
        gvs.run_group_voxel_stats(
            bids_root=bids_root,
            pipeline="fc",
            measure="alff",
            contrast="ses-02_minus_ses-01",
            method="grf",
            group_csv=participants_tsv,
            out_dir=out_dir,
            z_thresh=3.1,
            p_thresh=0.05,
        )

    # Find the call that invoked `cluster`
    cluster_calls = [
        call for call in mock_run.call_args_list
        if call.args and call.args[0][0] == "cluster"
    ]
    assert cluster_calls, "Expected at least one call to FSL `cluster`"
    cluster_cmd = cluster_calls[0].args[0]
    cmd_str = " ".join(str(c) for c in cluster_cmd)

    assert "-t" in cluster_cmd, "cluster cmd must have -t flag"
    t_idx = cluster_cmd.index("-t")
    assert float(cluster_cmd[t_idx + 1]) == pytest.approx(3.1)

    assert "-p" in cluster_cmd
    p_idx = cluster_cmd.index("-p")
    assert float(cluster_cmd[p_idx + 1]) == pytest.approx(0.05)

    assert "--mm" in cluster_cmd, "cluster cmd must have --mm flag"
    assert "-i" in cluster_cmd, "cluster cmd must specify input with -i"


# ---------------------------------------------------------------------------
# Test 5 — TFCE paired: assert correct randomise CLI args
# ---------------------------------------------------------------------------

def test_tfce_paired_cli(tmp_path):
    """TFCE method calls `randomise -1 -T -n <n_perms>` for paired contrast."""
    bids_root, group_df = _synthetic_xcpd_tree(tmp_path)
    participants_tsv = bids_root / "participants.tsv"
    group_df.to_csv(participants_tsv, sep="\t", index=False)
    out_dir = tmp_path / "out_tfce_paired"

    def fake_run(cmd, **kwargs):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = ""
        mock.stderr = ""
        return mock

    with patch("group_voxel_stats_xcpd.run_cmd", side_effect=fake_run) as mock_run:
        gvs.run_group_voxel_stats(
            bids_root=bids_root,
            pipeline="fc",
            measure="alff",
            contrast="ses-02_minus_ses-01",
            method="tfce",
            group_csv=participants_tsv,
            out_dir=out_dir,
            n_permutations=500,
        )

    randomise_calls = [
        call for call in mock_run.call_args_list
        if call.args and call.args[0][0] == "randomise"
    ]
    assert randomise_calls, "Expected at least one call to FSL `randomise`"
    rand_cmd = randomise_calls[0].args[0]

    assert "-1" in rand_cmd, "Paired t-test should use one-sample flag -1"
    assert "-T" in rand_cmd, "TFCE requires -T flag"
    assert "-n" in rand_cmd
    n_idx = rand_cmd.index("-n")
    assert int(rand_cmd[n_idx + 1]) == 500
    assert "-m" in rand_cmd, "randomise must have mask -m"


# ---------------------------------------------------------------------------
# Test 6 — TFCE two-sample: design matrix written with correct dimensions
# ---------------------------------------------------------------------------

def test_tfce_two_sample_cli(tmp_path):
    """TFCE two-sample writes design.mat with correct shape."""
    n = 6
    groups = ["Walking"] * 3 + ["Control"] * 3
    bids_root, group_df = _synthetic_xcpd_tree(
        tmp_path, n_subjects=n, group_labels=groups
    )
    participants_tsv = bids_root / "participants.tsv"
    group_df.to_csv(participants_tsv, sep="\t", index=False)
    out_dir = tmp_path / "out_tfce_group"

    def fake_run(cmd, **kwargs):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = ""
        mock.stderr = ""
        return mock

    with patch("group_voxel_stats_xcpd.run_cmd", side_effect=fake_run):
        gvs.run_group_voxel_stats(
            bids_root=bids_root,
            pipeline="fc",
            measure="alff",
            contrast="group-walking_minus_control",
            method="tfce",
            group_csv=participants_tsv,
            out_dir=out_dir,
            n_permutations=50,
        )

    design_mat = out_dir / "design.mat"
    assert design_mat.exists(), "design.mat must be written for two-sample TFCE"
    content = design_mat.read_text()
    # Check NumWaves and NumPoints
    assert "/NumWaves 2" in content, "Two-sample design has 2 waves"
    assert f"/NumPoints {n}" in content, f"Design must have {n} rows"

    design_con = out_dir / "design.con"
    assert design_con.exists(), "design.con must be written"


# ---------------------------------------------------------------------------
# Test 7 — Mask derivation
# ---------------------------------------------------------------------------

def test_mask_derivation(tmp_path):
    """derive_mask creates a valid boolean mask from a list of NIfTI paths."""
    paths = []
    for i in range(4):
        data = np.ones(SMALL_SHAPE, dtype=np.float32)
        data[0, 0, 0] = 0.0  # one voxel zero in all → excluded from mask
        p = tmp_path / f"map_{i}.nii.gz"
        _make_nifti(data, p)
        paths.append(p)

    mask_out = tmp_path / "mask.nii.gz"
    mask_data, mask_img = gvs.derive_mask(paths, mask_out)

    assert mask_out.exists()
    assert mask_data.shape == SMALL_SHAPE
    assert mask_data.dtype == bool
    total_vox = int(np.prod(SMALL_SHAPE))
    assert mask_data.sum() == total_vox - 1, "One zero voxel should be excluded"


# ---------------------------------------------------------------------------
# Test 8 — Output file completeness (FDR)
# ---------------------------------------------------------------------------

def test_output_files_fdr(tmp_path):
    """All required output files exist after a successful FDR run."""
    bids_root, group_df = _synthetic_xcpd_tree(tmp_path)
    participants_tsv = bids_root / "participants.tsv"
    group_df.to_csv(participants_tsv, sep="\t", index=False)
    out_dir = tmp_path / "out_complete"

    gvs.run_group_voxel_stats(
        bids_root=bids_root,
        pipeline="fc",
        measure="alff",
        contrast="ses-02_minus_ses-01",
        method="fdr",
        group_csv=participants_tsv,
        out_dir=out_dir,
    )

    required_files = [
        "tstat.nii.gz",
        "zstat.nii.gz",
        "pcorr.nii.gz",
        "cluster_table.tsv",
        "report.json",
        "report.html",
    ]
    for fname in required_files:
        assert (out_dir / fname).exists(), f"Missing output: {fname}"


# ---------------------------------------------------------------------------
# Test 9 — report.json contains expected fields
# ---------------------------------------------------------------------------

def test_report_json_fields(tmp_path):
    """report.json contains all provenance fields."""
    bids_root, group_df = _synthetic_xcpd_tree(tmp_path)
    participants_tsv = bids_root / "participants.tsv"
    group_df.to_csv(participants_tsv, sep="\t", index=False)
    out_dir = tmp_path / "out_report"

    gvs.run_group_voxel_stats(
        bids_root=bids_root,
        pipeline="fc",
        measure="alff",
        contrast="ses-02_minus_ses-01",
        method="fdr",
        group_csv=participants_tsv,
        out_dir=out_dir,
    )

    report = json.loads((out_dir / "report.json").read_text())
    for key in ("pipeline", "measure", "contrast", "method", "n_subjects", "timestamp"):
        assert key in report, f"report.json missing key: {key}"
    assert report["pipeline"] == "fc"
    assert report["measure"] == "alff"
    assert report["contrast"] == "ses-02_minus_ses-01"
    assert report["method"] == "fdr"
    assert report["n_subjects"] == N_SUBJECTS
