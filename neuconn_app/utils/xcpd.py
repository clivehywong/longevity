"""
XCP-D execution helpers.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import json
import os
import shlex
import signal
import subprocess

try:
    from jinja2 import Environment, FileSystemLoader
except ImportError:
    Environment = None  # type: ignore[assignment,misc]
    FileSystemLoader = None  # type: ignore[assignment]

from utils.pipeline_state import set_run_info, set_step_status, append_pipeline_log
from utils.hpc import HPCConfig, HPCConnection
from utils.xcpd_atlases import (
    atlas_cli_dataset_args,
    custom_xcpd_atlas_ids,
    ensure_xcpd_atlas_dataset,
    normalize_xcpd_atlas_selection,
    remote_xcpd_atlas_dataset_path,
)


def _safe_disconnect(conn: Optional[HPCConnection]) -> None:
    if conn is None:
        return
    try:
        conn.disconnect()
    except Exception:
        pass


def _strip_bids_prefix(values: Optional[Iterable[str]], prefix: str) -> List[str]:
    if not values:
        return []
    stripped = []
    for value in values:
        text = str(value)
        if text.startswith(prefix):
            text = text[len(prefix):]
        stripped.append(text)
    return stripped


def _bind_arg(path: str) -> str:
    expanded = os.path.expanduser(path)
    return f"{expanded}:{expanded}"


def _deduplicate_paths(paths: Iterable[str]) -> List[str]:
    unique: List[str] = []
    for path in paths:
        if path and path not in unique:
            unique.append(path)
    return unique


def _build_remote_bind_mounts(config: Dict[str, Any], hpc_cfg: HPCConfig) -> List[str]:
    base = hpc_cfg.remote_base
    remote_derivatives = str(Path(base) / "derivatives") if base else ""

    remote_bind_mounts = config.get("hpc", {}).get("remote_bind_mounts", [])
    if remote_bind_mounts:
        resolved: List[str] = []
        expansions = {
            "base": base,
            "bids": hpc_cfg.remote_bids,
            "fmriprep": hpc_cfg.remote_fmriprep,
            "xcpd_fc": hpc_cfg.remote_xcpd_fc,
            "xcpd_ec": hpc_cfg.remote_xcpd_ec,
            "work": hpc_cfg.remote_work,
            "derivatives": remote_derivatives,
            "atlases": str(Path(base) / "atlases") if base else "",
        }
        for bind_mount in remote_bind_mounts:
            text = str(bind_mount)
            for key, value in expansions.items():
                text = text.replace(f"${{{key}}}", value)
            resolved.append(text)
        return _deduplicate_paths(resolved)

    return _deduplicate_paths(
        [
            base,
            hpc_cfg.remote_bids,
            remote_derivatives,
            str(Path(base) / "atlases") if base else "",
            hpc_cfg.remote_work,
            str(Path(hpc_cfg.singularity_xcpd).parent) if hpc_cfg.singularity_xcpd else "",
        ]
    )


def _local_xcpd_image(config: Dict[str, Any]) -> str:
    """Return the resolved local XCP-D Singularity image path.

    Preference order:
    1. software.singularity_images.xcp_d  (new canonical key)
    2. xcpd.singularity_image_path        (legacy key, kept for backward compat)
    """
    software_path = config.get("software", {}).get("singularity_images", {}).get("xcp_d", "")
    if software_path:
        return os.path.expanduser(software_path)
    return os.path.expanduser(config["xcpd"]["singularity_image_path"])


def _local_bind_mounts(config: Dict[str, Any]) -> List[str]:
    """Return local bind mounts, preferring software.singularity_bind_mounts."""
    mounts = config.get("software", {}).get("singularity_bind_mounts")
    if mounts:
        return mounts
    return config["xcpd"].get("singularity_bind_mounts", [])



def build_xcpd_command(
    config: Dict[str, Any],
    pipeline_name: str,
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
) -> List[str]:
    """Build the Singularity command for an XCP-D run."""
    paths = config["paths"]
    xcpd_config = config["xcpd"][pipeline_name]
    image_path = _local_xcpd_image(config)
    bind_mounts = _local_bind_mounts(config)
    selected_atlases = normalize_xcpd_atlas_selection(xcpd_config.get("atlases", []))

    output_dir = paths["xcpd_fc_dir"] if pipeline_name == "fc" else paths["xcpd_ec_dir"]
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    command = ["singularity", "run"]
    for bind_mount in bind_mounts:
        command.extend(["-B", _bind_arg(bind_mount)])

    dataset_root = ensure_xcpd_atlas_dataset(config, selected_atlases)
    command.extend(
        [
            image_path,
            paths["fmriprep_dir"],
            output_dir,
            "participant",
            "--mode",
            str(xcpd_config["mode"]),
            "-p",
            str(xcpd_config["nuisance_regressors"]),
            "-f",
            str(xcpd_config["fd_thresh"]),
            "--min-time",
            str(xcpd_config["min_time"]),
            "--motion-filter-type",
            str(xcpd_config["motion_filter_type"]),
            "--band-stop-min",
            str(xcpd_config["band_stop_min"]),
            "--band-stop-max",
            str(xcpd_config["band_stop_max"]),
            "--lower-bpf",
            str(xcpd_config["lower_bpf"]),
            "--upper-bpf",
            str(xcpd_config["upper_bpf"]),
            "--smoothing",
            str(xcpd_config["smoothing"]),
            "--output-type",
            str(xcpd_config["output_type"]),
            "--output-layout",
            str(xcpd_config.get("output_layout", "bids")),
            "--input-type",
            str(xcpd_config.get("input_type", "fmriprep")),
            "--file-format",
            str(xcpd_config.get("file_format", "nifti")),
            "--report-output-level",
            str(xcpd_config.get("report_output_level", "session")),
        ]
    )

    command.extend(atlas_cli_dataset_args(config, selected_atlases, str(dataset_root) if dataset_root else None))
    if selected_atlases:
        command.extend(["--atlases", *[str(atlas) for atlas in selected_atlases]])

    participant_labels = _strip_bids_prefix(participant_labels, "sub-")
    if participant_labels:
        command.extend(["--participant-label", *participant_labels])

    session_ids = _strip_bids_prefix(session_ids, "ses-")
    if session_ids:
        command.extend(["--session-id", *session_ids])

    return command


def build_remote_xcpd_command(
    config: Dict[str, Any],
    pipeline_name: str,
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
    remote_dataset_root: Optional[str] = None,
) -> List[str]:
    """Build the remote Singularity command for an XCP-D run."""
    hpc_cfg = HPCConfig.from_config(config)
    xcpd_config = config["xcpd"][pipeline_name]
    image_path = os.path.expanduser(hpc_cfg.singularity_xcpd or config["xcpd"]["singularity_image_path"])
    remote_output = hpc_cfg.remote_xcpd_fc if pipeline_name == "fc" else hpc_cfg.remote_xcpd_ec
    selected_atlases = normalize_xcpd_atlas_selection(xcpd_config.get("atlases", []))

    bind_mounts = _build_remote_bind_mounts(config, hpc_cfg)
    command = ["singularity", "run"]
    for bind_mount in bind_mounts:
        command.extend(["-B", f"{bind_mount}:{bind_mount}"])

    command.extend(
        [
            image_path,
            hpc_cfg.remote_fmriprep,
            remote_output,
            "participant",
            "--mode",
            str(xcpd_config["mode"]),
            "-p",
            str(xcpd_config["nuisance_regressors"]),
            "-f",
            str(xcpd_config["fd_thresh"]),
            "--min-time",
            str(xcpd_config["min_time"]),
            "--motion-filter-type",
            str(xcpd_config["motion_filter_type"]),
            "--band-stop-min",
            str(xcpd_config["band_stop_min"]),
            "--band-stop-max",
            str(xcpd_config["band_stop_max"]),
            "--lower-bpf",
            str(xcpd_config["lower_bpf"]),
            "--upper-bpf",
            str(xcpd_config["upper_bpf"]),
            "--smoothing",
            str(xcpd_config["smoothing"]),
            "--output-type",
            str(xcpd_config["output_type"]),
            "--output-layout",
            str(xcpd_config.get("output_layout", "bids")),
            "--input-type",
            str(xcpd_config.get("input_type", "fmriprep")),
            "--file-format",
            str(xcpd_config.get("file_format", "nifti")),
            "--report-output-level",
            str(xcpd_config.get("report_output_level", "session")),
        ]
    )

    command.extend(atlas_cli_dataset_args(config, selected_atlases, remote_dataset_root))
    if selected_atlases:
        command.extend(["--atlases", *[str(atlas) for atlas in selected_atlases]])

    participant_labels = _strip_bids_prefix(participant_labels, "sub-")
    if participant_labels:
        command.extend(["--participant-label", *participant_labels])

    session_ids = _strip_bids_prefix(session_ids, "ses-")
    if session_ids:
        command.extend(["--session-id", *session_ids])

    return command


def generate_xcpd_slurm_script(
    config: Dict[str, Any],
    pipeline_name: str,
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
    remote_dataset_root: Optional[str] = None,
) -> str:
    """Render the XCP-D SLURM batch script using the xcpd_slurm.j2 template.

    Returns the rendered script as a string.
    """
    if Environment is None:
        raise RuntimeError("jinja2 is required but not installed")

    hpc_cfg = HPCConfig.from_config(config)
    remote_output = hpc_cfg.remote_xcpd_fc if pipeline_name == "fc" else hpc_cfg.remote_xcpd_ec

    # Build the full singularity command, then strip off the "singularity run -B … image"
    # prefix to get just the XCP-D CLI arguments.
    full_command = build_remote_xcpd_command(
        config,
        pipeline_name,
        participant_labels=participant_labels,
        session_ids=session_ids,
        remote_dataset_root=remote_dataset_root,
    )
    # full_command = ["singularity", "run", "-B", "...", ..., image_path, fmriprep_dir, ...]
    # Split at the image path to get post-image args; the template handles bind mounts separately.
    image_path = hpc_cfg.singularity_xcpd or config["xcpd"]["singularity_image_path"]
    try:
        img_idx = full_command.index(image_path)
        xcpd_args = " ".join(shlex.quote(p) for p in full_command[img_idx + 1:])
    except ValueError:
        # Fallback: use everything after the last bind-mount argument
        xcpd_args = " ".join(shlex.quote(p) for p in full_command[2:])

    bind_mounts = _build_remote_bind_mounts(config, hpc_cfg)

    cpus = hpc_cfg.xcpd_cpus if hpc_cfg.xcpd_cpus else hpc_cfg.cpus
    memory = hpc_cfg.xcpd_memory if hpc_cfg.xcpd_memory else hpc_cfg.memory
    time_limit = hpc_cfg.xcpd_time_limit if hpc_cfg.xcpd_time_limit else hpc_cfg.time_limit

    templates_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    template = env.get_template("xcpd_slurm.j2")

    return template.render(
        job_name=f"xcpd_{pipeline_name}",
        pipeline=pipeline_name,
        partition=hpc_cfg.partition,
        cpus=cpus,
        memory=memory,
        time_limit=time_limit,
        remote_base=hpc_cfg.remote_base,
        remote_output=remote_output,
        remote_fmriprep=hpc_cfg.remote_fmriprep,
        remote_work=hpc_cfg.remote_work,
        singularity_image=image_path,
        bind_mounts=bind_mounts,
        xcpd_args=xcpd_args,
        participants=list(_strip_bids_prefix(participant_labels, "sub-") or []),
    )



    qc_root = Path(
        config["paths"]["xcpd_fc_qc_dir"]
        if pipeline_name == "fc"
        else config["paths"]["xcpd_ec_qc_dir"]
    )
    qc_root.mkdir(parents=True, exist_ok=True)
    run_dir = qc_root / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return {
        "run_dir": run_dir,
        "log_file": run_dir / f"{pipeline_name}_xcpd.log",
        "command_file": run_dir / f"{pipeline_name}_command.txt",
        "manifest_file": run_dir / f"{pipeline_name}_manifest.json",
    }


def start_xcpd_run(
    config: Dict[str, Any],
    pipeline_name: str,
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Start a background XCP-D run and persist its metadata."""
    artifacts = _run_artifact_paths(config, pipeline_name)
    command = build_xcpd_command(
        config,
        pipeline_name,
        participant_labels=participant_labels,
        session_ids=session_ids,
    )

    with open(artifacts["command_file"], "w") as f:
        f.write(" ".join(shlex.quote(part) for part in command) + "\n")

    log_handle = open(artifacts["log_file"], "w")
    process = subprocess.Popen(
        command,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_handle.close()

    run_info = {
        "pipeline": pipeline_name,
        "pid": process.pid,
        "status": "running",
        "command": command,
        "started_at": datetime.now().isoformat(),
        "participant_labels": list(participant_labels or []),
        "session_ids": list(session_ids or []),
        "run_dir": str(artifacts["run_dir"]),
        "log_file": str(artifacts["log_file"]),
    }

    with open(artifacts["manifest_file"], "w") as f:
        json.dump(run_info, f, indent=2)

    set_run_info(config, f"xcpd_{pipeline_name}", run_info)
    set_step_status(config, f"xcpd_{pipeline_name}", "running", f"PID {process.pid}")
    append_pipeline_log(config, f"Started XCP-D {pipeline_name.upper()} run (pid={process.pid})")
    return run_info


def start_remote_xcpd_run(
    config: Dict[str, Any],
    pipeline_name: str,
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Submit an XCP-D SLURM job on the configured HPC host."""
    artifacts = _run_artifact_paths(config, pipeline_name)
    hpc_cfg = HPCConfig.from_config(config)
    selected_atlases = normalize_xcpd_atlas_selection(config["xcpd"][pipeline_name].get("atlases", []))
    remote_dataset_root = _sync_remote_xcpd_atlas_dataset(config, selected_atlases, hpc_cfg)

    # Render SLURM script
    script_content = generate_xcpd_slurm_script(
        config,
        pipeline_name,
        participant_labels=participant_labels,
        session_ids=session_ids,
        remote_dataset_root=remote_dataset_root,
    )

    # Save script locally for inspection
    local_script = artifacts["run_dir"] / f"xcpd_{pipeline_name}_job.sh"
    with open(local_script, "w") as f:
        f.write(script_content)

    # Upload script to HPC and submit
    remote_script = f"{hpc_cfg.remote_base}/xcpd_{pipeline_name}_job.sh"
    remote_log_out = f"{hpc_cfg.remote_base}/logs/xcpd_{pipeline_name}_${{SLURM_JOB_ID}}.out"
    remote_log_err = f"{hpc_cfg.remote_base}/logs/xcpd_{pipeline_name}_${{SLURM_JOB_ID}}.err"

    conn = None
    try:
        conn = HPCConnection(hpc_cfg)
        conn.connect()
        conn.write_file(remote_script, script_content)
        mkdir_cmd = f"mkdir -p {shlex.quote(f'{hpc_cfg.remote_base}/logs')}"
        conn.execute(mkdir_cmd, timeout=30)
        sbatch_cmd = f"sbatch {shlex.quote(remote_script)}"
        stdout, stderr, exit_code = conn.execute(sbatch_cmd, timeout=60)
    finally:
        _safe_disconnect(conn)

    if exit_code != 0:
        raise RuntimeError(stderr or stdout or "sbatch failed")

    # sbatch stdout: "Submitted batch job 12345"
    job_id = stdout.strip().split()[-1]

    run_info = {
        "pipeline": pipeline_name,
        "job_id": job_id,
        "status": "running",
        "backend": "hpc",
        "remote_script": remote_script,
        "remote_log_out": remote_log_out,
        "remote_log_err": remote_log_err,
        "started_at": datetime.now().isoformat(),
        "participant_labels": list(participant_labels or []),
        "session_ids": list(session_ids or []),
        "run_dir": str(artifacts["run_dir"]),
        "log_file": str(artifacts["log_file"]),
        "local_script": str(local_script),
    }
    with open(artifacts["manifest_file"], "w") as f:
        json.dump(run_info, f, indent=2)

    set_run_info(config, f"xcpd_{pipeline_name}", run_info)
    set_step_status(config, f"xcpd_{pipeline_name}", "running", f"SLURM job {job_id}")
    append_pipeline_log(config, f"Submitted XCP-D {pipeline_name.upper()} SLURM job {job_id}")
    return run_info


def is_process_running(pid: int) -> bool:
    """Check whether a PID is still alive."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def refresh_xcpd_run(config: Dict[str, Any], pipeline_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Refresh the status of an XCP-D run stored in pipeline state."""
    run_key = f"xcpd_{pipeline_name}"
    run_info = state.get("runs", {}).get(run_key)
    if not run_info:
        return state

    backend = run_info.get("backend", "local")
    job_id = run_info.get("job_id")
    pid = run_info.get("pid")

    if backend == "hpc" and job_id:
        conn = None
        try:
            hpc_cfg = HPCConfig.from_config(config)
            conn = HPCConnection(hpc_cfg)
            conn.connect()
            stdout, _, _ = conn.execute(
                f"squeue -j {shlex.quote(str(job_id))} -h -o %T 2>/dev/null || sacct -j {shlex.quote(str(job_id))} -n -o State 2>/dev/null | head -1",
                timeout=30,
            )
            slurm_state = stdout.strip().upper()
            if slurm_state in ("RUNNING", "PENDING", "COMPLETING"):
                return state
        except Exception:
            return state
        finally:
            _safe_disconnect(conn)
    elif backend == "hpc" and pid:
        # Legacy: old runs tracked by PID
        conn = None
        try:
            hpc_cfg = HPCConfig.from_config(config)
            conn = HPCConnection(hpc_cfg)
            conn.connect()
            stdout, _, _ = conn.execute(f"ps -p {int(pid)} -o pid=", timeout=30)
            if stdout.strip():
                return state
        except Exception:
            return state
        finally:
            _safe_disconnect(conn)
    elif pid and is_process_running(pid):
        return state

    run_info["status"] = "completed"
    run_info["completed_at"] = datetime.now().isoformat()
    state["runs"][run_key] = run_info
    set_run_info(config, run_key, run_info, state=state)
    set_step_status(config, f"xcpd_{pipeline_name}", "completed", "Process finished", state=state)
    append_pipeline_log(config, f"XCP-D {pipeline_name.upper()} run finished", state=state)
    return state


def stop_xcpd_run(config: Dict[str, Any], pipeline_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Terminate a running XCP-D process or cancel a SLURM job."""
    run_key = f"xcpd_{pipeline_name}"
    run_info = state.get("runs", {}).get(run_key)
    if not run_info:
        return state

    backend = run_info.get("backend", "local")
    job_id = run_info.get("job_id")
    pid = run_info.get("pid")

    try:
        if backend == "hpc":
            conn = None
            try:
                hpc_cfg = HPCConfig.from_config(config)
                conn = HPCConnection(hpc_cfg)
                conn.connect()
                if job_id:
                    cancel_cmd = f"scancel {shlex.quote(str(job_id))}"
                else:
                    cancel_cmd = f"kill {int(pid)}"
                stdout, stderr, exit_code = conn.execute(cancel_cmd, timeout=30)
                if exit_code != 0:
                    raise RuntimeError(stderr or stdout or f"Cancel exited with status {exit_code}")
            except Exception as exc:
                _safe_disconnect(conn)
                set_step_status(
                    config,
                    f"xcpd_{pipeline_name}",
                    "failed",
                    f"Failed to stop HPC job: {exc}",
                    state=state,
                )
                append_pipeline_log(
                    config,
                    f"Failed to stop XCP-D {pipeline_name.upper()} run on HPC: {exc}",
                    level="error",
                    state=state,
                )
                return state
            finally:
                _safe_disconnect(conn)
        elif pid:
            os.killpg(int(pid), signal.SIGTERM)

        run_info["status"] = "stopped"
        run_info["stopped_at"] = datetime.now().isoformat()
        state["runs"][run_key] = run_info
        set_run_info(config, run_key, run_info, state=state)
        set_step_status(config, f"xcpd_{pipeline_name}", "failed", "Stopped by user", state=state)
        append_pipeline_log(config, f"Stopped XCP-D {pipeline_name.upper()} run", level="warning", state=state)
    except ProcessLookupError:
        pass
    return state


def collect_qc_reports(output_dir: Path) -> Dict[str, List[Path]]:
    """Collect QC artifacts produced by XCP-D."""
    return {
        "qc_csv": sorted(output_dir.glob("**/*_qc.csv")),
        "exec_reports": sorted(output_dir.glob("**/*exec_report*.html")),
        "timeseries": sorted(output_dir.glob("**/*timeseries*.tsv")),
        "connectomes": sorted(output_dir.glob("**/*connectome*.tsv")),
        "bold": sorted(output_dir.glob("**/*desc-denoised_bold.nii.gz")),
        "reho": sorted(output_dir.glob("**/*_reho.nii.gz")),
        "alff": sorted(output_dir.glob("**/*_alff.nii.gz")),
        "falff": sorted(output_dir.glob("**/*_falff.nii.gz")),
    }


def _sync_remote_xcpd_atlas_dataset(
    config: Dict[str, Any],
    atlas_ids: Optional[Iterable[str]],
    hpc_cfg: HPCConfig,
) -> Optional[str]:
    """Sync the generated custom atlas dataset to the configured HPC host."""
    if not custom_xcpd_atlas_ids(config, atlas_ids):
        return None

    local_dataset = ensure_xcpd_atlas_dataset(config, atlas_ids)
    if local_dataset is None:
        return None

    remote_dataset_root = remote_xcpd_atlas_dataset_path(hpc_cfg.remote_base)
    conn = None
    try:
        conn = HPCConnection(hpc_cfg)
        conn.connect()
        conn.execute(f"mkdir -p {shlex.quote(remote_dataset_root)}", timeout=60)
    finally:
        _safe_disconnect(conn)

    rsync_cmd = [
        "rsync",
        "-avz",
    ]
    if hpc_cfg.ssh_key:
        ssh_key = str(Path(hpc_cfg.ssh_key).expanduser())
        rsync_cmd.extend(["-e", f"ssh -i {ssh_key}"])
    rsync_cmd.extend([
        f"{str(local_dataset)}/",
        f"{hpc_cfg.user}@{hpc_cfg.host}:{remote_dataset_root}/",
    ])
    result = subprocess.run(
        rsync_cmd,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "Failed to sync XCP-D atlas dataset to HPC")

    return remote_dataset_root
