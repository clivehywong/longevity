"""Streamlit submit page for Local Measures subject-level HPC analysis."""

from __future__ import annotations

from pathlib import Path
import shlex
import sys
from typing import Dict, List, Optional, Tuple

import streamlit as st

# Match dynamically loaded page import style used elsewhere in neuconn_app.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.bids import detect_acquisition_params, scan_bids_directory
from utils.config import load_config
from utils.connectivity_workflow import ConnectivitySubmission, ConnectivityWorkflowManager
from utils.hpc import HPCConfig, HPCConnection

ANALYSIS_TYPE = "local_measures"
SESSION_KEY_PREFIX = "submit_local_"
INPUT_SOURCE_LABELS = {
    "XCP-D FC": "xcpd_fc",
    "XCP-D FC+GSR": "xcpd_fc_gsr",
    "Custom path": "custom",
}
NEIGHBORHOOD_LABELS = {
    "7 voxels": "faces",
    "19 voxels": "faces_edges",
    "27 voxels": "faces_edges_corners",
}
STATUS_BADGES = {
    "green": ":green[● Ready]",
    "yellow": ":orange[● Warning]",
    "red": ":red[● Blocked]",
}


@st.cache_data(show_spinner=False)
def _load_cached_config() -> Dict:
    return load_config()


@st.cache_data(show_spinner=False)
def _scan_bids_cached(bids_dir: str) -> Dict:
    bids_path = Path(bids_dir).expanduser()
    summary = scan_bids_directory(bids_path)
    subject_sessions: List[Dict[str, str]] = []
    if bids_path.exists():
        for sub_dir in sorted(bids_path.glob("sub-*")):
            if not sub_dir.is_dir():
                continue
            sessions = sorted(s for s in sub_dir.glob("ses-*") if s.is_dir())
            if not sessions:
                subject_sessions.append({"subject": sub_dir.name, "session": "", "pair": sub_dir.name})
            for ses_dir in sessions:
                subject_sessions.append(
                    {
                        "subject": sub_dir.name,
                        "session": ses_dir.name,
                        "pair": f"{sub_dir.name}_{ses_dir.name}",
                    }
                )
    return {"summary": summary, "subject_sessions": subject_sessions}


@st.cache_data(show_spinner=False)
def _detect_tr_cached(bids_dir: str) -> Optional[float]:
    params = detect_acquisition_params(Path(bids_dir).expanduser())
    tr = params.get("tr")
    return float(tr) if tr else None


def _state_key(name: str) -> str:
    return f"{SESSION_KEY_PREFIX}{name}"


def _get_config() -> Dict:
    config = st.session_state.get("config")
    if config:
        return config
    try:
        return _load_cached_config()
    except Exception as exc:
        st.error(f"Could not load configuration: {exc}")
        return {}


def _default_local_output_dir(config: Dict) -> str:
    paths = config.get("paths", {})
    return str(Path(paths.get("subject_level_dir") or paths.get("derivatives_dir") or "").expanduser())


def _default_remote_output_dir(config: Dict) -> str:
    hpc_config = HPCConfig.from_config(config)
    if hpc_config.remote_base:
        return str(Path(hpc_config.remote_base) / "derivatives" / "subject_level")
    return _default_local_output_dir(config)


def _default_remote_log_dir(config: Dict) -> str:
    hpc_config = HPCConfig.from_config(config)
    if hpc_config.remote_base:
        return str(Path(hpc_config.remote_base) / "logs" / "local_measures")
    paths = config.get("paths", {})
    runs_dir = paths.get("pipeline_runs_dir") or paths.get("derivatives_dir") or "logs"
    return str(Path(runs_dir).expanduser() / "local_measures")


def _resolve_input_path(config: Dict, input_source: str, custom_path: str) -> str:
    paths = config.get("paths", {})
    hpc_config = HPCConfig.from_config(config)
    if input_source == "xcpd_fc_gsr":
        return paths.get("xcpd_fc_gsr_dir") or hpc_config.remote_xcpd_fc_gsr
    if input_source == "xcpd_fc":
        return paths.get("xcpd_fc_dir") or hpc_config.remote_xcpd_fc
    return custom_path.strip()


def _remote_path_for_source(config: Dict, input_source: str, local_path: str) -> str:
    hpc_config = HPCConfig.from_config(config)
    if input_source == "xcpd_fc_gsr":
        return hpc_config.remote_xcpd_fc_gsr or local_path
    if input_source == "xcpd_fc":
        return hpc_config.remote_xcpd_fc or local_path
    return local_path


def _split_pair(pair: str) -> Tuple[str, str]:
    if "_" not in pair:
        return pair, ""
    subject, session = pair.split("_", 1)
    return subject, session


def _subjects_for_manager(selected_pairs: List[str]) -> List[str]:
    return sorted({pair.split("_", 1)[0] for pair in selected_pairs})


def _sessions_for_manager(selected_pairs: List[str]) -> List[str]:
    return sorted({session for _, session in (_split_pair(pair) for pair in selected_pairs) if session})


def _path_exists_locally(path_value: str) -> bool:
    return bool(path_value) and Path(path_value).expanduser().exists()


def _path_exists_on_hpc(config: Dict, path_value: str) -> Tuple[bool, str]:
    if not path_value:
        return False, "No path provided"
    hpc = config.get("hpc", {})
    if not hpc.get("enabled", False):
        return False, "HPC is disabled"
    conn = None
    try:
        hpc_config = HPCConfig.from_config(config)
        conn = HPCConnection(hpc_config)
        conn.connect()
        exists = conn.file_exists(path_value)
        return exists, "Found on HPC" if exists else "Not found on HPC"
    except Exception as exc:
        return False, str(exc)
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass


def _validate_submission(
    config: Dict,
    selected_pairs: List[str],
    measures: List[str],
    input_path: str,
    remote_input_path: str,
    mask_path: str,
    check_hpc: bool = True,
) -> List[str]:
    errors: List[str] = []
    if not selected_pairs:
        errors.append("Select at least one subject/session pair.")
    if not measures:
        errors.append("Select at least one output measure.")
    if not input_path and not remote_input_path:
        errors.append("Configure an input source path.")
    elif not _path_exists_locally(input_path):
        if check_hpc:
            exists, detail = _path_exists_on_hpc(config, remote_input_path or input_path)
            if not exists:
                errors.append(f"Input source not found locally or on HPC: {input_path or remote_input_path} ({detail})")
        else:
            errors.append(f"Input source not found locally: {input_path}")
    if mask_path and not _path_exists_locally(mask_path):
        if check_hpc:
            exists, detail = _path_exists_on_hpc(config, mask_path)
            if not exists:
                errors.append(f"Brain mask not found locally or on HPC: {mask_path} ({detail})")
        else:
            errors.append(f"Brain mask not found locally: {mask_path}")
    return errors


def _render_hpc_status(config: Dict) -> None:
    hpc = config.get("hpc", {})
    hpc_config = HPCConfig.from_config(config)
    st.subheader("1. HPC Connection")
    col1, col2, col3 = st.columns(3)
    col1.metric("Enabled", "Yes" if hpc.get("enabled", False) else "No")
    col2.metric("Host", hpc_config.host or "Not set")
    col3.metric("User", hpc_config.user or "Not set")

    with st.expander("Connection details", expanded=False):
        d1, d2 = st.columns(2)
        d1.text_input("Remote base", value=hpc_config.remote_base, disabled=True, key=_state_key("remote_base_display"))
        d1.text_input("Remote XCP-D FC", value=hpc_config.remote_xcpd_fc, disabled=True, key=_state_key("remote_xcpd_fc_display"))
        d2.text_input("Remote XCP-D FC+GSR", value=hpc_config.remote_xcpd_fc_gsr, disabled=True, key=_state_key("remote_xcpd_fc_gsr_display"))
        d2.text_input("Partition", value=hpc_config.partition, disabled=True, key=_state_key("partition_display"))

        if st.button("Test HPC connection", key=_state_key("test_connection")):
            try:
                with st.spinner(f"Connecting to {hpc_config.host}..."):
                    conn = HPCConnection(hpc_config)
                    conn.connect()
                    stdout, stderr, exit_code = conn.execute("hostname && whoami", timeout=20)
                    conn.disconnect()
                if exit_code == 0:
                    st.success(stdout.strip())
                else:
                    st.error(stderr.strip() or "Connection command failed")
            except Exception as exc:
                st.error(f"Connection failed: {exc}")

    if not hpc.get("enabled", False):
        st.warning("HPC is disabled in configuration. Enable it in Settings before submitting.")


def _render_subject_selector(config: Dict) -> List[str]:
    st.subheader("2. Subject / Session Selection")
    bids_dir = config.get("paths", {}).get("bids_dir", "")
    if not bids_dir:
        st.error("BIDS directory is not configured.")
        return []

    scan = _scan_bids_cached(bids_dir)
    if scan["summary"].get("error"):
        st.error(scan["summary"]["error"])
        return []

    subject_sessions = scan["subject_sessions"]
    all_pairs = [row["pair"] for row in subject_sessions]
    session_counts: Dict[str, int] = {}
    for row in subject_sessions:
        session_counts[row["subject"]] = session_counts.get(row["subject"], 0) + (1 if row["session"] else 0)
    longitudinal_pairs = [row["pair"] for row in subject_sessions if session_counts.get(row["subject"], 0) >= 2]

    c1, c2, c3 = st.columns(3)
    c1.metric("Subjects", len(session_counts))
    c2.metric("Subject/session pairs", len(all_pairs))
    c3.metric("Longitudinal subjects", sum(1 for count in session_counts.values() if count >= 2))

    select_all = st.checkbox("Select all", value=False, key=_state_key("select_all"))
    longitudinal_only = st.checkbox(
        "Longitudinal only (≥2 sessions)",
        value=True,
        key=_state_key("longitudinal_only"),
    )
    options = longitudinal_pairs if longitudinal_only else all_pairs
    subjects_key = _state_key("subjects")
    if select_all:
        st.session_state[subjects_key] = options
    elif subjects_key in st.session_state:
        st.session_state[subjects_key] = [pair for pair in st.session_state[subjects_key] if pair in options]
    default = st.session_state.get(subjects_key, options[: min(4, len(options))])

    selected = st.multiselect(
        "Subject/session pairs",
        options=options,
        default=default,
        key=subjects_key,
        help="Pairs are stored as sub-XXX_ses-YY.",
    )
    st.caption(f"Selected {len(selected)} pair(s): {', '.join(selected[:6])}{'…' if len(selected) > 6 else ''}")
    return selected


def _render_options(config: Dict) -> Dict:
    st.subheader("3. Analysis Options")
    local_cfg = config.get("connectivity", {}).get("local_measures", {})
    bandpass = local_cfg.get("bandpass") or [0.01, 0.1]

    input_label = st.radio(
        "Input source",
        list(INPUT_SOURCE_LABELS.keys()),
        horizontal=True,
        key=_state_key("input_source_label"),
    )
    input_source = INPUT_SOURCE_LABELS[input_label]
    custom_input = ""
    if input_source == "custom":
        custom_input = st.text_input("Custom input path", key=_state_key("custom_input_path"))

    col1, col2, col3, col4 = st.columns(4)
    high_pass = col1.number_input("High-pass", min_value=0.0, max_value=1.0, value=float(bandpass[0]), step=0.005, format="%.3f", key=_state_key("high_pass"))
    low_pass = col2.number_input("Low-pass", min_value=0.0, max_value=1.0, value=float(bandpass[1]), step=0.005, format="%.3f", key=_state_key("low_pass"))
    alff_low = col3.number_input("ALFF/fALFF band low", min_value=0.0, max_value=1.0, value=0.01, step=0.005, format="%.3f", key=_state_key("alff_band_low"))
    alff_high = col4.number_input("ALFF/fALFF band high", min_value=0.0, max_value=1.0, value=0.08, step=0.005, format="%.3f", key=_state_key("alff_band_high"))

    auto_tr = st.checkbox("Auto-detect from JSON", value=True, key=_state_key("auto_tr"))
    detected_tr = _detect_tr_cached(config.get("paths", {}).get("bids_dir", "")) if auto_tr else None
    tr_default = float(detected_tr or local_cfg.get("tr") or 0.8)
    tr = st.number_input("TR (seconds)", min_value=0.1, max_value=10.0, value=tr_default, step=0.1, format="%.3f", key=_state_key("tr"))
    if detected_tr:
        st.caption(f"Detected TR from BIDS sidecars: {detected_tr:g}s")

    col5, col6 = st.columns(2)
    smoothing_options = [0, 4, 6, 8]
    smoothing_default = int(local_cfg.get("smoothing_fwhm", 6))
    smoothing_index = smoothing_options.index(smoothing_default) if smoothing_default in smoothing_options else 2
    smoothing = col5.selectbox("Smoothing FWHM", smoothing_options, index=smoothing_index, format_func=lambda v: f"{v} mm", key=_state_key("smoothing_fwhm"))
    reho_label = col6.selectbox("ReHo neighborhood", list(NEIGHBORHOOD_LABELS.keys()), index=2, key=_state_key("reho_neighborhood_label"))

    mask_label = st.radio("Brain mask", ["Auto (XCP-D)", "Custom path"], horizontal=True, key=_state_key("mask_label"))
    mask_path = ""
    if mask_label == "Custom path":
        mask_path = st.text_input("Custom brain mask path", key=_state_key("custom_mask_path"))

    st.markdown("**Output measures**")
    m1, m2, m3 = st.columns(3)
    measures = []
    if m1.checkbox("fALFF", value=True, key=_state_key("measure_falff")):
        measures.append("fALFF")
    if m2.checkbox("ALFF", value=True, key=_state_key("measure_alff")):
        measures.append("ALFF")
    if m3.checkbox("ReHo", value=True, key=_state_key("measure_reho")):
        measures.append("ReHo")

    with st.expander("HPC resources", expanded=True):
        hpc_config = HPCConfig.from_config(config)
        r1, r2, r3 = st.columns(3)
        wall_time = r1.text_input("Wall time", value="02:00:00", key=_state_key("wall_time"))
        memory = r2.text_input("Memory", value="16G", key=_state_key("memory"))
        cpus = r3.number_input("CPUs per task", min_value=1, max_value=64, value=4, step=1, key=_state_key("cpus"))
        partition_options = [hpc_config.partition] if hpc_config.partition else ["shared_cpu"]
        partition = st.selectbox("Partition", partition_options, index=0, key=_state_key("partition"))
        max_parallel = st.slider("Max parallel jobs", min_value=1, max_value=44, value=20, key=_state_key("max_parallel"))

    input_path = _resolve_input_path(config, input_source, custom_input)
    remote_input_path = _remote_path_for_source(config, input_source, input_path)
    options = {
        "input_source": input_source,
        "input_path": input_path,
        "remote_input_path": remote_input_path,
        "high_pass": high_pass,
        "low_pass": low_pass,
        "alff_band_low": alff_low,
        "alff_band_high": alff_high,
        "tr": tr,
        "auto_detect_tr": auto_tr,
        "smoothing_fwhm": smoothing,
        "reho_neighborhood": NEIGHBORHOOD_LABELS[reho_label],
        "brain_mask": "auto" if mask_label == "Auto (XCP-D)" else mask_path,
        "measures": measures,
        "time": wall_time,
        "memory": memory,
        "cpus": cpus,
        "partition": partition,
        "max_parallel": max_parallel,
        "output_dir": _default_remote_output_dir(config),
        "log_dir": _default_remote_log_dir(config),
        "remote_project_dir": HPCConfig.from_config(config).remote_base,
    }
    st.session_state[_state_key("options")] = options
    return options


def _render_preflight(config: Dict, selected_pairs: List[str], options: Dict) -> None:
    st.subheader("4. Manifest Preflight")
    local_exists = _path_exists_locally(options.get("input_path", ""))
    remote_path = options.get("remote_input_path") or options.get("input_path", "")
    measures = options.get("measures", [])
    warnings = []
    blockers = []

    if not selected_pairs:
        blockers.append("No subject/session pairs selected")
    if not measures:
        blockers.append("No output measures selected")
    if not options.get("input_path") and not remote_path:
        blockers.append("Input path is empty")
    elif not local_exists:
        warnings.append("Input path is not present locally; submit validation will check the HPC path.")
    if options.get("brain_mask") not in (None, "", "auto") and not _path_exists_locally(str(options["brain_mask"])):
        warnings.append("Custom mask is not present locally; submit validation will check the HPC path.")

    badge = "red" if blockers else "yellow" if warnings else "green"
    st.markdown(f"**Status:** {STATUS_BADGES[badge]}")
    p1, p2, p3 = st.columns(3)
    p1.metric("Pairs", len(selected_pairs))
    p2.metric("Measures", len(measures))
    p3.metric("Local input", "Found" if local_exists else "Missing")
    st.caption(f"Input path: `{options.get('input_path') or remote_path}`")
    if warnings:
        for warning in warnings:
            st.warning(warning)
    if blockers:
        for blocker in blockers:
            st.error(blocker)


def _render_actions(config: Dict, selected_pairs: List[str], options: Dict) -> None:
    st.subheader("5. Submit")
    manager = ConnectivityWorkflowManager(config)
    subjects = _subjects_for_manager(selected_pairs)
    sessions = _sessions_for_manager(selected_pairs)
    submit_options = dict(options)
    if sessions:
        submit_options["sessions"] = sessions
    submit_options["selected_pairs"] = selected_pairs

    validation_args = (
        config,
        selected_pairs,
        submit_options.get("measures", []),
        submit_options.get("input_path", ""),
        submit_options.get("remote_input_path", ""),
        "" if submit_options.get("brain_mask") == "auto" else str(submit_options.get("brain_mask", "")),
    )

    dry_col, submit_col = st.columns(2)
    with dry_col:
        if st.button("🔍 Dry-run (preview SLURM script)", key=_state_key("dry_run"), use_container_width=True):
            errors = _validate_submission(*validation_args, check_hpc=False)
            non_path_errors = [e for e in errors if "not found locally" not in e]
            if non_path_errors:
                for error in non_path_errors:
                    st.error(error)
            else:
                command = manager.build_subject_level_command(ANALYSIS_TYPE, submit_options, subjects)
                sub = manager.submit(ANALYSIS_TYPE, submit_options, subjects, dry_run=True)
                st.success(f"Dry-run saved: {sub.submission_id}")
                st.code(command, language="bash")

    with submit_col:
        if st.button("🚀 Submit to HPC", key=_state_key("submit"), type="primary", use_container_width=True):
            errors = _validate_submission(*validation_args, check_hpc=True)
            if errors:
                for error in errors:
                    st.error(error)
                return
            with st.spinner("Submitting local measures job to HPC..."):
                sub = manager.submit(analysis_type=ANALYSIS_TYPE, options=submit_options, subjects=subjects, dry_run=False)
            if sub.status == "failed":
                st.error(sub.notes or "Submission failed")
            else:
                st.success(f"Submitted job {sub.job_id}")
                st.code(manager.build_subject_level_command(ANALYSIS_TYPE, submit_options, subjects), language="bash")


def _submission_summary(submission: ConnectivitySubmission) -> str:
    pairs = submission.options.get("selected_pairs") or []
    measures = submission.options.get("measures") or []
    return (
        f"Job `{submission.job_id or 'N/A'}` · **{submission.status}** · "
        f"{len(pairs) or len(submission.subjects)} pair(s) · "
        f"{', '.join(measures) if measures else 'measures not recorded'}"
    )


def _render_monitor(config: Dict) -> None:
    st.subheader("6. Submission Monitor")
    manager = ConnectivityWorkflowManager(config)
    submissions = [sub for sub in manager.list_submissions() if sub.analysis_type == ANALYSIS_TYPE]
    if not submissions:
        st.info("No Local Measures submissions recorded yet.")
        return

    for sub in submissions:
        with st.expander(f"{sub.submitted_at[:19]} · {sub.job_id or 'N/A'} · {sub.status}", expanded=False):
            st.markdown(_submission_summary(sub))
            st.caption(f"Submission ID: `{sub.submission_id}`")
            st.caption(f"Output: `{sub.output_dir or 'not configured'}`")
            if sub.notes:
                st.warning(sub.notes)
            b1, b2, b3 = st.columns(3)
            if b1.button("🔄 Refresh", key=_state_key(f"refresh_{sub.submission_id}")):
                try:
                    status = manager.refresh_status(sub.submission_id)
                    st.success(f"Status: {status}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Refresh failed: {exc}")
            if b2.button("🛑 Cancel", key=_state_key(f"cancel_{sub.submission_id}")):
                try:
                    if manager.cancel(sub.submission_id):
                        st.success("Cancellation requested")
                        st.rerun()
                    else:
                        st.error("Cancellation failed")
                except Exception as exc:
                    st.error(f"Cancel failed: {exc}")
            if b3.button("⬇️ Download", key=_state_key(f"download_{sub.submission_id}")):
                remote_output = sub.output_dir or "<remote-output-dir>"
                local_output = _default_local_output_dir(config)
                hpc_config = HPCConfig.from_config(config)
                remote = f"{hpc_config.user}@{hpc_config.host}:{shlex.quote(str(remote_output).rstrip('/') + '/')}"
                command = f"rsync -av {remote} {shlex.quote(str(local_output).rstrip('/') + '/')}"
                st.info("Run this download command from the project machine after outputs are ready:")
                st.code(command, language="bash")

            with st.expander("Command preview / options", expanded=False):
                command = sub.options.get("command_preview")
                if command:
                    st.code(command, language="bash")
                st.json(sub.options)


def render():
    st.title("📊 Submit Local Measures Analysis")
    config = _get_config()
    if not config:
        return

    _render_hpc_status(config)
    selected_pairs = _render_subject_selector(config)
    options = _render_options(config)
    _render_preflight(config, selected_pairs, options)
    _render_actions(config, selected_pairs, options)
    _render_monitor(config)
