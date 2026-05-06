#!/usr/bin/env python3
"""
Delta (Post−Pre) Group-Level Statistics Pipeline

Faster alternative to mixed-design ANOVA for Group×Time interaction.

**Workflow:**
1. Validate inputs (FSL tools, canonical CSV)
2. Load canonical subject order; drop unpaired subjects BEFORE computation
3. Collect ses-01 and ses-02 z-maps per subject
4. Compute per-subject delta maps: fslmaths ses02 -sub ses01 delta.nii.gz
5. Merge delta maps into 4D NIfTI (walking first, then control)
6. Generate two-sample t-test design files (NO -D flag)
7. Run FSL randomise WITHOUT -D, with -T (TFCE) or -c 2.3 (GRF)
8. Generate metadata.json with subject_order for visualization
9. Apply FDR if requested

**Usage:**
  python group_delta_stats.py \\
    --bids-root /path/to/project \\
    --seed atlas-4S256Parcels:RH_Cont_Par_1 \\
    --pipeline fc \\
    --measure pearson \\
    --n-perms 5000

**Dependencies:**
  - FSL (fslmaths, fslmerge, randomise must be in PATH)
  - Python: numpy, nibabel, pandas, subprocess
"""

import sys
import os
import argparse
import logging
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import subprocess

import numpy as np
import pandas as pd
import nibabel as nib

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.group_stats_validation import SubjectDataValidator
from utils.seed_viz import cli_token_to_seed_dir_name


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers (mirrors group_mixed_design_stats.py)
# ---------------------------------------------------------------------------

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


class DeltaStatsRunner:
    """Orchestrator for delta (Post−Pre) group-level statistics workflow.

    Computes per-subject Post−Pre difference maps, then runs a two-sample
    t-test (walking vs control) via FSL randomise. This is mathematically
    equivalent to the Group×Time interaction from a full mixed ANOVA, but
    dramatically faster (operates on N subjects rather than 2N sessions).
    """

    def __init__(
        self,
        bids_root: str,
        seed: Optional[str] = None,
        stat_map: Optional[str] = None,
        pipeline: str = "fc",
        measure: str = "pearson",
        output_dir: Optional[str] = None,
        n_perm: int = 5000,
        mask_path: Optional[str] = None,
        canonical_order_csv: Optional[str] = None,
        correction: str = "TFCE",
    ):
        if seed is None and stat_map is None:
            raise ValueError("Exactly one of seed or stat_map must be provided")
        if seed is not None and stat_map is not None:
            raise ValueError("Provide either seed or stat_map, not both")

        self.bids_root = Path(bids_root)
        self.seed = seed
        self.stat_map = stat_map
        self.pipeline = pipeline
        self.measure = measure
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
        elif seed is not None:
            seed_dir_name = cli_token_to_seed_dir_name(seed)
            self.output_dir = (
                self.bids_root
                / "derivatives" / "connectivity"
                / pipeline / "group" / "seed"
                / seed_dir_name / f"measure-{measure}" / "delta"
            )
        else:
            self.output_dir = (
                self.bids_root / "derivatives" / "connectivity"
                / pipeline / "group" / stat_map / "delta"
            )

        # State populated during run
        self.canonical_order: Optional[pd.DataFrame] = None
        # paired_subjects: list of (subject, group, ses01_path, ses02_path)
        self.paired_subjects: Optional[List[Tuple[str, str, str, str]]] = None
        self.delta_paths: Optional[Dict[str, str]] = None  # subject → delta path
        self.walking_subjects: Optional[List[str]] = None
        self.control_subjects: Optional[List[str]] = None
        self.merged_nifti_path: Optional[Path] = None

    # -----------------------------------------------------------------------
    # Main entry point
    # -----------------------------------------------------------------------

    def run(self) -> bool:
        """Execute full delta statistics pipeline."""
        try:
            logger.info("=" * 70)
            logger.info("Starting delta (Post−Pre) group statistics pipeline")
            if self.seed:
                logger.info(f"  Seed: {self.seed}")
            else:
                logger.info(f"  Stat map: {self.stat_map}")
            logger.info(f"  Pipeline: {self.pipeline}")
            logger.info(f"  Measure: {self.measure}")
            logger.info(f"  N permutations: {self.n_perm}")
            logger.info(f"  Correction: {self.correction}")
            logger.info("=" * 70)

            if not self._step_validate_inputs():
                return False
            if not self._step_load_canonical_order():
                return False
            if not self._step_collect_zmap_pairs():
                return False
            if not self._step_compute_deltas():
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

    # -----------------------------------------------------------------------
    # Step 1: Validate inputs
    # -----------------------------------------------------------------------

    def _step_validate_inputs(self) -> bool:
        """Step 1: Validate inputs."""
        logger.info("\n[Step 1] Validating inputs...")

        if not self.bids_root.exists():
            logger.error(f"BIDS root not found: {self.bids_root}")
            return False

        if self.seed is not None and ":" not in self.seed:
            logger.error(f"Seed must be in format 'atlas:seed_name', got: {self.seed}")
            return False

        if self.stat_map is not None and self.stat_map not in ("alff", "reho"):
            logger.error(f"stat_map must be 'alff' or 'reho', got: {self.stat_map}")
            return False

        valid_pipelines = ["fc", "fc_gsr", "ec"]
        if self.pipeline not in valid_pipelines:
            logger.error(f"Pipeline must be one of {valid_pipelines}, got: {self.pipeline}")
            return False

        if not self.canonical_order_csv.exists():
            logger.error(f"Canonical order CSV not found: {self.canonical_order_csv}")
            return False

        # Check FSL tools
        for tool in ("fslmaths", "fslmerge", "randomise"):
            result = subprocess.run(["which", tool], capture_output=True, timeout=5)
            if result.returncode != 0:
                logger.error(f"{tool} not found in PATH. Please ensure FSL is installed.")
                return False

        logger.info("✓ All inputs validated")
        return True

    # -----------------------------------------------------------------------
    # Step 2: Load canonical order, drop unpaired subjects
    # -----------------------------------------------------------------------

    def _step_load_canonical_order(self) -> bool:
        """Step 2: Load canonical subject order; drop unpaired subjects."""
        logger.info("\n[Step 2] Loading canonical subject order...")

        try:
            self.canonical_order = _to_canonical_order(_read_subject_table(self.canonical_order_csv))

            if len(self.canonical_order) == 0:
                logger.error("Canonical order is empty — no subjects found")
                return False

            # Drop unpaired subjects BEFORE any computation
            subject_session_counts = self.canonical_order.groupby("subject")["session"].count()
            unpaired = subject_session_counts[subject_session_counts != 2]
            if len(unpaired) > 0:
                logger.warning(
                    f"{len(unpaired)} subjects lack both sessions; dropping: {list(unpaired.index)}"
                )
                complete = subject_session_counts[subject_session_counts == 2].index
                self.canonical_order = self.canonical_order[
                    self.canonical_order["subject"].isin(complete)
                ].reset_index(drop=True)
                self.canonical_order["row_index"] = range(len(self.canonical_order))

            if len(self.canonical_order) == 0:
                logger.error("No paired subjects remain after dropping unpaired")
                return False

            n_subjects = self.canonical_order["subject"].nunique()
            control_count = (self.canonical_order["group"] == "control").sum() // 2
            walking_count = (self.canonical_order["group"] == "walking").sum() // 2
            logger.info(
                f"✓ Canonical order loaded: {n_subjects} subjects "
                f"({control_count} control, {walking_count} walking)"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to load canonical order: {e}")
            return False

    # -----------------------------------------------------------------------
    # Step 3: Collect ses-01 and ses-02 map pairs
    # -----------------------------------------------------------------------

    def _step_collect_zmap_pairs(self) -> bool:
        """Step 3: Find ses-01 and ses-02 maps for each subject."""
        logger.info("\n[Step 3] Collecting z-map pairs (ses-01 and ses-02)...")

        try:
            seed_filter = self.seed.split(":")[1] if self.seed and ":" in self.seed else None

            # Build per-subject, per-session path lookup
            subject_session_map: Dict[Tuple[str, str], Optional[str]] = {}

            if self.seed is not None:
                # Use SubjectDataValidator to find seed FC z-maps
                validator = SubjectDataValidator(
                    bids_root=str(self.bids_root),
                    canonical_order_csv=str(self.canonical_order_csv),
                    pipeline=self.pipeline,
                    measure=self.measure,
                )
                for _, row in self.canonical_order.iterrows():
                    key = (row["subject"], row["session"])
                    path = validator._find_zmap_file(row["subject"], row["session"], seed_filter)
                    subject_session_map[key] = str(path) if path else None
            else:
                # ALFF / ReHo maps
                map_entries = _find_alff_reho_maps(
                    self.bids_root, self.pipeline, self.canonical_order, self.stat_map
                )
                for subj, sess, _grp, path in map_entries:
                    subject_session_map[(subj, sess)] = path

            # Build paired list: each subject needs both sessions
            paired = []
            missing = []
            for subject in sorted(self.canonical_order["subject"].unique()):
                grp = self.canonical_order.loc[
                    self.canonical_order["subject"] == subject, "group"
                ].iloc[0]
                path01 = subject_session_map.get((subject, "ses-01"))
                path02 = subject_session_map.get((subject, "ses-02"))
                if path01 and path02:
                    paired.append((subject, grp, path01, path02))
                else:
                    missing.append(
                        f"{subject}: ses-01={'found' if path01 else 'MISSING'}, "
                        f"ses-02={'found' if path02 else 'MISSING'}"
                    )

            if missing:
                logger.warning(f"Dropping {len(missing)} subjects with incomplete maps:")
                for m in missing:
                    logger.warning(f"  {m}")

            if len(paired) == 0:
                logger.error("No subjects with both ses-01 and ses-02 maps found")
                return False

            # Check minimum per group
            n_walking = sum(1 for _, g, _, _ in paired if g == "walking")
            n_control = sum(1 for _, g, _, _ in paired if g == "control")
            if n_walking < 2 or n_control < 2:
                logger.error(
                    f"Need ≥2 subjects per group; got {n_walking} walking, {n_control} control"
                )
                return False

            self.paired_subjects = paired
            logger.info(f"✓ {len(paired)} subjects with paired maps ({n_walking} walking, {n_control} control)")
            return True

        except Exception as e:
            logger.error(f"Failed to collect z-map pairs: {e}")
            return False

    # -----------------------------------------------------------------------
    # Step 4: Compute per-subject delta maps
    # -----------------------------------------------------------------------

    def _step_compute_deltas(self) -> bool:
        """Step 4: Compute delta = ses-02 − ses-01 per subject via fslmaths."""
        logger.info("\n[Step 4] Computing delta maps (ses-02 − ses-01)...")

        try:
            delta_dir = self.output_dir / "delta_maps"
            delta_dir.mkdir(parents=True, exist_ok=True)

            self.delta_paths = {}
            errors = []

            for subject, group, ses01_path, ses02_path in self.paired_subjects:
                out_path = delta_dir / f"{subject}_delta.nii.gz"
                cmd = [
                    "fslmaths",
                    ses02_path,
                    "-sub", ses01_path,
                    str(out_path),
                ]
                logger.debug(f"  {subject}: fslmaths {Path(ses02_path).name} -sub {Path(ses01_path).name}")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode != 0:
                    errors.append(f"{subject}: fslmaths failed: {result.stderr[:200]}")
                    continue
                if not out_path.exists():
                    errors.append(f"{subject}: output not created: {out_path}")
                    continue
                self.delta_paths[subject] = str(out_path)

            if errors:
                for err in errors:
                    logger.error(f"  {err}")
                if len(self.delta_paths) == 0:
                    return False
                logger.warning(f"Proceeding with {len(self.delta_paths)} successful delta maps")

            logger.info(f"✓ {len(self.delta_paths)} delta maps computed → {delta_dir.name}/")
            return True

        except Exception as e:
            logger.error(f"Failed to compute delta maps: {e}")
            return False

    # -----------------------------------------------------------------------
    # Step 5: Merge delta maps into 4D NIfTI
    # -----------------------------------------------------------------------

    def _step_merge_4d_nifti(self) -> bool:
        """Step 5: Merge delta maps → 4D NIfTI (walking first, then control)."""
        logger.info("\n[Step 5] Merging delta maps into 4D NIfTI...")

        try:
            # Sort: walking subjects (alphabetical), then control subjects (alphabetical)
            walking_pairs = sorted(
                [(s, g, d) for s, g, _, _ in self.paired_subjects
                 for d in [self.delta_paths.get(s)] if d and g == "walking"],
                key=lambda x: x[0],
            )
            control_pairs = sorted(
                [(s, g, d) for s, g, _, _ in self.paired_subjects
                 for d in [self.delta_paths.get(s)] if d and g == "control"],
                key=lambda x: x[0],
            )

            self.walking_subjects = [s for s, _, _ in walking_pairs]
            self.control_subjects = [s for s, _, _ in control_pairs]

            ordered_paths = [d for _, _, d in walking_pairs] + [d for _, _, d in control_pairs]

            if not ordered_paths:
                logger.error("No delta maps to merge")
                return False

            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.merged_nifti_path = self.output_dir / "delta_4d.nii.gz"

            cmd = ["fslmerge", "-t", str(self.merged_nifti_path)] + ordered_paths
            logger.debug(f"Merging {len(ordered_paths)} delta maps...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                logger.error(f"fslmerge failed: {result.stderr}")
                return False

            if not self.merged_nifti_path.exists():
                logger.error(f"Merged NIfTI not created: {self.merged_nifti_path}")
                return False

            img = nib.load(str(self.merged_nifti_path))
            n1 = len(self.walking_subjects)
            n2 = len(self.control_subjects)
            logger.info(
                f"✓ Merged 4D delta NIfTI shape {img.shape} "
                f"({n1} walking + {n2} control = {n1+n2} subjects)"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to merge 4D NIfTI: {e}")
            return False

    # -----------------------------------------------------------------------
    # Step 6: Generate FSL design files (two-sample t-test)
    # -----------------------------------------------------------------------

    def _step_generate_design_files(self) -> bool:
        """Step 6: Generate FSL design files for two-sample t-test.

        Design: [1 0] for walking, [0 1] for control.
        Contrasts: walking > control, control > walking.
        NO -D flag, NO F-test file, NO exchangeability blocks.
        """
        logger.info("\n[Step 6] Generating FSL two-sample t-test design files...")

        try:
            n1 = len(self.walking_subjects)
            n2 = len(self.control_subjects)
            n_total = n1 + n2

            # design.mat
            mat_lines = [
                f"/NumWaves 2",
                f"/NumPoints {n_total}",
                "/Matrix",
            ]
            for _ in range(n1):
                mat_lines.append("1 0")
            for _ in range(n2):
                mat_lines.append("0 1")
            mat_content = "\n".join(mat_lines) + "\n"

            # design.con
            con_lines = [
                "/NumWaves 2",
                "/NumContrasts 2",
                "/Matrix",
                "1 -1",   # walking > control (walking increased more)
                "-1 1",   # control > walking
            ]
            con_content = "\n".join(con_lines) + "\n"

            self.output_dir.mkdir(parents=True, exist_ok=True)
            mat_path = self.output_dir / "design.mat"
            con_path = self.output_dir / "design.con"

            mat_path.write_text(mat_content)
            con_path.write_text(con_content)

            self.design_files = {"design.mat": mat_path, "design.con": con_path}

            logger.debug(f"design.mat: {n_total} rows, 2 columns")
            logger.debug(f"design.con: 2 contrasts (walking>control, control>walking)")
            logger.info(f"✓ Design files generated (two-sample t-test, {n1} vs {n2})")
            return True

        except Exception as e:
            logger.error(f"Failed to generate design files: {e}")
            return False

    # -----------------------------------------------------------------------
    # Step 7: Run FSL randomise (NO -D flag)
    # -----------------------------------------------------------------------

    def _step_run_randomise(self) -> bool:
        """Step 7: Run FSL randomise WITHOUT -D flag."""
        logger.info("\n[Step 7] Running FSL randomise (no -D, two-sample t-test)...")

        try:
            randomise_dir = self.output_dir / "randomise_outputs"
            randomise_dir.mkdir(parents=True, exist_ok=True)

            if self.mask_path and self.mask_path.exists():
                mask = str(self.mask_path)
            else:
                mask = self._get_standard_mask()
                if not mask:
                    logger.error("Could not determine brain mask path")
                    return False

            logger.debug(f"Using mask: {mask}")

            cmd = [
                "randomise",
                "-i", str(self.merged_nifti_path),
                "-o", str(randomise_dir / "delta"),
                "-d", str(self.design_files["design.mat"]),
                "-t", str(self.design_files["design.con"]),
                "-m", mask,
                "-n", str(self.n_perm),
                # NO -D flag — the [1,0/0,1] design is already correct
                # NO -e (no exchangeability blocks)
                # NO -f (no F-test)
            ]

            if self.correction == "TFCE":
                cmd.append("-T")
            elif self.correction == "GRF":
                cmd.extend(["-c", "2.3"])

            logger.debug(f"Command: {' '.join(cmd)}")

            logs_dir = self.output_dir / "randomise_logs"
            logs_dir.mkdir(parents=True, exist_ok=True)

            stdout_log = logs_dir / "randomise_stdout.log"
            stderr_log = logs_dir / "randomise_stderr.log"

            with open(stdout_log, "w") as so, open(stderr_log, "w") as se:
                result = subprocess.run(cmd, stdout=so, stderr=se)

            if result.returncode != 0:
                logger.error(f"randomise failed with exit code {result.returncode}")
                try:
                    logger.error(f"stderr: {stderr_log.read_text()[:500]}")
                except Exception:
                    pass
                return False

            logger.debug(f"Logs saved to: {logs_dir}")
            logger.info(f"✓ randomise completed ({self.n_perm} permutations)")

            if self.correction == "FDR":
                self._step_apply_fdr(randomise_dir, mask)

            return True

        except Exception as e:
            logger.error(f"Failed to run randomise: {e}")
            return False

    # -----------------------------------------------------------------------
    # Step 8: Generate metadata report
    # -----------------------------------------------------------------------

    def _step_generate_report(self) -> bool:
        """Step 8: Generate metadata.json with subject_order."""
        logger.info("\n[Step 8] Generating metadata report...")

        try:
            n_walking = len(self.walking_subjects)
            n_control = len(self.control_subjects)

            metadata = {
                "source": "delta",
                "pipeline": self.pipeline,
                "measure": self.measure,
                "correction": self.correction,
                "n_permutations": self.n_perm,
                "n_walking": n_walking,
                "n_control": n_control,
                "subject_order": {
                    "walking": [f"{s} ses-01→ses-02" for s in self.walking_subjects],
                    "control": [f"{s} ses-01→ses-02" for s in self.control_subjects],
                },
                "note": (
                    "Tests Group×Time interaction (Post−Pre change: Walking vs Control). "
                    "Individual z-maps available for 2×2 visualization."
                ),
            }

            if self.seed is not None:
                metadata["seed"] = self.seed
            else:
                metadata["stat_map"] = self.stat_map

            # Parse randomise outputs for statistics
            randomise_dir = self.output_dir / "randomise_outputs"
            metadata["statistics"] = self._parse_randomise_outputs(randomise_dir)

            metadata_path = self.output_dir / "metadata.json"
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)

            logger.debug(f"Metadata saved: {metadata_path}")
            logger.info(f"✓ Report generated: {metadata_path.name}")
            return True

        except Exception as e:
            logger.error(f"Failed to generate report: {e}")
            return False

    # -----------------------------------------------------------------------
    # Step 9 (optional): FDR correction
    # -----------------------------------------------------------------------

    def _step_apply_fdr(self, randomise_dir: Path, mask_path: str) -> None:
        """Apply Benjamini-Hochberg FDR to randomise vox_p maps."""
        from scipy.stats import rankdata  # noqa: PLC0415

        try:
            mask_img = nib.load(mask_path)
            mask_data = mask_img.get_fdata().astype(bool)
        except Exception as exc:
            logger.warning(f"Could not load mask for FDR; skipping: {exc}")
            return

        vox_p_files = sorted(randomise_dir.glob("delta_vox_p_tstat*.nii.gz"))
        if not vox_p_files:
            logger.warning("No delta_vox_p_tstat*.nii.gz found for FDR correction.")
            return

        for vox_p_path in vox_p_files:
            try:
                img = nib.load(str(vox_p_path))
                data = img.get_fdata()  # values = 1-p

                p_vals = 1.0 - data
                in_mask = mask_data & np.isfinite(p_vals)
                flat_p = p_vals[in_mask]

                n = len(flat_p)
                order = np.argsort(flat_p)
                ranks = rankdata(flat_p, method="ordinal")
                q_vals = np.minimum(1.0, flat_p * n / ranks)
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

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _parse_randomise_outputs(self, randomise_dir: Path) -> Dict[str, Any]:
        """Parse randomise outputs for statistics."""
        stats: Dict[str, Any] = {"corrp_files": []}

        corrp_patterns = [
            "delta_tfce_corrp_*.nii.gz",
            "delta_clustere_corrp_*.nii.gz",
            "delta_fdr_corrp_*.nii.gz",
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
        except Exception as e:
            logger.debug(f"Error parsing outputs: {e}")

        return stats

    def _get_standard_mask(self) -> Optional[str]:
        """Get standard space mask path.

        Priority per AGENTS.md §6: dilated MNI mask required for voxelwise analyses.
        """
        candidates = [
            self.bids_root / "atlases" / "MNI152NLin2009cAsym_res-02_desc-brain_mask_dilated.nii.gz",
            self.bids_root / "atlases" / "MNI152_T1_2mm_brain_mask_dil.nii.gz",
        ]
        for c in candidates:
            if c.exists():
                logger.info(f"Using project dilated MNI mask: {c}")
                return str(c)

        fsl_dir = os.environ.get("FSLDIR", "")
        if fsl_dir:
            fsl_mask = Path(fsl_dir) / "data" / "standard" / "MNI152_T1_2mm_brain_mask.nii.gz"
            if fsl_mask.exists():
                logger.info(f"Using FSL standard mask: {fsl_mask}")
                return str(fsl_mask)

        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delta (Post−Pre) group-level statistics pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--bids-root", required=True, help="Project root directory")
    parser.add_argument(
        "--seed", default=None,
        help="Seed CLI token (e.g., 'atlas-4S256Parcels:LH_Cont_PFCl_3') for seed FC",
    )
    parser.add_argument(
        "--stat-map", default=None, choices=["alff", "reho"],
        help="Stat map type for ALFF/ReHo analysis (alternative to --seed)",
    )
    parser.add_argument("--pipeline", default="fc", help="XCP-D pipeline (default: fc)")
    parser.add_argument("--measure", default="pearson", help="Connectivity measure (default: pearson)")
    parser.add_argument("--n-perms", type=int, default=5000, help="Number of permutations (default: 5000)")
    parser.add_argument(
        "--correction", default="TFCE", choices=["TFCE", "GRF", "FDR"],
        help="Correction method (default: TFCE)",
    )
    parser.add_argument("--mask", default=None, help="Brain mask path (optional)")
    parser.add_argument("--canonical-csv", default=None, help="Canonical subject order CSV/TSV (optional)")
    parser.add_argument("--output-dir", default=None, help="Output directory (optional)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()
    setup_logging(args.debug)

    if args.seed is None and args.stat_map is None:
        parser.error("Provide either --seed or --stat-map")
    if args.seed is not None and args.stat_map is not None:
        parser.error("Provide either --seed or --stat-map, not both")

    runner = DeltaStatsRunner(
        bids_root=args.bids_root,
        seed=args.seed,
        stat_map=args.stat_map,
        pipeline=args.pipeline,
        measure=args.measure,
        n_perm=args.n_perms,
        mask_path=args.mask,
        canonical_order_csv=args.canonical_csv,
        output_dir=args.output_dir,
        correction=args.correction,
    )

    success = runner.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
