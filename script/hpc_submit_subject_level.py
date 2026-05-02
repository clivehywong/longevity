#!/usr/bin/env python3
"""
HPC Subject-Level Job Submission Wrapper for SLURM Array Parallelization

Submits SLURM job arrays for subject-session-level analyses driven by XCP-D:
- Seed-based connectivity (compute_seed_connectivity_xcpd.py)
- Network connectivity (compute_network_connectivity_xcpd.py)

Local measures are now produced directly by XCP-D (no separate submission).

Supports test mode, dry-run, and manifest tracking for group-level readiness.
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# ---------------------------------------------------------------------------
# XCP-D pipeline constants
# ---------------------------------------------------------------------------

#: All 8 connectivity measures exported by the backends
DEFAULT_XCPD_MEASURES = ",".join([
    "pearson", "spearman", "partial_correlation", "plv",
    "wpli", "coherence", "amplitude_envelope_correlation", "mutual_information",
])

#: 5 recommended XCP-D built-in atlases (mirrors xcpd_atlases.recommended_xcpd_atlases)
DEFAULT_XCPD_ATLASES: List[str] = [
    "4S256Parcels", "4S456Parcels", "Glasser", "Gordon", "Tian"
]


# ---------------------------------------------------------------------------
# Public helpers: session-pair discovery + SLURM script generation
# ---------------------------------------------------------------------------

def build_xcpd_session_pairs(
    bids_root: str | Path,
    pipeline: str = "fc",
    subjects: Optional[List[str]] = None,
) -> List[Tuple[str, str]]:
    """Return (subject, session) pairs available for *pipeline* in XCP-D outputs.

    Scans ``bids_root/derivatives/preprocessing/xcpd/{pipeline}/`` for
    ``sub-*/ses-*`` directories.  Falls back to scanning ``bids_root/bids/``
    (or ``bids_root`` directly if it contains sub-* dirs) with the two
    canonical sessions ``ses-01``/``ses-02`` when XCP-D outputs are absent.

    Parameters
    ----------
    bids_root:
        Project root (parent of ``bids/``).
    pipeline:
        XCP-D pipeline name (``fc``, ``fc_gsr``, ``ec``).
    subjects:
        Optional allow-list; when given only these subjects are included.
    """
    bids_root = Path(bids_root)
    xcpd_pl_dir = bids_root / "derivatives" / "preprocessing" / "xcpd" / pipeline
    pairs: List[Tuple[str, str]] = []

    if xcpd_pl_dir.exists():
        for sub_dir in sorted(xcpd_pl_dir.glob("sub-*")):
            if not sub_dir.is_dir():
                continue
            sub = sub_dir.name
            if subjects and sub not in subjects:
                continue
            for ses_dir in sorted(sub_dir.glob("ses-*")):
                if ses_dir.is_dir():
                    pairs.append((sub, ses_dir.name))
        return pairs

    # Fallback: scan BIDS tree
    bids_dir = bids_root / "bids" if (bids_root / "bids").exists() else bids_root
    for sub_dir in sorted(bids_dir.glob("sub-*")):
        if not sub_dir.is_dir():
            continue
        sub = sub_dir.name
        if subjects and sub not in subjects:
            continue
        for ses in ("ses-01", "ses-02"):
            if (sub_dir / ses).exists():
                pairs.append((sub, ses))
    return pairs


def generate_xcpd_subject_script(
    analysis: str,
    pipeline: str,
    measures: str,
    seeds: Optional[List[str]],
    atlases: Optional[List[str]],
    bids_root: str,
    out_root: str,
    session_pairs: List[Tuple[str, str]],
    log_dir: str = "logs",
    time_limit: str = "06:00:00",
    mem: str = "16G",
    cpus: int = 4,
    partition: str = "cpu-long",
    max_parallel: int = 20,
    tr: float = 0.8,
    force: bool = False,
    test_mode: bool = False,
) -> str:
    """Generate a SLURM array bash script for XCP-D-driven subject-level analysis.

    Parameters
    ----------
    analysis:
        ``"seed"`` → ``compute_seed_connectivity_xcpd.py``
        ``"network"`` → ``compute_network_connectivity_xcpd.py``
    pipeline:
        XCP-D pipeline name propagated to the backend (``--pipeline``).
    measures:
        Comma-separated connectivity measures propagated to ``--measures``.
    seeds:
        Seed specs (repeatable ``--seed`` flags) — required for seed analysis.
    atlases:
        Atlas names (repeatable ``--atlas`` flags) — for network analysis.
        Defaults to :data:`DEFAULT_XCPD_ATLASES` when *None*.
    bids_root:
        Project root path embedded in the script.
    out_root:
        Output root embedded in the script (``--out-root``).
    session_pairs:
        Ordered list of ``(subject, session)`` tuples; determines array size.
    log_dir:
        SLURM log directory embedded in the ``#SBATCH`` directives.
    time_limit, mem, cpus, partition, max_parallel:
        SLURM resource parameters.
    tr:
        Repetition time in seconds (passed to backend as ``--tr``).
    force:
        When True append ``--force`` to the backend call.
    test_mode:
        When True restrict to the first 2 session pairs.
    """
    if analysis not in ("seed", "network"):
        raise ValueError(f"analysis must be 'seed' or 'network', got {analysis!r}")

    effective_pairs = session_pairs[:2] if test_mode else list(session_pairs)
    if not effective_pairs:
        raise ValueError("session_pairs is empty — nothing to submit")

    n_jobs = len(effective_pairs)
    limit = min(max_parallel, n_jobs)

    subjects_arr = " ".join(f'"{sub}"' for sub, _ in effective_pairs)
    sessions_arr = " ".join(f'"{ses}"' for _, ses in effective_pairs)

    force_flag = " \\\n    --force" if force else ""

    if analysis == "seed":
        if not seeds:
            raise ValueError("seeds list is required for analysis='seed'")
        seed_lines = "\n    ".join(
            f"--seed {shlex.quote(s)} \\" for s in seeds
        )
        backend = (
            f"python3 script/compute_seed_connectivity_xcpd.py \\\n"
            f"    --bids-root \"{bids_root}\" \\\n"
            f"    --subject \"$SUBJECT\" \\\n"
            f"    --session \"$SESSION\" \\\n"
            f"    --pipeline {pipeline} \\\n"
            f"    {seed_lines}\n"
            f"    --measures {shlex.quote(measures)} \\\n"
            f"    --out-root \"{out_root}\" \\\n"
            f"    --tr {tr}{force_flag}"
        )
    else:  # network
        effective_atlases = atlases if atlases else DEFAULT_XCPD_ATLASES
        atlas_lines = "\n    ".join(
            f"--atlas {a} \\" for a in effective_atlases
        )
        backend = (
            f"python3 script/compute_network_connectivity_xcpd.py \\\n"
            f"    --bids-root \"{bids_root}\" \\\n"
            f"    --subject \"$SUBJECT\" \\\n"
            f"    --session \"$SESSION\" \\\n"
            f"    --pipeline {pipeline} \\\n"
            f"    {atlas_lines}\n"
            f"    --measures {shlex.quote(measures)} \\\n"
            f"    --out-root \"{out_root}\" \\\n"
            f"    --tr {tr}{force_flag}"
        )

    script = f"""#!/bin/bash
# SLURM XCP-D Subject-Level {analysis.capitalize()} Connectivity Array
# Generated: {datetime.now().isoformat()}
# Pipeline: {pipeline}  Measures: {measures}

#SBATCH --job-name={analysis}_connectivity
#SBATCH --array=1-{n_jobs}%{limit}
#SBATCH --time={time_limit}
#SBATCH --mem={mem}
#SBATCH --cpus-per-task={cpus}
#SBATCH --partition={partition}
#SBATCH --output={log_dir}/{analysis}_%A_%a.out
#SBATCH --error={log_dir}/{analysis}_%A_%a.err

set -euo pipefail

# ---------- subject/session lookup (1-based SLURM index) ----------
SUBJECTS_ARRAY=({subjects_arr})
SESSIONS_ARRAY=({sessions_arr})
IDX=$(( SLURM_ARRAY_TASK_ID - 1 ))
SUBJECT="${{SUBJECTS_ARRAY[$IDX]}}"
SESSION="${{SESSIONS_ARRAY[$IDX]}}"

LOG_FILE="{log_dir}/{analysis}_${{SLURM_ARRAY_JOB_ID}}_${{SLURM_ARRAY_TASK_ID}}_${{SUBJECT}}_${{SESSION}}.log"

log_info() {{ echo "[$(date +'%Y-%m-%d %H:%M:%S')] [INFO] $*" | tee -a "$LOG_FILE"; }}
log_error() {{ echo "[$(date +'%Y-%m-%d %H:%M:%S')] [ERROR] $*" | tee -a "$LOG_FILE"; }}

log_info "Starting {analysis} for $SUBJECT $SESSION (array task ${{SLURM_ARRAY_TASK_ID}}/${{SLURM_ARRAY_TASK_COUNT:-{n_jobs}}})"

# ---------- manifest: expected marker ----------
mkdir -p outputs/expected outputs/done
touch "outputs/expected/${{SUBJECT}}_${{SESSION}}_{analysis}.expected"

# ---------- backend ----------
if {backend} \\
    >> "$LOG_FILE" 2>&1; then
    log_info "SUCCESS: {analysis} for $SUBJECT $SESSION"
    touch "outputs/done/${{SUBJECT}}_${{SESSION}}_{analysis}.done"
else
    log_error "FAILED: {analysis} for $SUBJECT $SESSION"
    exit 1
fi
"""
    return script


class SubjectLevelHPCSubmitter:
    """Manage subject-level HPC job array submission and monitoring"""

    def __init__(
        self,
        config_file: Optional[str] = None,
        log_dir: str = "logs",
        output_dir: str = "results",
    ):
        """
        Initialize submitter.

        Args:
            config_file: Path to connectivity_config.yaml (default: .github/connectivity_config.yaml)
            log_dir: Directory for SLURM logs
            output_dir: Base output directory for results
        """
        self.log_dir = Path(log_dir)
        self.output_dir = Path(output_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Load config
        if config_file is None:
            config_file = ".github/connectivity_config.yaml"

        self.config_path = Path(config_file)
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config not found: {self.config_path}")

        with open(self.config_path, "r") as f:
            self.config = yaml.safe_load(f)

        self._validate_config()
        self._init_subjects()
        self._init_analyses()

    def _validate_config(self):
        """Validate config structure"""
        required_sections = ["atlases", "seeds", "hpc", "preprocessing", "output"]
        for section in required_sections:
            if section not in self.config:
                raise ValueError(f"Config missing required section: {section}")

        hpc_config = self.config.get("hpc", {})
        if "session_level" not in hpc_config:
            raise ValueError("Config missing hpc.session_level")

    def _init_subjects(self):
        """Initialize subject list from BIDS directory"""
        self.bids_root = Path("bids")
        if not self.bids_root.exists():
            raise FileNotFoundError("BIDS directory not found: bids/")

        # Get all subjects sorted
        subject_dirs = sorted(self.bids_root.glob("sub-*"))
        self.subjects = [d.name for d in subject_dirs if d.is_dir()]

        if not self.subjects:
            raise ValueError("No subjects found in BIDS directory")

        self.n_subjects = len(self.subjects)

        # Extract subject numbers for array indexing
        self.subject_numbers = []
        for sub in self.subjects:
            try:
                num = int(sub.split("-")[1])
                self.subject_numbers.append(num)
            except (IndexError, ValueError) as e:
                raise ValueError(f"Invalid subject format: {sub}") from e

    def _init_analyses(self):
        """Initialize analysis lists from config"""
        # Seeds
        self.seeds = list(self.config["seeds"].keys())
        self.n_seeds = len(self.seeds)

        # Atlases
        self.atlases = list(self.config["atlases"].keys())

        # Sessions (hardcoded from spec)
        self.sessions = ["ses-01", "ses-02"]
        self.n_sessions = len(self.sessions)

        # Analysis types
        self.analysis_types = ["local_measures", "seed_connectivity", "network_connectivity"]

    def _get_subject_from_index(self, array_idx: int) -> str:
        """
        Get subject ID from SLURM array task index.

        Args:
            array_idx: 1-based SLURM array index

        Returns:
            Subject ID (e.g., 'sub-033')
        """
        if array_idx < 1 or array_idx > self.n_subjects:
            raise ValueError(f"Array index {array_idx} out of range [1, {self.n_subjects}]")

        return self.subjects[array_idx - 1]

    def _get_fmriprep_bold(
        self, subject: str, session: str, space: str = "MNI152NLin2009cAsym", res: int = 2
    ) -> Optional[Path]:
        """
        Get path to preprocessed BOLD file for a subject-session.

        Args:
            subject: Subject ID (e.g., 'sub-033')
            session: Session label (e.g., 'ses-01')
            space: BOLD space
            res: Resolution

        Returns:
            Path to BOLD file or None if not found
        """
        fmriprep_root = Path("fmriprep")
        if not fmriprep_root.exists():
            return None

        # Search for BOLD files matching pattern
        pattern = f"{subject}/{session}/func/{subject}_{session}_space-{space}_res-{res}_desc-preproc_bold.nii.gz"
        bold_file = fmriprep_root / pattern

        return bold_file if bold_file.exists() else None

    def _get_fmriprep_confounds(
        self, subject: str, session: str
    ) -> Optional[Path]:
        """
        Get path to confounds TSV for a subject-session.

        Args:
            subject: Subject ID
            session: Session label

        Returns:
            Path to confounds TSV or None if not found
        """
        fmriprep_root = Path("fmriprep")
        if not fmriprep_root.exists():
            return None

        # Search for confounds file
        confounds_pattern = f"{subject}/{session}/func/{subject}_{session}_desc-confounds_timeseries.tsv"
        confounds_file = fmriprep_root / confounds_pattern

        return confounds_file if confounds_file.exists() else None

    def _check_fmriprep_available(self) -> bool:
        """Check if fMRIPrep outputs exist for sufficient subjects"""
        count = 0
        for subject in self.subjects[:5]:  # Check first 5
            for session in self.sessions:
                bold_file = self._get_fmriprep_bold(subject, session)
                if bold_file:
                    count += 1

        return count > 0

    def _check_disk_space(self, required_gb: float = 500) -> bool:
        """
        Check if sufficient disk space available.

        Args:
            required_gb: Required GB

        Returns:
            True if available, False otherwise
        """
        stat = os.statvfs(self.output_dir)
        available_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
        return available_gb >= required_gb

    def validate_requirements(self, verbose: bool = True) -> bool:
        """
        Validate all requirements for job submission.

        Args:
            verbose: Print validation messages

        Returns:
            True if all checks pass, False otherwise
        """
        checks = {
            "Config loaded": self.config is not None,
            "Subjects found": self.n_subjects > 0,
            "Seeds found": self.n_seeds > 0,
            "fMRIPrep available": self._check_fmriprep_available(),
            "Disk space": self._check_disk_space(),
            "SLURM available": self._check_slurm_available(),
        }

        if verbose:
            print("\n" + "=" * 70)
            print("PRE-SUBMISSION VALIDATION")
            print("=" * 70)
            for check, result in checks.items():
                status = "✓" if result else "✗"
                print(f"  [{status}] {check}")

            print(f"\nConfiguration:")
            print(f"  - Subjects: {self.n_subjects}")
            print(f"  - Sessions: {self.n_sessions}")
            print(f"  - Seeds: {self.n_seeds}")
            print(f"  - Atlases: {len(self.atlases)}")
            print(f"  - Total jobs (subject×session): {self.n_subjects * self.n_sessions}")
            print("=" * 70 + "\n")

        return all(checks.values())

    @staticmethod
    def _check_slurm_available() -> bool:
        """Check if SLURM is available"""
        try:
            result = subprocess.run(
                ["which", "sbatch"], capture_output=True, timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def generate_template_script(
        self,
        test_mode: bool = False,
    ) -> str:
        """
        Generate SLURM template script.

        Args:
            test_mode: If True, limit to 2 subjects

        Returns:
            Template script content
        """
        # Determine job array size
        n_jobs = 2 if test_mode else self.n_subjects
        array_limit = min(20, n_jobs)  # Max 20 parallel

        # Get HPC config
        hpc_cfg = self.config["hpc"]["session_level"]
        time_hours = hpc_cfg.get("time_limit_hours", 6)
        mem = hpc_cfg.get("mem_per_seed", "16G")
        cpus = hpc_cfg.get("cpus_per_task", 4)
        partition = hpc_cfg.get("partition", "cpu-long")
        job_name = hpc_cfg.get("job_name_prefix", "subject_level")

        # QoS if specified
        qos_line = ""
        if hpc_cfg.get("qos"):
            qos_line = f"#SBATCH --qos={hpc_cfg['qos']}\n"

        script = f"""#!/bin/bash
# SLURM Subject-Level Connectivity Analysis Job Array
# Generated: {datetime.now().isoformat()}

#SBATCH --job-name={job_name}_connectivity
#SBATCH --array=1-{n_jobs}%{array_limit}
#SBATCH --time={time_hours}:00:00
#SBATCH --mem={mem}
#SBATCH --cpus-per-task={cpus}
#SBATCH --partition={partition}
{qos_line}#SBATCH --output={self.log_dir}/subject_level_%A_%a.out
#SBATCH --error={self.log_dir}/subject_level_%A_%a.err

# ============================================================================
# Subject-Level Connectivity Analysis Pipeline
# Runs local measures, seed connectivity, and network connectivity
# for each subject-session pair
# ============================================================================

set -euo pipefail

# Configuration
REPO_ROOT="{Path.cwd()}"
FMRIPREP_ROOT="${{REPO_ROOT}}/fmriprep"
OUTPUT_ROOT="{self.output_dir}"
CONFIG_FILE=".github/connectivity_config.yaml"
LOG_DIR="{self.log_dir}"

# SLURM variables
ARRAY_ID=${{SLURM_ARRAY_TASK_ID}}
JOB_ID=${{SLURM_ARRAY_JOB_ID}}

# ============================================================================
# Helper Functions
# ============================================================================

log_info() {{
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [INFO] $@" | tee -a "${{LOG_FILE}}"
}}

log_error() {{
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [ERROR] $@" | tee -a "${{LOG_FILE}}"
}}

fail_marker() {{
    local subject=$1
    local session=$2
    local analysis=$3
    touch "${{LOG_DIR}}/.${{subject}}_${{session}}_${{analysis}}.failed"
}}

success_marker() {{
    local subject=$1
    local session=$2
    local analysis=$3
    rm -f "${{LOG_DIR}}/.${{subject}}_${{session}}_${{analysis}}.failed"
}}

get_subject_from_index() {{
    local idx=$1
    # Dynamically fetch subject from array index
    # This relies on BIDS directory being in sorted order
    cd "${{REPO_ROOT}}"
    python3 -c "
import sys
sys.path.insert(0, 'script')
from hpc_submit_subject_level import SubjectLevelHPCSubmitter
submitter = SubjectLevelHPCSubmitter()
print(submitter._get_subject_from_index($idx))
"
}}

# ============================================================================
# Main Execution
# ============================================================================

# Get subject ID for this array task
SUBJECT=$(get_subject_from_index $ARRAY_ID)
LOG_FILE="${{LOG_DIR}}/subject_level_${{JOB_ID}}_${{ARRAY_ID}}_${{SUBJECT}}.log"

log_info "Starting subject-level analysis for $SUBJECT (array task $ARRAY_ID/${{SLURM_ARRAY_TASK_COUNT}})"
log_info "Job ID: $JOB_ID | Array ID: $ARRAY_ID"

cd "$REPO_ROOT"

# Process both sessions
for SESSION in ses-01 ses-02; do
    log_info "Processing $SUBJECT $SESSION"
    
    # Find BOLD file
    BOLD_FILE=$(find "$FMRIPREP_ROOT" -name "${{SUBJECT}}_${{SESSION}}_*_desc-preproc_bold.nii.gz" | head -1)
    
    if [[ ! -f "$BOLD_FILE" ]]; then
        log_error "BOLD file not found for $SUBJECT $SESSION"
        continue
    fi
    
    # Find confounds file
    CONFOUNDS_FILE=$(find "$FMRIPREP_ROOT" -name "${{SUBJECT}}_${{SESSION}}_*desc-confounds_timeseries.tsv" | head -1)
    
    if [[ ! -f "$CONFOUNDS_FILE" ]]; then
        log_error "Confounds file not found for $SUBJECT $SESSION"
        continue
    fi
    
    log_info "BOLD: $BOLD_FILE"
    log_info "Confounds: $CONFOUNDS_FILE"
    
    # ========================================================================
    # 1. LOCAL MEASURES
    # ========================================================================
    
    ANALYSIS="local_measures"
    LOCAL_OUTPUT="${{OUTPUT_ROOT}}/local_measures/${{SUBJECT}}_${{SESSION}}"
    
    log_info "Running $ANALYSIS for $SUBJECT $SESSION"
    
    if python3 script/compute_local_measures.py \\
        --fmriprep "$FMRIPREP_ROOT" \\
        --output "$LOCAL_OUTPUT" \\
        --subjects "$SUBJECT" \\
        --sessions "$SESSION" \\
        --tr 0.8 \\
        --low-freq 0.01 \\
        --high-freq 0.1 \\
        --config "$CONFIG_FILE" \\
        >> "${{LOG_FILE}}" 2>&1; then
        
        log_info "$ANALYSIS completed successfully"
        success_marker "$SUBJECT" "$SESSION" "$ANALYSIS"
        
        # Record in manifest
        python3 script/hpc_manifest.py \\
            --manifest "${{OUTPUT_ROOT}}/.manifest.json" \\
            record \\
            --subject "$SUBJECT" \\
            --session "$SESSION" \\
            --seed "N/A" \\
            --atlas "N/A" \\
            --status complete \\
            --output "$LOCAL_OUTPUT" \\
            --job-id "$JOB_ID" 2>&1 | tee -a "${{LOG_FILE}}" || true
    else
        log_error "$ANALYSIS failed"
        fail_marker "$SUBJECT" "$SESSION" "$ANALYSIS"
    fi
    
    # ========================================================================
    # 2. SEED-BASED CONNECTIVITY (all seeds)
    # ========================================================================
    
    ANALYSIS="seed_connectivity"
    SEED_OUTPUT_BASE="${{OUTPUT_ROOT}}/seed_based"
    
    log_info "Running $ANALYSIS for $SUBJECT $SESSION"
    
    # Get seeds from config using Python
    SEEDS=$(python3 -c "
import yaml
cfg = yaml.safe_load(open('$CONFIG_FILE'))
print(' '.join(cfg['seeds'].keys()))
")
    
    for SEED in $SEEDS; do
        for ATLAS in DiFuMo256 Schaefer400; do
            SEED_OUTPUT="${{SEED_OUTPUT_BASE}}/${{ATLAS}}/${{SEED}}/${{SUBJECT}}_${{SESSION}}"
            
            if python3 script/seed_based_connectivity.py \\
                --fmriprep "$FMRIPREP_ROOT" \\
                --seeds script/motor_cerebellar_seeds.json \\
                --metadata bids/participants.tsv \\
                --output "$SEED_OUTPUT" \\
                --seed-names "$SEED" \\
                --space MNI152NLin2009cAsym \\
                --high-pass 0.01 \\
                --low-pass 0.1 \\
                >> "${{LOG_FILE}}" 2>&1; then
                
                log_info "Seed $SEED completed for $ATLAS"
                success_marker "$SUBJECT" "$SESSION" "$SEED"
                
                python3 script/hpc_manifest.py \\
                    --manifest "${{OUTPUT_ROOT}}/.manifest.json" \\
                    record \\
                    --subject "$SUBJECT" \\
                    --session "$SESSION" \\
                    --seed "$SEED" \\
                    --atlas "$ATLAS" \\
                    --status complete \\
                    --output "$SEED_OUTPUT" \\
                    --job-id "$JOB_ID" 2>&1 | tee -a "${{LOG_FILE}}" || true
            else
                log_error "Seed $SEED failed for $ATLAS"
                fail_marker "$SUBJECT" "$SESSION" "$SEED"
            fi
        done
    done
    
    # ========================================================================
    # 3. NETWORK CONNECTIVITY (all atlases)
    # ========================================================================
    
    ANALYSIS="network_connectivity"
    
    log_info "Running $ANALYSIS for $SUBJECT $SESSION"
    
    for ATLAS in DiFuMo256 Schaefer400; do
        NETWORK_OUTPUT="${{OUTPUT_ROOT}}/network_connectivity/${{ATLAS}}/${{SUBJECT}}_${{SESSION}}"
        
        if python3 script/compute_network_connectivity.py \\
            --bold "$BOLD_FILE" \\
            --confounds "$CONFOUNDS_FILE" \\
            --output "$NETWORK_OUTPUT" \\
            --atlas "$ATLAS" \\
            --tr 0.8 \\
            --high-pass 0.01 \\
            --low-pass 0.1 \\
            --smoothing 6.0 \\
            >> "${{LOG_FILE}}" 2>&1; then
            
            log_info "Network connectivity completed for $ATLAS"
            success_marker "$SUBJECT" "$SESSION" "$ANALYSIS"
            
            python3 script/hpc_manifest.py \\
                --manifest "${{OUTPUT_ROOT}}/.manifest.json" \\
                record \\
                --subject "$SUBJECT" \\
                --session "$SESSION" \\
                --seed "N/A" \\
                --atlas "$ATLAS" \\
                --status complete \\
                --output "$NETWORK_OUTPUT" \\
                --job-id "$JOB_ID" 2>&1 | tee -a "${{LOG_FILE}}" || true
        else
            log_error "Network connectivity failed for $ATLAS"
            fail_marker "$SUBJECT" "$SESSION" "$ANALYSIS"
        fi
    done
    
done

log_info "Completed all analyses for $SUBJECT"
"""
        return script

    def generate_template_script_from_file(
        self, template_path: Optional[str] = None, test_mode: bool = False
    ) -> str:
        """
        Load template from file if available, otherwise generate.

        Args:
            template_path: Path to template file
            test_mode: If True, limit to 2 subjects

        Returns:
            Template script content
        """
        if template_path and Path(template_path).exists():
            with open(template_path, "r") as f:
                return f.read()

        return self.generate_template_script(test_mode=test_mode)

    def submit_job_array(
        self,
        test_mode: bool = False,
        dry_run: bool = False,
    ) -> Optional[str]:
        """
        Submit SLURM job array.

        Args:
            test_mode: Only submit jobs for 2 subjects
            dry_run: Print script without submitting

        Returns:
            SLURM job ID or None if dry_run or submission failed
        """
        # Generate template first (dry-run doesn't need validation)
        template_script = self.generate_template_script(test_mode=test_mode)

        if dry_run:
            print("\n" + "=" * 70)
            print("DRY RUN: SLURM Script")
            print("=" * 70 + "\n")
            print(template_script)
            print("\n" + "=" * 70 + "\n")
            return None

        # Validate requirements only for actual submission
        if not self.validate_requirements(verbose=True):
            if not self._check_slurm_available():
                print("Warning: SLURM not available. Use --dry-run to test.")
            return None

        # Write to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, dir=self.log_dir
        ) as f:
            f.write(template_script)
            script_path = f.name

        try:
            # Submit job
            result = subprocess.run(
                ["sbatch", script_path],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )

            # Extract job ID
            output_line = result.stdout.strip()
            # Format: "Submitted batch job 12345"
            job_id = output_line.split()[-1]

            print("\n" + "=" * 70)
            print("JOB SUBMITTED SUCCESSFULLY")
            print("=" * 70)
            print(f"Job ID: {job_id}")
            print(f"Script: {script_path}")
            print(f"Log dir: {self.log_dir}")
            print(f"Output dir: {self.output_dir}")
            if test_mode:
                print("(Test mode: 2 subjects only)")
            print("=" * 70 + "\n")

            return job_id

        except subprocess.CalledProcessError as e:
            print(f"Error submitting job: {e.stderr}", file=sys.stderr)
            return None
        except subprocess.TimeoutExpired:
            print("Error: Job submission timed out", file=sys.stderr)
            return None
        finally:
            # Keep script for reference but don't delete
            pass

    def check_job_array_status(self, job_id: str) -> Dict:
        """
        Check status of SLURM job array.

        Args:
            job_id: SLURM job ID

        Returns:
            Status dictionary
        """
        try:
            result = subprocess.run(
                ["squeue", "-j", job_id, "-o", "%T %R"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return {"status": "NOT_FOUND", "job_id": job_id}

            # Parse output
            lines = result.stdout.strip().split("\n")
            if len(lines) < 2:
                return {"status": "UNKNOWN", "job_id": job_id}

            # Count job states
            states = {}
            for line in lines[1:]:  # Skip header
                parts = line.split()
                if parts:
                    state = parts[0]
                    states[state] = states.get(state, 0) + 1

            return {
                "job_id": job_id,
                "states": states,
                "total_jobs": sum(states.values()),
            }

        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {"status": "ERROR", "job_id": job_id}

    def load_manifest(self) -> Dict:
        """Load and display manifest status"""
        manifest_path = self.output_dir / ".manifest.json"

        if not manifest_path.exists():
            print("Manifest not yet created")
            return {}

        with open(manifest_path, "r") as f:
            manifest = json.load(f)

        return manifest

    def print_summary(self):
        """Print summary of submission configuration"""
        print("\n" + "=" * 70)
        print("SUBJECT-LEVEL HPC SUBMISSION SUMMARY")
        print("=" * 70)
        print(f"Configuration: {self.config_path}")
        print(f"\nAnalysis Scope:")
        print(f"  - Subjects: {self.n_subjects} (sub-{self.subject_numbers[0]:03d} to sub-{self.subject_numbers[-1]:03d})")
        print(f"  - Sessions: {self.n_sessions}")
        print(f"  - Seeds: {self.n_seeds}")
        print(f"  - Atlases: {len(self.atlases)}")
        print(f"\nAnalysis Types:")
        for analysis in self.analysis_types:
            print(f"  - {analysis}")
        print(f"\nOutput Configuration:")
        print(f"  - Results: {self.output_dir}")
        print(f"  - Logs: {self.log_dir}")
        print(f"\nJob Array Configuration:")
        hpc_cfg = self.config["hpc"]["session_level"]
        print(f"  - Time limit: {hpc_cfg.get('time_limit_hours', 6)} hours")
        print(f"  - Memory: {hpc_cfg.get('mem_per_seed', '16G')}")
        print(f"  - CPUs: {hpc_cfg.get('cpus_per_task', 4)}")
        print(f"  - Partition: {hpc_cfg.get('partition', 'cpu-long')}")
        print(f"  - Array limit: {hpc_cfg.get('job_array_limit', 100)} parallel")
        print("=" * 70 + "\n")


def main():
    """CLI interface.

    When ``--analysis`` is given (``seed`` or ``network``) the script uses the
    XCP-D-driven backends.  Without ``--analysis`` it falls back to the legacy
    config-file-driven flow.
    """
    parser = argparse.ArgumentParser(
        description="HPC Subject-Level Job Submission Wrapper for SLURM"
    )

    # ---- XCP-D backend arguments (new) ----
    parser.add_argument(
        "--analysis",
        choices=["seed", "network"],
        default=None,
        help="Analysis type for XCP-D backends: 'seed' or 'network'.  "
             "When omitted the legacy config-driven flow is used.",
    )
    parser.add_argument(
        "--pipeline",
        choices=["fc", "fc_gsr", "ec"],
        default="fc",
        help="XCP-D pipeline (default: fc).",
    )
    parser.add_argument(
        "--measures",
        default=DEFAULT_XCPD_MEASURES,
        help=(
            "Comma-separated connectivity measures (default: all 8). "
            "Propagated to --measures of the backend."
        ),
    )
    parser.add_argument(
        "--seed",
        dest="seeds",
        action="append",
        default=None,
        metavar="SPEC",
        help=(
            "Seed spec (repeatable). Formats: "
            "atlas-<name>:<parcel> | sphere:<x>,<y>,<z>[,r=<mm>][,name=<n>] | "
            "nifti:<path>[,name=<n>].  Required for --analysis seed."
        ),
    )
    parser.add_argument(
        "--atlas",
        dest="atlases",
        action="append",
        default=None,
        metavar="ATLAS",
        help=(
            "Atlas name (repeatable). Used for --analysis network. "
            f"Defaults to: {', '.join(DEFAULT_XCPD_ATLASES)}"
        ),
    )
    parser.add_argument(
        "--bids-root",
        default=".",
        help="Project BIDS root (parent of bids/, default: current directory).",
    )
    parser.add_argument(
        "--out-root",
        default="derivatives/connectivity",
        help="Output root for connectivity results (default: derivatives/connectivity).",
    )
    parser.add_argument(
        "--subjects",
        default=None,
        help="Comma-separated subject IDs to include (default: all discovered).",
    )
    parser.add_argument(
        "--tr",
        type=float,
        default=0.8,
        help="Repetition time in seconds (default: 0.8).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Pass --force to backend (recompute existing outputs).",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=20,
        help="Maximum concurrent SLURM array tasks (default: 20).",
    )

    # ---- SLURM resource arguments ----
    parser.add_argument("--time", default="06:00:00", help="SLURM wall time.")
    parser.add_argument("--memory", default="16G", help="SLURM memory per task.")
    parser.add_argument("--cpus", type=int, default=4, help="CPUs per task.")
    parser.add_argument("--partition", default="cpu-long", help="SLURM partition.")

    # ---- Legacy / shared arguments ----
    parser.add_argument(
        "--config",
        default=".github/connectivity_config.yaml",
        help="Path to connectivity config YAML (legacy flow).",
    )
    parser.add_argument(
        "--log-dir",
        default="logs",
        help="Directory for SLURM logs.",
    )
    parser.add_argument(
        "--output-dir",
        default="results",
        help="Base directory for results (legacy flow).",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Restrict to 2 session pairs / subjects (useful for testing).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the SLURM script without submitting.",
    )
    parser.add_argument(
        "--check-job",
        help="Check status of a previously submitted job (provide job ID).",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate requirements without submitting (legacy flow).",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print submission summary (legacy flow).",
    )

    args = parser.parse_args()

    # ------------------------------------------------------------------ #
    # XCP-D-driven path (--analysis seed | network)                        #
    # ------------------------------------------------------------------ #
    if args.analysis is not None:
        try:
            subject_filter = (
                [s.strip() for s in args.subjects.split(",") if s.strip()]
                if args.subjects
                else None
            )
            session_pairs = build_xcpd_session_pairs(
                bids_root=args.bids_root,
                pipeline=args.pipeline,
                subjects=subject_filter,
            )
            if not session_pairs:
                print(
                    f"[WARNING] No (subject, session) pairs found for pipeline "
                    f"'{args.pipeline}' under '{args.bids_root}'.",
                    file=sys.stderr,
                )
                if args.dry_run:
                    print("(dry-run: using placeholder pair for script preview)")
                    session_pairs = [("sub-033", "ses-01")]
                else:
                    return 1

            script = generate_xcpd_subject_script(
                analysis=args.analysis,
                pipeline=args.pipeline,
                measures=args.measures,
                seeds=args.seeds,
                atlases=args.atlases,
                bids_root=args.bids_root,
                out_root=args.out_root,
                session_pairs=session_pairs,
                log_dir=args.log_dir,
                time_limit=args.time,
                mem=args.memory,
                cpus=args.cpus,
                partition=args.partition,
                max_parallel=args.max_parallel,
                tr=args.tr,
                force=args.force,
                test_mode=args.test_mode,
            )

            if args.dry_run:
                print("\n" + "=" * 70)
                print(f"DRY RUN: SLURM Script ({args.analysis} / {args.pipeline})")
                print("=" * 70 + "\n")
                print(script)
                print("=" * 70 + "\n")
                return 0

            log_path = Path(args.log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            script_file = log_path / (
                f"xcpd_{args.analysis}_{args.pipeline}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sh"
            )
            script_file.write_text(script)
            script_file.chmod(0o755)

            result = subprocess.run(
                ["sbatch", str(script_file)],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            job_id = result.stdout.strip().split()[-1]
            print(f"Submitted XCP-D {args.analysis} array job: {job_id}")
            print(f"Script: {script_file}")
            return 0

        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    # ------------------------------------------------------------------ #
    # Legacy config-file-driven path (no --analysis)                       #
    # ------------------------------------------------------------------ #
    try:
        submitter = SubjectLevelHPCSubmitter(
            config_file=args.config,
            log_dir=args.log_dir,
            output_dir=args.output_dir,
        )

        if args.summary:
            submitter.print_summary()
            return 0

        if args.validate:
            is_valid = submitter.validate_requirements(verbose=True)
            return 0 if is_valid else 1

        if args.check_job:
            status = submitter.check_job_array_status(args.check_job)
            print(json.dumps(status, indent=2))
            return 0

        job_id = submitter.submit_job_array(
            test_mode=args.test_mode,
            dry_run=args.dry_run,
        )

        return 0 if job_id or args.dry_run else 1

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
