"""
HPC Connection and Job Management

SSH/SFTP operations for HPC workflow:
- HPCConfig: Configuration dataclass for HPC settings
- HPCConnection: SSH connection manager (paramiko)
- HPCWorkflowManager: Full workflow orchestration
  - upload_batch_selective(): Upload only specified modalities
  - generate_slurm_script(): Generate SLURM script from Jinja2 template
  - submit_job(): Submit via sbatch, return job ID
  - check_job_status(): Poll squeue for job status
  - download_results(): Rsync derivatives back
  - cleanup_remote(): Remove uploaded BIDS and work dirs

Space-efficient workflow:
- Selective upload (include only configured modalities: anat, func, fmap by default)
- Batched processing (configurable concurrent jobs)
- Auto-cleanup after download
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Callable, Tuple, Any
import subprocess
import time
import os
import re
import logging
from enum import Enum
from datetime import datetime
import json

logger = logging.getLogger(__name__)

try:
    import paramiko
except ImportError:
    paramiko = None

try:
    from jinja2 import Environment, FileSystemLoader
except ImportError:
    Environment = None
    FileSystemLoader = None


class JobStatus(Enum):
    """SLURM job status codes."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETING = "COMPLETING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    NODE_FAIL = "NODE_FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass
class HPCConfig:
    """HPC configuration parameters."""
    host: str
    user: str
    ssh_key: Optional[str] = None
    remote_base: str = ""
    remote_bids: str = ""
    remote_fmriprep: str = ""
    remote_xcpd_fc: str = ""
    remote_xcpd_ec: str = ""
    remote_work: str = ""
    singularity_fmriprep: str = ""
    singularity_xcpd: str = ""
    singularity_fmripost_aroma: str = ""
    singularity_qsiprep: str = ""
    singularity_qsirecon: str = ""
    freesurfer_license: str = ""
    partition: str = "shared_cpu"
    cpus: int = 8
    memory: str = "32GB"
    time_limit: str = "24:00:00"
    max_concurrent: int = 4
    modalities: List[str] = field(default_factory=lambda: ["anat", "fmap", "func"])
    xcpd_cpus: int = 0
    xcpd_memory: str = ""
    xcpd_time_limit: str = ""

    @classmethod
    def from_config(cls, config: Dict) -> 'HPCConfig':
        """Create HPCConfig from app configuration dictionary."""
        hpc = config.get('hpc', {})
        remote = hpc.get('remote_paths', {})
        singularity = hpc.get('singularity_images', {})
        slurm = hpc.get('slurm', {})
        transfer = hpc.get('transfer', {})

        # Handle ${base} variable expansion
        base = remote.get('base', '')
        bids = remote.get('bids', '').replace('${base}', base)
        fmriprep = remote.get('fmriprep', '').replace('${base}', base)
        xcpd_fc = remote.get('xcpd_fc', '').replace('${base}', base)
        xcpd_ec = remote.get('xcpd_ec', '').replace('${base}', base)
        work = remote.get('work', '').replace('${base}', base)

        return cls(
            host=hpc.get('host', ''),
            user=hpc.get('user', ''),
            ssh_key=hpc.get('ssh_key'),
            remote_base=base,
            remote_bids=bids,
            remote_fmriprep=fmriprep,
            remote_xcpd_fc=xcpd_fc,
            remote_xcpd_ec=xcpd_ec,
            remote_work=work,
            singularity_fmriprep=singularity.get('fmriprep', ''),
            singularity_xcpd=singularity.get('xcp_d', ''),
            singularity_fmripost_aroma=singularity.get('fmripost_aroma', ''),
            singularity_qsiprep=singularity.get('qsiprep', ''),
            singularity_qsirecon=singularity.get('qsirecon', ''),
            freesurfer_license=singularity.get('freesurfer_license', ''),
            partition=slurm.get('partition', 'shared_cpu'),
            cpus=slurm.get('default_cpus', 8),
            memory=slurm.get('default_memory', '32GB'),
            time_limit=slurm.get('default_time', '24:00:00'),
            max_concurrent=slurm.get('max_concurrent_jobs', 4),
            modalities=transfer.get('modalities', ['anat', 'fmap', 'func']),
            xcpd_cpus=slurm.get('xcpd_cpus', 0),
            xcpd_memory=slurm.get('xcpd_memory', ''),
            xcpd_time_limit=slurm.get('xcpd_time', ''),
        )


@dataclass
class SubjectJobStatus:
    """Status of a single subject's processing job."""
    subject_id: str
    array_index: int
    job_id: str
    status: JobStatus
    start_time: Optional[str] = None
    elapsed_time: Optional[str] = None
    node: Optional[str] = None


@dataclass
class WorkflowState:
    """Current state of the HPC workflow."""
    subjects: List[str]
    current_step: str  # upload, submit, monitor, download, cleanup, completed
    job_id: Optional[str] = None
    job_statuses: List[SubjectJobStatus] = field(default_factory=list)
    upload_progress: Dict[str, str] = field(default_factory=dict)  # subject -> status
    download_progress: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    failed_subjects: List[str] = field(default_factory=list)
    start_time: Optional[str] = None
    restart_jobs: List[Dict] = field(default_factory=list)  # [{job_id, subjects, submitted_at}]
    original_script: Optional[str] = None  # SLURM script stored for restart reuse

    def to_dict(self) -> Dict:
        """Serialize state to dictionary."""
        return {
            'subjects': self.subjects,
            'current_step': self.current_step,
            'job_id': self.job_id,
            'job_statuses': [
                {
                    'subject_id': s.subject_id,
                    'array_index': s.array_index,
                    'job_id': s.job_id,
                    'status': s.status.value,
                    'start_time': s.start_time,
                    'elapsed_time': s.elapsed_time,
                    'node': s.node
                }
                for s in self.job_statuses
            ],
            'upload_progress': self.upload_progress,
            'download_progress': self.download_progress,
            'errors': self.errors,
            'failed_subjects': self.failed_subjects,
            'start_time': self.start_time,
            'restart_jobs': self.restart_jobs,
            'original_script': self.original_script,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'WorkflowState':
        """Deserialize from dictionary."""
        state = cls(
            subjects=data.get('subjects', []),
            current_step=data.get('current_step', 'upload'),
            job_id=data.get('job_id'),
            upload_progress=data.get('upload_progress', {}),
            download_progress=data.get('download_progress', {}),
            errors=data.get('errors', []),
            failed_subjects=data.get('failed_subjects', []),
            start_time=data.get('start_time'),
            restart_jobs=data.get('restart_jobs', []),
            original_script=data.get('original_script'),
        )
        for s in data.get('job_statuses', []):
            state.job_statuses.append(SubjectJobStatus(
                subject_id=s['subject_id'],
                array_index=s['array_index'],
                job_id=s['job_id'],
                status=JobStatus(s.get('status', 'UNKNOWN')),
                start_time=s.get('start_time'),
                elapsed_time=s.get('elapsed_time'),
                node=s.get('node')
            ))
        return state


class HPCConnection:
    """SSH/SFTP connection manager using paramiko."""

    def __init__(self, config: HPCConfig):
        """
        Initialize HPC connection.

        Args:
            config: HPCConfig with connection parameters
        """
        if paramiko is None:
            raise ImportError("paramiko is required for HPC connection. Install with: pip install paramiko")

        self.config = config
        self.ssh: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None
        self._connected = False

    def connect(self) -> bool:
        """
        Establish SSH connection to HPC.

        Returns:
            True if connection successful

        Raises:
            ConnectionError: If connection fails
        """
        try:
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Connection kwargs
            connect_kwargs = {
                'hostname': self.config.host,
                'username': self.config.user,
                'timeout': 30,
            }

            # Use SSH key if specified, otherwise rely on ssh-agent
            if self.config.ssh_key:
                key_path = Path(self.config.ssh_key).expanduser()
                connect_kwargs['key_filename'] = str(key_path)
            else:
                # Use ssh-agent
                connect_kwargs['allow_agent'] = True
                connect_kwargs['look_for_keys'] = True

            self.ssh.connect(**connect_kwargs)
            self.sftp = self.ssh.open_sftp()
            self._connected = True
            return True

        except Exception as e:
            self._connected = False
            raise ConnectionError(f"Failed to connect to {self.config.host}: {e}")

    def disconnect(self) -> None:
        """Close SSH connection."""
        if self.sftp:
            self.sftp.close()
            self.sftp = None
        if self.ssh:
            self.ssh.close()
            self.ssh = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if connection is active."""
        return self._connected and self.ssh is not None

    def execute(self, command: str, timeout: int = 60) -> Tuple[str, str, int]:
        """
        Execute command on remote host.

        Args:
            command: Shell command to execute
            timeout: Command timeout in seconds

        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to HPC")

        stdin, stdout, stderr = self.ssh.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()

        return (
            stdout.read().decode('utf-8'),
            stderr.read().decode('utf-8'),
            exit_code
        )

    def file_exists(self, remote_path: str) -> bool:
        """Check if remote file/directory exists."""
        if not self.is_connected:
            raise ConnectionError("Not connected to HPC")

        try:
            self.sftp.stat(remote_path)
            return True
        except FileNotFoundError:
            return False

    def mkdir_p(self, remote_path: str) -> None:
        """Create remote directory recursively."""
        if not self.is_connected:
            raise ConnectionError("Not connected to HPC")

        dirs_to_create = []
        path = remote_path

        while path:
            if self.file_exists(path):
                break
            dirs_to_create.append(path)
            path = str(Path(path).parent)

        for d in reversed(dirs_to_create):
            try:
                self.sftp.mkdir(d)
            except IOError:
                pass  # Directory may already exist

    def write_file(self, content: str, remote_path: str) -> None:
        """Write content to remote file."""
        if not self.is_connected:
            raise ConnectionError("Not connected to HPC")

        self.mkdir_p(str(Path(remote_path).parent))

        with self.sftp.file(remote_path, 'w') as f:
            f.write(content)

    def read_file(self, remote_path: str) -> str:
        """Read a remote text file."""
        if not self.is_connected:
            raise ConnectionError("Not connected to HPC")

        with self.sftp.file(remote_path, 'r') as f:
            content = f.read()

        if isinstance(content, bytes):
            return content.decode('utf-8')
        return content

    def __enter__(self) -> 'HPCConnection':
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()


class HPCWorkflowManager:
    """
    Full HPC workflow orchestration for fMRIPrep.

    Workflow steps:
    1. upload_batch_selective() - Upload BIDS data (excluding dwi)
    2. generate_slurm_script() - Create SLURM submission script
    3. submit_job() - Submit to HPC queue
    4. check_job_status() - Monitor job progress
    5. download_results() - Retrieve derivatives
    6. cleanup_remote() - Remove uploaded data
    """

    def __init__(
        self,
        hpc_config: HPCConfig,
        local_bids: str,
        local_output: str,
        fmriprep_config: Optional[Dict] = None,
        template_dir: Optional[str] = None
    ):
        """
        Initialize workflow manager.

        Args:
            hpc_config: HPC configuration
            local_bids: Local BIDS directory path
            local_output: Local output directory for derivatives
            fmriprep_config: fMRIPrep settings (output_spaces, flags)
            template_dir: Directory containing Jinja2 templates
        """
        self.config = hpc_config
        self.local_bids = Path(local_bids)
        self.local_output = Path(local_output)
        self.fmriprep_config = fmriprep_config or {}

        # Set up Jinja2 template environment
        if template_dir is None:
            template_dir = Path(__file__).parent.parent / "templates"

        if Environment is not None:
            self.jinja_env = Environment(
                loader=FileSystemLoader(str(template_dir)),
                autoescape=False
            )
        else:
            self.jinja_env = None

        # Connection (lazy initialization)
        self._connection: Optional[HPCConnection] = None

    def get_connection(self) -> HPCConnection:
        """Get or create HPC connection."""
        if self._connection is None or not self._connection.is_connected:
            self._connection = HPCConnection(self.config)
            self._connection.connect()
        return self._connection

    def close_connection(self) -> None:
        """Close HPC connection."""
        if self._connection:
            self._connection.disconnect()
            self._connection = None

    def upload_batch_selective(
        self,
        subjects: List[str],
        progress_callback: Optional[Callable[[str, str, float], None]] = None
    ) -> Dict[str, bool]:
        """
        Upload BIDS data for all subjects in a SINGLE rsync call.

        Uses one SSH connection to avoid HPC rate limiting.
        rsync natively handles: skip identical files, update modified, upload new.

        Args:
            subjects: List of subject IDs (without sub- prefix)
            progress_callback: Callback(subject, status, progress_pct)

        Returns:
            Dict mapping subject_id -> upload_success
        """
        results = {}

        # ── Pre-flight: check which subject dirs exist locally ───────────────
        valid_subjects = []
        for sub_id in subjects:
            if (self.local_bids / f"sub-{sub_id}").exists():
                valid_subjects.append(sub_id)
            else:
                results[sub_id] = False
                if progress_callback:
                    progress_callback(sub_id, "ERROR: Directory not found", 0.0)

        if not valid_subjects:
            return results

        if progress_callback:
            for sub_id in valid_subjects:
                progress_callback(sub_id, "Queued for batch upload...", 0.0)

        # ── Build single rsync command for all subjects ──────────────────────
        ssh_opts = (
            "ssh"
            " -o StrictHostKeyChecking=no"
            " -o ServerAliveInterval=60"
            " -o ServerAliveCountMax=10"
            " -o ControlMaster=auto"
            " -o ControlPath=/tmp/rsync_cm_%h_%p_%r"
            " -o ControlPersist=60"
        )

        remote_target = f"{self.config.user}@{self.config.host}:{self.config.remote_bids}/"

        cmd = [
            "rsync", "-avz",
            "--info=progress2",
            "-e", ssh_opts,
        ]

        # Per-subject include filters
        for sub_id in valid_subjects:
            sub = f"sub-{sub_id}"
            cmd += [f"--include={sub}/", f"--include={sub}/ses-*/"]
            for mod in self.config.modalities:
                cmd += [
                    f"--include={sub}/ses-*/{mod}/",
                    f"--include={sub}/ses-*/{mod}/**",
                ]
            # Include per-subject metadata files
            cmd += [f"--include={sub}/*.json", f"--include={sub}/*.tsv"]

        # Root-level BIDS metadata
        cmd += [
            "--include=dataset_description.json",
            "--include=participants.tsv",
            "--include=participants.json",
        ]

        # Exclude everything else
        cmd += [
            "--exclude=*/",
            "--exclude=*",
        ]

        # Source (trailing / to copy contents) and destination
        cmd += [
            f"{self.local_bids}/",
            remote_target,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour timeout for entire batch
            )

            # rc=0 = success, rc=24 = "some files vanished during transfer" (non-fatal)
            all_ok = result.returncode in (0, 24)

            for sub_id in valid_subjects:
                results[sub_id] = all_ok
                if progress_callback:
                    if all_ok:
                        progress_callback(sub_id, "Complete", 1.0)
                    else:
                        err_msg = (result.stderr or result.stdout or "unknown error")[:200]
                        progress_callback(
                            sub_id,
                            f"ERROR (rc={result.returncode}): {err_msg}",
                            1.0
                        )

            if not all_ok:
                print(f"[upload_batch_selective] rc={result.returncode}\n"
                      f"STDOUT: {result.stdout[:500]}\nSTDERR: {result.stderr[:500]}")

        except subprocess.TimeoutExpired:
            for sub_id in valid_subjects:
                results[sub_id] = False
                if progress_callback:
                    progress_callback(sub_id, "ERROR: Timeout (>1h)", 1.0)
        except Exception as e:
            for sub_id in valid_subjects:
                results[sub_id] = False
                if progress_callback:
                    progress_callback(sub_id, f"ERROR: {str(e)[:200]}", 1.0)

        # Upload dataset_description.json
        self._ensure_dataset_description()

        return results

    def _ensure_dataset_description(self) -> None:
        """Ensure dataset_description.json exists on remote."""
        try:
            conn = self.get_connection()
            remote_desc = f"{self.config.remote_bids}/dataset_description.json"

            if not conn.file_exists(remote_desc):
                # Check if local exists
                local_desc = self.local_bids / "dataset_description.json"
                if local_desc.exists():
                    # Upload it
                    cmd = [
                        "rsync", "-avz",
                        str(local_desc),
                        f"{self.config.user}@{self.config.host}:{remote_desc}"
                    ]
                    subprocess.run(cmd, capture_output=True, timeout=60)
                else:
                    # Create minimal one
                    content = json.dumps({
                        "Name": "BIDS Dataset",
                        "BIDSVersion": "1.6.0",
                        "DatasetType": "raw"
                    })
                    conn.write_file(content, remote_desc)
        except Exception:
            pass  # Non-critical

    def generate_slurm_script(
        self,
        subjects: List[str],
        job_name: str = "fmriprep_long",
        cpus: Optional[int] = None,
        memory: Optional[str] = None,
        time_limit: Optional[str] = None,
        max_concurrent: Optional[int] = None,
        extra_flags: Optional[List[str]] = None
    ) -> str:
        """
        Generate SLURM submission script from Jinja2 template.

        Args:
            subjects: List of subject IDs
            job_name: SLURM job name
            cpus: CPUs per task (default from config)
            memory: Memory allocation (default from config)
            time_limit: Wall time limit (default from config)
            max_concurrent: Max concurrent array tasks (default from config)
            extra_flags: Additional fMRIPrep flags

        Returns:
            Generated SLURM script content
        """
        if self.jinja_env is None:
            raise ImportError("Jinja2 is required. Install with: pip install jinja2")

        # Use defaults from config if not specified
        cpus = cpus or self.config.cpus
        memory = memory or self.config.memory
        time_limit = time_limit or self.config.time_limit
        max_concurrent = max_concurrent or self.config.max_concurrent

        # Get fMRIPrep settings
        output_spaces = self.fmriprep_config.get('output_spaces', [
            "MNI152NLin2009cAsym:res-2",
            "MNI152NLin6Asym:res-2",
            "T1w",
            "fsnative"
        ])

        base_flags = self.fmriprep_config.get('flags', [
            "--subject-anatomical-reference unbiased",
            "--skip-bids-validation",
            "--ignore slicetiming"
        ])

        if extra_flags:
            base_flags = base_flags + extra_flags

        # Calculate memory in MB
        memory_mb = self._parse_memory_to_mb(memory)

        # Render template
        template = self.jinja_env.get_template('fmriprep_slurm.j2')

        script = template.render(
            job_name=job_name,
            num_subjects=len(subjects),
            max_concurrent=max_concurrent,
            partition=self.config.partition,
            cpus=cpus,
            memory=memory,
            memory_mb=memory_mb,
            time_limit=time_limit,
            remote_base=self.config.remote_base,
            remote_bids=self.config.remote_bids,
            remote_fmriprep=self.config.remote_fmriprep,
            remote_work=self.config.remote_work,
            singularity_image=self.config.singularity_fmriprep,
            freesurfer_license=self.config.freesurfer_license,
            output_spaces=output_spaces,
            fmriprep_flags=base_flags,
            subjects=subjects
        )

        return script

    def _parse_memory_to_mb(self, memory: str) -> int:
        """Convert memory string (e.g., '32GB') to MB."""
        memory = memory.upper().strip()

        if memory.endswith('GB'):
            return int(memory[:-2]) * 1024
        elif memory.endswith('G'):
            return int(memory[:-1]) * 1024
        elif memory.endswith('MB'):
            return int(memory[:-2])
        elif memory.endswith('M'):
            return int(memory[:-1])
        else:
            # Assume MB
            return int(memory)

    def submit_job(
        self,
        subjects: List[str],
        script_content: Optional[str] = None,
        **script_kwargs
    ) -> str:
        """
        Submit fMRIPrep job to HPC.

        Args:
            subjects: List of subject IDs
            script_content: Pre-generated script content (optional)
            **script_kwargs: Arguments passed to generate_slurm_script()

        Returns:
            SLURM job ID

        Raises:
            RuntimeError: If submission fails
        """
        conn = self.get_connection()

        # Generate script if not provided
        if script_content is None:
            script_content = self.generate_slurm_script(subjects, **script_kwargs)

        # Upload subject list
        sublist_path = f"{self.config.remote_base}/sublist.txt"
        sublist_content = "\n".join(subjects)
        conn.write_file(sublist_content, sublist_path)

        # Upload SLURM script
        script_path = f"{self.config.remote_base}/fmriprep_job.sh"
        conn.write_file(script_content, script_path)

        # Create necessary directories
        conn.execute(f"mkdir -p {self.config.remote_fmriprep} {self.config.remote_work} {self.config.remote_base}/logs")

        # Clean up orphaned report-generation temp folders (UUID-named dirs in work/)
        # e.g. 20260410-174950_4f621b0a-6e89-42cd-9a60-b547cc4746e9
        conn.execute(
            f"find {self.config.remote_work} -maxdepth 1 -type d "
            f"-regextype posix-extended -regex '.*/[0-9]{{8}}-[0-9]{{6}}_[a-f0-9-]{{36}}$' "
            f"-exec rm -rf {{}} + 2>/dev/null || true"
        )

        # Submit job
        stdout, stderr, exit_code = conn.execute(
            f"cd {self.config.remote_base} && sbatch fmriprep_job.sh"
        )

        if exit_code != 0:
            raise RuntimeError(f"Job submission failed: {stderr}")

        # Extract job ID from sbatch output
        # Expected: "Submitted batch job 12345"
        match = re.search(r'Submitted batch job (\d+)', stdout)
        if not match:
            raise RuntimeError(f"Could not parse job ID from: {stdout}")

        return match.group(1)

    def load_submission_script(self, script_name: str = "fmriprep_job.sh") -> Optional[str]:
        """Load a previously submitted SLURM script from the remote project directory."""
        conn = self.get_connection()
        script_path = f"{self.config.remote_base}/{script_name}"
        if not conn.file_exists(script_path):
            return None

        content = conn.read_file(script_path)
        return content if content.strip() else None

    def check_job_status(
        self,
        job_id: str,
        subjects: List[str],
        local_fmriprep_dir: Optional[str] = None,
    ) -> List[SubjectJobStatus]:
        """
        Check status of submitted job.

        Args:
            job_id: SLURM job ID
            subjects: List of subject IDs (for mapping array indices)

            local_fmriprep_dir: Optional local fmriprep output dir. If provided,
                subjects whose HTML exists locally are reported as COMPLETED
                even after remote cleanup.

        Returns:
            List of SubjectJobStatus for each subject
        """
        conn = self.get_connection()

        # Query squeue for job status
        # Format: JobID, ArrayTaskID, State, StartTime, TimeUsed, NodeList
        stdout, stderr, exit_code = conn.execute(
            f"squeue -j {job_id} -h -o '%A_%a|%T|%S|%M|%N' 2>/dev/null || true"
        )

        # Parse running jobs
        running_jobs = {}
        for line in stdout.strip().split('\n'):
            if not line:
                continue
            try:
                parts = line.split('|')
                if len(parts) >= 2:
                    job_array = parts[0]
                    state = parts[1]
                    start_time = parts[2] if len(parts) > 2 else None
                    elapsed = parts[3] if len(parts) > 3 else None
                    node = parts[4] if len(parts) > 4 else None

                    # Extract array index
                    if '_' in job_array:
                        array_idx = int(job_array.split('_')[1])
                        running_jobs[array_idx] = {
                            'status': state,
                            'start_time': start_time,
                            'elapsed': elapsed,
                            'node': node
                        }
            except (ValueError, IndexError):
                continue

        # Also check sacct for completed jobs - use wider format to catch all states
        # Use --parsable2 for reliable pipe-delimited output
        stdout_sacct, _, _ = conn.execute(
            f"sacct -j {job_id} --parsable2 -n -o 'JobID,State,ExitCode' 2>/dev/null || true"
        )

        completed_jobs = {}
        for line in stdout_sacct.strip().split('\n'):
            if not line:
                continue
            try:
                parts = line.split('|')
                if len(parts) >= 2:
                    job_part = parts[0].strip()
                    state = parts[1].strip()

                    # Only look for array task entries (e.g., "12345_1")
                    # Skip batch/extern steps (contain '.')
                    if '_' in job_part and '.' not in job_part:
                        array_idx = int(job_part.split('_')[1])
                        if array_idx not in running_jobs:
                            completed_jobs[array_idx] = state
            except (ValueError, IndexError):
                continue

        # Build status list
        statuses = []
        for idx, sub_id in enumerate(subjects):
            array_idx = idx + 1  # SLURM arrays are 1-indexed

            if array_idx in running_jobs:
                # Job is actively in squeue (RUNNING or PENDING)
                info = running_jobs[array_idx]
                status = self._parse_slurm_state(info['status'])
                statuses.append(SubjectJobStatus(
                    subject_id=sub_id,
                    array_index=array_idx,
                    job_id=f"{job_id}_{array_idx}",
                    status=status,
                    start_time=info['start_time'],
                    elapsed_time=info['elapsed'],
                    node=info['node']
                ))
            elif array_idx in completed_jobs:
                # Job found in sacct history
                status = self._parse_slurm_state(completed_jobs[array_idx])

                # If sacct says FAILED, verify by checking for output HTML
                # (fMRIPrep may exit non-zero due to Sentry cleanup despite success)
                if status == JobStatus.FAILED:
                    html_exists = conn.file_exists(
                        f"{self.config.remote_fmriprep}/sub-{sub_id}.html"
                    )
                    if not html_exists and local_fmriprep_dir:
                        local_html = Path(local_fmriprep_dir) / f"sub-{sub_id}.html"
                        html_exists = local_html.exists()
                    if html_exists:
                        status = JobStatus.COMPLETED

                statuses.append(SubjectJobStatus(
                    subject_id=sub_id,
                    array_index=array_idx,
                    job_id=f"{job_id}_{array_idx}",
                    status=status
                ))
            else:
                # Not in squeue or sacct - check output files to determine status
                html_exists = conn.file_exists(
                    f"{self.config.remote_fmriprep}/sub-{sub_id}.html"
                )
                if html_exists:
                    # Output HTML exists → completed successfully
                    status = JobStatus.COMPLETED
                else:
                    # Check local fmriprep directory first (handles post-cleanup case
                    # where remote files are gone but HTML was downloaded locally)
                    local_html_exists = False
                    if local_fmriprep_dir:
                        local_html = Path(local_fmriprep_dir) / f"sub-{sub_id}.html"
                        local_html_exists = local_html.exists()

                    if local_html_exists:
                        # HTML was downloaded locally → job genuinely completed
                        status = JobStatus.COMPLETED
                    else:
                        # Try one more time: query sacct for this specific array task
                        stdout_specific, _, _ = conn.execute(
                            f"sacct -j {job_id}_{array_idx} --parsable2 -n -o 'State' 2>/dev/null || true"
                        )
                        specific_state = stdout_specific.strip().split('\n')[0].split('|')[0].strip()
                        if specific_state:
                            status = self._parse_slurm_state(specific_state)
                        else:
                            # Job not found anywhere - unknown/not yet started
                            status = JobStatus.PENDING

                statuses.append(SubjectJobStatus(
                    subject_id=sub_id,
                    array_index=array_idx,
                    job_id=f"{job_id}_{array_idx}",
                    status=status
                ))

        return statuses

    def _parse_slurm_state(self, state: str) -> JobStatus:
        """Convert SLURM state string to JobStatus enum."""
        state = self._normalize_slurm_state(state)
        state_map = {
            'PENDING': JobStatus.PENDING,
            'PD': JobStatus.PENDING,
            'CONFIGURING': JobStatus.PENDING,
            'CF': JobStatus.PENDING,
            'SUSPENDED': JobStatus.PENDING,
            'S': JobStatus.PENDING,
            'RUNNING': JobStatus.RUNNING,
            'R': JobStatus.RUNNING,
            'COMPLETING': JobStatus.COMPLETING,
            'CG': JobStatus.COMPLETING,
            'COMPLETED': JobStatus.COMPLETED,
            'CD': JobStatus.COMPLETED,
            'FAILED': JobStatus.FAILED,
            'F': JobStatus.FAILED,
            'OUT_OF_MEMORY': JobStatus.FAILED,
            'OOM': JobStatus.FAILED,
            'CANCELLED': JobStatus.CANCELLED,
            'CA': JobStatus.CANCELLED,
            'PREEMPTED': JobStatus.CANCELLED,
            'PR': JobStatus.CANCELLED,
            'TIMEOUT': JobStatus.TIMEOUT,
            'TO': JobStatus.TIMEOUT,
            'DEADLINE': JobStatus.TIMEOUT,
            'DL': JobStatus.TIMEOUT,
            'NODE_FAIL': JobStatus.NODE_FAIL,
            'NF': JobStatus.NODE_FAIL,
            'BOOT_FAIL': JobStatus.NODE_FAIL,
            'BF': JobStatus.NODE_FAIL,
        }
        return state_map.get(state, JobStatus.UNKNOWN)

    def _normalize_slurm_state(self, state: str) -> str:
        """Strip sacct decorations like 'CANCELLED by 1234' down to the base state."""
        normalized = (state or "").upper().strip()
        if not normalized:
            return normalized

        normalized = normalized.split()[0].rstrip('+')
        match = re.match(r'[A-Z_]+', normalized)
        return match.group(0) if match else normalized

    def is_job_complete(self, statuses: List[SubjectJobStatus]) -> bool:
        """Check if all jobs have finished (completed, failed, or cancelled)."""
        terminal_states = {
            JobStatus.COMPLETED, JobStatus.FAILED,
            JobStatus.CANCELLED, JobStatus.TIMEOUT, JobStatus.NODE_FAIL
        }
        return all(s.status in terminal_states for s in statuses)

    def cancel_tasks(
        self,
        job_id: str,
        subject_statuses: List[SubjectJobStatus],
    ) -> Dict[str, bool]:
        """
        Cancel specific array tasks by subject.

        Args:
            job_id: Parent SLURM job ID
            subject_statuses: List of SubjectJobStatus objects to cancel

        Returns:
            Dict mapping subject_id -> True if scancel succeeded
        """
        conn = self.get_connection()
        results: Dict[str, bool] = {}
        for s in subject_statuses:
            task_spec = s.job_id if s.job_id and "_" in s.job_id else f"{job_id}_{s.array_index}"
            _, stderr, rc = conn.execute(f"scancel {task_spec}")
            results[s.subject_id] = (rc == 0)
            if rc != 0:
                logger.warning("scancel %s failed: %s", task_spec, stderr.strip())
        return results

    def submit_restart_job(
        self,
        subjects: List[str],
        original_script_content: str,
        restart_index: int,
    ) -> str:
        """
        Submit a restart wave as a new array job for a subset of subjects.

        Uses restart-suffixed filenames so originals are never overwritten.

        Args:
            subjects: List of subject IDs to restart
            original_script_content: The SLURM script from the original submission
            restart_index: 0-based wave number (len(state.restart_jobs) before append)

        Returns:
            New SLURM job ID

        Raises:
            RuntimeError: If submission fails
        """
        conn = self.get_connection()
        label = f"restart{restart_index}"

        # Write the new subject list
        sublist_path = f"{self.config.remote_base}/sublist_{label}.txt"
        conn.write_file("\n".join(subjects), sublist_path)

        # Patch the original script for this restart
        patched = self._patch_restart_script(original_script_content, subjects, label)

        script_path = f"{self.config.remote_base}/fmriprep_{label}.sh"
        conn.write_file(patched, script_path)

        # Ensure directories exist
        conn.execute(
            f"mkdir -p {self.config.remote_fmriprep} {self.config.remote_work} "
            f"{self.config.remote_base}/logs"
        )

        # Submit
        stdout, stderr, exit_code = conn.execute(
            f"cd {self.config.remote_base} && sbatch fmriprep_{label}.sh"
        )

        if exit_code != 0:
            raise RuntimeError(f"Restart submission failed: {stderr}")

        match = re.search(r'Submitted batch job (\d+)', stdout)
        if not match:
            raise RuntimeError(f"Could not parse job ID from: {stdout}")

        return match.group(1)

    def _patch_restart_script(
        self,
        script: str,
        subjects: List[str],
        label: str,
    ) -> str:
        """
        Patch the original SLURM script for a restart wave.

        Substitutions:
        1. Array size:    --array=1-N%M  →  --array=1-{len(subjects)}%M
        2. Sublist file:  sublist.txt    →  sublist_{label}.txt
        3. Job name:      --job-name=X   →  --job-name=X_{label}
        """
        # 1. Rewrite array directive, preserve concurrency cap (%M) if present
        def replace_array(m):
            cap = m.group(1) or ""
            return f"#SBATCH --array=1-{len(subjects)}{cap}"

        script = re.sub(
            r"#SBATCH\s+--array=1-\d+(%\d+)?",
            replace_array,
            script,
        )

        # 2. Sublist filename
        script = script.replace("sublist.txt", f"sublist_{label}.txt")

        # 3. Job name — cosmetic, aids squeue readability
        script = re.sub(
            r"(#SBATCH\s+--job-name=\S+)",
            rf"\1_{label}",
            script,
        )

        return script

    def check_all_job_statuses(
        self,
        state: 'WorkflowState',
        local_fmriprep_dir: Optional[str] = None,
    ) -> List[SubjectJobStatus]:
        """
        Check status across original job and all restart waves.

        Later restart waves shadow earlier ones per subject (last write wins).

        Args:
            state: Current WorkflowState with job_id, subjects, restart_jobs
            local_fmriprep_dir: Local fmriprep directory for HTML fallback checks

        Returns:
            One SubjectJobStatus per subject with the most recent status
        """
        # Start with the original job
        merged: Dict[str, SubjectJobStatus] = {}

        if state.job_id and state.job_id != "reconciled":
            for s in self.check_job_status(
                state.job_id, state.subjects,
                local_fmriprep_dir=local_fmriprep_dir,
            ):
                merged[s.subject_id] = s

        # Each restart wave overwrites entries for its subjects
        for wave in state.restart_jobs:
            wave_subjects = wave.get("subjects", [])
            wave_job_id = wave.get("job_id")
            if wave_job_id and wave_subjects:
                for s in self.check_job_status(
                    wave_job_id, wave_subjects,
                    local_fmriprep_dir=local_fmriprep_dir,
                ):
                    merged[s.subject_id] = s

        # Fallback: if sacct expired and a subject has no live status,
        # keep the last-known status from state.job_statuses
        for s in state.job_statuses:
            if s.subject_id not in merged:
                merged[s.subject_id] = s

        # Return in original subject order
        ordered = []
        for sub_id in state.subjects:
            if sub_id in merged:
                ordered.append(merged[sub_id])
        # Include any subjects only in restart waves (shouldn't happen, but be safe)
        seen = set(state.subjects)
        for sub_id, status in merged.items():
            if sub_id not in seen:
                ordered.append(status)

        return ordered

    def download_results(
        self,
        subjects: List[str],
        progress_callback: Optional[Callable[[str, str, float], None]] = None
    ) -> Dict[str, bool]:
        """
        Download fMRIPrep derivatives for subjects.

        Uses rsync for efficient transfer. Excludes fsnative space to save space.
        Continues even if some subjects fail.

        Args:
            subjects: List of subject IDs
            progress_callback: Callback(subject, status, progress_pct)

        Returns:
            Dict mapping subject_id -> download_success
        """
        results = {}
        total = len(subjects)

        # Ensure local output directory exists
        self.local_output.mkdir(parents=True, exist_ok=True)

        remote_source = f"{self.config.user}@{self.config.host}:{self.config.remote_fmriprep}"

        for idx, sub_id in enumerate(subjects):
            sub_dir = f"sub-{sub_id}"

            if progress_callback:
                progress_callback(sub_id, "Downloading...", idx / total)

            # Download subject directory (excluding fsnative)
            cmd = [
                "rsync", "-avz", "--progress",
                "--exclude=*_space-fsnative_*",
                f"{remote_source}/{sub_dir}/",
                f"{self.local_output}/{sub_dir}/"
            ]

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=3600  # 1 hour timeout per subject
                )

                success = result.returncode == 0

                # Also download HTML report
                if success:
                    html_cmd = [
                        "rsync", "-avz",
                        f"{remote_source}/{sub_dir}.html",
                        f"{self.local_output}/"
                    ]
                    subprocess.run(html_cmd, capture_output=True, timeout=60)

                results[sub_id] = success
                status = "Complete" if success else f"ERROR: {result.stderr[:100]}"

            except subprocess.TimeoutExpired:
                results[sub_id] = False
                status = "ERROR: Timeout"
            except Exception as e:
                results[sub_id] = False
                status = f"ERROR: {str(e)[:100]}"

            if progress_callback:
                progress_callback(sub_id, status, (idx + 1) / total)

        # Download dataset-level files
        try:
            subprocess.run([
                "rsync", "-avz",
                f"{remote_source}/dataset_description.json",
                f"{self.local_output}/"
            ], capture_output=True, timeout=60)

            subprocess.run([
                "rsync", "-avz",
                f"{remote_source}/logs/",
                f"{self.local_output}/logs/"
            ], capture_output=True, timeout=300)
        except Exception:
            pass  # Non-critical

        return results

    def cleanup_remote(
        self,
        subjects: List[str],
        cleanup_bids: bool = True,
        cleanup_derivatives: bool = True,
        cleanup_work: bool = True,
        progress_callback: Optional[Callable[[str, str, float], None]] = None
    ) -> Dict[str, bool]:
        """
        Clean up remote files for subjects.

        Args:
            subjects: List of subject IDs
            cleanup_bids: Remove uploaded BIDS data
            cleanup_derivatives: Remove fMRIPrep outputs
            cleanup_work: Remove work directories
            progress_callback: Callback(subject, status, progress_pct)

        Returns:
            Dict mapping subject_id -> cleanup_success
        """
        results = {}
        total = len(subjects)
        conn = self.get_connection()

        for idx, sub_id in enumerate(subjects):
            if progress_callback:
                progress_callback(sub_id, "Cleaning...", idx / total)

            try:
                rm_paths = []

                if cleanup_bids:
                    rm_paths.append(f"{self.config.remote_bids}/sub-{sub_id}")

                if cleanup_derivatives:
                    rm_paths.append(f"{self.config.remote_fmriprep}/sub-{sub_id}")
                    rm_paths.append(f"{self.config.remote_fmriprep}/sub-{sub_id}.html")

                if cleanup_work:
                    # Remove per-subject work trees across older and newer fMRIPrep layouts.
                    rm_paths.extend([
                        f"{self.config.remote_work}/fmriprep*/single_subject_{sub_id}_wf",
                        f"{self.config.remote_work}/fmriprep*_wf/single_subject_{sub_id}_wf",
                        f"{self.config.remote_work}/fmriprep*_wf/sub_{sub_id}_*",
                        f"{self.config.remote_work}/fmriprep*_wf/sub-{sub_id}*",
                        f"{self.config.remote_work}/fmriprep*sub-{sub_id}*",
                        f"{self.config.remote_work}/fmriprep*sub_{sub_id}*",
                    ])

                if rm_paths:
                    rm_cmd = f"rm -rf {' '.join(rm_paths)}"
                    stdout, stderr, exit_code = conn.execute(rm_cmd, timeout=300)
                    results[sub_id] = exit_code == 0
                else:
                    results[sub_id] = True

                status = "Complete" if results[sub_id] else f"ERROR: {stderr[:100]}"

            except Exception as e:
                results[sub_id] = False
                status = f"ERROR: {str(e)[:100]}"

            if progress_callback:
                progress_callback(sub_id, status, (idx + 1) / total)

        return results

    def run_full_workflow(
        self,
        subjects: List[str],
        progress_callback: Optional[Callable[[str, str, float], None]] = None,
        poll_interval: int = 300
    ) -> WorkflowState:
        """
        Execute complete workflow: upload -> submit -> monitor -> download -> cleanup.

        This is primarily for non-interactive use. For Streamlit, use individual
        methods with manual refresh.

        Args:
            subjects: List of subject IDs
            progress_callback: Progress callback
            poll_interval: Seconds between job status checks

        Returns:
            Final workflow state
        """
        state = WorkflowState(
            subjects=subjects,
            current_step='upload',
            start_time=datetime.now().isoformat()
        )

        try:
            # 1. Upload
            state.upload_progress = {}
            upload_results = self.upload_batch_selective(
                subjects,
                progress_callback=lambda s, st, p: state.upload_progress.update({s: st})
            )

            # Check for complete upload failure
            if not any(upload_results.values()):
                state.errors.append("All uploads failed")
                return state

            # Filter to successfully uploaded subjects
            uploaded_subjects = [s for s, ok in upload_results.items() if ok]

            # 2. Submit
            state.current_step = 'submit'
            state.job_id = self.submit_job(uploaded_subjects)

            # 3. Monitor
            state.current_step = 'monitor'
            while True:
                state.job_statuses = self.check_job_status(state.job_id, uploaded_subjects)

                if self.is_job_complete(state.job_statuses):
                    break

                time.sleep(poll_interval)

            # 4. Download
            state.current_step = 'download'
            successful_subjects = [
                s.subject_id for s in state.job_statuses
                if s.status == JobStatus.COMPLETED
            ]

            state.download_progress = {}
            self.download_results(
                successful_subjects,
                progress_callback=lambda s, st, p: state.download_progress.update({s: st})
            )

            # 5. Cleanup
            state.current_step = 'cleanup'
            self.cleanup_remote(uploaded_subjects)

            state.current_step = 'completed'

        except Exception as e:
            state.errors.append(str(e))

        finally:
            self.close_connection()

        return state
