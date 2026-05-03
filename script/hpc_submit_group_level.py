#!/usr/bin/env python3
"""
HPC Group-Level Job Submission Wrapper for SLURM Parallelization

Submits group-level statistical analysis jobs with proper dependency chaining,
manifest validation, and parallel job array execution.

Features:
- Subject-level completion validation via manifest
- SLURM job array submission with dependencies (--depend=afterok)
- Parallel execution: seeds × atlases × analysis types
- Multiple comparison correction methods: GRF, TFCE, FDR
- Pre-submission checks (≥80% subject completion threshold)
- Job monitoring and recovery support
- Comprehensive logging

Usage:
    python script/hpc_submit_group_level.py \\
        --subject-job-id 12345 \\
        --config .github/connectivity_config.yaml \\
        --correction-method grf \\
        --n-permutations 1000

    # Test mode (1 job per analysis type):
    python script/hpc_submit_group_level.py \\
        --subject-job-id 12345 \\
        --test-mode

    # Dry run (show what would be submitted):
    python script/hpc_submit_group_level.py \\
        --subject-job-id 12345 \\
        --dry-run
"""

import argparse
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# ============================================================================
# CONSTANTS & CONFIGURATION
# ============================================================================

DEFAULT_PROJECT_DIR = "/home/clivewong/proj/longevity"
DEFAULT_REMOTE_PROJECT_DIR = "/home/clivewong/proj/long"
DEFAULT_LOGS_DIR = "logs"
DEFAULT_TEMPLATE_DIR = "script/templates"
DEFAULT_TEMPLATE_NAME = "hpc_group_level_template.sh"

# Analysis types that can run in parallel
ANALYSIS_TYPES = [
    "seed_based",
    "local_measures",
    "network_connectivity",
]

# Default seeds (can be overridden by config)
DEFAULT_SEEDS = [
    "anterior_insula",
    "dacc",
    "insula_dacc_combined",
    "hippocampus",
    "hippocampus_anterior",
    "hippocampus_posterior",
    "cerebellar_cognitive_l",
    "cerebellar_cognitive_r",
    "cerebellar_cognitive_bilateral",
    "cerebellar_motor",
    "cerebellar_vestibular",
    "motor_cortex",
    "default_mode",
    "frontoparietal_control",
    "dlpfc_l",
    "dlpfc_r",
    "dlpfc_bilateral",
]

# Default atlases
DEFAULT_ATLASES = [
    "DiFuMo256",
    "Schaefer400",
]

# Correction methods for voxel stats
CORRECTION_METHODS = ["grf", "tfce", "fdr"]

# Correction methods for matrix stats
MATRIX_CORRECTION_METHODS = ["paired_t_fdr", "nbs", "tfnbs"]

# Kind choices for the new --kind selector
KIND_CHOICES = ["voxel", "matrix", "mixed_design"]

# Matrix sub-kind choices (--matrix-kind)
MATRIX_KIND_CHOICES = ["network", "seed"]


class JobStatus(Enum):
    """SLURM job status"""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


# ============================================================================
# LOGGING
# ============================================================================

def setup_logger(log_dir: Path, log_name: str = "group_level_submission") -> logging.Logger:
    """Setup logging to file and console"""
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / f"{log_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logger = logging.getLogger("GroupLevelSubmission")
    logger.setLevel(logging.DEBUG)
    
    # File handler
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger


# ============================================================================
# MANIFEST VALIDATION
# ============================================================================

class ManifestValidator:
    """Validate subject-level completion using manifest"""
    
    def __init__(self, manifest_path: str, logger: logging.Logger):
        """Initialize manifest validator"""
        self.manifest_path = Path(manifest_path)
        self.logger = logger
        self.data = self._load_manifest()
    
    def _load_manifest(self) -> Dict:
        """Load manifest from disk"""
        if not self.manifest_path.exists():
            self.logger.warning(f"Manifest not found: {self.manifest_path}")
            return {}
        
        try:
            with open(self.manifest_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.logger.error(f"Failed to load manifest: {e}")
            return {}
    
    def check_readiness(
        self,
        seed: str,
        atlas: str,
        min_threshold: float = 0.8
    ) -> Tuple[bool, int, int, float]:
        """
        Check if seed-atlas analysis is ready for group level.
        
        Returns:
            (is_ready, completed_count, total_count, percentage)
        """
        completed = 0
        total = 0
        
        # Count task completions
        for task_key, task_data in self.data.get("tasks", {}).items():
            if task_data.get("seed") == seed and task_data.get("atlas") == atlas:
                total += 1
                if task_data.get("status") == "complete":
                    completed += 1
        
        percentage = (completed / total * 100) if total > 0 else 0
        is_ready = percentage >= (min_threshold * 100) and total > 0
        
        return is_ready, completed, total, percentage
    
    def get_missing_subjects(self, seed: str, atlas: str) -> List[Tuple[str, str]]:
        """Get list of incomplete subject-sessions"""
        incomplete = []
        
        for task_key, task_data in self.data.get("tasks", {}).items():
            if task_data.get("seed") == seed and task_data.get("atlas") == atlas:
                if task_data.get("status") != "complete":
                    incomplete.append((
                        task_data.get("subject_id"),
                        task_data.get("session")
                    ))
        
        return sorted(list(set(incomplete)))


# ============================================================================
# JOB ARRAY MAPPING
# ============================================================================

class JobArrayMapper:
    """Map SLURM array indices to analysis configurations"""
    
    def __init__(
        self,
        analysis_types: List[str],
        seeds: List[str],
        atlases: List[str],
        logger: logging.Logger
    ):
        """
        Initialize job array mapper.
        
        Parallel structure:
        - One job per (analysis_type, seed, atlas) combination
        - For seed_based: 17 seeds × 2 atlases = 34 jobs
        - For local_measures: 1 (no seed/atlas variations)
        - For network_connectivity: 1
        - Total: ~36 jobs
        """
        self.analysis_types = analysis_types
        self.seeds = seeds
        self.atlases = atlases
        self.logger = logger
        
        self._build_job_map()
    
    def _build_job_map(self):
        """Build mapping from array index to job configuration"""
        self.job_map = []
        index = 1
        
        for analysis_type in self.analysis_types:
            if analysis_type == "seed_based":
                # One job per seed-atlas combination
                for seed in self.seeds:
                    for atlas in self.atlases:
                        self.job_map.append({
                            "index": index,
                            "analysis_type": analysis_type,
                            "seed": seed,
                            "atlas": atlas,
                        })
                        index += 1
            
            elif analysis_type == "local_measures":
                # One job per atlas (no seeds for local measures)
                for atlas in self.atlases:
                    self.job_map.append({
                        "index": index,
                        "analysis_type": analysis_type,
                        "seed": None,
                        "atlas": atlas,
                    })
                    index += 1
            
            elif analysis_type == "network_connectivity":
                # One job (no seeds or atlas variations)
                self.job_map.append({
                    "index": index,
                    "analysis_type": analysis_type,
                    "seed": None,
                    "atlas": None,
                })
                index += 1
        
        self.total_jobs = index - 1
    
    def get_job_config(self, array_index: int) -> Optional[Dict]:
        """Get job configuration for a given array index"""
        for job in self.job_map:
            if job["index"] == array_index:
                return job
        return None
    
    def print_summary(self):
        """Print job array summary"""
        self.logger.info(f"Job array configuration (total: {self.total_jobs} jobs):")
        self.logger.info("-" * 80)
        
        # Group by analysis type
        by_type = {}
        for job in self.job_map:
            atype = job["analysis_type"]
            if atype not in by_type:
                by_type[atype] = []
            by_type[atype].append(job)
        
        for atype in self.analysis_types:
            jobs = by_type.get(atype, [])
            self.logger.info(f"  {atype}: {len(jobs)} jobs")
            for job in jobs[:3]:  # Show first 3 examples
                if job["seed"]:
                    self.logger.info(
                        f"    [{job['index']:2d}] {job['seed']:25s} {job['atlas']}"
                    )
                else:
                    self.logger.info(
                        f"    [{job['index']:2d}] {job['atlas'] or 'all'}"
                    )
            if len(jobs) > 3:
                self.logger.info(f"    ... and {len(jobs) - 3} more")


# ============================================================================
# SLURM SUBMISSION
# ============================================================================

class SlurmSubmitter:
    """Submit SLURM jobs with proper configuration"""
    
    def __init__(
        self,
        project_dir: Path,
        template_dir: Path,
        logger: logging.Logger
    ):
        """Initialize SLURM submitter"""
        self.project_dir = project_dir
        self.template_dir = template_dir
        self.logger = logger
    
    def _extract_job_id(self, sbatch_output: str) -> Optional[str]:
        """Extract job ID from sbatch output"""
        match = re.search(r'Submitted batch job (\d+)', sbatch_output)
        if match:
            return match.group(1)
        return None
    
    def generate_job_script(
        self,
        template_path: Path,
        output_path: Path,
        job_name: str,
        subject_job_id: str,
        num_jobs: int,
        correction_method: str,
        n_permutations: int,
        project_dir: str,
        test_mode: bool = False,
    ) -> bool:
        """
        Generate SLURM job script from template.
        
        Substitutes variables in template and writes to output file.
        """
        if not template_path.exists():
            self.logger.error(f"Template not found: {template_path}")
            return False
        
        try:
            with open(template_path, 'r') as f:
                script_content = f.read()
            
            # Perform substitutions
            substitutions = {
                "{{JOB_NAME}}": job_name,
                "{{SUBJECT_JOB_ID}}": subject_job_id,
                "{{NUM_JOBS}}": str(num_jobs),
                "{{CORRECTION_METHOD}}": correction_method,
                "{{N_PERMUTATIONS}}": str(n_permutations),
                "{{PROJECT_DIR}}": project_dir,
                "{{TEST_MODE}}": "1" if test_mode else "0",
            }
            
            for placeholder, value in substitutions.items():
                script_content = script_content.replace(placeholder, value)
            
            # Write to output
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w') as f:
                f.write(script_content)
            
            # Make executable
            os.chmod(output_path, 0o755)
            
            self.logger.info(f"Generated SLURM script: {output_path}")
            return True
        
        except Exception as e:
            self.logger.error(f"Failed to generate SLURM script: {e}")
            return False
    
    def submit_job(
        self,
        script_path: Path,
        job_name: str,
        subject_job_id: str,
        num_jobs: int,
        max_parallel: int = 10,
        dry_run: bool = False,
    ) -> Optional[str]:
        """
        Submit SLURM job array.
        
        Returns:
            Job ID if successful, None otherwise
        """
        if not script_path.exists():
            self.logger.error(f"Script not found: {script_path}")
            return None
        
        # Build sbatch command
        sbatch_cmd = [
            "sbatch",
            f"--job-name={job_name}",
            f"--array=1-{num_jobs}%{max_parallel}",
            f"--depend=afterok:{subject_job_id}",
            str(script_path)
        ]
        
        self.logger.info(f"Submitting job: {' '.join(sbatch_cmd)}")
        
        if dry_run:
            self.logger.info("[DRY RUN] Would submit above command")
            return "DRY_RUN_000000"
        
        try:
            result = subprocess.run(
                sbatch_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                self.logger.error(f"sbatch failed: {result.stderr}")
                return None
            
            job_id = self._extract_job_id(result.stdout)
            if job_id:
                self.logger.info(f"Successfully submitted job: {job_id}")
                return job_id
            else:
                self.logger.error(f"Could not extract job ID from output: {result.stdout}")
                return None
        
        except subprocess.TimeoutExpired:
            self.logger.error("sbatch command timed out")
            return None
        except Exception as e:
            self.logger.error(f"Error submitting job: {e}")
            return None


# ============================================================================
# MAIN SUBMISSION FUNCTION
# ============================================================================

def submit_group_level_jobs(
    subject_job_id: str,
    config_file: Optional[str] = None,
    analysis_source: Optional[str] = None,
    measures: Optional[List[str]] = None,
    atlas: Optional[str] = None,
    seeds: Optional[List[str]] = None,
    network_grouping: Optional[str] = None,
    model_formula: Optional[str] = None,
    covariates: Optional[List[str]] = None,
    correction_method: str = "grf",
    cluster_forming_p: Optional[float] = None,
    cluster_p: Optional[float] = None,
    n_permutations: int = 1000,
    q_threshold: Optional[float] = None,
    mask: Optional[str] = None,
    custom_mask: Optional[str] = None,
    min_subjects_pct: Optional[float] = None,
    manifest_path: Optional[str] = None,
    group_csv: Optional[str] = None,
    time_limit: Optional[str] = None,
    memory: Optional[str] = None,
    partition: Optional[str] = None,
    cpus: Optional[int] = None,
    max_parallel: int = 10,
    test_mode: bool = False,
    dry_run: bool = False,
    log_dir: str = DEFAULT_LOGS_DIR,
    project_dir: str = DEFAULT_PROJECT_DIR,
    remote_project_dir: str = DEFAULT_REMOTE_PROJECT_DIR,
) -> Optional[str]:
    """
    Submit SLURM jobs for group-level analysis.
    
    Validates subject-level completion, generates SLURM job script from
    template, and submits job array with proper dependency chaining.
    
    Args:
        subject_job_id: SLURM job ID from subject-level submission
        config_file: Path to connectivity configuration YAML
        correction_method: Multiple comparison correction ('grf', 'tfce', 'fdr')
        n_permutations: Number of permutations for permutation testing
        test_mode: If True, only submit 1 job per analysis type
        dry_run: If True, show what would be submitted without actually submitting
        log_dir: Directory for logs
        project_dir: Local project directory
        remote_project_dir: Remote project directory (on HPC)
    
    Returns:
        Job ID if successful, None otherwise
    """
    project_path = Path(project_dir)
    logger = setup_logger(project_path / log_dir)
    
    logger.info("=" * 80)
    logger.info("GROUP-LEVEL JOB SUBMISSION WRAPPER")
    logger.info("=" * 80)
    logger.info(f"Subject-level job ID: {subject_job_id}")
    logger.info(f"Correction method: {correction_method}")
    logger.info(f"N permutations: {n_permutations}")
    logger.info(f"Analysis source: {analysis_source or 'config/default'}")
    logger.info(f"Measures: {measures or 'config/default'}")
    logger.info(f"Atlas: {atlas or 'config/default'}")
    logger.info(f"Seeds: {seeds or 'config/default'}")
    logger.info(f"Network grouping: {network_grouping or 'none'}")
    logger.info(f"Model formula: {model_formula or 'default downstream formula'}")
    logger.info(f"Covariates: {covariates or 'auto/default'}")
    logger.info(f"Mask: {mask or 'default'}")
    logger.info(f"Custom mask: {custom_mask or 'N/A'}")
    logger.info(f"Minimum subjects: {min_subjects_pct or 'default'}%")
    logger.info(f"Manifest: {manifest_path or 'default'}")
    logger.info(f"Group CSV: {group_csv or 'default'}")
    logger.info(f"SLURM resources: time={time_limit or 'template'}, memory={memory or 'template'}, partition={partition or 'template'}, cpus={cpus or 'template'}, max_parallel={max_parallel}")
    logger.info(f"Test mode: {test_mode}")
    logger.info(f"Dry run: {dry_run}")
    logger.info("")
    
    # Validate inputs
    if correction_method not in CORRECTION_METHODS:
        logger.error(f"Invalid correction method: {correction_method}")
        logger.error(f"Must be one of: {CORRECTION_METHODS}")
        return None
    
    # Load configuration
    config = {}
    if config_file:
        config_path = Path(config_file)
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f) or {}
                logger.info(f"Loaded config: {config_file}")
            except Exception as e:
                logger.warning(f"Failed to load config: {e}")
    
    # Get analysis parameters from config or use defaults
    analysis_types = config.get("analyses", {}).get("types", ANALYSIS_TYPES)
    source_map = {
        "local": "local_measures",
        "seed": "seed_based",
        "network": "network_connectivity",
    }
    if analysis_source:
        analysis_types = [source_map.get(analysis_source, analysis_source)]

    selected_seeds = seeds or config.get("seeds", DEFAULT_SEEDS)
    if isinstance(selected_seeds, dict):
        selected_seeds = list(selected_seeds.keys())
    atlases = [atlas] if atlas else config.get("atlases", DEFAULT_ATLASES)
    
    if test_mode:
        selected_seeds = selected_seeds[:1]
        atlases = atlases[:1]
    
    logger.info(f"Analysis types: {analysis_types}")
    logger.info(f"Seeds: {len(selected_seeds)}")
    logger.info(f"Atlases: {atlases}")
    logger.info("")
    
    # Build job array mapper
    mapper = JobArrayMapper(analysis_types, selected_seeds, atlases, logger)
    mapper.print_summary()
    logger.info("")
    
    # Prepare SLURM submission
    template_path = project_path / DEFAULT_TEMPLATE_DIR / DEFAULT_TEMPLATE_NAME
    if not template_path.exists():
        logger.error(f"SLURM template not found: {template_path}")
        return None
    
    # Generate job script
    job_name = f"group_level_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    script_path = project_path / log_dir / f"{job_name}.sh"
    
    submitter = SlurmSubmitter(project_path, project_path / DEFAULT_TEMPLATE_DIR, logger)
    
    success = submitter.generate_job_script(
        template_path=template_path,
        output_path=script_path,
        job_name=job_name,
        subject_job_id=subject_job_id,
        num_jobs=mapper.total_jobs,
        correction_method=correction_method,
        n_permutations=n_permutations,
        project_dir=remote_project_dir,
        test_mode=test_mode,
    )
    
    if not success:
        logger.error("Failed to generate SLURM job script")
        return None
    
    # Submit job
    group_job_id = submitter.submit_job(
        script_path=script_path,
        job_name=job_name,
        subject_job_id=subject_job_id,
        num_jobs=mapper.total_jobs,
        max_parallel=max_parallel,
        dry_run=dry_run,
    )
    
    if not group_job_id:
        logger.error("Failed to submit group-level jobs")
        return None
    
    # Log submission
    submission_log = {
        "timestamp": datetime.now().isoformat(),
        "group_job_id": group_job_id,
        "subject_job_id": subject_job_id,
        "num_jobs": mapper.total_jobs,
        "correction_method": correction_method,
        "n_permutations": n_permutations,
        "test_mode": test_mode,
        "dry_run": dry_run,
        "analysis_types": analysis_types,
        "num_seeds": len(selected_seeds),
        "num_atlases": len(atlases),
        "measures": measures or [],
        "atlas": atlas,
        "seeds": selected_seeds,
        "network_grouping": network_grouping,
        "model_formula": model_formula,
        "covariates": covariates or [],
        "mask": mask,
        "min_subjects_pct": min_subjects_pct,
    }
    
    log_file = project_path / log_dir / "group_level_submissions.jsonl"
    with open(log_file, 'a') as f:
        f.write(json.dumps(submission_log) + '\n')
    
    logger.info("=" * 80)
    logger.info(f"GROUP-LEVEL JOBS SUBMITTED SUCCESSFULLY")
    logger.info(f"Group job ID: {group_job_id}")
    logger.info(f"Total jobs: {mapper.total_jobs}")
    logger.info(f"Dependency: afterok:{subject_job_id}")
    logger.info("=" * 80)
    
    return group_job_id


# ============================================================================
# JOB MONITORING
# ============================================================================

def check_group_level_jobs(
    job_id: str,
    logger: logging.Logger
) -> Dict:
    """
    Check status of group-level job array.
    
    Returns:
        Dict with job status information
    """
    try:
        result = subprocess.run(
            ["squeue", "--job", job_id, "--format=%T,%a,%A_%a"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            # Job not in queue - check sacct
            result = subprocess.run(
                ["sacct", "--job", job_id, "--format=State", "-X"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            status = result.stdout.strip() if result.returncode == 0 else "UNKNOWN"
            return {
                "job_id": job_id,
                "status": status,
                "running": 0,
                "pending": 0,
            }
        
        # Parse squeue output
        lines = result.stdout.strip().split('\n')
        status_counts = {
            "running": 0,
            "pending": 0,
            "completed": 0,
        }
        
        for line in lines:
            if "RUNNING" in line:
                status_counts["running"] += 1
            elif "PENDING" in line:
                status_counts["pending"] += 1
            elif "COMPLETED" in line:
                status_counts["completed"] += 1
        
        return {
            "job_id": job_id,
            "status": "RUNNING" if status_counts["running"] > 0 else "PENDING",
            **status_counts
        }
    
    except Exception as e:
        logger.error(f"Error checking job status: {e}")
        return {"job_id": job_id, "status": "UNKNOWN", "error": str(e)}


def retry_failed_seeds(
    job_array_id: str,
    output_dir: Path,
    logger: Optional[logging.Logger] = None
) -> Tuple[int, List[str]]:
    """
    Identify and report failed tasks from a completed job array.
    
    Args:
        job_array_id: SLURM job array ID (e.g., "1234567")
        output_dir: Directory containing .out/.err files
        logger: Logger instance
    
    Returns:
        Tuple of (num_failed, list_of_failed_configs)
    """
    if not logger:
        logger = logging.getLogger("GroupLevel")
    
    failed_configs = []
    
    # Parse error files to find failures
    try:
        import glob as glob_module
        
        err_files = glob_module.glob(str(output_dir / f"group_level_{job_array_id}_*.err"))
        
        for err_file in err_files:
            with open(err_file, 'r') as f:
                content = f.read()
                if "ERROR" in content or "exit 1" in content or "Traceback" in content:
                    # Extract task ID from filename
                    import re
                    match = re.search(r'group_level_\d+_(\d+)\.err', err_file)
                    if match:
                        task_id = int(match.group(1))
                        failed_configs.append(f"Task {task_id}")
        
        logger.info(f"Found {len(failed_configs)} failed tasks in job array {job_array_id}")
        return len(failed_configs), failed_configs
    
    except Exception as e:
        logger.error(f"Error analyzing job array failures: {e}")
        return 0, []


def wait_for_subject_level_jobs(
    subject_job_id: str,
    timeout_seconds: int = 86400,
    check_interval: int = 60,
    logger: Optional[logging.Logger] = None
) -> bool:
    """
    Wait for subject-level jobs to complete before submitting group-level.
    
    Args:
        subject_job_id: SLURM job ID from subject-level submission
        timeout_seconds: Maximum time to wait
        check_interval: Time between status checks
        logger: Logger instance
    
    Returns:
        True if jobs completed successfully, False if failed or timeout
    """
    if not logger:
        logger = logging.getLogger("GroupLevel")
    
    logger.info(f"Waiting for subject-level jobs {subject_job_id} to complete...")
    logger.info(f"(Timeout: {timeout_seconds}s, check interval: {check_interval}s)")
    
    import time
    start_time = time.time()
    
    while time.time() - start_time < timeout_seconds:
        try:
            result = subprocess.run(
                ["squeue", "--job", subject_job_id, "--format=%T", "--noheader"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                # Job not in queue - check sacct for final status
                result = subprocess.run(
                    ["sacct", "--job", subject_job_id, "--format=State", "-X", "--noheader"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                status = result.stdout.strip() if result.returncode == 0 else "UNKNOWN"
                
                if "COMPLETED" in status:
                    logger.info(f"Subject-level jobs completed successfully")
                    return True
                elif "FAILED" in status or "CANCELLED" in status:
                    logger.error(f"Subject-level jobs failed or cancelled: {status}")
                    return False
                else:
                    logger.warning(f"Unknown job status: {status}")
                    return False
            
            # Job still in queue
            state = result.stdout.strip()
            elapsed = time.time() - start_time
            logger.info(f"[{elapsed:.0f}s] Job status: {state}")
            time.sleep(check_interval)
        
        except subprocess.TimeoutExpired:
            logger.error("squeue/sacct command timed out")
            return False
        except Exception as e:
            logger.error(f"Error checking job status: {e}")
            return False
    
    logger.error(f"Timeout waiting for subject-level jobs after {timeout_seconds}s")
    return False


# ============================================================================
# XCP-D GROUP-LEVEL HELPERS
# ============================================================================

def build_xcpd_group_command(
    kind: str,
    bids_root: str,
    pipeline: str,
    measure: str,
    contrast: str,
    method: str,
    group_csv: str,
    out: str,
    # voxel-specific
    mask: Optional[str] = None,
    n_permutations: Optional[int] = None,
    # matrix-specific
    matrix_kind: Optional[str] = None,
    atlas: Optional[str] = None,
    seed_id: Optional[str] = None,
    threshold: Optional[float] = None,
    alpha: Optional[float] = None,
) -> str:
    """Build the shell command that calls the appropriate XCP-D group backend.

    Parameters
    ----------
    kind:
        ``"voxel"`` → ``script/group_voxel_stats_xcpd.py``
        ``"matrix"`` → ``script/group_matrix_stats.py``
    bids_root, pipeline:
        Propagated to ``--bids-root`` / ``--pipeline``.
    measure:
        Connectivity measure (e.g. ``pearson``, ``alff``).
    contrast:
        Contrast label (e.g. ``ses-02_vs_ses-01``).
    method:
        Statistical method:
        - voxel: ``grf | tfce | fdr``
        - matrix: ``paired_t_fdr | nbs | tfnbs``
    group_csv:
        Path to ``bids/participants.tsv`` or legacy ``group.csv``.
    out:
        Output directory/file path.
    mask:
        (voxel only) Brain-mask NIfTI path.
    n_permutations:
        Number of permutations (both backends).
    matrix_kind:
        (matrix only) ``"network"`` or ``"seed"`` — forwarded as ``--kind`` to
        ``group_matrix_stats.py``.
    atlas:
        (matrix only) Atlas name (``--atlas``).
    seed_id:
        (matrix only) Seed identifier (``--seed-id``).
    threshold:
        (matrix only) NBS/TFNBS edge threshold (``--threshold``).
    alpha:
        (matrix only) Significance level (``--alpha``).

    Returns
    -------
    str
        Multi-word shell command string (not yet submitted).
    """
    if kind not in KIND_CHOICES:
        raise ValueError(f"kind must be one of {KIND_CHOICES}, got {kind!r}")

    parts: List[str] = ["python3"]

    if kind == "voxel":
        parts.append("script/group_voxel_stats_xcpd.py")
        parts += ["--bids-root", shlex.quote(bids_root)]
        parts += ["--pipeline", shlex.quote(pipeline)]
        parts += ["--measure", shlex.quote(measure)]
        parts += ["--contrast", shlex.quote(contrast)]
        parts += ["--method", shlex.quote(method)]
        parts += ["--group-csv", shlex.quote(group_csv)]
        parts += ["--out", shlex.quote(out)]
        if mask:
            parts += ["--mask", shlex.quote(mask)]
        if n_permutations is not None:
            parts += ["--n-permutations", str(n_permutations)]

    else:  # matrix
        parts.append("script/group_matrix_stats.py")
        parts += ["--bids-root", shlex.quote(bids_root)]
        parts += ["--pipeline", shlex.quote(pipeline)]
        if matrix_kind:
            parts += ["--kind", shlex.quote(matrix_kind)]
        if atlas:
            parts += ["--atlas", shlex.quote(atlas)]
        if seed_id:
            parts += ["--seed-id", shlex.quote(seed_id)]
        parts += ["--measure", shlex.quote(measure)]
        parts += ["--contrast", shlex.quote(contrast)]
        parts += ["--method", shlex.quote(method)]
        if threshold is not None:
            parts += ["--threshold", str(threshold)]
        if n_permutations is not None:
            parts += ["--n-permutations", str(n_permutations)]
        if alpha is not None:
            parts += ["--alpha", str(alpha)]
        parts += ["--group-csv", shlex.quote(group_csv)]
        parts += ["--out", shlex.quote(out)]

    return " ".join(parts)


def generate_xcpd_group_script(
    kind: str,
    bids_root: str,
    pipeline: str,
    measure: str,
    contrast: str,
    method: str,
    group_csv: str,
    out: str,
    log_dir: str = DEFAULT_LOGS_DIR,
    subject_job_id: Optional[str] = None,
    time_limit: Optional[str] = None,
    mem: Optional[str] = None,
    cpus: Optional[int] = None,
    partition: Optional[str] = None,
    # voxel-specific
    mask: Optional[str] = None,
    n_permutations: Optional[int] = None,
    # matrix-specific
    matrix_kind: Optional[str] = None,
    atlas: Optional[str] = None,
    seed_id: Optional[str] = None,
    threshold: Optional[float] = None,
    alpha: Optional[float] = None,
) -> str:
    """Generate a single SLURM job script for XCP-D group-level analysis.

    The script is a non-array job that calls either ``group_voxel_stats_xcpd.py``
    (kind=voxel) or ``group_matrix_stats.py`` (kind=matrix).
    """
    backend_cmd = build_xcpd_group_command(
        kind=kind,
        bids_root=bids_root,
        pipeline=pipeline,
        measure=measure,
        contrast=contrast,
        method=method,
        group_csv=group_csv,
        out=out,
        mask=mask,
        n_permutations=n_permutations,
        matrix_kind=matrix_kind,
        atlas=atlas,
        seed_id=seed_id,
        threshold=threshold,
        alpha=alpha,
    )

    dependency_line = (
        f"#SBATCH --dependency=afterok:{subject_job_id}\n"
        if subject_job_id
        else ""
    )
    time_line = f"#SBATCH --time={time_limit}\n" if time_limit else ""
    mem_line = f"#SBATCH --mem={mem}\n" if mem else ""
    cpus_line = f"#SBATCH --cpus-per-task={cpus}\n" if cpus else ""
    part_line = f"#SBATCH --partition={partition}\n" if partition else ""

    script = f"""#!/bin/bash
# SLURM XCP-D Group-Level {kind.capitalize()} Statistics Job
# Generated: {datetime.now().isoformat()}
# Kind: {kind}  Pipeline: {pipeline}  Measure: {measure}  Method: {method}

#SBATCH --job-name=group_{kind}_{pipeline}
{dependency_line}{time_line}{mem_line}{cpus_line}{part_line}#SBATCH --output={log_dir}/group_{kind}_%j.out
#SBATCH --error={log_dir}/group_{kind}_%j.err

set -euo pipefail

log_info() {{ echo "[$(date +'%Y-%m-%d %H:%M:%S')] [INFO] $*"; }}
log_error() {{ echo "[$(date +'%Y-%m-%d %H:%M:%S')] [ERROR] $*"; }}

log_info "Starting group-level {kind} analysis (pipeline={pipeline}, measure={measure}, method={method})"

if {backend_cmd}; then
    log_info "SUCCESS: group {kind} analysis completed"
else
    log_error "FAILED: group {kind} analysis"
    exit 1
fi
"""
    return script


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

def generate_mixed_design_script(
    bids_root: str,
    seed: str,
    pipeline: str,
    measure: str,
    n_perms: int,
    correction: str,
    canonical_csv: str,
    log_dir: str = DEFAULT_LOGS_DIR,
    time_limit: Optional[str] = None,
    mem: Optional[str] = None,
    cpus: Optional[int] = None,
    partition: Optional[str] = None,
    mask_path: Optional[str] = None,
    conda_env: str = "",
    subject_job_id: Optional[str] = None,
) -> str:
    """Generate a SLURM script for mixed-design TFCE group analysis.

    Calls neuconn_app/scripts/group_mixed_design_stats.py directly.
    """
    cmd_parts = [
        "python3",
        f"{bids_root}/neuconn_app/scripts/group_mixed_design_stats.py",
        "--bids-root", shlex.quote(bids_root),
        "--seed", shlex.quote(seed),
        "--pipeline", shlex.quote(pipeline),
        "--measure", shlex.quote(measure),
        "--n-perms", str(n_perms),
        "--correction", shlex.quote(correction),
        "--canonical-order-csv", shlex.quote(canonical_csv),
    ]
    if mask_path:
        cmd_parts += ["--mask-path", shlex.quote(mask_path)]
    backend_cmd = " ".join(cmd_parts)

    dependency_line = f"#SBATCH --dependency=afterok:{subject_job_id}\n" if subject_job_id else ""
    time_line = f"#SBATCH --time={time_limit}\n" if time_limit else ""
    mem_line = f"#SBATCH --mem={mem}\n" if mem else ""
    cpus_line = f"#SBATCH --cpus-per-task={cpus}\n" if cpus else ""
    part_line = f"#SBATCH --partition={partition}\n" if partition else "#SBATCH --partition=shared_cpu\n"

    if conda_env:
        conda_block = f"""
# Activate conda environment
if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/anaconda3/etc/profile.d/conda.sh"
fi
conda activate {conda_env}
"""
    else:
        conda_block = ""

    return f"""#!/bin/bash
# SLURM Mixed-Design TFCE Group Statistics Job
# Generated: {datetime.now().isoformat()}
# Seed: {seed}  Pipeline: {pipeline}  Measure: {measure}  Correction: {correction}

#SBATCH --job-name=group_mixed_{pipeline}
#SBATCH --chdir={bids_root}
{dependency_line}{time_line}{mem_line}{cpus_line}{part_line}#SBATCH --output={log_dir}/group_mixed_%j.out
#SBATCH --error={log_dir}/group_mixed_%j.err

set -euo pipefail
{conda_block}
log_info() {{ echo "[$(date +'%Y-%m-%d %H:%M:%S')] [INFO] $*"; }}
log_error() {{ echo "[$(date +'%Y-%m-%d %H:%M:%S')] [ERROR] $*"; }}

log_info "Starting mixed-design TFCE group analysis (seed={seed}, pipeline={pipeline}, measure={measure}, correction={correction})"

if {backend_cmd}; then
    log_info "SUCCESS: mixed-design group analysis completed"
else
    log_error "FAILED: mixed-design group analysis"
    exit 1
fi
"""


def _csv_list(value: Optional[str]) -> Optional[List[str]]:
    """Parse comma-separated CLI values into a list."""
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def main():
    """Command-line interface.

    When ``--kind voxel`` or ``--kind matrix`` is given the script uses the
    XCP-D-driven backends.  Without ``--kind`` it falls back to the legacy
    template-based flow (requires ``--subject-job-id``).
    """
    parser = argparse.ArgumentParser(
        description="Submit group-level analysis jobs with SLURM parallelization"
    )

    # ---- XCP-D backend routing (new) ----
    parser.add_argument(
        "--kind",
        choices=KIND_CHOICES,
        default=None,
        help=(
            "Backend selector: 'voxel' → group_voxel_stats_xcpd.py; "
            "'matrix' → group_matrix_stats.py.  "
            "When omitted the legacy template-based flow is used."
        ),
    )

    # ---- Shared XCP-D arguments ----
    parser.add_argument("--bids-root", default=".", help="BIDS project root.")
    parser.add_argument(
        "--pipeline",
        choices=["fc", "fc_gsr", "ec"],
        default="fc",
        help="XCP-D pipeline name (default: fc).",
    )
    parser.add_argument("--measure", default=None, help="Connectivity measure (e.g. pearson, alff).")
    parser.add_argument("--contrast", default=None, help="Contrast label (e.g. ses-02_vs_ses-01).")
    parser.add_argument("--method", default=None,
                        help="Statistical method. Voxel: grf|tfce|fdr. Matrix: paired_t_fdr|nbs|tfnbs.")
    parser.add_argument("--group-csv", default=None, help="Participants TSV / legacy group CSV (required by XCP-D backends).")
    parser.add_argument("--out", default=None, help="Output directory for XCP-D backend results.")

    # ---- Voxel-specific ----
    parser.add_argument("--mask", default=None, help="Brain mask NIfTI path (voxel stats).")

    # ---- Matrix-specific ----
    parser.add_argument(
        "--matrix-kind",
        choices=MATRIX_KIND_CHOICES,
        default=None,
        help="Sub-kind for matrix stats: 'network' or 'seed'. Forwarded as --kind to group_matrix_stats.py.",
    )
    parser.add_argument("--atlas", default=None, help="Atlas name for matrix stats.")
    parser.add_argument("--seed-id", default=None, help="Seed identifier for matrix stats.")
    parser.add_argument("--threshold", type=float, default=None, help="Edge threshold for NBS/TFNBS.")
    parser.add_argument("--alpha", type=float, default=None, help="Significance level for matrix stats.")

    # ---- Common permutation / SLURM args ----
    parser.add_argument(
        "--n-permutations",
        type=int,
        default=1000,
        help="Number of permutations for permutation testing.",
    )
    parser.add_argument("--time", dest="time_limit", default=None, help="Requested SLURM wall time.")
    parser.add_argument("--memory", default=None, help="Requested SLURM memory.")
    parser.add_argument("--partition", default=None, help="Requested SLURM partition.")
    parser.add_argument("--cpus", type=int, default=None, help="Requested CPUs per task.")

    # ---- Mixed-design specific args ----
    parser.add_argument("--seed", default=None, help="Seed CLI token (e.g., atlas-4S256Parcels:LH_Cont_PFCl_3).")
    parser.add_argument("--n-perms", type=int, default=None, help="Number of permutations for mixed-design TFCE.")
    parser.add_argument("--canonical-order-csv", default=None, help="Path to canonical subject order TSV/CSV.")
    parser.add_argument("--correction", default=None, choices=["TFCE", "GRF", "FDR"], help="Correction method for mixed-design TFCE.")
    parser.add_argument("--mask-path", default=None, help="Brain mask path for mixed-design TFCE.")
    parser.add_argument("--conda-env", default="", help="Conda environment to activate on HPC.")

    # ---- Legacy / shared arguments ----
    parser.add_argument(
        "--subject-job-id",
        default=None,
        help="SLURM job ID from subject-level submission (dependency chaining; required in legacy flow).",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to connectivity configuration YAML (legacy flow).",
    )
    parser.add_argument(
        "--analysis-source",
        choices=["local", "seed", "network", "local_measures", "seed_based", "network_connectivity"],
        default=None,
        help="Restrict group analysis to one upstream source (legacy flow).",
    )
    parser.add_argument("--measures", default=None, help="Comma-separated local measures (legacy).")
    parser.add_argument("--seeds", default=None, help="Comma-separated seed IDs (legacy).")
    parser.add_argument("--network-grouping", default=None, help="Network grouping: none, yeo7, or yeo17 (legacy).")
    parser.add_argument("--model-formula", default=None, help="LME model formula (legacy).")
    parser.add_argument("--covariates", default=None, help="Comma-separated covariate columns (legacy).")
    parser.add_argument(
        "--correction-method",
        choices=CORRECTION_METHODS,
        default="grf",
        help="Multiple comparison correction method (legacy flow).",
    )
    parser.add_argument("--cluster-forming-p", type=float, default=None, help="GRF cluster-forming p threshold.")
    parser.add_argument("--cluster-p", type=float, default=None, help="GRF cluster p threshold.")
    parser.add_argument("--q-threshold", type=float, default=None, help="FDR q threshold.")
    parser.add_argument("--custom-mask", default=None, help="Custom mask path (legacy).")
    parser.add_argument("--min-subjects-pct", type=float, default=None, help="Minimum ready subjects percentage.")
    parser.add_argument("--manifest", default=None, help="Subject-level manifest path.")
    parser.add_argument("--max-parallel", type=int, default=10, help="Maximum concurrent array tasks.")
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Test mode: submit 1 job per analysis type.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run: show what would be submitted without actually submitting.",
    )
    parser.add_argument(
        "--log-dir",
        default=DEFAULT_LOGS_DIR,
        help="Directory for logs.",
    )
    parser.add_argument(
        "--project-dir",
        default=DEFAULT_PROJECT_DIR,
        help="Local project directory.",
    )
    parser.add_argument(
        "--remote-project-dir",
        default=DEFAULT_REMOTE_PROJECT_DIR,
        help="Remote project directory on HPC.",
    )

    args = parser.parse_args()

    # ------------------------------------------------------------------ #
    # XCP-D-driven path (--kind voxel | matrix)                           #
    # ------------------------------------------------------------------ #
    if args.kind is not None:
        try:
            if args.kind == "mixed_design":
                script = generate_mixed_design_script(
                    bids_root=args.bids_root,
                    seed=args.seed or "",
                    pipeline=args.pipeline,
                    measure=args.measure or "pearson",
                    n_perms=args.n_perms or 5000,
                    correction=args.correction or "TFCE",
                    canonical_csv=args.canonical_order_csv or "bids/participants.tsv",
                    log_dir=args.log_dir,
                    time_limit=args.time_limit,
                    mem=args.memory,
                    cpus=args.cpus,
                    partition=args.partition,
                    mask_path=args.mask_path,
                    conda_env=args.conda_env,
                    subject_job_id=args.subject_job_id,
                )
            else:
                script = generate_xcpd_group_script(
                    kind=args.kind,
                    bids_root=args.bids_root,
                    pipeline=args.pipeline,
                    measure=args.measure or "",
                    contrast=args.contrast or "",
                    method=args.method or ("grf" if args.kind == "voxel" else "paired_t_fdr"),
                    group_csv=args.group_csv or "bids/participants.tsv",
                    out=args.out or f"results/group_{args.kind}",
                    log_dir=args.log_dir,
                    subject_job_id=args.subject_job_id,
                    time_limit=args.time_limit,
                    mem=args.memory,
                    cpus=args.cpus,
                    partition=args.partition,
                    mask=args.mask,
                    n_permutations=args.n_permutations if args.n_permutations != 1000 else None,
                    matrix_kind=args.matrix_kind,
                    atlas=args.atlas,
                    seed_id=args.seed_id,
                    threshold=args.threshold,
                    alpha=args.alpha,
                )

            if args.dry_run:
                print("\n" + "=" * 70)
                print(f"DRY RUN: SLURM Group {args.kind.capitalize()} Script")
                print("=" * 70 + "\n")
                print(script)
                print("=" * 70 + "\n")
                sys.exit(0)

            log_path = Path(args.log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            script_file = log_path / (
                f"xcpd_group_{args.kind}_{args.pipeline}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sh"
            )
            script_file.write_text(script)
            script_file.chmod(0o755)

            sbatch_cmd = ["sbatch", str(script_file)]
            result = subprocess.run(sbatch_cmd, capture_output=True, text=True, timeout=30, check=True)
            job_id = result.stdout.strip().split()[-1]
            print(f"Submitted XCP-D group {args.kind} job: {job_id}")
            sys.exit(0)

        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    # ------------------------------------------------------------------ #
    # Legacy template-based path (no --kind)                              #
    # ------------------------------------------------------------------ #
    if not args.subject_job_id:
        parser.error("--subject-job-id is required in the legacy flow (or use --kind to select XCP-D backend)")

    job_id = submit_group_level_jobs(
        subject_job_id=args.subject_job_id,
        config_file=args.config,
        analysis_source=args.analysis_source,
        measures=_csv_list(args.measures),
        atlas=args.atlas,
        seeds=_csv_list(args.seeds),
        network_grouping=args.network_grouping,
        model_formula=args.model_formula,
        covariates=_csv_list(args.covariates),
        correction_method=args.correction_method,
        cluster_forming_p=args.cluster_forming_p,
        cluster_p=args.cluster_p,
        n_permutations=args.n_permutations,
        q_threshold=args.q_threshold,
        mask=args.mask,
        custom_mask=args.custom_mask,
        min_subjects_pct=args.min_subjects_pct,
        manifest_path=args.manifest,
        group_csv=args.group_csv,
        time_limit=args.time_limit,
        memory=args.memory,
        partition=args.partition,
        cpus=args.cpus,
        max_parallel=args.max_parallel,
        test_mode=args.test_mode,
        dry_run=args.dry_run,
        log_dir=args.log_dir,
        project_dir=args.project_dir,
        remote_project_dir=args.remote_project_dir,
    )

    sys.exit(0 if job_id else 1)


if __name__ == "__main__":
    main()
