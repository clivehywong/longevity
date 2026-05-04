#!/usr/bin/env python3
"""
Fast Parametric Group-Level Statistics (Change-Score Approach)

Voxelwise parametric t-tests for paired pre/post × 2-group mixed designs.
Much faster than permutation tests — runs in seconds rather than hours.
Results match FSL randomise sign conventions for direct comparison.

**Design (sign convention matching MixedDesignBuilder):**
  Time column: +1 pre (ses-01), -1 post (ses-02)
  Group column: +1 control, -1 walking

  Contrast 1 (Interaction): Welch t-test on delta_ctrl vs delta_walk
    where delta = pre − post (matching +1 pre, -1 post encoding)
    Positive tstat1 = control pre>post effect stronger than walking
  Contrast 2 (Time): one-sample t-test on all_delta (pre − post)
    Positive tstat2 = pre > post (connectivity decreases post-intervention)
  Contrast 3 (Group): Welch t-test on ctrl_mean vs walk_mean
    where mean = (pre + post) / 2 per subject
    Positive tstat3 = control > walking (matches tstat3 from randomise)

**Outputs** (to {output_dir}/lmm_outputs/):
  lmm_tstat1.nii.gz, lmm_tstat2.nii.gz, lmm_tstat3.nii.gz
  lmm_cluster_corrp_tstat{N}.nii.gz  (GRF cluster, if FSL available)
  lmm_summary.json

**Usage:**
  python group_lmm_stats.py \\
    --bids-root /path/to/project \\
    --seed atlas-4S256Parcels:LH_Cont_PFCl_3 \\
    --pipeline fc \\
    --measure pearson \\
    --canonical-csv /path/to/filtered.tsv \\
    --mask-path /path/to/mask.nii.gz
"""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import nibabel as nib
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "neuconn_app"))

from utils.group_stats_validation import SubjectDataValidator
from utils.seed_viz import cli_token_to_seed_dir_name

logger = logging.getLogger(__name__)

# ── Helpers ─────────────────────────────────────────────────────────────────

def _format_participant_id(value) -> str:
    subject = str(value).strip()
    if subject.startswith("sub-"):
        return subject
    digits = "".join(ch for ch in subject if ch.isdigit())
    return f"sub-{int(digits):03d}" if digits else subject


def _format_session_id(value) -> str:
    session = str(value).strip()
    if session.startswith("ses-"):
        return session
    digits = "".join(ch for ch in session if ch.isdigit())
    return f"ses-{int(digits):02d}" if digits else session


def _read_canonical_order(csv_path: Path) -> pd.DataFrame:
    """Load canonical order TSV/CSV → DataFrame with subject/session/group cols."""
    sep = "\t" if csv_path.suffix.lower() == ".tsv" else ","
    df = pd.read_csv(csv_path, sep=sep)

    required_expanded = {"row_index", "subject", "session", "group"}
    if required_expanded.issubset(df.columns):
        df = df.copy()
        df["subject"] = df["subject"].apply(_format_participant_id)
        df["session"] = df["session"].apply(_format_session_id)
        df["group"] = df["group"].astype(str).str.strip().str.lower()
        return df

    if not {"participant_id", "group"}.issubset(df.columns):
        raise ValueError(
            "Canonical CSV must have either {row_index, subject, session, group} "
            "or {participant_id, group} columns."
        )

    rows = []
    for pid, grp in df[["participant_id", "group"]].itertuples(index=False):
        subject = _format_participant_id(pid)
        group = str(grp).strip().lower()
        for session in ("ses-01", "ses-02"):
            rows.append({"row_index": len(rows), "subject": subject,
                         "session": session, "group": group})
    return pd.DataFrame(rows, columns=["row_index", "subject", "session", "group"])


def _load_zmap(bids_root: Path, pipeline: str, subject: str, session: str,
               seed_dir_name: str, measure: str) -> Optional[np.ndarray]:
    """Load a single zmap into a flat array. Returns None if not found."""
    seed_path = (
        bids_root / "derivatives" / "connectivity" / pipeline
        / subject / session / "seed" / seed_dir_name
    )
    if not seed_path.exists():
        return None
    pattern = f"*_measure-{measure}_seed-to-voxel_zmap.nii.gz"
    files = list(seed_path.glob(pattern))
    if not files:
        return None
    try:
        img = nib.load(str(files[0]))
        return img.get_fdata(dtype=np.float32).ravel()
    except Exception as e:
        logger.warning(f"Failed to load {files[0]}: {e}")
        return None


def _load_mask(mask_path: Path, ref_img: nib.Nifti1Image) -> np.ndarray:
    """Load mask and return boolean flat array aligned to ref_img shape."""
    mask_img = nib.load(str(mask_path))
    if mask_img.shape != ref_img.shape[:3]:
        from nilearn.image import resample_to_img
        mask_img = resample_to_img(mask_img, ref_img, interpolation="nearest")
    return mask_img.get_fdata().ravel() > 0


# ── Vectorized t-test functions ──────────────────────────────────────────────

def _one_sample_t(X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """One-sample t-test: H0 = 0. Returns (t, df) per voxel."""
    n = X.shape[0]
    mu = X.mean(axis=0)
    se = X.std(axis=0, ddof=1) / np.sqrt(n)
    t = np.where(se > 1e-12, mu / se, 0.0)
    df = np.full(t.shape, float(n - 1))
    return t, df


def _welch_t(A: np.ndarray, B: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Welch two-sample t-test with per-voxel Welch-Satterthwaite df.
    Returns (t, df) per voxel. Positive t = A > B."""
    n1, n2 = A.shape[0], B.shape[0]
    mu1, mu2 = A.mean(axis=0), B.mean(axis=0)
    var1 = A.var(axis=0, ddof=1)
    var2 = B.var(axis=0, ddof=1)
    se = np.sqrt(var1 / n1 + var2 / n2)
    t = np.where(se > 1e-12, (mu1 - mu2) / se, 0.0)
    # Welch-Satterthwaite df
    denom = (var1 ** 2 / (n1 ** 2 * (n1 - 1)) + var2 ** 2 / (n2 ** 2 * (n2 - 1)))
    df = np.where(denom > 1e-30, (var1 / n1 + var2 / n2) ** 2 / denom, float(n1 + n2 - 2))
    return t, df


def _t_to_z(t: np.ndarray, df: np.ndarray) -> np.ndarray:
    """Convert t-statistic to z-score preserving sign. Uses per-voxel df."""
    # Compute two-tailed p, then convert to z
    p2 = stats.t.sf(np.abs(t), df) * 2
    p2 = np.clip(p2, 1e-15, 1.0)
    z = stats.norm.isf(p2 / 2) * np.sign(t)
    return z.astype(np.float32)


# ── GRF cluster correction ───────────────────────────────────────────────────

def _fsl_available() -> bool:
    return subprocess.run(["which", "smoothest"], capture_output=True).returncode == 0


def _run_cmd(cmd: List[str], timeout: int = 300) -> Tuple[int, str, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def _parse_smoothest(stdout: str) -> Optional[Dict[str, float]]:
    """Parse smoothest output: DLH, RESELS, VOLUME."""
    params: Dict[str, float] = {}
    for line in stdout.split("\n"):
        parts = line.split()
        if len(parts) >= 2 and parts[0] in ("DLH", "RESELS", "VOLUME"):
            try:
                params[parts[0]] = float(parts[1])
            except ValueError:
                pass
    return params if len(params) >= 2 else None


def _parse_cluster_table(stdout: str) -> Dict[int, float]:
    """Parse fsl-cluster output table → {cluster_index: FWE_p}."""
    cluster_pvals: Dict[int, float] = {}
    for line in stdout.split("\n")[1:]:  # skip header
        parts = line.split()
        if len(parts) >= 3:
            try:
                c_idx = int(parts[0])
                c_p = float(parts[2])
                cluster_pvals[c_idx] = c_p
            except (ValueError, IndexError):
                pass
    return cluster_pvals


def _grf_cluster_correct(
    z_data: np.ndarray,
    mask_flat: np.ndarray,
    ref_img: nib.Nifti1Image,
    output_dir: Path,
    prefix: str,
    cluster_z: float = 2.3,
    cluster_p: float = 0.05,
) -> Optional[np.ndarray]:
    """Run GRF cluster correction on z-stat map (positive tail).
    Returns corrp flat array (1-FWE_p for significant clusters, 0 elsewhere),
    or None if FSL unavailable or correction fails.
    """
    if not _fsl_available():
        logger.warning("FSL smoothest not found — skipping GRF cluster correction")
        return None

    shape3d = ref_img.shape[:3]
    affine = ref_img.affine
    header = ref_img.header

    # Write z-stat NIfTI
    z_vol = np.zeros(shape3d, dtype=np.float32)
    z_vol.ravel()[mask_flat] = z_data
    z_path = output_dir / f"{prefix}_zstat.nii.gz"
    nib.save(nib.Nifti1Image(z_vol, affine, header), str(z_path))

    # Write mask NIfTI
    mask_vol = mask_flat.reshape(shape3d).astype(np.float32)
    mask_path = output_dir / f"{prefix}_mask.nii.gz"
    nib.save(nib.Nifti1Image(mask_vol, affine, header), str(mask_path))

    # Estimate smoothness
    rc, stdout, stderr = _run_cmd(["smoothest", "-z", str(z_path), "-m", str(mask_path)])
    if rc != 0:
        logger.warning(f"smoothest failed: {stderr[:500]}")
        return None
    params = _parse_smoothest(stdout)
    if params is None:
        logger.warning("smoothest: could not parse DLH/RESELS/VOLUME")
        return None
    logger.debug(f"Smoothness: {params}")

    # Threshold z-stat
    thresh_path = output_dir / f"{prefix}_zthresh.nii.gz"
    rc, _, stderr = _run_cmd(
        ["fslmaths", str(z_path), "-thr", str(cluster_z), str(thresh_path)]
    )
    if rc != 0:
        logger.warning(f"fslmaths threshold failed: {stderr[:500]}")
        return None

    # Run fsl-cluster
    cluster_idx_path = output_dir / f"{prefix}_cluster_index.nii.gz"
    lmax_path = output_dir / f"{prefix}_lmax.txt"
    cmd = [
        "fsl-cluster",
        "-i", str(thresh_path),
        "-t", str(cluster_z),
        "--othresh", str(thresh_path),
        "-o", str(cluster_idx_path),
        "--olmax", str(lmax_path),
        "-p", str(cluster_p),
        "-d", str(params["DLH"]),
        "--volume", str(int(params["VOLUME"])),
        "--mm",
    ]
    if "RESELS" in params:
        cmd.extend(["-r", str(params["RESELS"])])
    rc, stdout, stderr = _run_cmd(cmd, timeout=120)
    if rc != 0:
        logger.warning(f"fsl-cluster failed: {stderr[:500]}")
        return None

    # Build corrp map from cluster table
    cluster_pvals = _parse_cluster_table(stdout)
    if not cluster_pvals:
        logger.info("No significant clusters found at this threshold")
        # Return zero map (valid — just no clusters survive)
        return np.zeros(int(mask_flat.sum()), dtype=np.float32)

    # Load cluster index image
    try:
        cidx_img = nib.load(str(cluster_idx_path))
        cidx_flat = cidx_img.get_fdata().ravel()[mask_flat]
    except Exception as e:
        logger.warning(f"Could not load cluster index: {e}")
        return None

    corrp_flat = np.zeros(int(mask_flat.sum()), dtype=np.float32)
    for c_idx, c_p in cluster_pvals.items():
        corrp_flat[cidx_flat == c_idx] = 1.0 - c_p

    logger.info(
        f"GRF cluster correction: {len(cluster_pvals)} significant clusters "
        f"(p < {cluster_p})"
    )
    return corrp_flat


# ── Main pipeline ─────────────────────────────────────────────────────────────

class ParametricGroupStats:
    """Fast parametric group statistics for paired pre/post × 2-group designs."""

    CONTRAST_NAMES = {
        1: "Group×Time interaction",
        2: "Time effect (ses-01 > ses-02)",
        3: "Group effect (control > walking)",
    }

    def __init__(
        self,
        bids_root: str,
        seed: str,
        pipeline: str = "fc",
        measure: str = "pearson",
        canonical_csv: Optional[str] = None,
        mask_path: Optional[str] = None,
        output_dir: Optional[str] = None,
        cluster_z: float = 2.3,
        cluster_p: float = 0.05,
    ):
        self.bids_root = Path(bids_root)
        self.seed = seed
        self.pipeline = pipeline
        self.measure = measure
        self.cluster_z = cluster_z
        self.cluster_p = cluster_p

        seed_dir_name = cli_token_to_seed_dir_name(seed)
        self.seed_dir_name = seed_dir_name

        if canonical_csv:
            self.canonical_csv = Path(canonical_csv)
        else:
            participants_tsv = self.bids_root / "bids" / "participants.tsv"
            legacy_group_csv = self.bids_root / "group.csv"
            self.canonical_csv = (
                participants_tsv if participants_tsv.exists() else legacy_group_csv
            )

        if mask_path:
            self.mask_path = Path(mask_path)
        else:
            self.mask_path = (
                self.bids_root / "atlases" / "MNI152NLin2009cAsym_res-02_desc-brain_mask_dilated.nii.gz"
            )

        if output_dir:
            self.output_dir = Path(output_dir) / "lmm_outputs"
        else:
            self.output_dir = (
                self.bids_root / "derivatives" / "connectivity"
                / pipeline / "group" / "seed"
                / seed_dir_name / f"measure-{measure}" / "lmm_outputs"
            )

    def run(self) -> bool:
        """Execute full pipeline. Returns True on success."""
        try:
            logger.info("=" * 70)
            logger.info("Fast Parametric Group Statistics")
            logger.info(f"  Seed: {self.seed}")
            logger.info(f"  Pipeline: {self.pipeline}")
            logger.info(f"  Measure: {self.measure}")
            logger.info(f"  Output: {self.output_dir}")
            logger.info("=" * 70)

            self.output_dir.mkdir(parents=True, exist_ok=True)

            canonical = _read_canonical_order(self.canonical_csv)
            logger.info(f"Loaded {len(canonical)} rows from {self.canonical_csv}")

            # Load zmaps
            data = self._load_all_zmaps(canonical)
            if data is None:
                return False

            (
                pre_ctrl, post_ctrl,
                pre_walk, post_walk,
                ref_img, mask_flat,
                subjects_used,
            ) = data

            n_ctrl = pre_ctrl.shape[0]
            n_walk = pre_walk.shape[0]
            n_total = n_ctrl + n_walk
            logger.info(
                f"Data loaded: {n_ctrl} control + {n_walk} walking = {n_total} subjects, "
                f"{int(mask_flat.sum())} voxels in mask"
            )

            # Compute contrasts
            # delta = pre - post (positive = pre > post, matching Time col encoding)
            delta_ctrl = pre_ctrl - post_ctrl   # (n_ctrl, V)
            delta_walk = pre_walk - post_walk   # (n_walk, V)
            delta_all = np.vstack([delta_ctrl, delta_walk])  # (n_total, V)
            mean_ctrl = (pre_ctrl + post_ctrl) / 2           # (n_ctrl, V)
            mean_walk = (pre_walk + post_walk) / 2           # (n_walk, V)

            logger.info("Computing voxelwise t-tests...")

            # Contrast 1: Interaction (Welch ctrl_delta vs walk_delta)
            t1, df1 = _welch_t(delta_ctrl, delta_walk)
            # Contrast 2: Time (one-sample on all_delta)
            t2, df2 = _one_sample_t(delta_all)
            # Contrast 3: Group (Welch ctrl_mean vs walk_mean)
            t3, df3 = _welch_t(mean_ctrl, mean_walk)

            # Convert t → z for smoothest (requires z-stat maps)
            logger.info("Converting t → z for GRF smoothness estimation...")
            z1 = _t_to_z(t1, df1)
            z2 = _t_to_z(t2, df2)
            z3 = _t_to_z(t3, df3)

            shape3d = ref_img.shape[:3]
            affine = ref_img.affine
            header = ref_img.header

            # Save t-stat maps
            for idx, (t_data, name) in enumerate(
                [(t1, "tstat1"), (t2, "tstat2"), (t3, "tstat3")], start=1
            ):
                vol = np.zeros(shape3d, dtype=np.float32)
                vol.ravel()[mask_flat] = t_data
                path = self.output_dir / f"lmm_{name}.nii.gz"
                nib.save(nib.Nifti1Image(vol, affine, header), str(path))
                logger.info(f"Saved {path.name}")

            # GRF cluster correction on each z-stat (positive tail)
            fsl_ok = _fsl_available()
            corrp_paths: Dict[int, Optional[Path]] = {}

            for i, (z_data, prefix) in enumerate(
                [(z1, "c1"), (z2, "c2"), (z3, "c3")], start=1
            ):
                if fsl_ok:
                    corrp_flat = _grf_cluster_correct(
                        z_data, mask_flat, ref_img,
                        self.output_dir, prefix,
                        self.cluster_z, self.cluster_p,
                    )
                    if corrp_flat is not None:
                        vol = np.zeros(shape3d, dtype=np.float32)
                        vol.ravel()[mask_flat] = corrp_flat
                        path = self.output_dir / f"lmm_cluster_corrp_tstat{i}.nii.gz"
                        nib.save(nib.Nifti1Image(vol, affine, header), str(path))
                        logger.info(f"Saved {path.name}")
                        corrp_paths[i] = path
                else:
                    corrp_paths[i] = None

            if not fsl_ok:
                logger.warning(
                    "FSL not available — t-stat maps saved without cluster correction. "
                    "Install FSL to enable GRF cluster correction."
                )

            # Save summary
            summary = {
                "seed": self.seed,
                "pipeline": self.pipeline,
                "measure": self.measure,
                "n_control": n_ctrl,
                "n_walking": n_walk,
                "n_voxels_in_mask": int(mask_flat.sum()),
                "cluster_z_threshold": self.cluster_z,
                "cluster_p_threshold": self.cluster_p,
                "fsl_available": fsl_ok,
                "subjects_control": [r[0] for r in subjects_used if r[1] == "control"],
                "subjects_walking": [r[0] for r in subjects_used if r[1] == "walking"],
                "contrasts": {
                    str(k): v for k, v in self.CONTRAST_NAMES.items()
                },
            }
            summary_path = self.output_dir / "lmm_summary.json"
            summary_path.write_text(json.dumps(summary, indent=2))
            logger.info(f"Saved summary: {summary_path}")
            logger.info("✓ Fast parametric analysis complete")
            return True

        except Exception as e:
            logger.exception(f"Pipeline failed: {e}")
            return False

    def _load_all_zmaps(self, canonical: pd.DataFrame):
        """Load zmaps, pair by subject, return stacked arrays per group.

        Returns tuple: (pre_ctrl, post_ctrl, pre_walk, post_walk, ref_img, mask_flat, subjects_used)
        or None on failure.
        """
        # Group subjects by group/session
        subjects = canonical["subject"].unique()

        pre_ctrl_list: List[np.ndarray] = []
        post_ctrl_list: List[np.ndarray] = []
        pre_walk_list: List[np.ndarray] = []
        post_walk_list: List[np.ndarray] = []
        subjects_used: List[Tuple[str, str]] = []

        ref_img = None
        mask_flat = None
        n_skipped = 0

        for subject in subjects:
            rows = canonical[canonical["subject"] == subject]
            pre_rows = rows[rows["session"] == "ses-01"]
            post_rows = rows[rows["session"] == "ses-02"]
            if pre_rows.empty or post_rows.empty:
                logger.debug(f"{subject}: missing ses-01 or ses-02, skipping")
                n_skipped += 1
                continue

            group = pre_rows.iloc[0]["group"]
            pre_data = _load_zmap(
                self.bids_root, self.pipeline, subject, "ses-01",
                self.seed_dir_name, self.measure
            )
            post_data = _load_zmap(
                self.bids_root, self.pipeline, subject, "ses-02",
                self.seed_dir_name, self.measure
            )

            if pre_data is None:
                logger.debug(f"{subject} ses-01: zmap not found, skipping")
                n_skipped += 1
                continue
            if post_data is None:
                logger.debug(f"{subject} ses-02: zmap not found, skipping")
                n_skipped += 1
                continue

            # Load reference image and mask on first valid zmap
            if ref_img is None:
                seed_path = (
                    self.bids_root / "derivatives" / "connectivity" / self.pipeline
                    / subject / "ses-01" / "seed" / self.seed_dir_name
                )
                files = list(seed_path.glob(f"*_measure-{self.measure}_seed-to-voxel_zmap.nii.gz"))
                if not files:
                    continue
                ref_img = nib.load(str(files[0]))
                if self.mask_path and self.mask_path.exists():
                    mask_flat = _load_mask(self.mask_path, ref_img)
                    logger.info(
                        f"Mask applied: {int(mask_flat.sum())} / {mask_flat.size} voxels"
                    )
                else:
                    mask_flat = np.ones(ref_img.get_fdata().size, dtype=bool)
                    logger.warning("No mask found — using all voxels (slow!)")

            if group == "control":
                pre_ctrl_list.append(pre_data[mask_flat])
                post_ctrl_list.append(post_data[mask_flat])
            elif group == "walking":
                pre_walk_list.append(pre_data[mask_flat])
                post_walk_list.append(post_data[mask_flat])
            else:
                logger.warning(f"{subject}: unknown group '{group}', skipping")
                n_skipped += 1
                continue

            subjects_used.append((subject, group))

        if n_skipped > 0:
            logger.info(f"Skipped {n_skipped} subjects (missing zmaps or sessions)")

        if not pre_ctrl_list or not pre_walk_list:
            logger.error("Not enough data: need at least 1 subject per group")
            return None

        return (
            np.vstack(pre_ctrl_list),   # (n_ctrl, V)
            np.vstack(post_ctrl_list),
            np.vstack(pre_walk_list),   # (n_walk, V)
            np.vstack(post_walk_list),
            ref_img, mask_flat, subjects_used,
        )


# ── CLI entry point ──────────────────────────────────────────────────────────

def main() -> int:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Fast parametric group statistics (change-score approach)"
    )
    parser.add_argument("--bids-root", required=True, help="Project root directory")
    parser.add_argument("--seed", required=True, help="Seed token (e.g. atlas-4S256Parcels:LH_Cont_PFCl_3)")
    parser.add_argument("--pipeline", default="fc", choices=["fc", "fc_gsr", "ec"])
    parser.add_argument("--measure", default="pearson")
    parser.add_argument("--canonical-csv", help="Filtered canonical order CSV/TSV")
    parser.add_argument("--mask-path", help="Brain mask NIfTI (dilated MNI recommended)")
    parser.add_argument("--output-dir", help="Override output directory")
    parser.add_argument("--cluster-z", type=float, default=2.3,
                        help="Cluster-forming z-threshold (default: 2.3)")
    parser.add_argument("--cluster-p", type=float, default=0.05,
                        help="Cluster FWE p-threshold (default: 0.05)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print configuration and exit without running")

    args = parser.parse_args()

    if args.dry_run:
        print("Dry run — configuration:")
        print(f"  bids_root: {args.bids_root}")
        print(f"  seed:      {args.seed}")
        print(f"  pipeline:  {args.pipeline}")
        print(f"  measure:   {args.measure}")
        print(f"  canonical: {args.canonical_csv}")
        print(f"  mask:      {args.mask_path}")
        print(f"  cluster_z: {args.cluster_z}")
        print(f"  cluster_p: {args.cluster_p}")
        return 0

    runner = ParametricGroupStats(
        bids_root=args.bids_root,
        seed=args.seed,
        pipeline=args.pipeline,
        measure=args.measure,
        canonical_csv=args.canonical_csv,
        mask_path=args.mask_path,
        output_dir=args.output_dir,
        cluster_z=args.cluster_z,
        cluster_p=args.cluster_p,
    )

    success = runner.run()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
