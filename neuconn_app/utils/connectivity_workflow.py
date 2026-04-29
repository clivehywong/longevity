"""Connectivity-analysis HPC workflow state and submission orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
import json
from pathlib import Path
import re
import shlex
from typing import Dict, List, Optional, Literal, Any, Tuple
from uuid import uuid4

try:  # Support both package and Streamlit page-style imports.
    from .hpc import HPCConfig, HPCConnection
except ImportError:  # pragma: no cover - exercised by Streamlit path manipulation
    from hpc import HPCConfig, HPCConnection

AnalysisType = Literal[
    "local_measures",
    "seed_connectivity",
    "network_connectivity",
    "group_stats",
]

VALID_ANALYSIS_TYPES = {
    "local_measures",
    "seed_connectivity",
    "network_connectivity",
    "group_stats",
}

# Mapping from workflow analysis type to --analysis flag value in the
# XCP-D-driven hpc_submit_subject_level.py
_ANALYSIS_FLAG_MAP = {
    "seed_connectivity": "seed",
    "network_connectivity": "network",
}

VALID_STATUSES = {"submitted", "running", "completed", "failed", "cancelled"}


@dataclass
class ConnectivitySubmission:
    submission_id: str
    analysis_type: AnalysisType
    job_id: Optional[str]
    submitted_at: str
    options: Dict
    subjects: List[str]
    status: str
    output_dir: Optional[str]
    notes: Optional[str] = None


@dataclass
class ConnectivityWorkflowState:
    submissions: Dict[str, ConnectivitySubmission] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Serialize state to a JSON-compatible dictionary."""
        return {
            "submissions": {
                submission_id: asdict(submission)
                for submission_id, submission in self.submissions.items()
            }
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ConnectivityWorkflowState":
        """Load state from a dict, skipping malformed submission entries."""
        state = cls()
        if not isinstance(d, dict):
            return state

        raw_submissions = d.get("submissions", {})
        if isinstance(raw_submissions, list):
            iterable = ((item.get("submission_id"), item) for item in raw_submissions if isinstance(item, dict))
        elif isinstance(raw_submissions, dict):
            iterable = raw_submissions.items()
        else:
            return state

        for key, raw in iterable:
            if not isinstance(raw, dict):
                continue
            try:
                submission_id = str(raw.get("submission_id") or key or "").strip()
                analysis_type = raw.get("analysis_type")
                if not submission_id or analysis_type not in VALID_ANALYSIS_TYPES:
                    continue
                status = raw.get("status") if raw.get("status") in VALID_STATUSES else "submitted"
                subjects = raw.get("subjects", [])
                if not isinstance(subjects, list):
                    subjects = []
                options = raw.get("options", {})
                if not isinstance(options, dict):
                    options = {}
                state.submissions[submission_id] = ConnectivitySubmission(
                    submission_id=submission_id,
                    analysis_type=analysis_type,
                    job_id=raw.get("job_id"),
                    submitted_at=str(raw.get("submitted_at") or ""),
                    options=options,
                    subjects=[str(subject) for subject in subjects],
                    status=status,
                    output_dir=raw.get("output_dir"),
                    notes=raw.get("notes"),
                )
            except Exception:
                continue
        return state

    def add(self, sub: ConnectivitySubmission) -> None:
        self.submissions[sub.submission_id] = sub

    def update_status(
        self,
        submission_id: str,
        status: str,
        job_id: Optional[str] = None,
    ) -> None:
        if submission_id not in self.submissions:
            raise KeyError(f"Unknown connectivity submission: {submission_id}")
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid submission status: {status}")

        submission = self.submissions[submission_id]
        submission.status = status
        if job_id is not None:
            submission.job_id = job_id

    def list_by_type(self, analysis_type: AnalysisType) -> List[ConnectivitySubmission]:
        return [
            submission
            for submission in self.submissions.values()
            if submission.analysis_type == analysis_type
        ]


class ConnectivityWorkflowManager:
    """High-level connectivity-analysis HPC orchestrator using HPCConnection."""

    def __init__(self, config: Dict, connection=None):
        self.config = config or {}
        self.connection = connection
        self.hpc_config = HPCConfig.from_config(self.config)

    @property
    def state_file(self) -> Path:
        bids_dir = self._expand_path(
            self.config.get("paths", {}).get("bids_dir")
            or str(self._project_root() / "bids")
        )
        state_dir = bids_dir.parent / ".neuconn"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / "connectivity_workflow_state.json"

    def load_state(self) -> ConnectivityWorkflowState:
        try:
            if not self.state_file.exists():
                return ConnectivityWorkflowState()
            with open(self.state_file, "r", encoding="utf-8") as f:
                return ConnectivityWorkflowState.from_dict(json.load(f))
        except Exception:
            return ConnectivityWorkflowState()

    def save_state(self, state: ConnectivityWorkflowState) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, indent=2)

    def build_subject_level_command(
        self,
        analysis_type: AnalysisType,
        options: Dict,
        subjects: List[str],
    ) -> str:
        """Build the CLI command for script/hpc_submit_subject_level.py.

        ``local_measures`` is no longer submitted as a separate job (XCP-D
        produces those outputs natively).  Passing ``local_measures`` raises
        :class:`ValueError`.

        The command uses the XCP-D-driven ``--analysis {seed|network}`` flag
        together with ``--pipeline``, ``--measures``, repeated ``--seed`` /
        ``--atlas`` flags, ``--bids-root``, and ``--out-root``.
        """
        if analysis_type == "group_stats":
            raise ValueError("Use build_group_level_command for group_stats submissions")
        if analysis_type not in VALID_ANALYSIS_TYPES:
            raise ValueError(f"Unsupported analysis type: {analysis_type}")
        if analysis_type == "local_measures":
            raise ValueError(
                "local_measures is now produced by XCP-D; no subject-level "
                "submission is needed.  Use seed_connectivity or network_connectivity."
            )

        options = options or {}
        script_path = self._script_path("hpc_submit_subject_level.py", options)
        analysis_flag = _ANALYSIS_FLAG_MAP[analysis_type]
        parts = ["python", shlex.quote(str(script_path)), "--analysis", shlex.quote(analysis_flag)]

        # Core XCP-D flags
        scalar_options = [
            ("pipeline", "--pipeline"),
            ("measures", "--measures"),
            ("bids_root", "--bids-root"),
            ("out_root", "--out-root"),
            ("tr", "--tr"),
            ("max_parallel", "--max-parallel"),
            ("time", "--time"),
            ("memory", "--memory"),
            ("partition", "--partition"),
            ("cpus", "--cpus"),
            ("log_dir", "--log-dir"),
            ("output_dir", "--output-dir"),
        ]
        for key, flag in scalar_options:
            self._append_option(parts, flag, options.get(key))

        # Subjects filter
        self._append_option(parts, "--subjects", subjects)

        # Repeatable --seed flags (seed analysis)
        seeds = options.get("seeds") or options.get("seed") or []
        if isinstance(seeds, str):
            seeds = [s.strip() for s in seeds.split(",") if s.strip()]
        for seed in seeds:
            if seed:
                parts.extend(["--seed", shlex.quote(str(seed))])

        # Repeatable --atlas flags (network analysis)
        atlases = options.get("atlases") or options.get("atlas")
        if atlases is not None:
            if isinstance(atlases, str):
                atlases = [a.strip() for a in atlases.split(",") if a.strip()]
            for atlas in atlases:
                if atlas:
                    parts.extend(["--atlas", shlex.quote(str(atlas))])

        # Boolean flags
        for key, flag in (
            ("test_mode", "--test-mode"),
            ("dry_run", "--dry-run"),
            ("force", "--force"),
            ("validate", "--validate"),
            ("summary", "--summary"),
        ):
            if options.get(key) is True:
                parts.append(flag)

        return " ".join(parts)

    def build_group_level_command(self, options: Dict) -> str:
        """Build the CLI command for script/hpc_submit_group_level.py.

        Supports both the new XCP-D-driven ``--kind {voxel,matrix}`` path and
        the legacy path (no ``--kind``).
        """
        options = options or {}
        script_path = self._script_path("hpc_submit_group_level.py", options)
        parts = ["python", shlex.quote(str(script_path))]

        # New XCP-D routing flag
        if options.get("kind"):
            self._append_option(parts, "--kind", options.get("kind"))

        # Shared XCP-D arguments
        xcpd_option_map = [
            ("bids_root", "--bids-root"),
            ("pipeline", "--pipeline"),
            ("measure", "--measure"),
            ("contrast", "--contrast"),
            ("method", "--method"),
            ("group_csv", "--group-csv"),
            ("out", "--out"),
            # voxel-specific
            ("mask", "--mask"),
            # matrix-specific
            ("matrix_kind", "--matrix-kind"),
            ("atlas", "--atlas"),
            ("seed_id", "--seed-id"),
            ("threshold", "--threshold"),
            ("alpha", "--alpha"),
            ("n_permutations", "--n-permutations"),
            # SLURM resources
            ("time", "--time"),
            ("memory", "--memory"),
            ("partition", "--partition"),
            ("cpus", "--cpus"),
            ("log_dir", "--log-dir"),
        ]
        for key, flag in xcpd_option_map:
            self._append_option(parts, flag, options.get(key))

        # Legacy options (kept for backward compatibility)
        legacy_option_map = [
            ("subject_job_id", "--subject-job-id"),
            ("config", "--config"),
            ("analysis_source", "--analysis-source"),
            ("measures", "--measures"),
            ("seeds", "--seeds"),
            ("network_grouping", "--network-grouping"),
            ("model_formula", "--model-formula"),
            ("covariates", "--covariates"),
            ("correction_method", "--correction-method"),
            ("cluster_forming_p", "--cluster-forming-p"),
            ("cluster_p", "--cluster-p"),
            ("q_threshold", "--q-threshold"),
            ("custom_mask", "--custom-mask"),
            ("min_subjects_pct", "--min-subjects-pct"),
            ("manifest_path", "--manifest"),
            ("max_parallel", "--max-parallel"),
            ("project_dir", "--project-dir"),
            ("remote_project_dir", "--remote-project-dir"),
        ]
        for key, flag in legacy_option_map:
            self._append_option(parts, flag, options.get(key))

        if options.get("test_mode") is True:
            parts.append("--test-mode")
        if options.get("dry_run") is True:
            parts.append("--dry-run")

        return " ".join(parts)

    def submit(
        self,
        analysis_type: AnalysisType,
        options: Dict,
        subjects: List[str],
        dry_run: bool = False,
    ) -> ConnectivitySubmission:
        """Submit, or dry-run, a connectivity analysis and persist its record."""
        if analysis_type not in VALID_ANALYSIS_TYPES:
            raise ValueError(f"Unsupported analysis type: {analysis_type}")

        options_copy = dict(options or {})
        command = (
            self.build_group_level_command(options_copy)
            if analysis_type == "group_stats"
            else self.build_subject_level_command(analysis_type, options_copy, subjects)
        )

        job_id: Optional[str] = "DRY_RUN" if dry_run else None
        status = "submitted"
        notes = None
        if dry_run:
            options_copy["command_preview"] = command
        else:
            stdout, stderr, exit_code = self._execute(command, timeout=int(options_copy.get("timeout", 120)))
            job_id = self._extract_job_id(stdout) or self._extract_job_id(stderr)
            if exit_code != 0:
                status = "failed"
                notes = (stderr or stdout or f"Submission command failed with exit code {exit_code}").strip()
            elif not job_id:
                notes = (stdout or stderr or "Submission completed but no SLURM job ID was detected").strip()

        submission = ConnectivitySubmission(
            submission_id=self._new_submission_id(),
            analysis_type=analysis_type,
            job_id=job_id,
            submitted_at=datetime.now().isoformat(),
            options=options_copy,
            subjects=list(subjects or []),
            status=status,
            output_dir=self._output_dir(analysis_type, options_copy),
            notes=notes,
        )
        state = self.load_state()
        state.add(submission)
        self.save_state(state)
        return submission

    def refresh_status(self, submission_id: str) -> str:
        """Query SLURM for current status and persist the normalized result."""
        state = self.load_state()
        submission = state.submissions.get(submission_id)
        if submission is None:
            raise KeyError(f"Unknown connectivity submission: {submission_id}")
        if not submission.job_id:
            return submission.status
        if submission.job_id == "DRY_RUN":
            return submission.status

        job_id = shlex.quote(str(submission.job_id))
        sacct_cmd = f"sacct -j {job_id} --noheader --format=State --parsable2 | head -n 1"
        stdout, _, exit_code = self._execute(sacct_cmd, timeout=30)
        slurm_state = stdout.strip().splitlines()[0].strip() if stdout.strip() else ""

        if exit_code != 0 or not slurm_state:
            squeue_cmd = f"squeue -h -j {job_id} -o %T | head -n 1"
            stdout, _, _ = self._execute(squeue_cmd, timeout=30)
            slurm_state = stdout.strip().splitlines()[0].strip() if stdout.strip() else ""

        normalized = self._normalize_slurm_state(slurm_state)
        state.update_status(submission_id, normalized)
        self.save_state(state)
        return normalized

    def cancel(self, submission_id: str) -> bool:
        """Cancel a SLURM job with scancel and mark it cancelled on success."""
        state = self.load_state()
        submission = state.submissions.get(submission_id)
        if submission is None:
            raise KeyError(f"Unknown connectivity submission: {submission_id}")
        if not submission.job_id or submission.job_id == "DRY_RUN":
            state.update_status(submission_id, "cancelled")
            self.save_state(state)
            return True

        _, stderr, exit_code = self._execute(f"scancel {shlex.quote(str(submission.job_id))}", timeout=30)
        if exit_code == 0:
            state.update_status(submission_id, "cancelled")
            self.save_state(state)
            return True
        submission.notes = (stderr or "scancel failed").strip()
        self.save_state(state)
        return False

    def list_submissions(self) -> List[ConnectivitySubmission]:
        return sorted(
            self.load_state().submissions.values(),
            key=lambda submission: submission.submitted_at,
            reverse=True,
        )

    def _execute(self, command: str, timeout: int = 60) -> Tuple[str, str, int]:
        connection = self.connection
        created_connection = False
        if connection is None:
            connection = HPCConnection(self.hpc_config)
            created_connection = True

        try:
            if hasattr(connection, "is_connected") and not connection.is_connected:
                connection.connect()
            elif hasattr(connection, "connect") and not hasattr(connection, "is_connected"):
                connection.connect()
            return connection.execute(command, timeout=timeout)
        finally:
            if created_connection and hasattr(connection, "disconnect"):
                connection.disconnect()

    def _script_path(self, script_name: str, options: Dict) -> Path:
        project_root = options.get("remote_project_dir") or options.get("project_root")
        if not project_root:
            project_root = self.hpc_config.remote_base or str(self._project_root())
        return Path(str(project_root)).expanduser() / "script" / script_name

    def _project_root(self) -> Path:
        configured = self.config.get("paths", {}).get("project_root") or self.config.get("project_root")
        if configured:
            return self._expand_path(configured)
        return Path(__file__).resolve().parents[2]

    @staticmethod
    def _expand_path(path_value: Any) -> Path:
        return Path(str(path_value)).expanduser()

    @staticmethod
    def _append_option(parts: List[str], flag: str, value: Any) -> None:
        if value is None or value == "" or value == [] or value == ():
            return
        if isinstance(value, bool):
            if value:
                parts.append(flag)
            return
        if isinstance(value, (list, tuple, set)):
            value = ",".join(str(item) for item in value if item is not None and str(item) != "")
            if not value:
                return
        parts.extend([flag, shlex.quote(str(value))])

    @staticmethod
    def _extract_job_id(output: str) -> Optional[str]:
        if not output:
            return None
        match = re.search(r"Submitted batch job\s+(\d+)", output)
        if match:
            return match.group(1)
        match = re.search(r"\b(\d+)(?:_[\d-]+)?\b", output.strip())
        return match.group(1) if match else None

    @staticmethod
    def _normalize_slurm_state(slurm_state: str) -> str:
        state = (slurm_state or "").strip().upper().split()[0]
        if state in {"COMPLETED"}:
            return "completed"
        if state in {"RUNNING", "COMPLETING", "CONFIGURING", "RESIZING"}:
            return "running"
        if state in {"PENDING", "SUSPENDED"}:
            return "submitted"
        if state in {"CANCELLED", "CANCELLED+"}:
            return "cancelled"
        if state in {"FAILED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY", "PREEMPTED", "BOOT_FAIL"}:
            return "failed"
        return "failed" if state else "submitted"

    def _output_dir(self, analysis_type: AnalysisType, options: Dict) -> Optional[str]:
        if options.get("output_dir"):
            return str(options["output_dir"])
        paths = self.config.get("paths", {})
        if analysis_type == "group_stats":
            return paths.get("group_level_dir")
        return paths.get("subject_level_dir") or paths.get("derivatives_dir")

    @staticmethod
    def _new_submission_id() -> str:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"conn-{timestamp}-{uuid4().hex[:8]}"
