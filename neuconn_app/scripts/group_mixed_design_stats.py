#!/usr/bin/env python3
"""
Mixed-Design Group-Level Statistics Pipeline

Main entry point for running FSL randomise on paired pre/post × 2-group designs.

**Workflow:**
1. Validate inputs (seed, pipeline, measure, participants metadata)
2. Load canonical subject order from participants metadata or a canonical CSV
3. Validate all 72 zmaps using SubjectDataValidator
4. Merge 4D NIfTI using fslmerge
5. Generate FSL design files using MixedDesignBuilder
6. Run FSL randomise with TFCE
7. Generate summary report

**Usage:**
  python group_mixed_design_stats.py \\
    --bids-root /path/to/project-root \\
    --seed atlas-4S256Parcels:RH_Cont_Par_1 \\
    --pipeline fc \\
    --measure pearson \\
    --n-perm 5000

**Dependencies:**
  - FSL randomise (must be in PATH)
  - Python: numpy, nibabel, pandas, subprocess
"""

import sys
import argparse
import logging
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import subprocess

import numpy as np
import pandas as pd
import nibabel as nib

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.group_stats_design import MixedDesignBuilder
from utils.group_stats_validation import SubjectDataValidator
from utils.seed_viz import cli_token_to_seed_dir_name


logger = logging.getLogger(__name__)


def _read_subject_table(path: Path) -> pd.DataFrame:
    sep = "\t" if path.suffix.lower() == ".tsv" else ","
    return pd.read_csv(path, sep=sep)


def _format_participant_id(value: Any) -> str:
    subject = str(value).strip()
    if subject.startswith("sub-"):
        return subject
    digits = "".join(ch for ch in subject if ch.isdigit())
    if digits:
        return f"sub-{int(digits):03d}"
    return subject


def _format_session_id(value: Any) -> str:
    session = str(value).strip()
    if session.startswith("ses-"):
        return session
    digits = "".join(ch for ch in session if ch.isdigit())
    if digits:
        return f"ses-{int(digits):02d}"
    return session


def _to_canonical_order(df: pd.DataFrame) -> pd.DataFrame:
    canonical = df.copy()
    if "subject_id" in canonical.columns and "participant_id" not in canonical.columns:
        canonical = canonical.rename(columns={"subject_id": "participant_id"})

    required_cols = {"row_index", "subject", "session", "group"}
    if required_cols.issubset(canonical.columns):
        canonical["subject"] = canonical["subject"].apply(_format_participant_id)
        canonical["session"] = canonical["session"].apply(_format_session_id)
        canonical["group"] = canonical["group"].astype(str).str.strip().str.lower()
        return canonical

    if not {"participant_id", "group"}.issubset(canonical.columns):
        raise ValueError(
            "Canonical order file must contain either row_index/subject/session/group "
            "or participant_id/group columns."
        )

    rows = []
    for participant_id, group in canonical[["participant_id", "group"]].dropna(subset=["participant_id"]).itertuples(index=False):
        subject = _format_participant_id(participant_id)
        normalized_group = str(group).strip().lower()
        for session in ("ses-01", "ses-02"):
            rows.append(
                {
                    "row_index": len(rows),
                    "subject": subject,
                    "session": session,
                    "group": normalized_group,
                }
            )

    return pd.DataFrame(rows, columns=["row_index", "subject", "session", "group"])


def _find_alff_reho_maps(bids_root: Path, pipeline: str, canonical_df: pd.DataFrame, stat: str):
    """Find ALFF/ReHo maps for all subjects/sessions in canonical_df.
    
    Returns list of (subject, session, group, path_or_None) tuples.
    """
    results = []
    for _, row in canonical_df.iterrows():
        subject = row.get("subject", row.get("participant_id", ""))
        session = row.get("session", "ses-01")
        group = row.get("group", "")
        func_dir = (
            bids_root / "derivatives" / "preprocessing" / "xcpd"
            / pipeline / subject / session / "func"
        )
        pattern = f"*_space-MNI152NLin6Asym_res-2_stat-{stat}_boldmap.nii.gz"
        files = list(func_dir.glob(pattern)) if func_dir.exists() else []
        results.append((subject, session, group, str(files[0]) if files else None))
    return results


class GroupStatsRunner:
    """Orchestrator for mixed-design group-level statistics workflow."""
    
    def __init__(
        self,
        bids_root: str,
        seed: str,
        pipeline: str = "fc",
        measure: str = "pearson",
        output_dir: Optional[str] = None,
        n_perm: int = 5000,
        mask_path: Optional[str] = None,
        canonical_order_csv: Optional[str] = None,
        correction: str = "TFCE",
    ):
        self.bids_root = Path(bids_root)
        self.seed = seed
        self.pipeline = pipeline
        self.measure = measure
        self.n_perm = n_perm
        self.mask_path = Path(mask_path) if mask_path else None
        _corr = correction.upper()
        # "CLUSTER" is the canonical name; accept "GRF" as legacy alias
        self.correction = "GRF" if _corr == "CLUSTER" else _corr

        # Set canonical order / participant metadata file
        if canonical_order_csv:
            self.canonical_order_csv = Path(canonical_order_csv)
        else:
            participants_tsv = self.bids_root / "bids" / "participants.tsv"
            legacy_group_csv = self.bids_root / "group.csv"
            self.canonical_order_csv = (
                participants_tsv if participants_tsv.exists() or not legacy_group_csv.exists()
                else legacy_group_csv
            )

        # Set output directory — use canonical derivatives structure
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            seed_dir_name = cli_token_to_seed_dir_name(seed)
            self.output_dir = (
                self.bids_root
                / "derivatives" / "connectivity"
                / pipeline / "group" / "seed"
                / seed_dir_name / f"measure-{measure}"
            )

        # State
        self.canonical_order: Optional[pd.DataFrame] = None
        self.validation_df: Optional[pd.DataFrame] = None
        self.zmaps_list: Optional[List[str]] = None
        self.merged_nifti_path: Optional[Path] = None
        self.design_files: Optional[Dict[str, Path]] = None
    
    def run(self) -> bool:
        """Execute full pipeline."""
        try:
            logger.info("=" * 70)
            logger.info(f"Starting group statistics pipeline")
            logger.info(f"  Seed: {self.seed}")
            logger.info(f"  Pipeline: {self.pipeline}")
            logger.info(f"  Measure: {self.measure}")
            logger.info(f"  N permutations: {self.n_perm}")
            logger.info("=" * 70)
            
            if not self._step_validate_inputs():
                return False
            if not self._step_load_canonical_order():
                return False
            if not self._step_validate_zmaps():
                return False
            if not self._step_merge_4d_nifti():
                return False
            if not self._step_generate_design_files():
                return False
            if not self._step_run_randomise():
                return False
            if not self._step_generate_report():
                return False
            
            logger.info("=" * 70)
            logger.info("Pipeline completed successfully!")
            logger.info(f"Results saved to: {self.output_dir}")
            logger.info("=" * 70)
            return True
        
        except Exception as e:
            logger.exception(f"Pipeline failed with exception: {e}")
            return False
    
    def _step_validate_inputs(self) -> bool:
        """Step 1: Validate inputs."""
        logger.info("\n[Step 1] Validating inputs...")
        
        if not self.bids_root.exists():
            logger.error(f"BIDS root not found: {self.bids_root}")
            return False
        logger.debug(f"BIDS root exists: {self.bids_root}")
        
        if ":" not in self.seed:
            logger.error(f"Seed must be in format 'atlas:seed_name', got: {self.seed}")
            return False
        logger.debug(f"Seed format valid: {self.seed}")
        
        valid_pipelines = ["fc", "fc_gsr", "ec"]
        if self.pipeline not in valid_pipelines:
            logger.error(f"Pipeline must be one of {valid_pipelines}, got: {self.pipeline}")
            return False
        logger.debug(f"Pipeline valid: {self.pipeline}")
        
        if not self.canonical_order_csv.exists():
            logger.error(f"Canonical order CSV not found: {self.canonical_order_csv}")
            return False
        logger.debug(f"Canonical order CSV found: {self.canonical_order_csv}")
        
        participants_tsv = self.bids_root / "bids" / "participants.tsv"
        legacy_group_csv = self.bids_root / "group.csv"
        metadata_path = participants_tsv if participants_tsv.exists() else legacy_group_csv
        if not metadata_path.exists():
            logger.error(
                f"participants metadata not found: expected `{participants_tsv}` "
                f"(or legacy fallback `{legacy_group_csv}`)"
            )
            return False
        logger.debug(f"Participants metadata found: {metadata_path}")
        
        logger.info("✓ All inputs validated")
        return True
    
    def _step_load_canonical_order(self) -> bool:
        """Step 2: Load canonical subject order."""
        logger.info("\n[Step 2] Loading canonical subject order...")
        
        try:
            self.canonical_order = _to_canonical_order(_read_subject_table(self.canonical_order_csv))

            if len(self.canonical_order) == 0:
                logger.error("Canonical order is empty — no subjects found")
                return False
            n_subjects = len(self.canonical_order["subject"].unique())
            logger.debug(f"Canonical order: {len(self.canonical_order)} rows, {n_subjects} subjects")

            required_cols = ["row_index", "subject", "session", "group"]
            if not all(col in self.canonical_order.columns for col in required_cols):
                logger.error(f"Missing required columns. Has: {list(self.canonical_order.columns)}")
                return False

            control_count = (self.canonical_order["group"] == "control").sum()
            walking_count = (self.canonical_order["group"] == "walking").sum()

            logger.debug(f"Loaded: {len(self.canonical_order)} rows")
            logger.debug(f"  Control: {control_count}, Walking: {walking_count}")
            logger.info(f"✓ Canonical order loaded ({control_count} control, {walking_count} walking)")

            return True
        
        except Exception as e:
            logger.error(f"Failed to load canonical order: {e}")
            return False
    
    def _step_validate_zmaps(self) -> bool:
        """Step 3: Validate zmaps and filter to available subjects."""
        logger.info("\n[Step 3] Validating zmaps...")
        
        try:
            validator = SubjectDataValidator(
                bids_root=str(self.bids_root),
                canonical_order_csv=str(self.canonical_order_csv),
                pipeline=self.pipeline,
                measure=self.measure,
            )
            
            seed_filter = self.seed.split(":")[1] if ":" in self.seed else None
            self.validation_df = validator.validate_all_subjects(seed=seed_filter)
            
            error_count = self.validation_df["error"].notna().sum()
            valid_count = int(self.validation_df["exists"].sum())
            total_count = len(self.validation_df)
            
            logger.debug(f"Validation results: {valid_count}/{total_count} valid, {error_count} errors")
            
            if valid_count == 0:
                logger.error("No valid zmaps found — run subject-level analysis first")
                return False
            
            if error_count > 0:
                logger.warning(
                    f"{error_count}/{total_count} subjects missing zmaps; "
                    f"proceeding with {valid_count} available subjects"
                )
                # Filter canonical order to only subjects with valid zmaps
                valid_mask = (
                    self.validation_df["exists"] & self.validation_df["error"].isna()
                )
                valid_rows = self.validation_df[valid_mask][["subject", "session"]]
                self.canonical_order = self.canonical_order.merge(
                    valid_rows, on=["subject", "session"], how="inner"
                ).reset_index(drop=True)
                # Update row_index after filtering
                self.canonical_order["row_index"] = range(len(self.canonical_order))
                logger.info(
                    f"Filtered canonical order to {len(self.canonical_order)} rows "
                    f"({len(self.canonical_order['subject'].unique())} subjects)"
                )
            
            # Check minimum subjects per group
            for grp in ("control", "walking"):
                grp_count = (self.canonical_order["group"] == grp).sum()
                if grp_count < 2:
                    logger.error(
                        f"Need at least 2 {grp} sessions (got {grp_count}); "
                        "run more subject-level analyses"
                    )
                    return False
            
            # Must have paired data (each subject must have both sessions)
            subject_session_counts = self.canonical_order.groupby("subject")["session"].count()
            unpaired = subject_session_counts[subject_session_counts != 2]
            if len(unpaired) > 0:
                logger.warning(
                    f"{len(unpaired)} subjects have incomplete sessions "
                    f"(expected ses-01+ses-02): {list(unpaired.index)}; dropping them"
                )
                complete = subject_session_counts[subject_session_counts == 2].index
                self.canonical_order = self.canonical_order[
                    self.canonical_order["subject"].isin(complete)
                ].reset_index(drop=True)
                self.canonical_order["row_index"] = range(len(self.canonical_order))
            
            # Build zmaps list directly from filtered canonical_order (avoids validator's
            # unfiltered iteration in get_canonical_zmaps_list)
            self.zmaps_list = []
            for _, row in self.canonical_order.iterrows():
                zmap_path = validator._find_zmap_file(
                    row["subject"], row["session"], seed_filter
                )
                if zmap_path is None:
                    logger.error(
                        f"Zmap not found for {row['subject']} {row['session']} "
                        "after filtering — unexpected"
                    )
                    return False
                self.zmaps_list.append(str(zmap_path))
            
            valid_count = len(self.canonical_order)
            if len(self.zmaps_list) != valid_count:
                logger.error(f"Zmap count mismatch: expected {valid_count}, got {len(self.zmaps_list)}")
                return False
            
            logger.info(f"✓ {valid_count} zmaps validated and ready")
            return True
        
        except Exception as e:
            logger.error(f"Zmap validation failed: {e}")
            return False
    
    def _step_merge_4d_nifti(self) -> bool:
        """Step 4: Merge zmaps into 4D NIfTI."""
        logger.info("\n[Step 4] Merging zmaps into 4D NIfTI...")
        
        try:
            result = subprocess.run(["which", "fslmerge"], capture_output=True, timeout=5)
            if result.returncode != 0:
                logger.error("fslmerge not found in PATH. Please ensure FSL is installed.")
                return False
            
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.merged_nifti_path = self.output_dir / "4d_merged.nii.gz"
            
            logger.debug(f"Merging {len(self.zmaps_list)} zmaps...")
            cmd = ["fslmerge", "-t", str(self.merged_nifti_path)] + self.zmaps_list
            logger.debug(f"Command: {' '.join(cmd[:5])} ... ({len(self.zmaps_list)} files)")
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                logger.error(f"fslmerge failed: {result.stderr}")
                return False
            
            if not self.merged_nifti_path.exists():
                logger.error(f"Merged NIfTI not created: {self.merged_nifti_path}")
                return False
            
            img = nib.load(str(self.merged_nifti_path))
            shape = img.shape
            expected_n = len(self.zmaps_list)
            expected_shape = (91, 109, 91, expected_n)
            
            logger.debug(f"Merged NIfTI shape: {shape}")
            
            if shape != expected_shape:
                logger.error(f"Shape mismatch: expected {expected_shape}, got {shape}")
                return False
            
            logger.info(f"✓ Merged 4D NIfTI ({shape}): {self.merged_nifti_path.name}")
            return True
        
        except subprocess.TimeoutExpired:
            logger.error("fslmerge timed out (>300s)")
            return False
        except Exception as e:
            logger.error(f"Failed to merge 4D NIfTI: {e}")
            return False
    
    def _step_generate_design_files(self) -> bool:
        """Step 5: Generate FSL design files."""
        logger.info("\n[Step 5] Generating FSL design files...")
        
        try:
            control_rows = self.canonical_order[self.canonical_order["group"] == "control"]
            walking_rows = self.canonical_order[self.canonical_order["group"] == "walking"]
            
            control_subjects = sorted(control_rows["subject"].unique().tolist())
            walking_subjects = sorted(walking_rows["subject"].unique().tolist())
            
            logger.debug(f"Control subjects: {len(control_subjects)}")
            logger.debug(f"Walking subjects: {len(walking_subjects)}")
            
            builder = MixedDesignBuilder.from_paired_two_group(
                control_subjects=control_subjects,
                walking_subjects=walking_subjects,
                sessions=["ses-01", "ses-02"],
            )
            
            builder.build()
            
            is_valid, errors = builder.validate()
            if not is_valid:
                logger.error("Design matrix validation failed:")
                for error in errors:
                    logger.error(f"  {error}")
                return False
            
            logger.debug(f"Design matrix rank: {np.linalg.matrix_rank(builder.design_matrix)}")
            logger.debug(f"Design matrix shape: {builder.design_matrix.shape}")
            
            self.design_files = builder.save_fsl_files(self.output_dir)
            
            logger.debug(f"Saved design files: {list(self.design_files.keys())}")
            logger.info(f"✓ Design files generated ({len(self.design_files)} files)")
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to generate design files: {e}")
            return False
    
    def _step_run_randomise(self) -> bool:
        """Step 6: Run FSL randomise."""
        logger.info("\n[Step 6] Running FSL randomise...")
        
        try:
            result = subprocess.run(["which", "randomise"], capture_output=True, timeout=5)
            if result.returncode != 0:
                logger.error("randomise not found in PATH. Please ensure FSL is installed.")
                return False
            
            randomise_dir = self.output_dir / "randomise_outputs"
            randomise_dir.mkdir(parents=True, exist_ok=True)
            
            if self.mask_path and self.mask_path.exists():
                mask = str(self.mask_path)
            else:
                mask = self._get_standard_mask()
                if not mask:
                    logger.error("Could not determine mask path")
                    return False
            
            logger.debug(f"Using mask: {mask}")
            
            cmd = [
                "randomise",
                "-i", str(self.merged_nifti_path),
                "-o", str(randomise_dir / "randomise"),
                "-d", str(self.design_files["design.mat"]),
                "-t", str(self.design_files["design.con"]),
                "-f", str(self.design_files["design.fts"]),
                "-e", str(self.design_files["design.grp"]),
                "-m", mask,
                "-n", str(self.n_perm),
                "-D",
            ]

            # Add correction method flag
            if self.correction == "TFCE":
                cmd.append("-T")
            elif self.correction == "GRF":
                cmd.extend(["-c", "2.3"])  # cluster-based thresholding (z=2.3)
            # FDR: no extra randomise flag — vox_p maps are always written; we
            # apply Benjamini-Hochberg correction in Python after randomise completes.
            
            logger.debug(f"Command: {' '.join(cmd)}")
            
            logs_dir = self.output_dir / "randomise_logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            
            stdout_log = logs_dir / "randomise_stdout.log"
            stderr_log = logs_dir / "randomise_stderr.log"
            
            with open(stdout_log, "w") as stdout_f, open(stderr_f_path := stderr_log, "w") as stderr_f:
                result = subprocess.run(cmd, stdout=stdout_f, stderr=stderr_f)
            
            if result.returncode != 0:
                logger.error(f"randomise failed with return code {result.returncode}")
                try:
                    with open(stderr_f_path, "r") as f:
                        logger.error(f"stderr: {f.read()[:500]}")
                except Exception:
                    pass
                return False
            
            logger.debug(f"randomise logs saved to {logs_dir}")
            logger.info(f"✓ randomise completed ({self.n_perm} permutations)")

            # ── FDR post-processing ───────────────────────────────────────
            if self.correction == "FDR":
                self._apply_fdr_correction(randomise_dir, mask)

            return True

        except Exception as e:
            logger.error(f"Failed to run randomise: {e}")
            return False
    
    def _apply_fdr_correction(self, randomise_dir: Path, mask_path: str) -> None:
        """Apply Benjamini-Hochberg FDR correction to randomise vox_p maps.

        randomise (without -T/-c) writes ``randomise_vox_p_tstat*.nii.gz``
        containing (1 - uncorrected permutation p).  We load each map,
        apply BH FDR within the brain mask, and write
        ``randomise_fdr_corrp_tstat*.nii.gz`` in the same format so the
        viewer and report code treat them like TFCE/GRF corrp maps.
        """
        from scipy.stats import rankdata  # noqa: PLC0415

        try:
            mask_img = nib.load(mask_path)
            mask_data = mask_img.get_fdata().astype(bool)
        except Exception as exc:
            logger.warning(f"Could not load mask for FDR; skipping: {exc}")
            return

        vox_p_files = sorted(randomise_dir.glob("randomise_vox_p_tstat*.nii.gz"))
        if not vox_p_files:
            logger.warning("No randomise_vox_p_tstat*.nii.gz found for FDR correction.")
            return

        for vox_p_path in vox_p_files:
            try:
                img = nib.load(str(vox_p_path))
                data = img.get_fdata()  # values = 1-p (0=not sig, 1=highly sig)

                p_vals = 1.0 - data  # convert to p-values
                in_mask = mask_data & np.isfinite(p_vals)
                flat_p = p_vals[in_mask]

                # Benjamini-Hochberg FDR
                n = len(flat_p)
                order = np.argsort(flat_p)
                ranks = rankdata(flat_p, method="ordinal")
                q_vals = np.minimum(1.0, flat_p * n / ranks)
                # Enforce monotonicity (BH requires cumulative min from right)
                q_vals[order] = np.minimum.accumulate(q_vals[order[::-1]])[::-1]

                corrp = np.zeros_like(data)
                corrp[in_mask] = np.clip(1.0 - q_vals, 0.0, 1.0)

                out_name = vox_p_path.name.replace("_vox_p_tstat", "_fdr_corrp_tstat")
                out_path = randomise_dir / out_name
                nib.save(nib.Nifti1Image(corrp, img.affine, img.header), str(out_path))
                sig = (corrp > 0.95).sum()
                logger.info(f"FDR: {out_name} — {sig} voxels q<0.05")
            except Exception as exc:
                logger.warning(f"FDR correction failed for {vox_p_path.name}: {exc}")

    def _step_generate_report(self) -> bool:
        """Step 7: Generate summary report."""
        logger.info("\n[Step 7] Generating summary report...")
        
        try:
            randomise_dir = self.output_dir / "randomise_outputs"
            tfce_files = list(randomise_dir.glob("randomise_tfce_corrp_*.nii.gz"))
            logger.debug(f"Found {len(tfce_files)} TFCE output files")
            
            n_subjects = self.canonical_order["subject"].nunique()
            n_zmaps = len(self.zmaps_list)
            n_control = self.canonical_order[self.canonical_order["group"] == "control"]["subject"].nunique()
            n_walking = self.canonical_order[self.canonical_order["group"] == "walking"]["subject"].nunique()

            summary = {
                "pipeline": {
                    "seed": self.seed,
                    "pipeline": self.pipeline,
                    "measure": self.measure,
                    "n_permutations": self.n_perm,
                },
                "inputs": {
                    "n_subjects": n_subjects,
                    "n_zmaps": n_zmaps,
                    "n_control": n_control,
                    "n_walking": n_walking,
                    "canonical_order_csv": str(self.canonical_order_csv),
                },
                "outputs": {
                    "merged_nifti": str(self.merged_nifti_path),
                    "design_files": {k: str(v) for k, v in self.design_files.items()},
                    "randomise_outputs_dir": str(randomise_dir),
                    "randomise_logs_dir": str(self.output_dir / "randomise_logs"),
                },
            }
            
            stats = self._parse_randomise_outputs(randomise_dir)
            summary["statistics"] = stats
            
            summary_path = self.output_dir / "stats_summary.json"
            with open(summary_path, "w") as f:
                json.dump(summary, f, indent=2)
            
            logger.debug(f"Summary saved: {summary_path}")
            self._generate_html_report()
            logger.info(f"✓ Summary report generated")
            return True
        
        except Exception as e:
            logger.error(f"Failed to generate report: {e}")
            return False
    
    def _parse_randomise_outputs(self, randomise_dir: Path) -> Dict[str, Any]:
        """Parse randomise outputs for statistics (TFCE, GRF, or FDR)."""
        stats: Dict[str, Any] = {"corrp_files": [], "fstat_files": []}

        # Corrected p-value maps — pattern depends on correction method
        corrp_patterns = [
            "randomise_tfce_corrp_*.nii.gz",       # TFCE
            "randomise_clustere_corrp_*.nii.gz",    # GRF cluster
            "randomise_fdr_corrp_*.nii.gz",         # FDR (our post-processed output)
        ]
        try:
            for pattern in corrp_patterns:
                for fpath in sorted(randomise_dir.glob(pattern)):
                    try:
                        img = nib.load(str(fpath))
                        data = img.get_fdata()
                        voxels_sig = int((data > 0.95).sum())
                        stats["corrp_files"].append({
                            "filename": fpath.name,
                            "correction": (
                                "TFCE" if "tfce" in fpath.name
                                else "GRF" if "clustere" in fpath.name
                                else "FDR"
                            ),
                            "voxels_significant": voxels_sig,
                            "data_range": [float(np.min(data)), float(np.max(data))],
                        })
                    except Exception as e:
                        logger.debug(f"Failed to parse {fpath.name}: {e}")

            # Keep backward-compat key
            stats["tfce_files"] = [
                r for r in stats["corrp_files"] if r["correction"] == "TFCE"
            ]

            for fpath in sorted(randomise_dir.glob("randomise_fstat*.nii.gz")):
                try:
                    img = nib.load(str(fpath))
                    data = img.get_fdata()
                    stats["fstat_files"].append({
                        "filename": fpath.name,
                        "max_fstat": float(np.max(data)),
                        "mean_fstat": float(np.mean(data)),
                    })
                except Exception as e:
                    logger.debug(f"Failed to parse {fpath.name}: {e}")

        except Exception as e:
            logger.debug(f"Error parsing outputs: {e}")

        return stats
    
    def _generate_html_report(self) -> None:
        """Generate HTML report."""
        html_path = self.output_dir / "group_stats_report.html"
        
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Group Statistics Report - {self.seed}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; margin-top: 20px; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .info-box {{ background-color: #e7f3fe; padding: 10px; margin: 10px 0; }}
        code {{ background-color: #f4f4f4; padding: 2px 5px; }}
    </style>
</head>
<body>
    <h1>Group Statistics Report</h1>
    
    <div class="info-box">
        <p><strong>Seed:</strong> <code>{self.seed}</code></p>
        <p><strong>Pipeline:</strong> {self.pipeline}</p>
        <p><strong>Measure:</strong> {self.measure}</p>
        <p><strong>Permutations:</strong> {self.n_perm}</p>
    </div>
    
    <h2>Participants</h2>
    <table>
        <tr>
            <th>Group</th>
            <th>N Subjects</th>
            <th>N Sessions</th>
        </tr>
        <tr>
            <td>Control</td>
            <td>20</td>
            <td>40</td>
        </tr>
        <tr>
            <td>Walking</td>
            <td>16</td>
            <td>32</td>
        </tr>
    </table>
    
    <h2>Outputs</h2>
    <p>Results saved to: <code>{self.output_dir}</code></p>
    <ul>
        <li>4D merged NIfTI: <code>4d_merged.nii.gz</code></li>
        <li>Design files: <code>design.mat</code>, <code>design.con</code>, <code>design.fts</code>, <code>design.grp</code></li>
        <li>randomise outputs: <code>randomise_outputs/</code></li>
        <li>Logs: <code>randomise_logs/</code></li>
        <li>Summary: <code>stats_summary.json</code></li>
    </ul>
</body>
</html>"""
        
        with open(html_path, "w") as f:
            f.write(html_content)
        
        logger.debug(f"HTML report saved: {html_path}")
    
    def _get_standard_mask(self) -> Optional[str]:
        """Get standard space mask path or create one from merged NIfTI.

        Priority order (AGENTS.md §6: all voxelwise analyses must use dilated mask):
          1. Project-local dilated MNI mask (atlases/MNI152_T1_2mm_brain_mask_dil.nii.gz)
          2. FSL standard brain mask (non-dilated, fallback)
          3. Auto-derived mask from merged data (last resort)
        """
        # 1. Project-local dilated mask (preferred per AGENTS.md)
        dilated = self.bids_root / "atlases" / "MNI152_T1_2mm_brain_mask_dil.nii.gz"
        if dilated.exists():
            logger.info(f"Using project dilated MNI mask: {dilated}")
            return str(dilated)

        candidates = [
            "${FSLDIR}/data/standard/MNI152_T1_2mm_brain_mask.nii.gz",
            "/usr/share/fsl/5.0/data/standard/MNI152_T1_2mm_brain_mask.nii.gz",
            "/opt/fsl/data/standard/MNI152_T1_2mm_brain_mask.nii.gz",
        ]
        
        for candidate in candidates:
            expanded = Path(candidate).expanduser()
            if expanded.exists():
                logger.debug(f"Found mask: {expanded}")
                return str(expanded)
        
        try:
            result = subprocess.run(
                ["fslstd", "-brain"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                mask_path = result.stdout.strip()
                if Path(mask_path).exists():
                    logger.debug(f"Found mask via fslstd: {mask_path}")
                    return mask_path
        except:
            pass
        
        # If no standard mask found, create one from the merged NIfTI
        logger.warning("Could not auto-detect standard mask, creating one from merged NIfTI...")
        return self._create_mask_from_merged_nifti()
    
    def _create_mask_from_merged_nifti(self) -> Optional[str]:
        """Create a mask from the merged 4D NIfTI by averaging across the 4th dimension."""
        try:
            if not self.merged_nifti_path or not self.merged_nifti_path.exists():
                logger.error("Merged NIfTI path not set or doesn't exist")
                return None
            
            import nibabel as nib
            import numpy as np
            
            img = nib.load(str(self.merged_nifti_path))
            data = img.get_fdata()
            
            # Create mask by averaging across subjects and thresholding
            mean_data = np.mean(np.abs(data), axis=-1)
            mask_data = (mean_data > 0).astype(np.float32)
            
            # Save mask
            mask_img = nib.Nifti1Image(mask_data, affine=img.affine)
            mask_path = self.output_dir / "auto_mask.nii.gz"
            nib.save(mask_img, str(mask_path))
            
            logger.info(f"✓ Created automatic mask from merged NIfTI: {mask_path}")
            return str(mask_path)
        
        except Exception as e:
            logger.error(f"Failed to create mask from merged NIfTI: {e}")
            return None


class GroupStatsAlffRehoRunner:
    """Runner for ALFF/ReHo mixed-design randomise workflow."""

    def __init__(
        self,
        bids_root: str,
        stat: str,
        pipeline: str = "fc",
        output_dir: Optional[str] = None,
        n_perm: int = 5000,
        mask_path: Optional[str] = None,
        canonical_order_csv: Optional[str] = None,
        correction: str = "TFCE",
    ):
        self.bids_root = Path(bids_root)
        self.stat = stat
        self.pipeline = pipeline
        self.n_perm = n_perm
        self.mask_path = Path(mask_path) if mask_path else None
        _corr = correction.upper()
        self.correction = "GRF" if _corr == "CLUSTER" else _corr

        if canonical_order_csv:
            self.canonical_order_csv = Path(canonical_order_csv)
        else:
            participants_tsv = self.bids_root / "bids" / "participants.tsv"
            legacy_group_csv = self.bids_root / "group.csv"
            self.canonical_order_csv = (
                participants_tsv if participants_tsv.exists() or not legacy_group_csv.exists()
                else legacy_group_csv
            )

        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = (
                self.bids_root / "derivatives" / "connectivity"
                / pipeline / "group" / stat
            )

        self.canonical_order: Optional[pd.DataFrame] = None
        self.zmaps_list: Optional[List[str]] = None
        self.merged_nifti_path: Optional[Path] = None
        self.design_files: Optional[Dict[str, Path]] = None

    def run(self) -> bool:
        """Execute full pipeline."""
        try:
            logger.info("=" * 70)
            logger.info(f"Mixed-Design Group Statistics ({self.stat.upper()})")
            logger.info(f"  Pipeline: {self.pipeline}")
            logger.info(f"  N permutations: {self.n_perm}")
            logger.info("=" * 70)

            if not self._step_load_canonical():
                return False
            if not self._step_collect_maps():
                return False
            if not self._step_merge_4d_nifti():
                return False
            if not self._step_generate_design_files():
                return False
            if not self._step_run_randomise():
                return False

            logger.info("=" * 70)
            logger.info(f"Pipeline completed! Results: {self.output_dir}")
            logger.info("=" * 70)
            return True

        except Exception as e:
            logger.exception(f"Pipeline failed: {e}")
            return False

    def _step_load_canonical(self) -> bool:
        logger.info("[Step 1] Loading canonical subject order...")
        try:
            self.canonical_order = _to_canonical_order(
                _read_subject_table(self.canonical_order_csv)
            )
            if len(self.canonical_order) == 0:
                logger.error("No subjects found in canonical order")
                return False
            logger.info(f"✓ {len(self.canonical_order)} rows loaded")
            return True
        except Exception as e:
            logger.error(f"Failed: {e}")
            return False

    def _step_collect_maps(self) -> bool:
        logger.info(f"[Step 2] Collecting {self.stat.upper()} maps...")
        map_entries = _find_alff_reho_maps(
            self.bids_root, self.pipeline, self.canonical_order, self.stat
        )
        # Order maps according to canonical order (row_index order)
        subject_session_path: Dict[Tuple[str, str], Optional[str]] = {
            (s, sess): p for s, sess, _g, p in map_entries
        }
        self.zmaps_list = []
        missing = []
        for _, row in self.canonical_order.iterrows():
            key = (row["subject"], row["session"])
            path = subject_session_path.get(key)
            if path is None:
                missing.append(f"{row['subject']} {row['session']}")
            else:
                self.zmaps_list.append(path)

        if missing:
            logger.warning(f"{len(missing)} maps missing: {missing[:5]}")
            # Keep only rows with maps available
            available_keys = {(s, sess) for s, sess, _g, p in map_entries if p is not None}
            self.canonical_order = self.canonical_order[
                self.canonical_order.apply(
                    lambda r: (r["subject"], r["session"]) in available_keys, axis=1
                )
            ].reset_index(drop=True)
            self.canonical_order["row_index"] = range(len(self.canonical_order))
            self.zmaps_list = [
                subject_session_path[(r["subject"], r["session"])]
                for _, r in self.canonical_order.iterrows()
            ]

        if not self.zmaps_list:
            logger.error(f"No {self.stat.upper()} maps found. Run XCP-D first.")
            return False

        logger.info(f"✓ {len(self.zmaps_list)} maps found")
        return True

    def _step_merge_4d_nifti(self) -> bool:
        logger.info("[Step 3] Merging maps into 4D NIfTI...")
        try:
            result = subprocess.run(["which", "fslmerge"], capture_output=True, timeout=5)
            if result.returncode != 0:
                logger.error("fslmerge not found. Install FSL.")
                return False
            self.output_dir.mkdir(parents=True, exist_ok=True)
            randomise_dir = self.output_dir / "randomise_outputs"
            randomise_dir.mkdir(parents=True, exist_ok=True)
            self.merged_nifti_path = self.output_dir / "4d_merged.nii.gz"
            cmd = ["fslmerge", "-t", str(self.merged_nifti_path)] + self.zmaps_list
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                logger.error(f"fslmerge failed: {result.stderr}")
                return False
            logger.info(f"✓ Merged: {self.merged_nifti_path.name}")
            return True
        except Exception as e:
            logger.error(f"Merge failed: {e}")
            return False

    def _step_generate_design_files(self) -> bool:
        logger.info("[Step 4] Generating FSL design files...")
        try:
            control_rows = self.canonical_order[self.canonical_order["group"] == "control"]
            walking_rows = self.canonical_order[self.canonical_order["group"] == "walking"]
            control_subjects = sorted(control_rows["subject"].unique().tolist())
            walking_subjects = sorted(walking_rows["subject"].unique().tolist())
            builder = MixedDesignBuilder.from_paired_two_group(
                control_subjects=control_subjects,
                walking_subjects=walking_subjects,
                sessions=["ses-01", "ses-02"],
            )
            builder.build()
            is_valid, errors = builder.validate()
            if not is_valid:
                for err in errors:
                    logger.error(f"  {err}")
                return False
            self.design_files = builder.save_fsl_files(self.output_dir)
            logger.info(f"✓ Design files generated")
            return True
        except Exception as e:
            logger.error(f"Failed: {e}")
            return False

    def _step_run_randomise(self) -> bool:
        logger.info("[Step 5] Running FSL randomise...")
        try:
            result = subprocess.run(["which", "randomise"], capture_output=True, timeout=5)
            if result.returncode != 0:
                logger.error("randomise not found. Install FSL.")
                return False
            randomise_dir = self.output_dir / "randomise_outputs"
            randomise_dir.mkdir(parents=True, exist_ok=True)
            if self.mask_path and self.mask_path.exists():
                mask = str(self.mask_path)
            else:
                # Use standard MNI mask if available
                standard_masks = [
                    self.bids_root / "atlases" / "MNI152_T1_2mm_brain_mask_dil.nii.gz",
                    self.bids_root / "atlases" / "MNI152NLin2009cAsym_res-02_desc-brain_mask_dilated.nii.gz",
                ]
                mask = next((str(m) for m in standard_masks if m.exists()), None)
                if not mask:
                    logger.error("Could not find brain mask")
                    return False
            cmd = [
                "randomise",
                "-i", str(self.merged_nifti_path),
                "-o", str(randomise_dir / "randomise"),
                "-d", str(self.design_files["design.mat"]),
                "-t", str(self.design_files["design.con"]),
                "-f", str(self.design_files["design.fts"]),
                "-e", str(self.design_files["design.grp"]),
                "-m", mask,
                "-n", str(self.n_perm),
                "-D",
            ]
            if self.correction == "TFCE":
                cmd.append("-T")
            elif self.correction == "GRF":
                cmd.extend(["-c", "2.3"])
            logs_dir = self.output_dir / "randomise_logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            with open(logs_dir / "stdout.log", "w") as so, open(logs_dir / "stderr.log", "w") as se:
                result = subprocess.run(cmd, stdout=so, stderr=se)
            if result.returncode != 0:
                logger.error(f"randomise failed (exit {result.returncode})")
                return False
            if self.correction == "FDR":
                # reuse FDR logic from GroupStatsRunner
                _runner = GroupStatsRunner.__new__(GroupStatsRunner)
                _runner.bids_root = self.bids_root
                _runner.output_dir = self.output_dir
                _runner._apply_fdr_correction(randomise_dir, mask)
            logger.info(f"✓ randomise completed ({self.n_perm} permutations)")
            return True
        except Exception as e:
            logger.error(f"Failed: {e}")
            return False


def setup_logging(debug: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if debug else logging.INFO
    
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Mixed-design group-level statistics pipeline"
    )

    parser.add_argument("--bids-root", required=True, help="Project root directory")
    seed_group = parser.add_mutually_exclusive_group(required=True)
    seed_group.add_argument(
        "--seed",
        help="Seed token in CLI format"
    )
    seed_group.add_argument(
        "--stat-map",
        help="ALFF/ReHo stat map type: 'alff' or 'reho'"
    )
    parser.add_argument("--pipeline", default="fc", choices=["fc", "fc_gsr", "ec"], help="Pipeline (default: fc)")
    parser.add_argument("--measure", default="pearson", help="Connectivity measure (default: pearson)")
    parser.add_argument("--output-dir", help="Output directory (default: derivatives/connectivity/<pipeline>/group/seed/.../)")
    # Accept both --n-perm and --n-perms for compatibility
    parser.add_argument("--n-perms", "--n-perm", dest="n_perm", type=int, default=5000, help="Number of permutations (default: 5000)")
    # Accept both --mask-path and --mask for compatibility
    parser.add_argument("--mask-path", "--mask", dest="mask_path", help="FSL mask file path (auto-detect if not provided)")
    # Accept both --canonical-order-csv and --canonical-csv for compatibility
    parser.add_argument("--canonical-order-csv", "--canonical-csv", dest="canonical_order_csv", help="Path to canonical subject order CSV/TSV")
    parser.add_argument("--correction", default="TFCE", choices=["TFCE", "GRF", "Cluster", "FDR"],
                        help="Correction: TFCE (non-parametric TFCE), Cluster/GRF (non-parametric cluster z=2.3), FDR (BH on vox_p). Default: TFCE")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()
    setup_logging(debug=args.debug)
    logger.debug(f"Arguments: {args}")

    if args.seed:
        runner = GroupStatsRunner(
            bids_root=args.bids_root,
            seed=args.seed,
            pipeline=args.pipeline,
            measure=args.measure,
            output_dir=args.output_dir,
            n_perm=args.n_perm,
            mask_path=args.mask_path,
            canonical_order_csv=args.canonical_order_csv,
            correction=args.correction,
        )
    else:
        runner = GroupStatsAlffRehoRunner(
            bids_root=args.bids_root,
            stat=args.stat_map,
            pipeline=args.pipeline,
            output_dir=args.output_dir,
            n_perm=args.n_perm,
            mask_path=args.mask_path,
            canonical_order_csv=args.canonical_order_csv,
            correction=args.correction,
        )

    success = runner.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
