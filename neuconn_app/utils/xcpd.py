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


def build_xcpd_command(
    config: Dict[str, Any],
    pipeline_name: str,
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
) -> List[str]:
    """Build the Singularity command for an XCP-D run."""
    paths = config["paths"]
    xcpd_config = config["xcpd"][pipeline_name]
    image_path = os.path.expanduser(config["xcpd"]["singularity_image_path"])
    bind_mounts = config["xcpd"].get("singularity_bind_mounts", [])
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


def _run_artifact_paths(config: Dict[str, Any], pipeline_name: str) -> Dict[str, Path]:
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
    """Start an XCP-D run on the configured HPC host via SSH."""
    artifacts = _run_artifact_paths(config, pipeline_name)
    hpc_cfg = HPCConfig.from_config(config)
    selected_atlases = normalize_xcpd_atlas_selection(config["xcpd"][pipeline_name].get("atlases", []))
    remote_dataset_root = _sync_remote_xcpd_atlas_dataset(config, selected_atlases, hpc_cfg)
    command = build_remote_xcpd_command(
        config,
        pipeline_name,
        participant_labels=participant_labels,
        session_ids=session_ids,
        remote_dataset_root=remote_dataset_root,
    )
    remote_output = hpc_cfg.remote_xcpd_fc if pipeline_name == "fc" else hpc_cfg.remote_xcpd_ec
    remote_log = f"{hpc_cfg.remote_base}/{pipeline_name}_xcpd.log"
    remote_command = (
        f"mkdir -p {shlex.quote(str(remote_output))} "
        f"{shlex.quote(str(hpc_cfg.remote_work))} && "
        f"{{ command -v module &>/dev/null && module load singularity 2>/dev/null || true; }} && "
        f"nohup {' '.join(shlex.quote(part) for part in command)} > {shlex.quote(remote_log)} 2>&1 & echo $!"
    )

    with open(artifacts["command_file"], "w") as f:
        f.write(remote_command + "\n")

    conn = None
    try:
        conn = HPCConnection(hpc_cfg)
        conn.connect()
        stdout, stderr, exit_code = conn.execute(remote_command, timeout=60)
    finally:
        _safe_disconnect(conn)

    if exit_code != 0:
        raise RuntimeError(stderr or stdout or "Failed to start remote XCP-D run")

    pid = int(stdout.strip().splitlines()[-1])
    run_info = {
        "pipeline": pipeline_name,
        "pid": pid,
        "status": "running",
        "backend": "hpc",
        "command": command,
        "remote_log": remote_log,
        "started_at": datetime.now().isoformat(),
        "participant_labels": list(participant_labels or []),
        "session_ids": list(session_ids or []),
        "run_dir": str(artifacts["run_dir"]),
        "log_file": str(artifacts["log_file"]),
    }
    with open(artifacts["manifest_file"], "w") as f:
        json.dump(run_info, f, indent=2)

    set_run_info(config, f"xcpd_{pipeline_name}", run_info)
    set_step_status(config, f"xcpd_{pipeline_name}", "running", f"HPC pid {pid}")
    append_pipeline_log(config, f"Started remote XCP-D {pipeline_name.upper()} run (pid={pid})")
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

    pid = run_info.get("pid")
    backend = run_info.get("backend", "local")
    if pid:
        if backend == "hpc":
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
        elif is_process_running(pid):
            return state

    run_info["status"] = "completed"
    run_info["completed_at"] = datetime.now().isoformat()
    state["runs"][run_key] = run_info
    set_run_info(config, run_key, run_info, state=state)
    set_step_status(config, f"xcpd_{pipeline_name}", "completed", "Process finished", state=state)
    append_pipeline_log(config, f"XCP-D {pipeline_name.upper()} run finished", state=state)
    return state


def stop_xcpd_run(config: Dict[str, Any], pipeline_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Terminate a running XCP-D process."""
    run_key = f"xcpd_{pipeline_name}"
    run_info = state.get("runs", {}).get(run_key)
    if not run_info or not run_info.get("pid"):
        return state

    pid = int(run_info["pid"])
    try:
        if run_info.get("backend") == "hpc":
            conn = None
            try:
                hpc_cfg = HPCConfig.from_config(config)
                conn = HPCConnection(hpc_cfg)
                conn.connect()
                stdout, stderr, exit_code = conn.execute(f"kill {pid}", timeout=30)
                if exit_code != 0:
                    raise RuntimeError(stderr or stdout or f"kill exited with status {exit_code}")
            except Exception as exc:
                _safe_disconnect(conn)
                set_step_status(
                    config,
                    f"xcpd_{pipeline_name}",
                    "failed",
                    f"Failed to stop HPC process: {exc}",
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
        else:
            os.killpg(pid, signal.SIGTERM)
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
