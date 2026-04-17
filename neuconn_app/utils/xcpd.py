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
        command.extend(["--fs-license-file", fs_license])

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
) -> str:
    """Render the XCP-D SLURM batch script using the xcpd_slurm.j2 template.

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

    # Build the full singularity command, then strip off the "singularity run -B … image"
    # prefix to get just the XCP-D CLI arguments.
    full_command = build_remote_xcpd_command(
        config,
        pipeline_name,
        participant_labels=participant_labels,
        session_ids=session_ids,
        remote_dataset_root=remote_dataset_root,
        remote_fmriprep_dir=remote_fmriprep_dir,
        work_dir=work_dir,
    )
    # full_command = ["singularity", "run", "-B", "...", ..., image_path, fmriprep_dir, ...]
    # Split at the image path to get post-image args; the template handles bind mounts separately.
    image_path = os.path.expanduser(hpc_cfg.singularity_xcpd or config["xcpd"]["singularity_image_path"])
    try:
        img_idx = full_command.index(image_path)
        xcpd_args = " ".join(shlex.quote(p) for p in full_command[img_idx + 1:])
    except ValueError:
        # Fallback: use everything after the last bind-mount argument
        xcpd_args = " ".join(shlex.quote(p) for p in full_command[2:])

    bind_mounts = _build_remote_bind_mounts(config, hpc_cfg)
    fs_license = os.path.expanduser(hpc_cfg.freesurfer_license or "")
    if fs_license:
        bind_mounts = list(bind_mounts)
        if fs_license not in bind_mounts:
            bind_mounts.append(fs_license)

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
        remote_fmriprep=remote_fmriprep_dir or hpc_cfg.remote_fmriprep,
        remote_work=hpc_cfg.remote_work,
        work_dir=work_dir or _remote_xcpd_work_dir(hpc_cfg, pipeline_name),
        singularity_image=image_path,
        fs_license=hpc_cfg.freesurfer_license,
        bind_mounts=bind_mounts,
        xcpd_args=xcpd_args,
        participants=list(_strip_bids_prefix(participant_labels, "sub-") or []),
    )



def _run_artifact_paths(config: Dict[str, Any], pipeline_name: str) -> Dict[str, Any]:
    """Create and return local run artifact paths for this pipeline."""
    qc_dir_key = f"xcpd_{pipeline_name}_qc_dir"
    qc_root = Path(config["paths"].get(qc_dir_key) or config["paths"]["xcpd_fc_qc_dir"])
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
) -> Dict[str, Any]:
    """Submit an XCP-D SLURM job on the configured HPC host."""
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
    )

    # Save script locally for inspection
    local_script = artifacts["run_dir"] / f"xcpd_{pipeline_name}_job.sh"
    with open(local_script, "w") as f:
        f.write(script_content)

    # Upload script to HPC and submit
    remote_script = f"{hpc_cfg.remote_base}/xcpd_{pipeline_name}_job.sh"

    conn = None
    try:
        conn = HPCConnection(hpc_cfg)
        conn.connect()
        conn.write_file(script_content, remote_script)
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
    remote_log_out = f"{hpc_cfg.remote_base}/logs/xcpd_{pipeline_name}_{job_id}.out"
    remote_log_err = f"{hpc_cfg.remote_base}/logs/xcpd_{pipeline_name}_{job_id}.err"

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
        "fmriprep_dir": str(preflight["fmriprep_dir"]),
        "work_dir": str(preflight["work_dir"]),
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
    progress = parse_xcpd_progress(Path(log_file) if log_file else None)
    if progress["has_error"] and not progress["is_done"]:
        run_info["status"] = "failed"
        run_info["completed_at"] = datetime.now().isoformat()
        state["runs"][run_key] = run_info
        state = set_run_info(config, run_key, run_info, state=state)
        state = set_step_status(config, f"xcpd_{pipeline_name}", "failed", "Error detected in log", state=state)
        append_pipeline_log(config, f"XCP-D {pipeline_name.upper()} run failed (error in log)", level="error", state=state)
        return state

    run_info["status"] = "completed"
    run_info["completed_at"] = datetime.now().isoformat()
    state["runs"][run_key] = run_info
    state = set_run_info(config, run_key, run_info, state=state)
    state = set_step_status(config, f"xcpd_{pipeline_name}", "completed", "Process finished", state=state)
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


def parse_xcpd_progress(log_file: Optional[Path], stored_total: Optional[int] = None) -> Dict[str, Any]:
    """Parse an XCP-D/nipype log file and return progress information.

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
    }
    if not log_file or not Path(log_file).exists():
        return result
    try:
        content = Path(log_file).read_text(errors="ignore")
    except OSError:
        return result

    lines = content.splitlines()
    result["last_lines"] = lines[-50:]

    for line in lines:
        m = re.search(r"workflow graph with (\d+) nodes", line)
        if m:
            result["nodes_total"] = int(m.group(1))
        if "[Node] Finished" in line:
            result["nodes_done"] += 1
        m = re.search(r'\[Node\] (?:Setting-up|Executing) "([^"]+)"', line)
        if m:
            # Show only the short node name (last dotted component)
            result["current_node"] = m.group(1).split(".")[-1]
        if " ERROR " in line or "Traceback (most recent" in line or line.startswith("FATAL:") or " FATAL " in line:
            result["has_error"] = True
        if "Workflow finished" in line or "XCP-D finished successfully" in line:
            result["is_done"] = True

    return result


def fetch_hpc_xcpd_log(config: Dict[str, Any], run_info: Dict[str, Any]) -> Optional[Path]:
    """Download the full remote XCP-D SLURM log to the local log_file path.

    Returns the local Path on success, None on failure.
    """
    remote_log = run_info.get("remote_log_out")
    local_log = run_info.get("log_file")
    if not remote_log or not local_log:
        return None
    hpc_cfg = HPCConfig.from_config(config)
    conn = None
    try:
        conn = HPCConnection(hpc_cfg)
        conn.connect()
        stdout, _, exit_code = conn.execute(
            f"cat {shlex.quote(remote_log)} 2>/dev/null",
            timeout=120,
        )
        if stdout:
            local_path = Path(local_log)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(stdout)
            return local_path
    except Exception:
        pass
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
    if hpc_cfg.ssh_key:
        rsync_cmd.extend(["-e", f"ssh -i {Path(hpc_cfg.ssh_key).expanduser()}"])

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
    if hpc_cfg.ssh_key:
        ssh_key = str(Path(hpc_cfg.ssh_key).expanduser())
        rsync_cmd.extend(["-e", f"ssh -i {ssh_key}"])

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
