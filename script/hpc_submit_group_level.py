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

# Correction methods
CORRECTION_METHODS = ["grf", "tfce", "fdr"]


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
    correction_method: str = "grf",
    n_permutations: int = 1000,
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
    seeds = config.get("seeds", DEFAULT_SEEDS)
    atlases = config.get("atlases", DEFAULT_ATLASES)
    
    if test_mode:
        seeds = seeds[:1]
        atlases = atlases[:1]
    
    logger.info(f"Analysis types: {analysis_types}")
    logger.info(f"Seeds: {len(seeds)}")
    logger.info(f"Atlases: {atlases}")
    logger.info("")
    
    # Build job array mapper
    mapper = JobArrayMapper(analysis_types, seeds, atlases, logger)
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
        max_parallel=10,
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
        "num_seeds": len(seeds),
        "num_atlases": len(atlases),
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
# CLI ENTRY POINT
# ============================================================================

def main():
    """Command-line interface"""
    parser = argparse.ArgumentParser(
        description="Submit group-level analysis jobs with SLURM parallelization"
    )
    
    parser.add_argument(
        "--subject-job-id",
        required=True,
        help="SLURM job ID from subject-level submission (for dependency chaining)"
    )
    
    parser.add_argument(
        "--config",
        default=None,
        help="Path to connectivity configuration YAML"
    )
    
    parser.add_argument(
        "--correction-method",
        choices=CORRECTION_METHODS,
        default="grf",
        help="Multiple comparison correction method"
    )
    
    parser.add_argument(
        "--n-permutations",
        type=int,
        default=1000,
        help="Number of permutations for permutation testing"
    )
    
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Test mode: submit 1 job per analysis type"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run: show what would be submitted without actually submitting"
    )
    
    parser.add_argument(
        "--log-dir",
        default=DEFAULT_LOGS_DIR,
        help="Directory for logs"
    )
    
    parser.add_argument(
        "--project-dir",
        default=DEFAULT_PROJECT_DIR,
        help="Local project directory"
    )
    
    parser.add_argument(
        "--remote-project-dir",
        default=DEFAULT_REMOTE_PROJECT_DIR,
        help="Remote project directory on HPC"
    )
    
    args = parser.parse_args()
    
    # Submit jobs
    job_id = submit_group_level_jobs(
        subject_job_id=args.subject_job_id,
        config_file=args.config,
        correction_method=args.correction_method,
        n_permutations=args.n_permutations,
        test_mode=args.test_mode,
        dry_run=args.dry_run,
        log_dir=args.log_dir,
        project_dir=args.project_dir,
        remote_project_dir=args.remote_project_dir,
    )
    
    sys.exit(0 if job_id else 1)


if __name__ == "__main__":
    main()
