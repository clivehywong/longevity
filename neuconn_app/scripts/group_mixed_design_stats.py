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
        self.correction = correction.upper()

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

            if len(self.canonical_order) != 72:
                logger.error(f"Expected 72 rows, got {len(self.canonical_order)}")
                return False

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
        """Step 3: Validate all 72 zmaps."""
        logger.info("\n[Step 3] Validating 72 zmaps...")
        
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
            valid_count = self.validation_df["exists"].sum()
            
            logger.debug(f"Validation results: {valid_count} valid, {error_count} errors")
            
            if error_count > 0:
                logger.error(f"Zmap validation failed: {error_count} errors")
                for idx, row in self.validation_df[self.validation_df["error"].notna()].iterrows():
                    logger.error(f"  {row['subject']} {row['session']}: {row['error']}")
                return False
            
            if valid_count != 72:
                logger.error(f"Expected 72 valid zmaps, got {valid_count}")
                return False
            
            self.zmaps_list = validator.get_canonical_zmaps_list(
                validation_df=self.validation_df,
                seed=seed_filter,
            )
            
            if len(self.zmaps_list) != 72:
                logger.error(f"Expected 72 zmaps, got {len(self.zmaps_list)}")
                return False
            
            logger.info(f"✓ All 72 zmaps validated and ready")
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
            expected_shape = (91, 109, 91, 72)
            
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
                cmd.extend(["--vxl", "-c", "3.1"])  # cluster-based GRF
            # FDR: no extra flag — randomise applies FDR correction by default
            
            logger.debug(f"Command: {' '.join(cmd)}")
            
            logs_dir = self.output_dir / "randomise_logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            
            stdout_log = logs_dir / "randomise_stdout.log"
            stderr_log = logs_dir / "randomise_stderr.log"
            
            with open(stdout_log, "w") as stdout_f, open(stderr_log, "w") as stderr_f:
                result = subprocess.run(cmd, stdout=stdout_f, stderr=stderr_f, timeout=3600)
            
            if result.returncode != 0:
                logger.error(f"randomise failed with return code {result.returncode}")
                try:
                    with open(stderr_log, "r") as f:
                        logger.error(f"stderr: {f.read()[:500]}")
                except:
                    pass
                return False
            
            logger.debug(f"randomise logs saved to {logs_dir}")
            logger.info(f"✓ randomise completed ({self.n_perm} permutations)")
            return True
        
        except subprocess.TimeoutExpired:
            logger.error("randomise timed out (>3600s)")
            return False
        except Exception as e:
            logger.error(f"Failed to run randomise: {e}")
            return False
    
    def _step_generate_report(self) -> bool:
        """Step 7: Generate summary report."""
        logger.info("\n[Step 7] Generating summary report...")
        
        try:
            randomise_dir = self.output_dir / "randomise_outputs"
            tfce_files = list(randomise_dir.glob("randomise_tfce_corrp_*.nii.gz"))
            logger.debug(f"Found {len(tfce_files)} TFCE output files")
            
            summary = {
                "pipeline": {
                    "seed": self.seed,
                    "pipeline": self.pipeline,
                    "measure": self.measure,
                    "n_permutations": self.n_perm,
                },
                "inputs": {
                    "n_subjects": 36,
                    "n_zmaps": 72,
                    "n_control": 40,
                    "n_walking": 32,
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
        """Parse randomise outputs for statistics."""
        stats = {"tfce_files": [], "fstat_files": []}
        
        try:
            tfce_corrp_files = sorted(randomise_dir.glob("randomise_tfce_corrp_*.nii.gz"))
            for fpath in tfce_corrp_files:
                try:
                    img = nib.load(str(fpath))
                    data = img.get_fdata()
                    voxels_sig = (data > 0.95).sum()
                    
                    stats["tfce_files"].append({
                        "filename": fpath.name,
                        "voxels_significant": int(voxels_sig),
                        "data_range": [float(np.min(data)), float(np.max(data))],
                    })
                except Exception as e:
                    logger.debug(f"Failed to parse {fpath.name}: {e}")
            
            fstat_files = sorted(randomise_dir.glob("randomise_fstat*.nii.gz"))
            for fpath in fstat_files:
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
        """Get standard space mask path or create one from merged NIfTI."""
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
    parser.add_argument("--seed", required=True, help="Seed CLI token (e.g., atlas-4S256Parcels:RH_Cont_Par_1 or sphere:x,y,z,r=6)")
    parser.add_argument("--pipeline", default="fc", choices=["fc", "fc_gsr", "ec"], help="Pipeline (default: fc)")
    parser.add_argument("--measure", default="pearson", help="Connectivity measure (default: pearson)")
    parser.add_argument("--output-dir", help="Output directory (default: derivatives/connectivity/<pipeline>/group/seed/.../)")
    # Accept both --n-perm and --n-perms for compatibility
    parser.add_argument("--n-perms", "--n-perm", dest="n_perm", type=int, default=5000, help="Number of permutations (default: 5000)")
    # Accept both --mask-path and --mask for compatibility
    parser.add_argument("--mask-path", "--mask", dest="mask_path", help="FSL mask file path (auto-detect if not provided)")
    # Accept both --canonical-order-csv and --canonical-csv for compatibility
    parser.add_argument("--canonical-order-csv", "--canonical-csv", dest="canonical_order_csv", help="Path to canonical subject order CSV/TSV")
    parser.add_argument("--correction", default="TFCE", choices=["TFCE", "GRF", "FDR"], help="Multiple comparison correction (default: TFCE)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()
    setup_logging(debug=args.debug)
    logger.debug(f"Arguments: {args}")

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

    success = runner.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
