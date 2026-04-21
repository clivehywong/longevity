"""
XCP-D execution helpers.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import json
import os
import re
import shlex
import shutil
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
    missing_xcpd_atlas_resources,
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


def _bool_flag(value: Any) -> str:
    return "y" if bool(value) else "n"


def _local_xcpd_work_dir(config: Dict[str, Any], pipeline_name: str) -> Path:
    work_dir = Path(config["paths"]["xcpd_dir"]) / "work" / pipeline_name
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _remote_xcpd_work_dir(hpc_cfg: HPCConfig, pipeline_name: str) -> str:
    work_root = hpc_cfg.remote_work or str(Path(hpc_cfg.remote_base) / "work")
    return str(Path(work_root) / "xcpd" / pipeline_name)


def _resolved_local_fmriprep_dir(config: Dict[str, Any]) -> str:
    candidates = _deduplicate_paths(
        [
            os.path.expanduser(str(config["paths"].get("fmriprep_dir", ""))),
            os.path.expanduser(str(config["paths"].get("legacy_fmriprep_dir", ""))),
        ]
    )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return candidates[0] if candidates else ""


def _remote_dir_exists(conn: HPCConnection, remote_path: str) -> bool:
    stdout, _, exit_code = conn.execute(f"test -d {shlex.quote(remote_path)} && echo READY", timeout=30)
    return exit_code == 0 and stdout.strip() == "READY"


def _remote_file_exists(conn: HPCConnection, remote_path: str) -> bool:
    stdout, _, exit_code = conn.execute(f"test -f {shlex.quote(remote_path)} && echo READY", timeout=30)
    return exit_code == 0 and stdout.strip() == "READY"


def _resolved_remote_fmriprep_dir(hpc_cfg: HPCConfig, conn: Optional[HPCConnection] = None) -> str:
    candidates = _deduplicate_paths([hpc_cfg.remote_fmriprep, hpc_cfg.remote_legacy_fmriprep])
    if conn is None:
        return candidates[0] if candidates else ""
    for candidate in candidates:
        if candidate and _remote_dir_exists(conn, candidate):
            return candidate
    return candidates[0] if candidates else ""


def _path_matches_filters(path: Path, participant_labels: Optional[Iterable[str]], session_ids: Optional[Iterable[str]]) -> bool:
    parts = set(path.parts)
    participants = {f"sub-{label}" for label in _strip_bids_prefix(participant_labels, "sub-")}
    sessions = {f"ses-{label}" for label in _strip_bids_prefix(session_ids, "ses-")}
    if participants and not participants.intersection(parts):
        return False
    if sessions and not sessions.intersection(parts):
        return False
    return True


def _local_has_matching_inputs(
    fmriprep_dir: str,
    file_format: str,
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
) -> bool:
    input_dir = Path(fmriprep_dir)
    pattern = "*dtseries.nii" if file_format == "cifti" else "*desc-preproc_bold.nii.gz"
    for candidate in input_dir.rglob(pattern):
        if _path_matches_filters(candidate, participant_labels, session_ids):
            return True
    return False


def _detect_local_file_formats(
    fmriprep_dir: str,
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
) -> List[str]:
    detected: List[str] = []
    if _local_has_matching_inputs(fmriprep_dir, "nifti", participant_labels, session_ids):
        detected.append("nifti")
    if _local_has_matching_inputs(fmriprep_dir, "cifti", participant_labels, session_ids):
        detected.append("cifti")
    return detected


def _remote_find_pattern(
    fmriprep_dir: str,
    file_pattern: str,
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
) -> str:
    base = f"find {shlex.quote(fmriprep_dir)}"
    subjects = [f"sub-{label}" for label in _strip_bids_prefix(participant_labels, "sub-")]
    sessions = [f"ses-{label}" for label in _strip_bids_prefix(session_ids, "ses-")]
    if not subjects:
        subjects = ["sub-*"]
    if not sessions:
        sessions = ["ses-*"]
    predicates = [
        f"-path {shlex.quote(f'*/{subject}/{session}/func/{file_pattern}')}"
        for subject in subjects
        for session in sessions
    ]
    return f"{base} \\( {' -o '.join(predicates)} \\) -print -quit"


def _remote_has_matching_inputs(
    conn: HPCConnection,
    fmriprep_dir: str,
    file_format: str,
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
) -> bool:
    pattern = "*dtseries.nii" if file_format == "cifti" else "*desc-preproc_bold.nii.gz"
    stdout, _, exit_code = conn.execute(
        _remote_find_pattern(
            fmriprep_dir,
            pattern,
            participant_labels=participant_labels,
            session_ids=session_ids,
        ),
        timeout=60,
    )
    return exit_code == 0 and bool(stdout.strip())


def _detect_remote_file_formats(
    conn: HPCConnection,
    fmriprep_dir: str,
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
) -> List[str]:
    detected: List[str] = []
    if _remote_has_matching_inputs(conn, fmriprep_dir, "nifti", participant_labels, session_ids):
        detected.append("nifti")
    if _remote_has_matching_inputs(conn, fmriprep_dir, "cifti", participant_labels, session_ids):
        detected.append("cifti")
    return detected


def _xcpd_fs_license(config: Dict[str, Any], hpc_cfg: Optional[HPCConfig] = None) -> str:
    if hpc_cfg is not None:
        return os.path.expanduser(hpc_cfg.freesurfer_license or "")
    return os.path.expanduser(
        config.get("software", {}).get("singularity_images", {}).get("freesurfer_license", "")
        or config.get("xcpd", {}).get("freesurfer_license", "")
    )


def _local_xcpd_preflight(
    config: Dict[str, Any],
    pipeline_name: str,
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    xcpd_config = config["xcpd"][pipeline_name]
    image_path = _local_xcpd_image(config)
    fs_license = _xcpd_fs_license(config)
    if shutil.which("singularity") is None:
        raise RuntimeError("Local XCP-D preflight failed: singularity is not available on PATH.")
    if not image_path or not Path(image_path).exists():
        raise RuntimeError(f"Local XCP-D preflight failed: image not found at {image_path}.")
    if fs_license and not Path(fs_license).exists():
        raise RuntimeError(f"Local XCP-D preflight failed: FreeSurfer license not found at {fs_license}.")

    fmriprep_dir = _resolved_local_fmriprep_dir(config)
    if not fmriprep_dir or not Path(fmriprep_dir).exists():
        raise RuntimeError(
            "Local XCP-D preflight failed: could not find fMRIPrep derivatives in either "
            f"{config['paths'].get('fmriprep_dir')} or {config['paths'].get('legacy_fmriprep_dir')}."
        )
    if not (Path(fmriprep_dir) / "dataset_description.json").exists():
        raise RuntimeError(
            f"Local XCP-D preflight failed: {fmriprep_dir} is missing dataset_description.json."
        )

    configured_format = str(xcpd_config.get("file_format", "auto"))
    detected_formats = _detect_local_file_formats(
        fmriprep_dir,
        participant_labels=participant_labels,
        session_ids=session_ids,
    )
    if configured_format != "auto" and configured_format not in detected_formats:
        detected_label = ", ".join(detected_formats) if detected_formats else "none"
        raise RuntimeError(
            "Local XCP-D preflight failed: configured file_format "
            f"'{configured_format}' is incompatible with {fmriprep_dir}. Detected formats: {detected_label}."
        )

    missing = missing_xcpd_atlas_resources(config, xcpd_config.get("atlases", []))
    if missing:
        raise RuntimeError(
            "Local XCP-D preflight failed: missing atlas resources: "
            + ", ".join(str(path) for path in missing)
        )

    work_dir = _local_xcpd_work_dir(config, pipeline_name)
    return {
        "backend": "local",
        "fmriprep_dir": fmriprep_dir,
        "work_dir": str(work_dir),
        "image_path": image_path,
        "fs_license": fs_license,
        "detected_formats": detected_formats,
    }


def _remote_xcpd_preflight(
    config: Dict[str, Any],
    pipeline_name: str,
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    hpc_cfg = HPCConfig.from_config(config)
    image_path = os.path.expanduser(hpc_cfg.singularity_xcpd or config["xcpd"]["singularity_image_path"])
    fs_license = _xcpd_fs_license(config, hpc_cfg)
    atlas_ids = config["xcpd"][pipeline_name].get("atlases", [])
    missing = missing_xcpd_atlas_resources(config, atlas_ids)
    if missing:
        raise RuntimeError(
            "HPC XCP-D preflight failed: missing atlas resources: "
            + ", ".join(str(path) for path in missing)
        )
    if custom_xcpd_atlas_ids(config, atlas_ids) and shutil.which("rsync") is None:
        raise RuntimeError("HPC XCP-D preflight failed: rsync is required to sync custom atlas datasets.")

    conn = None
    try:
        conn = HPCConnection(hpc_cfg)
        conn.connect()
        singularity_check = (
            "if [ -f /etc/profile.d/modules.sh ]; then source /etc/profile.d/modules.sh; "
            "elif [ -f /usr/share/Modules/init/bash ]; then source /usr/share/Modules/init/bash; fi; "
            "if command -v singularity >/dev/null 2>&1; then echo READY; "
            "elif command -v module >/dev/null 2>&1; then module load singularity >/dev/null 2>&1 || true; "
            "command -v singularity >/dev/null 2>&1 && echo READY || echo MISSING; "
            "else echo MISSING; fi"
        )
        stdout, _, exit_code = conn.execute(singularity_check, timeout=60)
        if exit_code != 0 or stdout.strip() != "READY":
            raise RuntimeError(
                "HPC XCP-D preflight failed: singularity is unavailable until module initialization succeeds."
            )
        stdout, _, exit_code = conn.execute(f"test -f {shlex.quote(image_path)} && echo READY", timeout=30)
        if exit_code != 0 or stdout.strip() != "READY":
            raise RuntimeError(f"HPC XCP-D preflight failed: image not found at {image_path}.")
        if fs_license:
            stdout, _, exit_code = conn.execute(f"test -f {shlex.quote(fs_license)} && echo READY", timeout=30)
            if exit_code != 0 or stdout.strip() != "READY":
                raise RuntimeError(f"HPC XCP-D preflight failed: FreeSurfer license not found at {fs_license}.")

        configured_format = str(config["xcpd"][pipeline_name].get("file_format", "auto"))
        detected_formats: List[str] = []
        fmriprep_dir = ""
        searched_candidates = _deduplicate_paths([hpc_cfg.remote_fmriprep, hpc_cfg.remote_legacy_fmriprep])
        for candidate in searched_candidates:
            if not candidate or not _remote_dir_exists(conn, candidate):
                continue
            if not _remote_file_exists(conn, str(Path(candidate) / "dataset_description.json")):
                continue
            candidate_formats = _detect_remote_file_formats(
                conn,
                candidate,
                participant_labels=participant_labels,
                session_ids=session_ids,
            )
            if configured_format != "auto" and configured_format in candidate_formats:
                fmriprep_dir = candidate
                detected_formats = candidate_formats
                break
            if candidate_formats and not fmriprep_dir:
                fmriprep_dir = candidate
                detected_formats = candidate_formats

        if not fmriprep_dir:
            raise RuntimeError(
                "HPC XCP-D preflight failed: no remote fMRIPrep directory with dataset_description.json contains XCP-D-readable inputs under "
                + ", ".join(searched_candidates)
                + "."
            )
        if configured_format != "auto" and configured_format not in detected_formats:
            detected_label = ", ".join(detected_formats) if detected_formats else "none"
            raise RuntimeError(
                "HPC XCP-D preflight failed: configured file_format "
                f"'{configured_format}' is incompatible with {fmriprep_dir}. Detected formats: {detected_label}."
            )
    finally:
        _safe_disconnect(conn)

    return {
        "backend": "hpc",
        "fmriprep_dir": fmriprep_dir,
        "work_dir": _remote_xcpd_work_dir(hpc_cfg, pipeline_name),
        "image_path": image_path,
        "fs_license": fs_license,
        "detected_formats": detected_formats,
    }


def run_xcpd_preflight(
    config: Dict[str, Any],
    pipeline_name: str,
    backend: str = "local",
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    if backend == "hpc":
        return _remote_xcpd_preflight(
            config,
            pipeline_name,
            participant_labels=participant_labels,
            session_ids=session_ids,
        )
    return _local_xcpd_preflight(
        config,
        pipeline_name,
        participant_labels=participant_labels,
        session_ids=session_ids,
    )


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
    fmriprep_dir: Optional[str] = None,
    work_dir: Optional[str] = None,
) -> List[str]:
    """Build the Singularity command for an XCP-D run."""
    paths = config["paths"]
    xcpd_config = config["xcpd"][pipeline_name]
    image_path = _local_xcpd_image(config)
    bind_mounts = _local_bind_mounts(config)
    selected_atlases = normalize_xcpd_atlas_selection(xcpd_config.get("atlases", []))

    output_dir_key = f"xcpd_{pipeline_name}_dir"
    output_dir = paths.get(output_dir_key) or paths["xcpd_fc_dir"]
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    resolved_fmriprep_dir = fmriprep_dir or _resolved_local_fmriprep_dir(config)
    resolved_work_dir = work_dir or str(_local_xcpd_work_dir(config, pipeline_name))
    Path(resolved_work_dir).mkdir(parents=True, exist_ok=True)

    command = ["singularity", "run"]
    for bind_mount in bind_mounts:
        command.extend(["-B", _bind_arg(bind_mount)])

    # Bind-mount the FreeSurfer license file if it's not already covered
    fs_license = os.path.expanduser(
        config.get("software", {}).get("singularity_images", {}).get("freesurfer_license", "")
        or config.get("xcpd", {}).get("freesurfer_license", "")
    )
    if fs_license and Path(fs_license).exists():
        command.extend(["-B", f"{fs_license}:{fs_license}"])

    dataset_root = ensure_xcpd_atlas_dataset(config, selected_atlases)
    command.extend(
        [
            image_path,
            resolved_fmriprep_dir,
            output_dir,
            "participant",
            "--mode",
            str(xcpd_config["mode"]),
            "-p",
            str(xcpd_config["nuisance_regressors"]),
            "--dummy-scans",
            str(xcpd_config.get("dummy_scans", "auto")),
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
            "--smoothing",
            str(xcpd_config["smoothing"]),
            "--head-radius",
            str(xcpd_config.get("head_radius", "auto")),
            "--min-coverage",
            str(xcpd_config.get("min_coverage", 0.5)),
            "--output-type",
            str(xcpd_config["output_type"]),
            "--output-layout",
            str(xcpd_config.get("output_layout", "bids")),
            "--input-type",
            str(xcpd_config.get("input_type", "fmriprep")),
            "--file-format",
            str(xcpd_config.get("file_format", "cifti")),
            "--report-output-level",
            str(xcpd_config.get("report_output_level", "session")),
            "--output-run-wise-correlations",
            _bool_flag(xcpd_config.get("output_run_wise_correlations", True)),
            "-w",
            resolved_work_dir,
        ]
    )

    if xcpd_config.get("despike", True):
        command.append("--despike")
    # Bandpass filter is ON by default; only add --disable-bandpass-filter to turn it off
    if not xcpd_config.get("bandpass_filter", True):
        command.append("--disable-bandpass-filter")
    else:
        command.extend([
            "--lower-bpf", str(xcpd_config.get("high_pass", xcpd_config.get("lower_bpf", 0.01))),
            "--upper-bpf", str(xcpd_config.get("low_pass", xcpd_config.get("upper_bpf", 0.08))),
        ])
    if xcpd_config.get("clean_workdir"):
        command.append("--clean-workdir")

    if fs_license:
        if not Path(fs_license).exists():
            raise FileNotFoundError(f"FreeSurfer license file not found: {fs_license}")
        command.extend(["--fs-license-file", fs_license])

    # Concurrency limits — cap Nipype workers to the allocated CPUs so multiple
    # simultaneous jobs on a shared node don't starve each other.
    nprocs = xcpd_config.get("nprocs")
    if nprocs:
        command.extend(["--nprocs", str(nprocs)])
    omp_nthreads = xcpd_config.get("omp_nthreads")
    if omp_nthreads:
        command.extend(["--omp-nthreads", str(omp_nthreads)])

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
    remote_fmriprep_dir: Optional[str] = None,
    work_dir: Optional[str] = None,
    omit_work_dir: bool = False,
) -> List[str]:
    """Build the remote Singularity command for an XCP-D run."""
    hpc_cfg = HPCConfig.from_config(config)
    xcpd_config = config["xcpd"][pipeline_name]
    image_path = os.path.expanduser(hpc_cfg.singularity_xcpd or config["xcpd"]["singularity_image_path"])
    if pipeline_name == "fc":
        remote_output = hpc_cfg.remote_xcpd_fc
    elif pipeline_name == "fc_gsr":
        remote_output = hpc_cfg.remote_xcpd_fc_gsr
    else:
        remote_output = hpc_cfg.remote_xcpd_ec
    resolved_remote_fmriprep = remote_fmriprep_dir or hpc_cfg.remote_fmriprep or hpc_cfg.remote_legacy_fmriprep
    resolved_work_dir = work_dir or _remote_xcpd_work_dir(hpc_cfg, pipeline_name)
    selected_atlases = normalize_xcpd_atlas_selection(xcpd_config.get("atlases", []))

    bind_mounts = _build_remote_bind_mounts(config, hpc_cfg)
    command = ["singularity", "run"]
    for bind_mount in bind_mounts:
        command.extend(["-B", f"{bind_mount}:{bind_mount}"])

    fs_license = os.path.expanduser(hpc_cfg.freesurfer_license or "")
    if fs_license:
        command.extend(["-B", f"{fs_license}:{fs_license}"])

    command.extend(
        [
            image_path,
            resolved_remote_fmriprep,
            remote_output,
            "participant",
            "--mode",
            str(xcpd_config["mode"]),
            "-p",
            str(xcpd_config["nuisance_regressors"]),
            "--dummy-scans",
            str(xcpd_config.get("dummy_scans", "auto")),
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
            "--smoothing",
            str(xcpd_config["smoothing"]),
            "--head-radius",
            str(xcpd_config.get("head_radius", "auto")),
            "--min-coverage",
            str(xcpd_config.get("min_coverage", 0.5)),
            "--output-type",
            str(xcpd_config["output_type"]),
            "--output-layout",
            str(xcpd_config.get("output_layout", "bids")),
            "--input-type",
            str(xcpd_config.get("input_type", "fmriprep")),
            "--file-format",
            str(xcpd_config.get("file_format", "cifti")),
            "--report-output-level",
            str(xcpd_config.get("report_output_level", "session")),
            "--output-run-wise-correlations",
            _bool_flag(xcpd_config.get("output_run_wise_correlations", True)),
        ]
    )

    if not omit_work_dir:
        command.extend(["-w", resolved_work_dir])

    if xcpd_config.get("despike", True):
        command.append("--despike")
    # Bandpass filter is ON by default; only add --disable-bandpass-filter to turn it off
    if not xcpd_config.get("bandpass_filter", True):
        command.append("--disable-bandpass-filter")
    else:
        command.extend([
            "--lower-bpf", str(xcpd_config.get("high_pass", xcpd_config.get("lower_bpf", 0.01))),
            "--upper-bpf", str(xcpd_config.get("low_pass", xcpd_config.get("upper_bpf", 0.08))),
        ])
    if xcpd_config.get("clean_workdir"):
        command.append("--clean-workdir")

    if fs_license:
        command.extend(["--fs-license-file", fs_license])

    # Concurrency limits — cap Nipype workers to the allocated CPUs so multiple
    # simultaneous jobs on a shared node don't starve each other.
    nprocs = xcpd_config.get("nprocs")
    if nprocs:
        command.extend(["--nprocs", str(nprocs)])
    omp_nthreads = xcpd_config.get("omp_nthreads")
    if omp_nthreads:
        command.extend(["--omp-nthreads", str(omp_nthreads)])

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
    remote_fmriprep_dir: Optional[str] = None,
    work_dir: Optional[str] = None,
    max_concurrent: Optional[int] = None,
    partition: Optional[str] = None,
) -> str:
    """Render the XCP-D SLURM batch script using the xcpd_slurm.j2 template.

    Uses a SLURM array job (``--array=1-N%max_concurrent``) so each subject
    runs as an independent task.  The participant list is written to a separate
    sublist file on the HPC before submission.

    Args:
        max_concurrent: Maximum simultaneous array tasks.  Defaults to
            ``config['hpc']['slurm']['max_concurrent_jobs']`` (or 4).
        partition: SLURM partition name.  Defaults to ``hpc_cfg.partition``.

    Returns the rendered script as a string.
    """
    if Environment is None:
        raise RuntimeError("jinja2 is required but not installed")

    hpc_cfg = HPCConfig.from_config(config)
    if pipeline_name == "fc":
        remote_output = hpc_cfg.remote_xcpd_fc
    elif pipeline_name == "fc_gsr":
        remote_output = hpc_cfg.remote_xcpd_fc_gsr
    else:
        remote_output = hpc_cfg.remote_xcpd_ec

    # Build xcpd_args WITHOUT --participant-label or -w — the template injects
    # per-array-task subject and per-subject work directory at runtime.
    full_command = build_remote_xcpd_command(
        config,
        pipeline_name,
        participant_labels=None,   # omit here; array job picks subject from file
        session_ids=session_ids,
        remote_dataset_root=remote_dataset_root,
        remote_fmriprep_dir=remote_fmriprep_dir,
        work_dir=work_dir,
        omit_work_dir=True,        # template adds per-subject -w at runtime
    )
    image_path = os.path.expanduser(hpc_cfg.singularity_xcpd or config["xcpd"]["singularity_image_path"])
    try:
        img_idx = full_command.index(image_path)
        raw_args = full_command[img_idx + 1:]
    except ValueError:
        raw_args = full_command[2:]

    # Group args into logical pairs/singles for multiline rendering.
    # Flags like --despike stand alone; flags with values stay paired.
    xcpd_arg_lines: list[str] = []
    i = 0
    while i < len(raw_args):
        token = raw_args[i]
        if token.startswith("-"):
            # Check if the next token is a value (not another flag)
            if i + 1 < len(raw_args) and not raw_args[i + 1].startswith("-"):
                # Collect all value tokens until the next flag
                vals = []
                j = i + 1
                while j < len(raw_args) and not raw_args[j].startswith("-"):
                    vals.append(shlex.quote(raw_args[j]))
                    j += 1
                xcpd_arg_lines.append(f"{shlex.quote(token)} {' '.join(vals)}")
                i = j
            else:
                xcpd_arg_lines.append(shlex.quote(token))
                i += 1
        else:
            # Positional arg (e.g. bids_dir, output_dir, analysis_level)
            xcpd_arg_lines.append(shlex.quote(token))
            i += 1

    bind_mounts = _build_remote_bind_mounts(config, hpc_cfg)
    fs_license = os.path.expanduser(hpc_cfg.freesurfer_license or "")
    if fs_license:
        bind_mounts = list(bind_mounts)
        if fs_license not in bind_mounts:
            bind_mounts.append(fs_license)

    xcpd_cfg = config.get("xcpd", {}).get(pipeline_name, {})
    nprocs = int(xcpd_cfg.get("nprocs") or 8)
    omp_nthreads = int(xcpd_cfg.get("omp_nthreads") or 1)
    cpus = nprocs * omp_nthreads or hpc_cfg.cpus
    memory = hpc_cfg.xcpd_memory if hpc_cfg.xcpd_memory else hpc_cfg.memory
    time_limit = hpc_cfg.xcpd_time_limit if hpc_cfg.xcpd_time_limit else hpc_cfg.time_limit

    participants = list(_strip_bids_prefix(participant_labels, "sub-") or [])
    num_subjects = len(participants) if participants else 1

    slurm_cfg = config.get("hpc", {}).get("slurm", {})
    _max_concurrent = max_concurrent if max_concurrent is not None else int(slurm_cfg.get("max_concurrent_jobs", 4))
    _partition = partition if partition is not None else hpc_cfg.partition

    sublist_file = f"{hpc_cfg.remote_base}/sublist_xcpd_{pipeline_name}.txt"

    templates_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    template = env.get_template("xcpd_slurm.j2")

    return template.render(
        job_name=f"xcpd_{pipeline_name}",
        pipeline=pipeline_name,
        partition=_partition,
        cpus=cpus,
        memory=memory,
        time_limit=time_limit,
        num_subjects=num_subjects,
        max_concurrent=_max_concurrent,
        remote_base=hpc_cfg.remote_base,
        remote_output=remote_output,
        remote_fmriprep=remote_fmriprep_dir or hpc_cfg.remote_fmriprep,
        remote_work=hpc_cfg.remote_work,
        work_dir=work_dir or _remote_xcpd_work_dir(hpc_cfg, pipeline_name),
        singularity_image=image_path,
        fs_license=hpc_cfg.freesurfer_license,
        bind_mounts=bind_mounts,
        xcpd_arg_lines=xcpd_arg_lines,
        participants=participants,
        sublist_file=sublist_file,
    )



def _run_artifact_paths(config: Dict[str, Any], pipeline_name: str) -> Dict[str, Any]:
    """Create and return local run artifact paths for this pipeline.

    Run artifacts (logs, SLURM scripts, manifests) are stored under
    ``pipeline_runs_dir`` — separate from QC reports — so the naming
    is not misleading.
    """
    runs_root = Path(
        config["paths"].get("pipeline_runs_dir")
        or (Path(config["paths"]["derivatives_dir"]) / "pipeline_runs")
    ) / f"xcpd_{pipeline_name}"
    runs_root.mkdir(parents=True, exist_ok=True)
    run_dir = runs_root / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
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
    preflight = run_xcpd_preflight(
        config,
        pipeline_name,
        backend="local",
        participant_labels=participant_labels,
        session_ids=session_ids,
    )
    command = build_xcpd_command(
        config,
        pipeline_name,
        participant_labels=participant_labels,
        session_ids=session_ids,
        fmriprep_dir=str(preflight["fmriprep_dir"]),
        work_dir=str(preflight["work_dir"]),
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
        "backend": "local",
        "command": command,
        "started_at": datetime.now().isoformat(),
        "participant_labels": list(participant_labels or []),
        "session_ids": list(session_ids or []),
        "fmriprep_dir": str(preflight["fmriprep_dir"]),
        "work_dir": str(preflight["work_dir"]),
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
    dep_job_id: Optional[str] = None,
    max_concurrent: Optional[int] = None,
    partition: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit an XCP-D SLURM array job on the configured HPC host.

    Args:
        dep_job_id: If provided, submits with ``--dependency=afterok:{dep_job_id}``
            so this job only starts after that predecessor succeeds.
        max_concurrent: Maximum simultaneous array tasks (``--array=1-N%K``).
        partition: SLURM partition to target.
    """
    artifacts = _run_artifact_paths(config, pipeline_name)
    hpc_cfg = HPCConfig.from_config(config)
    preflight = run_xcpd_preflight(
        config,
        pipeline_name,
        backend="hpc",
        participant_labels=participant_labels,
        session_ids=session_ids,
    )
    selected_atlases = normalize_xcpd_atlas_selection(config["xcpd"][pipeline_name].get("atlases", []))
    remote_dataset_root = _sync_remote_xcpd_atlas_dataset(config, selected_atlases, hpc_cfg)

    # Render SLURM script
    script_content = generate_xcpd_slurm_script(
        config,
        pipeline_name,
        participant_labels=participant_labels,
        session_ids=session_ids,
        remote_dataset_root=remote_dataset_root,
        remote_fmriprep_dir=str(preflight["fmriprep_dir"]),
        work_dir=str(preflight["work_dir"]),
        max_concurrent=max_concurrent,
        partition=partition,
    )

    # Save script locally for inspection
    local_script = artifacts["run_dir"] / f"xcpd_{pipeline_name}_job.sh"
    with open(local_script, "w") as f:
        f.write(script_content)

    # Upload sublist + script to HPC and submit
    remote_script = f"{hpc_cfg.remote_base}/xcpd_{pipeline_name}_job.sh"
    sublist_file = f"{hpc_cfg.remote_base}/sublist_xcpd_{pipeline_name}.txt"
    participants = list(_strip_bids_prefix(participant_labels, "sub-") or [])
    sublist_content = "\n".join(participants)

    conn = None
    try:
        conn = HPCConnection(hpc_cfg)
        conn.connect()
        conn.execute(f"mkdir -p {shlex.quote(f'{hpc_cfg.remote_base}/logs')}", timeout=30)
        conn.write_file(sublist_content, sublist_file)
        conn.write_file(script_content, remote_script)
        sbatch_cmd = (
            f"sbatch --dependency=afterok:{dep_job_id} {shlex.quote(remote_script)}"
            if dep_job_id
            else f"sbatch {shlex.quote(remote_script)}"
        )
        stdout, stderr, exit_code = conn.execute(sbatch_cmd, timeout=60)
    finally:
        _safe_disconnect(conn)

    if exit_code != 0:
        raise RuntimeError(stderr or stdout or "sbatch failed")

    # sbatch stdout: "Submitted batch job 12345"
    job_id = stdout.strip().split()[-1]
    # Array jobs use %A_%a in the SLURM template, producing files like
    # xcpd_fc_4131_1.out.  Store the prefix so fetch/cleanup helpers can
    # enumerate all per-task log files via glob.
    remote_log_prefix = f"{hpc_cfg.remote_base}/logs/xcpd_{pipeline_name}_{job_id}"
    remote_log_out = f"{remote_log_prefix}.out"
    remote_log_err = f"{remote_log_prefix}.err"

    run_info = {
        "pipeline": pipeline_name,
        "job_id": job_id,
        "status": "queued",
        "backend": "hpc",
        "remote_script": remote_script,
        "remote_sublist": sublist_file,
        "remote_log_out": remote_log_out,
        "remote_log_err": remote_log_err,
        "remote_log_prefix": remote_log_prefix,
        "submitted_at": datetime.now().isoformat(),
        "participant_labels": list(participant_labels or []),
        "session_ids": list(session_ids or []),
        "fmriprep_dir": str(preflight["fmriprep_dir"]),
        "work_dir": str(preflight["work_dir"]),
        "run_dir": str(artifacts["run_dir"]),
        "log_file": str(artifacts["log_file"]),
        "local_script": str(local_script),
    }
    with open(artifacts["manifest_file"], "w") as f:
        json.dump(run_info, f, indent=2)

    set_run_info(config, f"xcpd_{pipeline_name}", run_info)
    set_step_status(config, f"xcpd_{pipeline_name}", "queued", f"SLURM job {job_id}")
    append_pipeline_log(config, f"Submitted XCP-D {pipeline_name.upper()} SLURM job {job_id}")
    return run_info


def start_xcpd_chain(
    config: Dict[str, Any],
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
    nprocs: Optional[int] = None,
    omp_nthreads: Optional[int] = None,
    max_concurrent: Optional[int] = None,
    partition: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Submit FC → FC+GSR → EC as a SLURM dependency chain.

    Each pipeline is submitted with ``--dependency=afterok:{prev_job_id}`` so
    they run sequentially on the HPC.  Returns a mapping of pipeline name to
    ``run_info`` dict (as returned by :func:`start_remote_xcpd_run`).
    """
    if nprocs is not None:
        config = dict(config)
        config.setdefault("xcpd", {})
        config["xcpd"] = dict(config.get("xcpd", {}))
        config["xcpd"]["nprocs"] = nprocs
        if omp_nthreads is not None:
            config["xcpd"]["omp_nthreads"] = omp_nthreads

    results: Dict[str, Dict[str, Any]] = {}
    prev_job_id: Optional[str] = None
    for pipeline in _PIPELINE_ORDER:
        run_info = start_remote_xcpd_run(
            config,
            pipeline,
            participant_labels=participant_labels,
            session_ids=session_ids,
            dep_job_id=prev_job_id,
            max_concurrent=max_concurrent,
            partition=partition,
        )
        results[pipeline] = run_info
        prev_job_id = run_info["job_id"]
    return results


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
            # Query both state and reason so we can distinguish pending types.
            # For array jobs squeue returns one line per active task; take the
            # highest-priority state: RUNNING > PENDING > others.
            stdout, _, _ = conn.execute(
                f"squeue -j {shlex.quote(str(job_id))} -h -o '%T|%r' 2>/dev/null",
                timeout=30,
            )
            raw = stdout.strip()
            slurm_state = ""
            slurm_reason = ""
            if raw:
                # Collect all states from array tasks
                task_states: List[str] = []
                task_reasons: List[str] = []
                for task_line in raw.splitlines():
                    task_line = task_line.strip()
                    if not task_line:
                        continue
                    if "|" in task_line:
                        st, rs = task_line.upper().split("|", 1)
                    else:
                        st, rs = task_line.upper(), ""
                    task_states.append(st)
                    task_reasons.append(rs)
                # Prefer RUNNING > COMPLETING > PENDING > anything else
                for pref in ("RUNNING", "COMPLETING", "PENDING"):
                    if pref in task_states:
                        idx = task_states.index(pref)
                        slurm_state = pref
                        slurm_reason = task_reasons[idx]
                        break
                if not slurm_state and task_states:
                    slurm_state = task_states[0]
                    slurm_reason = task_reasons[0]

            if not slurm_state:
                # Job has left the queue; query sacct for final state.
                # For array jobs, check all task states and report the
                # worst outcome (FAILED > CANCELLED > TIMEOUT > COMPLETED).
                stdout, _, _ = conn.execute(
                    f"sacct -j {shlex.quote(str(job_id))} -n -o State --parsable2 2>/dev/null",
                    timeout=30,
                )
                sacct_states = [s.strip().upper() for s in stdout.strip().splitlines() if s.strip()]
                failure_states = {"FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY", "PREEMPTED"}
                failed = [s for s in sacct_states if s in failure_states]
                if failed:
                    slurm_state = failed[0]
                elif sacct_states:
                    slurm_state = sacct_states[0]
                slurm_reason = ""

            if slurm_state == "PENDING":
                # Detect unsatisfiable dependency early
                if "DEPENDENCYNEVERSATISFIED" in slurm_reason.replace(" ", ""):
                    run_info["status"] = "failed"
                    run_info["completed_at"] = datetime.now().isoformat()
                    run_info["slurm_state"] = slurm_state
                    run_info["slurm_reason"] = slurm_reason
                    state["runs"][run_key] = run_info
                    state = set_run_info(config, run_key, run_info, state=state)
                    state = set_step_status(config, f"xcpd_{pipeline_name}", "failed", "SLURM dependency never satisfied", state=state)
                    append_pipeline_log(config, f"XCP-D {pipeline_name.upper()} dependency never satisfied (upstream job failed/cancelled)", level="error", state=state)
                    return state
                # Update to queued state (heals old "running" status set at submission time)
                if run_info.get("status") != "queued":
                    run_info["status"] = "queued"
                    run_info["slurm_reason"] = slurm_reason
                    state["runs"][run_key] = run_info
                    state = set_run_info(config, run_key, run_info, state=state)
                    state = set_step_status(config, f"xcpd_{pipeline_name}", "queued", f"SLURM job {job_id} pending ({slurm_reason})", state=state)
                return state

            if slurm_state in ("RUNNING", "COMPLETING"):
                # Promote from queued → running when SLURM confirms execution started
                if run_info.get("status") == "queued":
                    run_info["status"] = "running"
                    run_info["started_at"] = run_info.get("started_at") or datetime.now().isoformat()
                    state["runs"][run_key] = run_info
                    state = set_run_info(config, run_key, run_info, state=state)
                    state = set_step_status(config, f"xcpd_{pipeline_name}", "running", f"SLURM job {job_id} running", state=state)
                return state

            if slurm_state in ("FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY", "PREEMPTED"):
                run_info["status"] = "failed"
                run_info["completed_at"] = datetime.now().isoformat()
                run_info["slurm_state"] = slurm_state
                state["runs"][run_key] = run_info
                state = set_run_info(config, run_key, run_info, state=state)
                state = set_step_status(config, f"xcpd_{pipeline_name}", "failed", f"SLURM state {slurm_state}", state=state)
                append_pipeline_log(config, f"XCP-D {pipeline_name.upper()} run failed on HPC ({slurm_state})", level="error", state=state)
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

    # Process is gone — determine success vs failure from log markers
    log_file = run_info.get("log_file")
    n_tasks = len(run_info.get("participant_labels") or []) or None
    progress = parse_xcpd_progress(Path(log_file) if log_file else None, n_expected_tasks=n_tasks)
    if progress["has_error"] and not progress["is_done"]:
        run_info["status"] = "failed"
        run_info["completed_at"] = datetime.now().isoformat()
        state["runs"][run_key] = run_info
        state = set_run_info(config, run_key, run_info, state=state)
        state = set_step_status(config, f"xcpd_{pipeline_name}", "failed", "Error detected in log", state=state)
        append_pipeline_log(config, f"XCP-D {pipeline_name.upper()} run failed (error in log)", level="error", state=state)
        _write_subject_status_files(config, pipeline_name, run_info, success=False)
        return state

    run_info["status"] = "completed"
    run_info["completed_at"] = datetime.now().isoformat()
    state["runs"][run_key] = run_info
    state = set_run_info(config, run_key, run_info, state=state)
    state = set_step_status(config, f"xcpd_{pipeline_name}", "completed", "Process finished", state=state)
    append_pipeline_log(config, f"XCP-D {pipeline_name.upper()} run finished", state=state)
    _write_subject_status_files(config, pipeline_name, run_info, success=True)
    return state


def _write_subject_status_files(
    config: Dict[str, Any], pipeline_name: str, run_info: Dict[str, Any], success: bool
) -> None:
    """Write a ``status`` sentinel file inside each subject's XCP-D output dir.

    These files let the UI quickly report per-subject completion without
    parsing the full log.  The file contains ``completed <timestamp>`` or
    ``failed <timestamp>``.
    """
    xcpd_dir_key = f"xcpd_{pipeline_name}_dir"
    xcpd_output_dir = Path(
        config["paths"].get(xcpd_dir_key)
        or config["paths"].get("xcpd_fc_dir", "")
    )
    if not xcpd_output_dir or not xcpd_output_dir.exists():
        return
    timestamp = run_info.get("completed_at", datetime.now().isoformat())
    status_text = f"completed {timestamp}" if success else f"failed {timestamp}"
    labels = run_info.get("participant_labels") or []
    for sub in labels:
        sub_id = sub if sub.startswith("sub-") else f"sub-{sub}"
        sub_dir = xcpd_output_dir / sub_id
        if sub_dir.exists():
            try:
                (sub_dir / "status").write_text(status_text)
            except OSError:
                pass


_PIPELINE_ORDER = ["fc", "fc_gsr", "ec"]


def stop_xcpd_run(config: Dict[str, Any], pipeline_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Terminate a running XCP-D process, or cancel a queued/running SLURM job.

    For queued jobs: sets step status back to ``not_started`` so re-submission
    is possible.  For running jobs: marks as ``failed``.
    When cancelling a SLURM job that has downstream queued dependents, those
    are automatically cancelled too (SLURM does not clean them up automatically
    when a dependency is unsatisfied).
    """
    run_key = f"xcpd_{pipeline_name}"
    run_info = state.get("runs", {}).get(run_key)
    if not run_info:
        return state

    backend = run_info.get("backend", "local")
    job_id = run_info.get("job_id")
    pid = run_info.get("pid")
    was_queued = run_info.get("status") == "queued"

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

                # Cascade: cancel any downstream pipelines that are queued
                # (SLURM PENDING jobs with unsatisfied deps stay in queue forever)
                try:
                    pipeline_idx = _PIPELINE_ORDER.index(pipeline_name)
                except ValueError:
                    pipeline_idx = -1
                if pipeline_idx >= 0:
                    for downstream in _PIPELINE_ORDER[pipeline_idx + 1:]:
                        ds_key = f"xcpd_{downstream}"
                        ds_run = state.get("runs", {}).get(ds_key, {})
                        if ds_run.get("status") in ("queued", "running") and ds_run.get("job_id"):
                            conn.execute(f"scancel {shlex.quote(str(ds_run['job_id']))}", timeout=30)
                            ds_run["status"] = "cancelled"
                            ds_run["stopped_at"] = datetime.now().isoformat()
                            state["runs"][ds_key] = ds_run
                            set_run_info(config, ds_key, ds_run, state=state)
                            set_step_status(config, ds_key, "not_started", "Cancelled — upstream pipeline stopped", state=state)
                            append_pipeline_log(config, f"Cancelled downstream XCP-D {downstream.upper()} (dependency cancelled)", level="warning", state=state)
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

        run_info["status"] = "cancelled" if was_queued else "stopped"
        run_info["stopped_at"] = datetime.now().isoformat()
        state["runs"][run_key] = run_info
        set_run_info(config, run_key, run_info, state=state)
        if was_queued:
            # Allow re-submission by resetting the step gate
            set_step_status(config, f"xcpd_{pipeline_name}", "not_started", "Cancelled by user", state=state)
        else:
            set_step_status(config, f"xcpd_{pipeline_name}", "failed", "Stopped by user", state=state)
        append_pipeline_log(config, f"Stopped XCP-D {pipeline_name.upper()} run", level="warning", state=state)
    except ProcessLookupError:
        pass
    return state


def collect_qc_reports(output_dir: Path) -> Dict[str, List[Path]]:
    """Collect QC artifacts produced by XCP-D."""
    if not output_dir.exists():
        return {k: [] for k in ("qc_csv", "exec_reports", "summary_reports", "motion", "outliers",
                                "timeseries", "connectomes", "bold", "reho", "alff", "falff")}
    return {
        "qc_csv": sorted(output_dir.glob("**/*_qc.csv")),
        # XCP-D produces per-run HTML reports with these patterns (not exec_report*.html)
        "exec_reports": sorted(output_dir.glob("**/*_desc-about_bold.html")),
        "summary_reports": sorted(output_dir.glob("**/*_desc-summary_bold.html")),
        "motion": sorted(output_dir.glob("**/*_motion.tsv")),
        "outliers": sorted(output_dir.glob("**/*_outliers.tsv")),
        "timeseries": sorted(output_dir.glob("**/*timeseries*.tsv")),
        "connectomes": sorted(output_dir.glob("**/*connectome*.tsv")),
        "bold": sorted(output_dir.glob("**/*desc-denoised_bold.nii.gz")),
        "reho": sorted(output_dir.glob("**/*_reho.nii.gz")),
        "alff": sorted(output_dir.glob("**/*_alff.nii.gz")),
        "falff": sorted(output_dir.glob("**/*_falff.nii.gz")),
    }


def parse_xcpd_progress(
    log_file: Optional[Path],
    stored_total: Optional[int] = None,
    n_expected_tasks: Optional[int] = None,
) -> Dict[str, Any]:
    """Parse an XCP-D/nipype log file and return progress information.

    For concatenated array-task logs (separated by ``=== filename ===``
    headers), aggregates progress across all tasks: ``nodes_total`` is
    ``per_task_graph_size * n_expected_tasks`` and ``nodes_done`` is the
    sum across tasks.

    Parameters
    ----------
    n_expected_tasks
        Number of SLURM array tasks expected (i.e. number of subjects).
        Used to compute a reliable ``nodes_total`` even when not all tasks
        have started yet.  Falls back to the number of "workflow graph"
        lines found in the log.

    Uses *stored_total* as a fallback when the "N nodes built" line has not
    yet been written to the local log (e.g. for HPC runs whose log was
    fetched only partially).
    """
    result: Dict[str, Any] = {
        "nodes_total": stored_total,
        "nodes_done": 0,
        "current_node": None,
        "last_lines": [],
        "has_error": False,
        "is_done": False,
        "task_count": 0,
        "tasks_done": 0,
    }
    if not log_file or not Path(log_file).exists():
        return result
    try:
        content = Path(log_file).read_text(errors="ignore")
    except OSError:
        return result

    lines = content.splitlines()
    result["last_lines"] = lines[-50:]

    # Track per-task graph sizes so we can sum for array jobs
    per_task_nodes: int = 0
    task_graph_count = 0

    for line in lines:
        m = re.search(r"workflow graph with (\d+) nodes", line)
        if m:
            per_task_nodes = int(m.group(1))
            task_graph_count += 1
        if "[Node] Finished" in line:
            result["nodes_done"] += 1
        m = re.search(r'\[Node\] (?:Setting-up|Executing) "([^"]+)"', line)
        if m:
            result["current_node"] = m.group(1).split(".")[-1]
        if " ERROR " in line or "Traceback (most recent" in line or line.startswith("FATAL:") or " FATAL " in line:
            result["has_error"] = True
        if "Workflow finished" in line or "XCP-D finished successfully" in line:
            result["tasks_done"] += 1

    result["task_count"] = task_graph_count

    if task_graph_count >= 1 and per_task_nodes:
        # Use the expected task count (from run_info participant list) when
        # available; fall back to the number of tasks whose logs we've seen.
        effective_tasks = n_expected_tasks or task_graph_count
        result["nodes_total"] = per_task_nodes * effective_tasks

    # All expected tasks must finish for the overall run to be "done"
    expected = n_expected_tasks or task_graph_count
    if result["tasks_done"] > 0 and expected > 0 and result["tasks_done"] >= expected:
        result["is_done"] = True

    return result


def fetch_hpc_xcpd_log(config: Dict[str, Any], run_info: Dict[str, Any]) -> Optional[Path]:
    """Download the full remote XCP-D SLURM log to the local log_file path.

    For SLURM array jobs, per-task logs (e.g. ``xcpd_fc_4131_1.out``,
    ``xcpd_fc_4131_2.out``) are concatenated into the single local file
    with separators so the caller can see all tasks' output.

    Returns the local Path on success, None on failure.
    """
    remote_log_prefix = run_info.get("remote_log_prefix")
    remote_log = run_info.get("remote_log_out")
    local_log = run_info.get("log_file")
    if not local_log:
        return None
    if not remote_log_prefix and not remote_log:
        return None
    hpc_cfg = HPCConfig.from_config(config)
    conn = None
    try:
        conn = HPCConnection(hpc_cfg)
        conn.connect()

        combined: List[str] = []

        if remote_log_prefix:
            # Enumerate array-task log files (sorted numerically).
            # Use find -name to avoid shell glob expansion vulnerabilities.
            prefix_dir = str(Path(remote_log_prefix).parent)
            prefix_base = str(Path(remote_log_prefix).name)
            stdout, _, _ = conn.execute(
                f"find {shlex.quote(prefix_dir)} -maxdepth 1 "
                f"\\( -name {shlex.quote(prefix_base + '_*.out')} "
                f"-o -name {shlex.quote(prefix_base + '.out')} "
                f"-o -name {shlex.quote(prefix_base + '_*.log')} "
                f"-o -name {shlex.quote(prefix_base + '.log')} \\) "
                f"2>/dev/null | sort -t_ -k3 -n",
                timeout=30,
            )
            log_files = [f for f in stdout.strip().splitlines() if f.strip()]
            if not log_files:
                # Fallback: try the exact remote_log_out path
                if remote_log:
                    log_files = [remote_log]
            for lf in log_files:
                lf = lf.strip()
                out, _, _ = conn.execute(
                    f"cat {shlex.quote(lf)} 2>/dev/null",
                    timeout=120,
                )
                if not out and lf.endswith(".out"):
                    # The SLURM .out file is empty (NFS log write failure).
                    # Check for the explicit .log file written by the job script
                    # via `exec > /tmp/... && cp to NFS` pattern.
                    explicit_log = str(Path(lf).with_suffix(".log"))
                    out, _, _ = conn.execute(
                        f"cat {shlex.quote(explicit_log)} 2>/dev/null",
                        timeout=120,
                    )
                if out:
                    fname = Path(lf).name
                    combined.append(f"=== {fname} ===")
                    combined.append(out)
        elif remote_log:
            out, _, _ = conn.execute(
                f"cat {shlex.quote(remote_log)} 2>/dev/null",
                timeout=120,
            )
            if out:
                combined.append(out)

        if combined:
            local_path = Path(local_log)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text("\n".join(combined))
            return local_path
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Failed to fetch HPC log for job %s", run_info.get("job_id"), exc_info=True
        )
    finally:
        _safe_disconnect(conn)
    return None


def download_xcpd_outputs_from_hpc(
    config: Dict[str, Any],
    pipeline_name: str,
    participant_labels: Optional[Iterable[str]] = None,
) -> str:
    """Rsync XCP-D pipeline outputs from HPC to the local output directory.

    Returns the local output directory path.
    """
    hpc_cfg = HPCConfig.from_config(config)
    paths = config["paths"]
    output_dir_key = f"xcpd_{pipeline_name}_dir"
    if paths.get(output_dir_key):
        local_out_dir = Path(paths[output_dir_key])
    else:
        local_out_dir = Path(paths.get("xcpd_dir", "derivatives/preprocessing/xcpd")) / pipeline_name
    local_out_dir.mkdir(parents=True, exist_ok=True)

    # Use the same pipeline → remote path mapping as build_remote_xcpd_command
    if pipeline_name == "fc":
        remote_xcpd_dir = hpc_cfg.remote_xcpd_fc
    elif pipeline_name == "fc_gsr":
        remote_xcpd_dir = hpc_cfg.remote_xcpd_fc_gsr
    else:
        remote_xcpd_dir = hpc_cfg.remote_xcpd_ec
    if not remote_xcpd_dir:
        remote_xcpd_dir = f"{hpc_cfg.remote_base}/derivatives/preprocessing/xcpd/{pipeline_name}"

    rsync_cmd = ["rsync", "-avz", "--no-perms"]
    _ssh_opts = []
    if hpc_cfg.port and hpc_cfg.port != 22:
        _ssh_opts += ["-p", str(hpc_cfg.port)]
    if hpc_cfg.ssh_key:
        _ssh_opts += ["-i", str(Path(hpc_cfg.ssh_key).expanduser())]
    if _ssh_opts:
        rsync_cmd.extend(["-e", "ssh " + " ".join(_ssh_opts)])

    subjects = [f"sub-{label}" if not label.startswith("sub-") else label
                for label in (participant_labels or [])]
    if subjects:
        # Include only selected subjects
        for sub in subjects:
            rsync_cmd += [f"--include={sub}/", f"--include={sub}/**"]
        rsync_cmd += ["--include=dataset_description.json", "--include=*.json",
                      "--include=*.bib", "--include=*.html",
                      "--exclude=*/"]
    # Also always include top-level files (dataset_description, etc.)
    rsync_cmd += [
        "--include=dataset_description.json",
        "--include=*.json",
        "--include=*.bib",
    ]

    rsync_cmd += [
        f"{hpc_cfg.user}@{hpc_cfg.host}:{remote_xcpd_dir}/",
        f"{local_out_dir}/",
    ]

    result = subprocess.run(rsync_cmd, capture_output=True, text=True, timeout=600)
    if result.returncode not in (0, 24):  # 24 = partial transfer (acceptable)
        raise RuntimeError(result.stderr or result.stdout or f"rsync exited {result.returncode}")
    return str(local_out_dir)


def cleanup_xcpd_hpc_files(config: Dict[str, Any], pipeline_name: str) -> None:
    """Remove XCP-D output, work directory, and SLURM script from HPC.

    Cleans the remote output directory (``derivatives/preprocessing/xcpd/<pipeline>``),
    work directory, SLURM scripts, and log files.
    Raises ``RuntimeError`` if the HPC connection fails.
    """
    from utils.pipeline_state import load_pipeline_state

    state = load_pipeline_state(config)
    run_key = f"xcpd_{pipeline_name}"
    run_info = state.get("runs", {}).get(run_key, {})
    hpc_cfg = HPCConfig.from_config(config)

    work_dir = run_info.get("work_dir") or _remote_xcpd_work_dir(hpc_cfg, pipeline_name)
    remote_script = run_info.get("remote_script")
    remote_log_prefix = run_info.get("remote_log_prefix")
    remote_log_out = run_info.get("remote_log_out")
    remote_log_err = run_info.get("remote_log_err")

    # Resolve the remote XCP-D output directory
    if pipeline_name == "fc":
        remote_output = hpc_cfg.remote_xcpd_fc
    elif pipeline_name == "fc_gsr":
        remote_output = hpc_cfg.remote_xcpd_fc_gsr
    else:
        remote_output = hpc_cfg.remote_xcpd_ec
    if not remote_output:
        remote_output = f"{hpc_cfg.remote_base}/derivatives/preprocessing/xcpd/{pipeline_name}"

    conn = None
    try:
        conn = HPCConnection(hpc_cfg)
        conn.connect()
        # Remove output directory
        if remote_output:
            conn.execute(f"rm -rf {shlex.quote(remote_output)}", timeout=120)
        # Remove work directory
        if work_dir:
            conn.execute(f"rm -rf {shlex.quote(work_dir)}", timeout=120)
        # Remove SLURM script
        if remote_script:
            conn.execute(f"rm -f {shlex.quote(remote_script)}", timeout=30)
        # Remove log files: for array jobs, use the prefix to match all
        # per-task logs (e.g. xcpd_fc_4131_1.out, xcpd_fc_4131_2.out).
        # Match exactly prefix.out, prefix.err (non-array legacy), and
        # prefix_N.out, prefix_N.err (array tasks) to avoid deleting logs
        # belonging to other jobs whose IDs share a common numeric prefix.
        if remote_log_prefix:
            prefix_dir = str(Path(remote_log_prefix).parent)
            prefix_base = str(Path(remote_log_prefix).name)
            find_cmd = (
                f"find {shlex.quote(prefix_dir)} -maxdepth 1 "
                f"\\( -name {shlex.quote(prefix_base + '.out')} "
                f"-o -name {shlex.quote(prefix_base + '.err')} "
                f"-o -name {shlex.quote(prefix_base + '.log')} "
                f"-o -name {shlex.quote(prefix_base + '_*.out')} "
                f"-o -name {shlex.quote(prefix_base + '_*.err')} "
                f"-o -name {shlex.quote(prefix_base + '_*.log')} \\) "
                f"2>/dev/null"
            )
            stdout, _, _ = conn.execute(find_cmd, timeout=30)
            for lf in stdout.strip().splitlines():
                lf = lf.strip()
                if lf:
                    conn.execute(f"rm -f {shlex.quote(lf)}", timeout=30)
        else:
            # Legacy: individual log paths
            for remote_file in (remote_log_out, remote_log_err):
                if remote_file:
                    conn.execute(f"rm -f {shlex.quote(remote_file)}", timeout=30)
        # Remove the sublist file
        remote_sublist = run_info.get("remote_sublist")
        if not remote_sublist:
            # Fallback for runs submitted before remote_sublist was stored
            remote_sublist = f"{hpc_cfg.remote_base}/sublist_xcpd_{pipeline_name}.txt"
        conn.execute(f"rm -f {shlex.quote(remote_sublist)}", timeout=30)
        append_pipeline_log(config, f"Cleaned up HPC files for XCP-D {pipeline_name.upper()}")
    finally:
        _safe_disconnect(conn)


def check_fmriprep_on_hpc(
    config: Dict[str, Any],
    participant_labels: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Lightweight check: are fMRIPrep outputs present on HPC for the given subjects?

    Returns a dict with:
      - ``available``: True if the remote fMRIPrep directory exists
      - ``remote_dir``: the remote path found (or None)
      - ``missing_subjects``: list of ``sub-*`` labels not found remotely
      - ``error``: error message string if the connection failed
    """
    hpc_cfg = HPCConfig.from_config(config)
    labels = list(_strip_bids_prefix(participant_labels or [], "sub-"))
    conn = None
    try:
        conn = HPCConnection(hpc_cfg)
        conn.connect()
        candidates = _deduplicate_paths([hpc_cfg.remote_fmriprep, hpc_cfg.remote_legacy_fmriprep])
        fmriprep_dir: Optional[str] = None
        for candidate in candidates:
            if candidate and _remote_dir_exists(conn, candidate):
                if _remote_file_exists(conn, str(Path(candidate) / "dataset_description.json")):
                    fmriprep_dir = candidate
                    break
        if not fmriprep_dir:
            return {"available": False, "remote_dir": None, "missing_subjects": [f"sub-{l}" for l in labels]}
        missing = []
        for label in labels:
            sub_dir = f"{fmriprep_dir}/sub-{label}"
            if not _remote_dir_exists(conn, sub_dir):
                missing.append(f"sub-{label}")
        return {"available": True, "remote_dir": fmriprep_dir, "missing_subjects": missing}
    except Exception as exc:
        return {"available": False, "remote_dir": None, "missing_subjects": [f"sub-{l}" for l in labels], "error": str(exc)}
    finally:
        _safe_disconnect(conn)


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
    _ssh_opts = []
    if hpc_cfg.port and hpc_cfg.port != 22:
        _ssh_opts += ["-p", str(hpc_cfg.port)]
    if hpc_cfg.ssh_key:
        _ssh_opts += ["-i", str(Path(hpc_cfg.ssh_key).expanduser())]
    if _ssh_opts:
        rsync_cmd.extend(["-e", "ssh " + " ".join(_ssh_opts)])
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


def sync_fmriprep_to_hpc(
    config: Dict[str, Any],
    participant_labels: Optional[Iterable[str]] = None,
    session_ids: Optional[Iterable[str]] = None,
    progress_callback=None,
) -> str:
    """Upload local fMRIPrep derivatives to the configured HPC host.

    Returns the remote fMRIPrep directory path on success.
    """
    hpc_cfg = HPCConfig.from_config(config)
    local_fmriprep = _resolved_local_fmriprep_dir(config)
    if not local_fmriprep or not Path(local_fmriprep).exists():
        raise RuntimeError(f"Local fMRIPrep directory not found: {local_fmriprep}")

    remote_fmriprep = hpc_cfg.remote_fmriprep
    if not remote_fmriprep:
        raise RuntimeError("No remote fMRIPrep path configured in HPC settings.")

    conn = None
    try:
        conn = HPCConnection(hpc_cfg)
        conn.connect()
        conn.execute(f"mkdir -p {shlex.quote(remote_fmriprep)}", timeout=60)
    finally:
        _safe_disconnect(conn)

    subjects = [f"sub-{label}" for label in _strip_bids_prefix(participant_labels, "sub-")]
    sessions = [f"ses-{label}" for label in _strip_bids_prefix(session_ids, "ses-")]

    rsync_cmd = [
        "rsync", "-avz",
        "--info=progress2",
        "--exclude=*_space-fsnative_*",
    ]
    # Build ssh command with port and optional key
    ssh_opts = []
    if hpc_cfg.port and hpc_cfg.port != 22:
        ssh_opts += ["-p", str(hpc_cfg.port)]
    if hpc_cfg.ssh_key:
        ssh_opts += ["-i", str(Path(hpc_cfg.ssh_key).expanduser())]
    if ssh_opts:
        rsync_cmd.extend(["-e", "ssh " + " ".join(ssh_opts)])

    if subjects:
        for sub in subjects:
            rsync_cmd += [f"--include={sub}/"]
            if sessions:
                for ses in sessions:
                    rsync_cmd += [
                        f"--include={sub}/{ses}/",
                        f"--include={sub}/{ses}/**",
                    ]
                # Always include the subject-level anat/ dir — XCP-D requires T1w/T2w
                # files stored there (not under session subdirs) for longitudinal data.
                rsync_cmd += [
                    f"--include={sub}/anat/",
                    f"--include={sub}/anat/**",
                    f"--include={sub}/figures/",
                    f"--include={sub}/figures/**",
                    f"--include={sub}/*.html",
                    f"--include={sub}/*.json",
                ]
            else:
                rsync_cmd += [f"--include={sub}/**"]
        rsync_cmd += [
            "--include=dataset_description.json",
            "--include=*.json",
            "--include=logs/",
            "--include=logs/**",
            "--exclude=*",
        ]

    rsync_cmd.extend([
        f"{str(local_fmriprep)}/",
        f"{hpc_cfg.user}@{hpc_cfg.host}:{remote_fmriprep}/",
    ])

    if progress_callback:
        progress_callback("Uploading fMRIPrep derivatives to HPC…")

    result = subprocess.run(
        rsync_cmd,
        capture_output=True,
        text=True,
        timeout=7200,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "rsync failed")

    return remote_fmriprep
