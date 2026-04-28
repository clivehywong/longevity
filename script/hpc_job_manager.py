#!/usr/bin/env python3
"""
HPC Job Manager: Submit and track SLURM jobs with dependencies and retry logic
"""

import json
import subprocess
import re
import time
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from enum import Enum


class JobStatus(Enum):
    """SLURM job status enumeration"""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class HpcJobManager:
    """Manage SLURM job submission, dependencies, and retry logic"""

    def __init__(self, project_dir: str, logs_dir: str = "logs"):
        """
        Initialize job manager.
        
        Args:
            project_dir: Root project directory
            logs_dir: Directory for job logs (relative to project_dir)
        """
        self.project_dir = Path(project_dir)
        self.logs_dir = self.project_dir / logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.job_log_file = self.logs_dir / "job_submissions.log"
        self.retry_log_file = self.logs_dir / "job_retries.log"

    def _log_submission(self, job_id: str, job_name: str, script: str, metadata: Dict = None):
        """Log job submission"""
        with open(self.job_log_file, 'a') as f:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "job_id": job_id,
                "job_name": job_name,
                "script": script,
                "metadata": metadata or {}
            }
            f.write(json.dumps(entry) + "\n")

    def _log_retry(self, subject_id: str, session: str, attempt: int, reason: str):
        """Log retry attempt"""
        with open(self.retry_log_file, 'a') as f:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "subject_id": subject_id,
                "session": session,
                "attempt": attempt,
                "reason": reason
            }
            f.write(json.dumps(entry) + "\n")

    def submit_subject_level_jobs(
        self,
        script: str,
        job_name: str,
        subjects: List[str],
        seeds: List[str],
        atlases: List[str],
        test_mode: bool = False,
        dependency: Optional[str] = None,
        array_parallelism: int = 20
    ) -> Optional[str]:
        """
        Submit subject-level job array with proper naming and logging.
        
        Args:
            script: Path to SLURM script
            job_name: Base name for the job
            subjects: List of subject IDs
            seeds: List of seed names
            atlases: List of atlas names
            test_mode: If True, only submit for first subject
            dependency: Optional job ID to depend on (--depend=afterok:$dependency)
            array_parallelism: Max parallel tasks in array
            
        Returns:
            Job ID (string) if successful, None if failed or dry-run
        """
        script_path = Path(script)
        if not script_path.exists():
            print(f"Error: Script not found: {script}")
            return None
        
        num_subjects = len(subjects)
        if test_mode:
            num_subjects = 1
            print(f"[TEST MODE] Submitting job array for {num_subjects} subject only")
        
        # Prepare sbatch command
        sbatch_cmd = ["sbatch"]
        
        # Set array size
        sbatch_cmd.extend([
            f"--array=1-{num_subjects}%{array_parallelism}"
        ])
        
        # Add job name
        full_job_name = f"{job_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        sbatch_cmd.extend(["--job-name", full_job_name])
        
        # Add dependency if specified
        if dependency:
            sbatch_cmd.extend(["--depend", f"afterok:{dependency}"])
            print(f"[INFO] Submitting with dependency: afterok:{dependency}")
        
        # Add script
        sbatch_cmd.append(str(script_path))
        
        try:
            print(f"[INFO] Submitting job array: {' '.join(sbatch_cmd)}")
            result = subprocess.run(
                sbatch_cmd,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                print(f"Error: sbatch failed with code {result.returncode}")
                print(f"stderr: {result.stderr}")
                return None
            
            # Extract job ID from output
            job_id = self._extract_job_id(result.stdout)
            if job_id:
                print(f"[SUCCESS] Submitted job array: {job_id}")
                self._log_submission(
                    job_id,
                    full_job_name,
                    script,
                    {
                        "num_subjects": num_subjects,
                        "num_seeds": len(seeds),
                        "num_atlases": len(atlases),
                        "dependency": dependency,
                        "subjects": subjects[:num_subjects],
                        "seeds": seeds,
                        "atlases": atlases
                    }
                )
                return job_id
            else:
                print("Error: Could not extract job ID from sbatch output")
                print(f"Output: {result.stdout}")
                return None
        
        except Exception as e:
            print(f"Error submitting job: {e}")
            return None

    def submit_group_level_jobs(
        self,
        script: str,
        job_name: str,
        subject_job_id: str,
        seeds: List[str],
        atlases: List[str],
        test_mode: bool = False
    ) -> Optional[str]:
        """
        Submit group-level jobs AFTER subject-level complete.
        Uses --depend=afterok:{subject_job_id}
        
        Args:
            script: Path to SLURM script
            job_name: Base name for the job
            subject_job_id: Job ID of subject-level jobs to depend on
            seeds: List of seed names
            atlases: List of atlas names
            test_mode: If True, use shorter arrays
            
        Returns:
            Job ID (string) if successful, None if failed
        """
        script_path = Path(script)
        if not script_path.exists():
            print(f"Error: Script not found: {script}")
            return None
        
        # Array size: one job per seed-atlas combination
        array_size = len(seeds) * len(atlases)
        if test_mode:
            array_size = 1
        
        # Prepare sbatch command
        sbatch_cmd = ["sbatch"]
        
        # Set array size
        sbatch_cmd.extend([
            f"--array=1-{array_size}%10"  # Max 10 parallel group analysis jobs
        ])
        
        # Add job name
        full_job_name = f"{job_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        sbatch_cmd.extend(["--job-name", full_job_name])
        
        # Add dependency on subject-level jobs
        sbatch_cmd.extend(["--depend", f"afterok:{subject_job_id}"])
        
        # Add script
        sbatch_cmd.append(str(script_path))
        
        try:
            print(f"[INFO] Submitting group-level jobs with dependency: afterok:{subject_job_id}")
            print(f"[INFO] Command: {' '.join(sbatch_cmd)}")
            result = subprocess.run(
                sbatch_cmd,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                print(f"Error: sbatch failed with code {result.returncode}")
                print(f"stderr: {result.stderr}")
                return None
            
            # Extract job ID
            job_id = self._extract_job_id(result.stdout)
            if job_id:
                print(f"[SUCCESS] Submitted group-level jobs: {job_id}")
                self._log_submission(
                    job_id,
                    full_job_name,
                    script,
                    {
                        "array_size": array_size,
                        "dependency": f"afterok:{subject_job_id}",
                        "seeds": seeds,
                        "atlases": atlases
                    }
                )
                return job_id
            else:
                print("Error: Could not extract job ID from sbatch output")
                return None
        
        except Exception as e:
            print(f"Error submitting group-level jobs: {e}")
            return None

    def submit_with_retry(
        self,
        script: str,
        subject_id: str,
        session: str,
        seed: str,
        atlas: str,
        max_retries: int = 3,
        wait_time: int = 60
    ) -> Optional[str]:
        """
        Submit job with automatic retry on failure.
        Logs retry attempts.
        
        Args:
            script: Path to SLURM script
            subject_id: Subject ID
            session: Session label
            seed: Seed name
            atlas: Atlas name
            max_retries: Maximum number of retry attempts
            wait_time: Wait time between retries (seconds)
            
        Returns:
            Final job ID if successful, None if failed
        """
        for attempt in range(1, max_retries + 1):
            print(f"\n[RETRY] Attempt {attempt}/{max_retries}: {subject_id} {session} {seed} {atlas}")
            
            sbatch_cmd = [
                "sbatch",
                f"--job-name=retry_{subject_id}_{session}_{seed}_{attempt}",
                str(script)
            ]
            
            try:
                result = subprocess.run(
                    sbatch_cmd,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    job_id = self._extract_job_id(result.stdout)
                    if job_id:
                        print(f"[SUCCESS] Submitted (attempt {attempt}): {job_id}")
                        self._log_retry(subject_id, session, attempt, "submitted_successfully")
                        return job_id
                
                self._log_retry(subject_id, session, attempt, f"sbatch_failed: {result.stderr}")
                
                if attempt < max_retries:
                    print(f"[INFO] Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
            
            except Exception as e:
                self._log_retry(subject_id, session, attempt, f"exception: {str(e)}")
                if attempt < max_retries:
                    print(f"[INFO] Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
        
        print(f"[FAILED] Could not submit job after {max_retries} attempts")
        return None

    def get_job_status(self, job_id: str) -> JobStatus:
        """
        Query SLURM for job status.
        
        Args:
            job_id: SLURM job ID
            
        Returns:
            JobStatus enum value
        """
        try:
            result = subprocess.run(
                ["squeue", "--job", job_id, "--format=%T", "--noheader"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                # Job not in queue - check if completed via sacct
                result = subprocess.run(
                    ["sacct", "--job", job_id, "--format=State", "--noheader", "-X"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    state = result.stdout.strip()
                    if "COMPLETED" in state:
                        return JobStatus.COMPLETED
                    elif "FAILED" in state:
                        return JobStatus.FAILED
                    elif "CANCELLED" in state:
                        return JobStatus.CANCELLED
                    else:
                        return JobStatus.UNKNOWN
                return JobStatus.UNKNOWN
            
            state = result.stdout.strip()
            
            if "RUNNING" in state:
                return JobStatus.RUNNING
            elif "PENDING" in state:
                return JobStatus.QUEUED
            elif "COMPLETED" in state:
                return JobStatus.COMPLETED
            elif "FAILED" in state:
                return JobStatus.FAILED
            elif "CANCELLED" in state:
                return JobStatus.CANCELLED
            else:
                return JobStatus.UNKNOWN
        
        except Exception as e:
            print(f"Error querying job status: {e}")
            return JobStatus.UNKNOWN

    def wait_for_job(
        self,
        job_id: str,
        max_wait_seconds: int = 86400,
        check_interval: int = 30
    ) -> bool:
        """
        Wait for a job to complete.
        
        Args:
            job_id: SLURM job ID
            max_wait_seconds: Maximum time to wait
            check_interval: Time between status checks (seconds)
            
        Returns:
            True if job completed successfully, False otherwise
        """
        print(f"[INFO] Waiting for job {job_id} to complete...")
        
        start_time = time.time()
        while time.time() - start_time < max_wait_seconds:
            status = self.get_job_status(job_id)
            
            if status == JobStatus.COMPLETED:
                print(f"[SUCCESS] Job {job_id} completed")
                return True
            elif status == JobStatus.FAILED:
                print(f"[ERROR] Job {job_id} failed")
                return False
            elif status == JobStatus.CANCELLED:
                print(f"[ERROR] Job {job_id} was cancelled")
                return False
            
            elapsed = time.time() - start_time
            print(f"[{elapsed:.0f}s] Job {job_id} status: {status.value}")
            time.sleep(check_interval)
        
        print(f"[ERROR] Timeout waiting for job {job_id}")
        return False

    def get_job_array_status(self, job_id: str) -> Dict:
        """
        Get status of all tasks in a job array.
        
        Args:
            job_id: SLURM job array ID
            
        Returns:
            Dict with status breakdown
        """
        try:
            result = subprocess.run(
                ["squeue", "--array", job_id, "--format=%T", "--noheader"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            statuses = result.stdout.strip().split('\n')
            
            status_counts = {
                "running": sum(1 for s in statuses if "RUNNING" in s),
                "pending": sum(1 for s in statuses if "PENDING" in s),
                "total": len(statuses)
            }
            
            return status_counts
        
        except Exception as e:
            print(f"Error querying job array status: {e}")
            return {"error": str(e)}

    @staticmethod
    def _extract_job_id(sbatch_output: str) -> Optional[str]:
        """Extract job ID from sbatch output"""
        match = re.search(r'Submitted batch job (\d+)', sbatch_output)
        if match:
            return match.group(1)
        return None
