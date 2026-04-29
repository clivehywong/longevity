#!/usr/bin/env python3
"""
Voxel-level group statistics over XCP-D ALFF/ReHo/seed-to-voxel maps.

Inputs
------
* XCP-D ALFF/ReHo:
    derivatives/preprocessing/xcpd/{pipeline}/sub-XX/ses-YY/func/
    *_space-MNI152NLin6Asym_res-2_stat-{alff,reho}_boldmap.nii.gz
* Seed-to-voxel z-maps:
    derivatives/connectivity/{pipeline}/sub-XX/ses-YY/seed/<seed_id>/
    *_seed-to-voxel_zmap.nii.gz

Outputs (under --out directory)
--------------------------------
    tstat.nii.gz        t-statistic map
    zstat.nii.gz        z-statistic map
    pcorr.nii.gz        cluster/FDR/TFCE-corrected p-values
    cluster_table.tsv   cluster peak coordinates + anatomy
    report.json         metadata / provenance
    report.html         lightweight HTML overview with Papaya link

Supported --measure : alff | reho | seed-<seed_id>
Supported --contrast: ses-02_minus_ses-01 | group-walking_minus_control | correlation_<colname>
Supported --method  : grf | tfce | fdr

Usage example
-------------
    python script/group_voxel_stats_xcpd.py \\
        --bids-root /home/clivewong/proj/longevity \\
        --pipeline fc \\
        --measure alff \\
        --contrast ses-02_minus_ses-01 \\
        --method tfce --n-permutations 5000 \\
        --group-csv /home/clivewong/proj/longevity/group.csv \\
        --mask /home/clivewong/proj/longevity/atlases/MNI152NLin6Asym_res-2_brainmask.nii.gz \\
        --out derivatives/connectivity/group/voxel/fc/ses-02_minus_ses-01/alff/tfce/
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import nibabel as nib
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

# Allow imports from the neuconn_app utils package
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "neuconn_app"))

from utils.xcpd_outputs import XcpdDiscovery  # noqa: E402

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRF_Z_THRESH = 3.1
GRF_P_THRESH = 0.05
DEFAULT_N_PERMS = 5000
GROUP_MASK_PATH = (
    "derivatives/connectivity/group/masks/MNI152NLin6Asym_res-2_brainmask.nii.gz"
)


# ---------------------------------------------------------------------------
# Subprocess helper (single point of contact for FSL calls → easy to mock)
# ---------------------------------------------------------------------------

def run_cmd(cmd: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    """Thin wrapper around subprocess.run. Mocked in tests."""
    logger.debug("CMD: %s", " ".join(str(c) for c in cmd))
    return subprocess.run(
        [str(c) for c in cmd],
        check=True,
        capture_output=True,
        text=True,
        **kwargs,
    )


def _fsl_available() -> bool:
    return shutil.which("randomise") is not None or shutil.which("cluster") is not None


# ---------------------------------------------------------------------------
# Map discovery helpers
# ---------------------------------------------------------------------------

def _get_xcpd_map(
    discovery: XcpdDiscovery,
    subject: str,
    session: str,
    pipeline: str,
    measure: str,
) -> Optional[Path]:
    """Return the ALFF or ReHo map path for one (subject, session), or None."""
    outputs = discovery.get(subject, session, pipeline)
    if measure == "alff":
        return outputs.alff_map
    if measure == "reho":
        return outputs.reho_map
    raise ValueError(f"Unknown local measure '{measure}'. Use alff or reho.")


def _get_seed_map(
    bids_root: Path,
    pipeline: str,
    subject: str,
    session: str,
    seed_id: str,
) -> Optional[Path]:
    """Return seed-to-voxel zmap for one (subject, session, seed_id), or None."""
    seed_dir = (
        bids_root
        / "derivatives"
        / "connectivity"
        / pipeline
        / subject
        / session
        / "seed"
        / seed_id
    )
    if not seed_dir.exists():
        return None
    matches = sorted(seed_dir.glob("*_seed-to-voxel_zmap.nii.gz"))
    return matches[0] if matches else None


def _get_map(
    bids_root: Path,
    discovery: XcpdDiscovery,
    subject: str,
    session: str,
    pipeline: str,
    measure: str,
) -> Optional[Path]:
    if measure.startswith("seed-"):
        seed_id = measure[len("seed-"):]
        return _get_seed_map(bids_root, pipeline, subject, session, seed_id)
    return _get_xcpd_map(discovery, subject, session, pipeline, measure)


# ---------------------------------------------------------------------------
# Data collection per contrast type
# ---------------------------------------------------------------------------

def collect_paired_data(
    bids_root: Path,
    discovery: XcpdDiscovery,
    group_df: pd.DataFrame,
    pipeline: str,
    measure: str,
    ses1: str = "ses-01",
    ses2: str = "ses-02",
) -> List[Tuple[str, Path, Path]]:
    """Return [(subject, ses1_path, ses2_path)] for subjects with both sessions."""
    records: List[Tuple[str, Path, Path]] = []
    for sub in group_df["subject_id"]:
        p1 = _get_map(bids_root, discovery, sub, ses1, pipeline, measure)
        p2 = _get_map(bids_root, discovery, sub, ses2, pipeline, measure)
        if p1 is not None and p2 is not None:
            records.append((sub, p1, p2))
        else:
            missing = [s for s, p in [(ses1, p1), (ses2, p2)] if p is None]
            logger.debug("%s: missing sessions %s for %s — skipped", sub, missing, measure)
    logger.info("Paired data: %d subjects with both %s and %s", len(records), ses1, ses2)
    return records


def collect_group_data(
    bids_root: Path,
    discovery: XcpdDiscovery,
    group_df: pd.DataFrame,
    pipeline: str,
    measure: str,
    sessions: Sequence[str] = ("ses-01", "ses-02"),
) -> List[Tuple[str, str, List[Path]]]:
    """Return [(subject, group, [paths])] averaging across available sessions."""
    records: List[Tuple[str, str, List[Path]]] = []
    for _, row in group_df.iterrows():
        sub = row["subject_id"]
        grp = row["group"]
        paths = [
            p
            for ses in sessions
            for p in [_get_map(bids_root, discovery, sub, ses, pipeline, measure)]
            if p is not None
        ]
        if paths:
            records.append((sub, grp, paths))
        else:
            logger.debug("%s: no maps found for %s — skipped", sub, measure)
    logger.info("Group data: %d subjects with ≥1 map", len(records))
    return records


# ---------------------------------------------------------------------------
# Mask handling
# ---------------------------------------------------------------------------

def load_masked_map(map_path: Path, mask_data: np.ndarray) -> np.ndarray:
    """Load NIfTI, apply boolean mask, return 1-D array of within-mask voxels."""
    img = nib.load(str(map_path))
    data = np.asarray(img.get_fdata(), dtype=np.float32)
    return data[mask_data]


def average_masked_maps(paths: List[Path], mask_data: np.ndarray) -> np.ndarray:
    """Load and average across sessions for one subject."""
    arrays = [load_masked_map(p, mask_data) for p in paths]
    return np.mean(arrays, axis=0)


def derive_mask(
    map_paths: List[Path],
    out_path: Path,
    n_subjects_for_mask: int = 10,
) -> Tuple[np.ndarray, nib.Nifti1Image]:
    """
    Build a group brain mask from the first N maps.

    Strategy: voxels that are non-zero and finite in ALL considered maps.
    """
    logger.info("Deriving group mask from up to %d maps…", n_subjects_for_mask)
    ref_img: Optional[nib.Nifti1Image] = None
    mask: Optional[np.ndarray] = None

    for p in map_paths[:n_subjects_for_mask]:
        img = nib.load(str(p))
        data = np.asarray(img.get_fdata(), dtype=np.float32)
        valid = np.isfinite(data) & (data != 0)
        if mask is None:
            mask = valid
            ref_img = img
        else:
            mask = mask & valid

    if mask is None or ref_img is None:
        raise RuntimeError("No maps available to derive brain mask.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    mask_img = nib.Nifti1Image(
        mask.astype(np.uint8), ref_img.affine, ref_img.header
    )
    nib.save(mask_img, str(out_path))
    logger.info("Mask saved to %s  (%d voxels)", out_path, mask.sum())
    return mask, mask_img


def load_or_derive_mask(
    bids_root: Path,
    mask_arg: Optional[Path],
    map_paths: List[Path],
) -> Tuple[np.ndarray, nib.Nifti1Image]:
    """Return (boolean mask array, mask NIfTI).

    If *mask_arg* exists on disk, load it. Otherwise derive from map_paths and
    cache it under GROUP_MASK_PATH relative to bids_root.
    """
    if mask_arg is not None and Path(mask_arg).exists():
        img = nib.load(str(mask_arg))
        mask_data = np.asarray(img.get_fdata(), dtype=bool)
        logger.info("Loaded mask from %s  (%d voxels)", mask_arg, mask_data.sum())
        return mask_data, img

    cached_path = bids_root / GROUP_MASK_PATH
    if cached_path.exists():
        img = nib.load(str(cached_path))
        mask_data = np.asarray(img.get_fdata(), dtype=bool)
        logger.info("Loaded cached mask  (%d voxels)", mask_data.sum())
        return mask_data, img

    mask_data, mask_img = derive_mask(map_paths, cached_path)
    return mask_data, mask_img


# ---------------------------------------------------------------------------
# Statistical conversion helpers
# ---------------------------------------------------------------------------

def t_to_z(t_stat: np.ndarray, df: float) -> np.ndarray:
    """Convert t-statistic to z-score preserving sign, clipped to ±8."""
    cdf = scipy_stats.t.cdf(t_stat, df=df)
    cdf = np.clip(cdf, 1e-15, 1 - 1e-15)
    z = scipy_stats.norm.ppf(cdf)
    return np.clip(z, -8.0, 8.0)


def bh_correction(p_values: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg FDR correction (scipy >= 1.8)."""
    from scipy.stats import false_discovery_control
    return false_discovery_control(p_values, method="bh")


# ---------------------------------------------------------------------------
# FSL design matrix helpers
# ---------------------------------------------------------------------------

def _write_fsl_vest(matrix: np.ndarray, path: Path) -> None:
    """Write a 2-D array as an FSL VEST-format .mat/.con file."""
    n_rows, n_cols = matrix.shape
    lines = [
        f"/NumWaves {n_cols}",
        f"/NumPoints {n_rows}",
        "/Matrix",
    ]
    for row in matrix:
        lines.append("\t".join(f"{v:.6f}" for v in row))
    path.write_text("\n".join(lines) + "\n")


def _build_one_sample_design(n: int, out_dir: Path) -> Tuple[Path, Path]:
    """One-sample t-test against 0 (for paired/difference maps)."""
    design_mat = np.ones((n, 1))
    contrast_mat = np.array([[1.0]])
    mat_path = out_dir / "design.mat"
    con_path = out_dir / "design.con"
    _write_fsl_vest(design_mat, mat_path)
    _write_fsl_vest(contrast_mat, con_path)
    return mat_path, con_path


def _build_two_sample_design(
    n1: int, n2: int, out_dir: Path
) -> Tuple[Path, Path]:
    """Two-sample t-test (group1 > group2)."""
    design_mat = np.zeros((n1 + n2, 2))
    design_mat[:n1, 0] = 1
    design_mat[n1:, 1] = 1
    contrast_mat = np.array([[1.0, -1.0]])
    mat_path = out_dir / "design.mat"
    con_path = out_dir / "design.con"
    _write_fsl_vest(design_mat, mat_path)
    _write_fsl_vest(contrast_mat, con_path)
    return mat_path, con_path


# ---------------------------------------------------------------------------
# Unmask helper
# ---------------------------------------------------------------------------

def unmask_data(
    voxel_data: np.ndarray,
    mask_data: np.ndarray,
    ref_img: nib.Nifti1Image,
    fill: float = 0.0,
) -> nib.Nifti1Image:
    """Put masked 1-D data back into brain-shaped volume."""
    vol = np.full(mask_data.shape, fill, dtype=np.float32)
    vol[mask_data] = voxel_data
    return nib.Nifti1Image(vol, ref_img.affine, ref_img.header)


def save_nifti(img: nib.Nifti1Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(img, str(path))
    logger.debug("Saved %s", path)


# ---------------------------------------------------------------------------
# FDR method (fully parametric, no FSL needed)
# ---------------------------------------------------------------------------

def run_fdr(
    contrast: str,
    group_df: pd.DataFrame,
    paired_data: Optional[List[Tuple[str, Path, Path]]],
    group_data: Optional[List[Tuple[str, str, List[Path]]]],
    mask_data: np.ndarray,
    ref_img: nib.Nifti1Image,
    out_dir: Path,
    bids_root: Path,
    discovery: XcpdDiscovery,
    pipeline: str,
    measure: str,
) -> Dict:
    """Compute FDR-corrected voxelwise stats."""
    logger.info("Running FDR analysis…")
    out_dir.mkdir(parents=True, exist_ok=True)

    if contrast == "ses-02_minus_ses-01":
        assert paired_data is not None
        ses1_maps = np.stack([load_masked_map(p1, mask_data) for _, p1, _ in paired_data])
        ses2_maps = np.stack([load_masked_map(p2, mask_data) for _, _, p2 in paired_data])
        diff = ses2_maps - ses1_maps
        t_stat, p_val = scipy_stats.ttest_1samp(diff, 0, axis=0)
        df = len(paired_data) - 1
        n_subjects = len(paired_data)

    elif contrast == "group-walking_minus_control":
        assert group_data is not None
        walk_maps = np.stack(
            [average_masked_maps(paths, mask_data) for _, grp, paths in group_data if grp == "Walking"]
        )
        ctrl_maps = np.stack(
            [average_masked_maps(paths, mask_data) for _, grp, paths in group_data if grp == "Control"]
        )
        t_stat, p_val = scipy_stats.ttest_ind(walk_maps, ctrl_maps, axis=0, equal_var=False)
        n1, n2 = len(walk_maps), len(ctrl_maps)
        df = min(n1 - 1, n2 - 1)
        n_subjects = n1 + n2
        logger.info("Walking n=%d, Control n=%d", n1, n2)

    elif contrast.startswith("correlation_"):
        colname = contrast[len("correlation_"):]
        assert group_data is not None
        if colname not in group_df.columns:
            raise ValueError(f"Column '{colname}' not found in group CSV.")
        sub_col = group_df.set_index("subject_id")[colname]
        col_vals, all_maps = [], []
        for sub, _, paths in group_data:
            if sub in sub_col.index and pd.notna(sub_col[sub]):
                col_vals.append(float(sub_col[sub]))
                all_maps.append(average_masked_maps(paths, mask_data))
        if len(col_vals) < 3:
            raise RuntimeError("Too few subjects with valid covariate values.")
        col_arr = np.array(col_vals)
        maps_mat = np.stack(all_maps)  # (N, V)
        N = len(col_arr)
        col_z = (col_arr - col_arr.mean()) / (col_arr.std(ddof=1) + 1e-12)
        maps_mean = maps_mat.mean(axis=0)
        maps_std = maps_mat.std(axis=0, ddof=1)
        maps_z = (maps_mat - maps_mean) / (maps_std + 1e-12)
        r = (col_z @ maps_z) / (N - 1)
        df = N - 2
        t_stat = r * np.sqrt(df) / np.sqrt(np.clip(1 - r**2, 1e-12, None))
        p_val = 2 * scipy_stats.t.sf(np.abs(t_stat), df=df)
        n_subjects = N

    else:
        raise ValueError(f"Unknown contrast: {contrast}")

    # BH FDR correction
    finite_mask = np.isfinite(p_val)
    pcorr = np.ones_like(p_val)
    if finite_mask.any():
        pcorr[finite_mask] = bh_correction(p_val[finite_mask])

    z_stat = t_to_z(t_stat, df)

    # Save maps
    save_nifti(unmask_data(t_stat, mask_data, ref_img), out_dir / "tstat.nii.gz")
    save_nifti(unmask_data(z_stat, mask_data, ref_img), out_dir / "zstat.nii.gz")
    save_nifti(unmask_data(pcorr, mask_data, ref_img), out_dir / "pcorr.nii.gz")

    # Simple cluster table from surviving voxels (q < 0.05)
    cluster_table = _make_simple_cluster_table(z_stat, pcorr, mask_data, ref_img, thresh=0.05)
    cluster_table.to_csv(out_dir / "cluster_table.tsv", sep="\t", index=False)

    logger.info("FDR done. %d voxels q<0.05.", (pcorr < 0.05).sum())
    return {"n_subjects": n_subjects, "df": df, "n_sig_voxels": int((pcorr < 0.05).sum())}


# ---------------------------------------------------------------------------
# GRF method (parametric t → z, then FSL cluster)
# ---------------------------------------------------------------------------

def run_grf(
    contrast: str,
    group_df: pd.DataFrame,
    paired_data: Optional[List[Tuple[str, Path, Path]]],
    group_data: Optional[List[Tuple[str, str, List[Path]]]],
    mask_data: np.ndarray,
    ref_img: nib.Nifti1Image,
    out_dir: Path,
    bids_root: Path,
    discovery: XcpdDiscovery,
    pipeline: str,
    measure: str,
    z_thresh: float = GRF_Z_THRESH,
    p_thresh: float = GRF_P_THRESH,
) -> Dict:
    """GRF correction via parametric t → z, then FSL cluster."""
    logger.info("Running GRF analysis (FSL cluster)…")
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Reuse FDR stats computation for the parametric t/z maps ---
    if contrast == "ses-02_minus_ses-01":
        assert paired_data is not None
        ses1_maps = np.stack([load_masked_map(p1, mask_data) for _, p1, _ in paired_data])
        ses2_maps = np.stack([load_masked_map(p2, mask_data) for _, _, p2 in paired_data])
        diff = ses2_maps - ses1_maps
        t_stat, _ = scipy_stats.ttest_1samp(diff, 0, axis=0)
        df = len(paired_data) - 1
        n_subjects = len(paired_data)

    elif contrast == "group-walking_minus_control":
        assert group_data is not None
        walk_maps = np.stack(
            [average_masked_maps(paths, mask_data) for _, grp, paths in group_data if grp == "Walking"]
        )
        ctrl_maps = np.stack(
            [average_masked_maps(paths, mask_data) for _, grp, paths in group_data if grp == "Control"]
        )
        t_stat, _ = scipy_stats.ttest_ind(walk_maps, ctrl_maps, axis=0, equal_var=False)
        n1, n2 = len(walk_maps), len(ctrl_maps)
        df = min(n1 - 1, n2 - 1)
        n_subjects = n1 + n2

    elif contrast.startswith("correlation_"):
        colname = contrast[len("correlation_"):]
        assert group_data is not None
        if colname not in group_df.columns:
            raise ValueError(f"Column '{colname}' not found in group CSV.")
        sub_col = group_df.set_index("subject_id")[colname]
        col_vals, all_maps = [], []
        for sub, _, paths in group_data:
            if sub in sub_col.index and pd.notna(sub_col[sub]):
                col_vals.append(float(sub_col[sub]))
                all_maps.append(average_masked_maps(paths, mask_data))
        col_arr = np.array(col_vals)
        maps_mat = np.stack(all_maps)
        N = len(col_arr)
        col_z = (col_arr - col_arr.mean()) / (col_arr.std(ddof=1) + 1e-12)
        maps_mean = maps_mat.mean(axis=0)
        maps_std = maps_mat.std(axis=0, ddof=1)
        maps_z = (maps_mat - maps_mean) / (maps_std + 1e-12)
        r = (col_z @ maps_z) / (N - 1)
        df = N - 2
        t_stat = r * np.sqrt(df) / np.sqrt(np.clip(1 - r**2, 1e-12, None))
        n_subjects = N
    else:
        raise ValueError(f"Unknown contrast: {contrast}")

    z_stat = t_to_z(t_stat, df)

    # Save maps for FSL
    tstat_img = unmask_data(t_stat, mask_data, ref_img)
    zstat_img = unmask_data(z_stat, mask_data, ref_img)
    zstat_path = out_dir / "zstat.nii.gz"
    save_nifti(tstat_img, out_dir / "tstat.nii.gz")
    save_nifti(zstat_img, zstat_path)

    # FSL cluster for GRF correction
    cluster_index_path = out_dir / "cluster_index.nii.gz"
    cluster_size_path = out_dir / "cluster_size.nii.gz"
    cluster_thresh_path = out_dir / "cluster_thresh.nii.gz"

    cluster_cmd = [
        "cluster",
        "-i", zstat_path,
        "-t", str(z_thresh),
        "-p", str(p_thresh),
        "--mm",
        "-o", cluster_index_path,
        "--osize", cluster_size_path,
        "--othresh", cluster_thresh_path,
    ]
    logger.info("FSL cluster: %s", " ".join(str(c) for c in cluster_cmd))
    result = run_cmd(cluster_cmd)

    # Parse FSL cluster stdout → TSV
    cluster_table = _parse_fsl_cluster_stdout(result.stdout)
    cluster_table.to_csv(out_dir / "cluster_table.tsv", sep="\t", index=False)

    # Build pcorr map: assign each voxel its cluster's p-value; 1.0 for sub-threshold
    pcorr_vol = np.ones(mask_data.shape, dtype=np.float32)
    if cluster_index_path.exists():
        idx_img = nib.load(str(cluster_index_path))
        idx_data = np.asarray(idx_img.get_fdata(), dtype=int)
        if not cluster_table.empty and "P" in cluster_table.columns:
            for _, row in cluster_table.iterrows():
                cid = int(row["Cluster Index"])
                pcorr_vol[idx_data == cid] = float(row["P"])
    pcorr_img = nib.Nifti1Image(pcorr_vol, ref_img.affine, ref_img.header)
    save_nifti(pcorr_img, out_dir / "pcorr.nii.gz")

    n_clusters = len(cluster_table)
    logger.info("GRF done. %d significant clusters.", n_clusters)
    return {"n_subjects": n_subjects, "df": df, "n_clusters": n_clusters, "z_thresh": z_thresh}


# ---------------------------------------------------------------------------
# TFCE method (FSL randomise -T)
# ---------------------------------------------------------------------------

def run_tfce(
    contrast: str,
    group_df: pd.DataFrame,
    paired_data: Optional[List[Tuple[str, Path, Path]]],
    group_data: Optional[List[Tuple[str, str, List[Path]]]],
    mask_data: np.ndarray,
    mask_img: nib.Nifti1Image,
    ref_img: nib.Nifti1Image,
    out_dir: Path,
    bids_root: Path,
    discovery: XcpdDiscovery,
    pipeline: str,
    measure: str,
    n_permutations: int = DEFAULT_N_PERMS,
) -> Dict:
    """TFCE via FSL randomise -T."""
    logger.info("Running TFCE analysis (FSL randomise -T, n=%d)…", n_permutations)
    out_dir.mkdir(parents=True, exist_ok=True)

    mask_path = out_dir / "mask.nii.gz"
    save_nifti(mask_img, mask_path)

    if contrast == "ses-02_minus_ses-01":
        assert paired_data is not None
        ses1_maps = np.stack([load_masked_map(p1, mask_data) for _, p1, _ in paired_data])
        ses2_maps = np.stack([load_masked_map(p2, mask_data) for _, _, p2 in paired_data])
        diff = ses2_maps - ses1_maps  # (N, V)
        n = len(paired_data)
        # Build 4D diff volume
        diff_4d = np.stack([
            unmask_data(diff[i], mask_data, ref_img).get_fdata()
            for i in range(n)
        ], axis=-1)
        input_img = nib.Nifti1Image(diff_4d.astype(np.float32), ref_img.affine)
        input_path = out_dir / "diff_4d.nii.gz"
        save_nifti(input_img, input_path)
        # One-sample t: use -1 flag
        randomise_cmd = [
            "randomise",
            "-i", input_path,
            "-o", out_dir / "tfce",
            "-m", mask_path,
            "-1",  # one-sample t-test
            "-T",
            "-n", str(n_permutations),
        ]
        n_subjects = n

    elif contrast == "group-walking_minus_control":
        assert group_data is not None
        walk_recs = [(s, ps) for s, g, ps in group_data if g == "Walking"]
        ctrl_recs = [(s, ps) for s, g, ps in group_data if g == "Control"]
        walk_maps = np.stack([average_masked_maps(ps, mask_data) for _, ps in walk_recs])
        ctrl_maps = np.stack([average_masked_maps(ps, mask_data) for _, ps in ctrl_recs])
        n1, n2 = len(walk_maps), len(ctrl_maps)
        all_maps = np.concatenate([walk_maps, ctrl_maps], axis=0)  # (N1+N2, V)
        all_4d = np.stack([
            unmask_data(all_maps[i], mask_data, ref_img).get_fdata()
            for i in range(n1 + n2)
        ], axis=-1)
        input_img = nib.Nifti1Image(all_4d.astype(np.float32), ref_img.affine)
        input_path = out_dir / "group_4d.nii.gz"
        save_nifti(input_img, input_path)
        mat_path, con_path = _build_two_sample_design(n1, n2, out_dir)
        randomise_cmd = [
            "randomise",
            "-i", input_path,
            "-o", out_dir / "tfce",
            "-m", mask_path,
            "-d", mat_path,
            "-t", con_path,
            "-T",
            "-n", str(n_permutations),
        ]
        n_subjects = n1 + n2
        logger.info("Walking n=%d, Control n=%d", n1, n2)

    elif contrast.startswith("correlation_"):
        colname = contrast[len("correlation_"):]
        assert group_data is not None
        if colname not in group_df.columns:
            raise ValueError(f"Column '{colname}' not found in group CSV.")
        sub_col = group_df.set_index("subject_id")[colname]
        col_vals, all_maps = [], []
        for sub, _, paths in group_data:
            if sub in sub_col.index and pd.notna(sub_col[sub]):
                col_vals.append(float(sub_col[sub]))
                all_maps.append(average_masked_maps(paths, mask_data))
        if len(col_vals) < 3:
            raise RuntimeError("Too few subjects with valid covariate values.")
        N = len(col_vals)
        maps_mat = np.stack(all_maps)  # (N, V)
        all_4d = np.stack([
            unmask_data(maps_mat[i], mask_data, ref_img).get_fdata()
            for i in range(N)
        ], axis=-1)
        input_img = nib.Nifti1Image(all_4d.astype(np.float32), ref_img.affine)
        input_path = out_dir / "corr_4d.nii.gz"
        save_nifti(input_img, input_path)
        # Demean covariate and use as regressor
        col_arr = np.array(col_vals, dtype=np.float64)
        col_arr -= col_arr.mean()
        design_mat = np.column_stack([col_arr, np.ones(N)])
        contrast_mat = np.array([[1.0, 0.0]])
        mat_path = out_dir / "design.mat"
        con_path = out_dir / "design.con"
        _write_fsl_vest(design_mat, mat_path)
        _write_fsl_vest(contrast_mat, con_path)
        randomise_cmd = [
            "randomise",
            "-i", input_path,
            "-o", out_dir / "tfce",
            "-m", mask_path,
            "-d", mat_path,
            "-t", con_path,
            "-T",
            "-n", str(n_permutations),
        ]
        n_subjects = N
    else:
        raise ValueError(f"Unknown contrast: {contrast}")

    logger.info("FSL randomise: %s", " ".join(str(c) for c in randomise_cmd))
    run_cmd(randomise_cmd)

    # Collect randomise outputs
    tfce_prefix = out_dir / "tfce"
    tstat_path = Path(str(tfce_prefix) + "_tstat1.nii.gz")
    corrp_path = Path(str(tfce_prefix) + "_tfce_corrp_tstat1.nii.gz")

    # Symlink or copy as canonical names if they exist
    for src, dst_name in [(tstat_path, "tstat.nii.gz"), (corrp_path, "corrp_raw.nii.gz")]:
        if src.exists():
            dst = out_dir / dst_name
            if not dst.exists():
                shutil.copy2(str(src), str(dst))

    # 1 - corrp → pcorr (randomise outputs 1-p as corrected p-value image)
    if corrp_path.exists():
        corrp_img = nib.load(str(corrp_path))
        pcorr_data = 1.0 - corrp_img.get_fdata().astype(np.float32)
        save_nifti(
            nib.Nifti1Image(pcorr_data, corrp_img.affine, corrp_img.header),
            out_dir / "pcorr.nii.gz",
        )

    if tstat_path.exists():
        tstat_img = nib.load(str(tstat_path))
        tdata = np.asarray(tstat_img.get_fdata(), dtype=np.float32)
        df_approx = n_subjects - 2
        zdata = t_to_z(tdata.ravel(), df_approx).reshape(tdata.shape)
        save_nifti(
            nib.Nifti1Image(zdata, tstat_img.affine, tstat_img.header),
            out_dir / "zstat.nii.gz",
        )

    # Minimal cluster table placeholder (proper labelling done by label_clusters script)
    pd.DataFrame(columns=["Cluster Index", "Voxels", "P", "Z-MAX",
                           "Z-MAX X (mm)", "Z-MAX Y (mm)", "Z-MAX Z (mm)"]).to_csv(
        out_dir / "cluster_table.tsv", sep="\t", index=False
    )

    logger.info("TFCE done.")
    return {"n_subjects": n_subjects, "n_permutations": n_permutations}


# ---------------------------------------------------------------------------
# Cluster table helpers
# ---------------------------------------------------------------------------

def _parse_fsl_cluster_stdout(stdout: str) -> pd.DataFrame:
    """Parse FSL cluster command tab-separated stdout into a DataFrame."""
    lines = [l for l in stdout.strip().splitlines() if l.strip()]
    if not lines:
        return pd.DataFrame()
    header = lines[0].split("\t")
    rows = [l.split("\t") for l in lines[1:] if l.strip()]
    if not rows:
        return pd.DataFrame(columns=header)
    df = pd.DataFrame(rows, columns=header)
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col])
        except (ValueError, TypeError):
            pass
    return df


def _make_simple_cluster_table(
    z_stat: np.ndarray,
    pcorr: np.ndarray,
    mask_data: np.ndarray,
    ref_img: nib.Nifti1Image,
    thresh: float = 0.05,
) -> pd.DataFrame:
    """Produce a minimal cluster table from surviving voxels (no FSL needed)."""
    from scipy.ndimage import label as ndlabel

    sig = np.zeros(mask_data.shape, dtype=np.float32)
    sig[mask_data] = np.where(pcorr < thresh, z_stat, 0.0)
    labeled, n_clusters = ndlabel(sig != 0)

    affine = ref_img.affine
    records = []
    for cid in range(1, n_clusters + 1):
        vox_idx = np.argwhere(labeled == cid)
        z_vals = sig[vox_idx[:, 0], vox_idx[:, 1], vox_idx[:, 2]]
        peak_vox = vox_idx[np.argmax(np.abs(z_vals))]
        peak_mm = nib.affines.apply_affine(affine, peak_vox)
        records.append({
            "Cluster Index": cid,
            "Voxels": len(vox_idx),
            "Z-MAX": float(z_vals[np.argmax(np.abs(z_vals))]),
            "Z-MAX X (mm)": float(peak_mm[0]),
            "Z-MAX Y (mm)": float(peak_mm[1]),
            "Z-MAX Z (mm)": float(peak_mm[2]),
        })
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def save_report_json(out_dir: Path, data: Dict) -> None:
    (out_dir / "report.json").write_text(json.dumps(data, indent=2))


def save_report_html(out_dir: Path, data: Dict) -> None:
    zstat_path = out_dir / "zstat.nii.gz"
    papaya_link = str(zstat_path) if zstat_path.exists() else "N/A"
    cluster_rows = ""
    cluster_tsv = out_dir / "cluster_table.tsv"
    if cluster_tsv.exists() and cluster_tsv.stat().st_size > 0:
        try:
            ct = pd.read_csv(cluster_tsv, sep="\t")
            if not ct.empty:
                cluster_rows = ct.to_html(index=False, border=1)
        except Exception:
            pass

    html = textwrap.dedent(f"""\
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="UTF-8">
          <title>Group Voxel Stats — {data.get('measure','')} {data.get('contrast','')} {data.get('method','')}</title>
          <style>
            body {{ font-family: Arial, sans-serif; margin: 2em; }}
            table {{ border-collapse: collapse; font-size: 0.9em; }}
            th, td {{ border: 1px solid #aaa; padding: 4px 8px; }}
            th {{ background: #dde; }}
            pre {{ background: #f4f4f4; padding: 1em; border-radius: 4px; }}
          </style>
        </head>
        <body>
          <h1>Group Voxel Statistics Report</h1>
          <h2>Parameters</h2>
          <pre>{json.dumps(data, indent=2)}</pre>
          <h2>Papaya Viewer</h2>
          <p>z-stat map: <code>{papaya_link}</code></p>
          <h2>Cluster Table</h2>
          {cluster_rows if cluster_rows else '<p>No significant clusters.</p>'}
        </body>
        </html>
    """)
    (out_dir / "report.html").write_text(html)


# ---------------------------------------------------------------------------
# Label clusters (optional, wraps label_clusters_with_fsl_atlasq.py)
# ---------------------------------------------------------------------------

def label_clusters(out_dir: Path, script_dir: Path) -> None:
    """Annotate cluster_table.tsv with anatomical labels (best-effort)."""
    cluster_tsv = out_dir / "cluster_table.tsv"
    labeller = script_dir / "label_clusters_with_fsl_atlasq.py"
    if not cluster_tsv.exists() or cluster_tsv.stat().st_size < 10:
        return
    if not labeller.exists():
        logger.debug("label_clusters_with_fsl_atlasq.py not found; skipping labelling.")
        return
    annotated = out_dir / "cluster_table_annotated.tsv"
    try:
        run_cmd(
            [sys.executable, str(labeller),
             "--cluster-table", str(cluster_tsv),
             "--output", str(annotated)],
        )
        shutil.copy2(str(annotated), str(cluster_tsv))
        logger.info("Cluster table annotated with anatomy.")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.warning("Cluster labelling failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run_group_voxel_stats(
    bids_root: Path,
    pipeline: str,
    measure: str,
    contrast: str,
    method: str,
    group_csv: Path,
    out_dir: Path,
    mask_path: Optional[Path] = None,
    n_permutations: int = DEFAULT_N_PERMS,
    z_thresh: float = GRF_Z_THRESH,
    p_thresh: float = GRF_P_THRESH,
    sessions: Tuple[str, str] = ("ses-01", "ses-02"),
) -> Path:
    """
    Full pipeline: collect maps → mask → stats → outputs.

    Returns *out_dir*.
    """
    out_dir = Path(out_dir)
    bids_root = Path(bids_root)

    group_df = pd.read_csv(group_csv)
    required_cols = {"subject_id", "group"}
    if not required_cols.issubset(group_df.columns):
        raise ValueError(f"group CSV must contain columns: {required_cols}")

    discovery = XcpdDiscovery(bids_root, pipeline=pipeline)

    # ------------------------------------------------------------------
    # Collect maps
    # ------------------------------------------------------------------
    ses1, ses2 = sessions
    paired_data: Optional[List[Tuple[str, Path, Path]]] = None
    group_data: Optional[List[Tuple[str, str, List[Path]]]] = None
    all_map_paths: List[Path] = []

    if contrast == "ses-02_minus_ses-01":
        paired_data = collect_paired_data(bids_root, discovery, group_df, pipeline, measure, ses1, ses2)
        if not paired_data:
            raise RuntimeError(f"No subjects with both {ses1} and {ses2} maps for {measure}.")
        all_map_paths = [p for _, p1, p2 in paired_data for p in (p1, p2)]
    else:
        group_data = collect_group_data(bids_root, discovery, group_df, pipeline, measure, sessions)
        if not group_data:
            raise RuntimeError(f"No subjects with any map found for {measure}.")
        all_map_paths = [p for _, _, paths in group_data for p in paths]

    # ------------------------------------------------------------------
    # Mask
    # ------------------------------------------------------------------
    mask_data, mask_img = load_or_derive_mask(bids_root, mask_path, all_map_paths)
    ref_img = nib.load(str(all_map_paths[0]))

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------
    if method == "fdr":
        stats_meta = run_fdr(
            contrast, group_df, paired_data, group_data,
            mask_data, ref_img, out_dir,
            bids_root, discovery, pipeline, measure,
        )
    elif method == "grf":
        if not _fsl_available():
            logger.warning("FSL not found — GRF will attempt to run but may fail.")
        stats_meta = run_grf(
            contrast, group_df, paired_data, group_data,
            mask_data, ref_img, out_dir,
            bids_root, discovery, pipeline, measure,
            z_thresh=z_thresh, p_thresh=p_thresh,
        )
    elif method == "tfce":
        if not _fsl_available():
            logger.warning("FSL not found — TFCE will attempt to run but may fail.")
        stats_meta = run_tfce(
            contrast, group_df, paired_data, group_data,
            mask_data, mask_img, ref_img, out_dir,
            bids_root, discovery, pipeline, measure,
            n_permutations=n_permutations,
        )
    else:
        raise ValueError(f"Unknown method '{method}'. Choose: grf, tfce, fdr.")

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------
    report_data = {
        "bids_root": str(bids_root),
        "pipeline": pipeline,
        "measure": measure,
        "contrast": contrast,
        "method": method,
        "n_permutations": n_permutations if method in ("grf", "tfce") else None,
        "z_thresh": z_thresh if method == "grf" else None,
        "p_thresh": p_thresh if method == "grf" else None,
        "out_dir": str(out_dir),
        "timestamp": datetime.utcnow().isoformat(),
        **stats_meta,
    }
    save_report_json(out_dir, report_data)
    save_report_html(out_dir, report_data)

    # ------------------------------------------------------------------
    # Annotate clusters (best-effort)
    # ------------------------------------------------------------------
    script_dir = Path(__file__).resolve().parent
    label_clusters(out_dir, script_dir)

    logger.info("All outputs written to %s", out_dir)
    return out_dir


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--bids-root", required=True, type=Path,
                        help="Root of the BIDS project.")
    parser.add_argument("--pipeline", required=True,
                        choices=["fc", "fc_gsr", "ec"],
                        help="XCP-D pipeline name.")
    parser.add_argument("--measure", required=True,
                        help="alff | reho | seed-<seed_id>")
    parser.add_argument("--contrast", required=True,
                        help="ses-02_minus_ses-01 | group-walking_minus_control | correlation_<col>")
    parser.add_argument("--method", required=True,
                        choices=["grf", "tfce", "fdr"],
                        help="Correction method.")
    parser.add_argument("--group-csv", required=True, type=Path,
                        help="CSV with subject_id, group columns.")
    parser.add_argument("--out", required=True, type=Path,
                        help="Output directory.")
    parser.add_argument("--mask", type=Path, default=None,
                        help="Brain mask NIfTI (MNI152NLin6Asym res-2). "
                             "Auto-derived from maps if not supplied.")
    parser.add_argument("--n-permutations", type=int, default=DEFAULT_N_PERMS,
                        help=f"Number of permutations for TFCE/GRF (default: {DEFAULT_N_PERMS}).")
    parser.add_argument("--z-thresh", type=float, default=GRF_Z_THRESH,
                        help=f"Cluster-forming z threshold for GRF (default: {GRF_Z_THRESH}).")
    parser.add_argument("--p-thresh", type=float, default=GRF_P_THRESH,
                        help=f"Cluster p threshold for GRF (default: {GRF_P_THRESH}).")
    parser.add_argument("--ses1", default="ses-01",
                        help="First session label (default: ses-01).")
    parser.add_argument("--ses2", default="ses-02",
                        help="Second session label (default: ses-02).")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = _parse_args(argv)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    run_group_voxel_stats(
        bids_root=args.bids_root,
        pipeline=args.pipeline,
        measure=args.measure,
        contrast=args.contrast,
        method=args.method,
        group_csv=args.group_csv,
        out_dir=args.out,
        mask_path=args.mask,
        n_permutations=args.n_permutations,
        z_thresh=args.z_thresh,
        p_thresh=args.p_thresh,
        sessions=(args.ses1, args.ses2),
    )


if __name__ == "__main__":
    main()
