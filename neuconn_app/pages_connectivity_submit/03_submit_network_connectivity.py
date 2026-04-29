"""Streamlit page for submitting network-connectivity subject-level HPC jobs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from typing import Dict, List, Tuple

import streamlit as st


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.connectivity_workflow import ConnectivitySubmission, ConnectivityWorkflowManager
from utils.hpc import HPCConfig, HPCConnection


SESSION_PREFIX = "submit_network_"
ATLAS_OPTIONS = ["DiFuMo256", "Schaefer400", "Schaefer200_Tian"]
NETWORK_GROUPING_OPTIONS = [
    "None (full N×N matrix)",
    "7 Yeo networks",
    "17 Yeo networks",
]
CORRELATION_OPTIONS = ["Pearson", "Partial", "Tangent"]
CONFOUND_OPTIONS = ["36P", "36P+spike", "aCompCor", "AROMA"]
OUTPUT_OPTIONS = {
    "correlation_matrix_hdf5": "Correlation matrix (HDF5)",
    "network_stats_csv": "Network stats CSV",
    "graph_metrics": "Graph metrics",
}


def _key(name: str) -> str:
    return f"{SESSION_PREFIX}{name}"


def _session_options() -> List[str]:
    return ["ses-01", "ses-02"]


def _normalise_subject_id(subject_name: str) -> str:
    return subject_name.replace("sub-", "", 1)


def _discover_subject_sessions(bids_dir: str) -> Dict[str, List[str]]:
    bids_path = Path(bids_dir).expanduser()
    if not bids_path.exists():
        return {}

    subjects: Dict[str, List[str]] = {}
    for subject_dir in sorted(bids_path.glob("sub-*")):
        if not subject_dir.is_dir():
            continue
        sessions = [
            session_dir.name
            for session_dir in sorted(subject_dir.glob("ses-*"))
            if session_dir.is_dir()
        ]
        if not sessions:
            sessions = [""]
        subjects[_normalise_subject_id(subject_dir.name)] = sessions
    return subjects


def _output_dir(config: Dict) -> str:
    paths = config.get("paths", {})
    return (
        paths.get("subject_level_fc_dir")
        or paths.get("subject_level_dir")
        or paths.get("derivatives_dir")
        or "results"
    )


def _remote_project_dir(config: Dict) -> str:
    hpc = config.get("hpc", {})
    remote = hpc.get("remote_paths", {})
    return remote.get("base", "") or config.get("project_root", "")


def _render_hpc_status(config: Dict) -> bool:
    st.subheader("1. HPC connection status")
    hpc = config.get("hpc", {})
    remote = hpc.get("remote_paths", {})

    enabled = bool(hpc.get("enabled", False))
    cols = st.columns(4)
    cols[0].metric("HPC", "Enabled" if enabled else "Disabled")
    cols[1].metric("Host", hpc.get("host", "not set") or "not set")
    cols[2].metric("User", hpc.get("user", "not set") or "not set")
    cols[3].metric("Partition", hpc.get("slurm", {}).get("partition", "shared_cpu"))

    st.caption(
        f"Remote base: `{remote.get('base', '') or 'not set'}`  \n"
        f"Remote BIDS: `{remote.get('bids', '') or 'not set'}`"
    )

    if not enabled:
        st.warning("HPC is disabled in Settings. Dry-runs are still available.")

    with st.expander("Test HPC Connection", expanded=False):
        if st.button("Test Connection", key=_key("test_connection")):
            try:
                hpc_cfg = HPCConfig.from_config(config)
                with st.spinner(f"Connecting to {hpc_cfg.host}..."):
                    conn = HPCConnection(hpc_cfg)
                    conn.connect()
                    stdout, stderr, exit_code = conn.execute("hostname && whoami", timeout=20)
                    conn.disconnect()
                if exit_code == 0:
                    st.success(f"Connection successful:\n{stdout.strip()}")
                else:
                    st.error(stderr.strip() or "Connection command failed.")
            except Exception as exc:
                st.error(f"Connection failed: {exc}")

    return enabled


def _render_subject_session_selection(config: Dict) -> Tuple[List[str], List[str]]:
    st.subheader("2. Subject/session selection")
    bids_dir = config.get("paths", {}).get("bids_dir", "")
    subject_sessions = _discover_subject_sessions(bids_dir)

    if not subject_sessions:
        st.error(f"No BIDS subjects found in `{bids_dir}`.")
        return [], []

    col1, col2 = st.columns(2)
    with col1:
        select_all = st.checkbox("All subjects", value=True, key=_key("all_subjects"))
    with col2:
        longitudinal_only = st.checkbox(
            "Longitudinal only (ses-01 + ses-02)",
            value=True,
            key=_key("longitudinal_only"),
        )

    filtered_subjects = [
        subject
        for subject, sessions in subject_sessions.items()
        if not longitudinal_only or {"ses-01", "ses-02"}.issubset(set(sessions))
    ]

    if select_all:
        selected_subjects = filtered_subjects
        st.multiselect(
            "Subjects",
            filtered_subjects,
            default=filtered_subjects,
            key=_key("subjects_display"),
            disabled=True,
        )
    else:
        selected_subjects = st.multiselect(
            "Subjects",
            filtered_subjects,
            default=filtered_subjects[: min(4, len(filtered_subjects))],
            key=_key("subjects"),
        )

    selected_sessions = st.multiselect(
        "Sessions",
        _session_options(),
        default=_session_options(),
        key=_key("sessions"),
        help="Submitted as a session filter for the subject-level network-connectivity job array.",
    )

    st.success(f"Selected {len(selected_subjects)} subject(s) × {len(selected_sessions)} session(s).")
    return selected_subjects, selected_sessions


def _render_analysis_options() -> Dict:
    st.subheader("3–8. Network connectivity options")

    col1, col2 = st.columns(2)
    with col1:
        atlas = st.radio("Atlas", ATLAS_OPTIONS, index=0, key=_key("atlas"))
        network_grouping = st.radio(
            "Network grouping",
            NETWORK_GROUPING_OPTIONS,
            index=0,
            key=_key("network_grouping"),
        )
    with col2:
        correlation_type = st.selectbox(
            "Correlation type",
            CORRELATION_OPTIONS,
            index=0,
            key=_key("correlation_type"),
        )
        confound_strategy = st.selectbox(
            "Confound strategy",
            CONFOUND_OPTIONS,
            index=0,
            key=_key("confound_strategy"),
        )

    st.markdown("**Filtering and smoothing**")
    fcol1, fcol2, fcol3 = st.columns(3)
    with fcol1:
        high_pass = st.number_input(
            "High-pass (Hz)",
            min_value=0.0,
            max_value=0.2,
            value=0.01,
            step=0.005,
            format="%.3f",
            key=_key("high_pass"),
        )
    with fcol2:
        low_pass = st.number_input(
            "Low-pass (Hz)",
            min_value=0.0,
            max_value=0.5,
            value=0.10,
            step=0.01,
            format="%.3f",
            key=_key("low_pass"),
        )
    with fcol3:
        smoothing_fwhm = st.number_input(
            "Smoothing FWHM (mm)",
            min_value=0.0,
            max_value=12.0,
            value=6.0,
            step=0.5,
            key=_key("smoothing_fwhm"),
        )

    st.markdown("**Outputs**")
    ocol1, ocol2, ocol3 = st.columns(3)
    output_values = {}
    for col, (output_key, label) in zip([ocol1, ocol2, ocol3], OUTPUT_OPTIONS.items()):
        with col:
            output_values[output_key] = st.checkbox(label, value=True, key=_key(output_key))

    output_types = [name for name, enabled in output_values.items() if enabled]
    return {
        "atlas": atlas,
        "network_grouping": network_grouping,
        "correlation_type": correlation_type.lower(),
        "confound_strategy": confound_strategy,
        "high_pass": high_pass,
        "low_pass": low_pass,
        "smoothing_fwhm": smoothing_fwhm,
        "output_types": output_types,
    }


def _render_hpc_resources(config: Dict) -> Dict:
    hpc = config.get("hpc", {})
    slurm = hpc.get("slurm", {})

    with st.expander("9. HPC resources", expanded=False):
        rcol1, rcol2, rcol3 = st.columns(3)
        with rcol1:
            cpus = st.number_input(
                "CPUs per task",
                min_value=1,
                max_value=64,
                value=int(slurm.get("default_cpus", 8)),
                key=_key("cpus"),
            )
        with rcol2:
            memory = st.text_input(
                "Memory",
                value=str(slurm.get("default_memory", "32GB")),
                key=_key("memory"),
            )
        with rcol3:
            time_limit = st.text_input(
                "Time limit",
                value=str(slurm.get("default_time", "24:00:00")),
                key=_key("time"),
            )

        rcol4, rcol5 = st.columns(2)
        with rcol4:
            partition = st.text_input(
                "Partition",
                value=str(slurm.get("partition", "shared_cpu")),
                key=_key("partition"),
            )
        with rcol5:
            max_parallel = st.number_input(
                "Max parallel array tasks",
                min_value=1,
                max_value=256,
                value=int(slurm.get("max_concurrent_jobs", 4)),
                key=_key("max_parallel"),
            )

    return {
        "cpus": cpus,
        "memory": memory,
        "time": time_limit,
        "partition": partition,
        "max_parallel": max_parallel,
    }


def _build_options(config: Dict, selected_sessions: List[str], analysis_options: Dict, resource_options: Dict) -> Dict:
    options = {
        **analysis_options,
        **resource_options,
        "sessions": selected_sessions,
        "output_dir": _output_dir(config),
        "remote_project_dir": _remote_project_dir(config),
    }
    return options


def _validate(selected_subjects: List[str], options: Dict) -> List[str]:
    errors = []
    if not selected_subjects:
        errors.append("Select at least one subject.")
    if not options.get("atlas"):
        errors.append("Choose an atlas.")
    if not options.get("output_types"):
        errors.append("Choose at least one output type.")
    if options.get("low_pass", 0) and options.get("high_pass", 0) >= options.get("low_pass", 0):
        errors.append("High-pass must be lower than low-pass.")
    return errors


def _render_preflight(manager: ConnectivityWorkflowManager, selected_subjects: List[str], options: Dict) -> None:
    st.subheader("10. Manifest preflight")
    errors = _validate(selected_subjects, options)
    manifest_path = manager.state_file
    expected_jobs = len(selected_subjects) * max(1, len(options.get("sessions", [])))

    cols = st.columns(4)
    cols[0].metric("Preflight", "Ready" if not errors else "Blocked")
    cols[1].metric("Subject-session jobs", expected_jobs)
    cols[2].metric("Atlas", options.get("atlas") or "None")
    cols[3].metric("Outputs", len(options.get("output_types", [])))

    if errors:
        st.error(" ".join(errors))
    else:
        st.success("✅ Manifest preflight passed")
    st.caption(f"Submission manifest: `{manifest_path}`")


def _render_actions(manager: ConnectivityWorkflowManager, selected_subjects: List[str], options: Dict) -> None:
    st.subheader("11. Actions")
    errors = _validate(selected_subjects, options)
    preview_command = manager.build_subject_level_command(
        "network_connectivity",
        dict(options),
        selected_subjects,
    )
    st.code(preview_command, language="bash")

    col1, col2 = st.columns(2)
    with col1:
        dry_run = st.button("🔍 Dry-run", key=_key("dry_run"), disabled=bool(errors))
    with col2:
        submit = st.button("🚀 Submit", type="primary", key=_key("submit"), disabled=bool(errors))

    if dry_run:
        submission = manager.submit(
            analysis_type="network_connectivity",
            options=options,
            subjects=selected_subjects,
            dry_run=True,
        )
        st.success(f"Dry-run saved at {submission.submitted_at} with job_id=DRY_RUN.")
        st.code(submission.options.get("command_preview", preview_command), language="bash")

    if submit:
        try:
            with st.spinner("Submitting network connectivity job array..."):
                submission = manager.submit(
                    analysis_type="network_connectivity",
                    options=options,
                    subjects=selected_subjects,
                    dry_run=False,
                )
            if submission.status == "failed":
                st.error(submission.notes or "Submission failed.")
            else:
                st.success(f"Submitted network connectivity job: {submission.job_id or 'pending job id'}")
        except Exception as exc:
            st.error(f"Submission failed: {exc}")


def _status_icon(status: str) -> str:
    return {
        "submitted": "🟡",
        "running": "🔵",
        "completed": "🟢",
        "failed": "🔴",
        "cancelled": "⚪",
    }.get(status, "⚪")


def _submission_row(submission: ConnectivitySubmission) -> Dict:
    return {
        "submitted_at": submission.submitted_at,
        "status": f"{_status_icon(submission.status)} {submission.status}",
        "job_id": submission.job_id or "",
        "subjects": len(submission.subjects),
        "atlas": submission.options.get("atlas", ""),
        "correlation": submission.options.get("correlation_type", ""),
        "outputs": ", ".join(submission.options.get("output_types", [])),
        "output_dir": submission.output_dir or "",
    }


def _render_monitor(manager: ConnectivityWorkflowManager) -> None:
    st.subheader("12. Submission monitor")
    submissions = [
        submission
        for submission in manager.list_submissions()
        if submission.analysis_type == "network_connectivity"
    ]

    col1, col2 = st.columns([1, 3])
    with col1:
        refresh = st.button("🔄 Refresh statuses", key=_key("refresh_statuses"))

    if refresh:
        for submission in submissions:
            if submission.job_id and submission.job_id != "DRY_RUN" and submission.status in {"submitted", "running"}:
                try:
                    manager.refresh_status(submission.submission_id)
                except Exception as exc:
                    st.warning(f"Could not refresh {submission.job_id}: {exc}")
        submissions = [
            submission
            for submission in manager.list_submissions()
            if submission.analysis_type == "network_connectivity"
        ]

    if not submissions:
        st.info("No past network_connectivity submissions yet.")
        return

    st.dataframe([_submission_row(submission) for submission in submissions], hide_index=True, width="stretch")

    with st.expander("Submission details", expanded=False):
        labels = [
            f"{submission.submitted_at} · {submission.job_id or 'no job id'} · {submission.status}"
            for submission in submissions
        ]
        selected_label = st.selectbox("Select submission", labels, key=_key("monitor_selection"))
        selected_submission = submissions[labels.index(selected_label)]
        st.json(
            {
                "submission_id": selected_submission.submission_id,
                "job_id": selected_submission.job_id,
                "status": selected_submission.status,
                "subjects": selected_submission.subjects,
                "options": selected_submission.options,
                "output_dir": selected_submission.output_dir,
                "notes": selected_submission.notes,
            }
        )


def render():
    st.title("🕸️ Submit Network Connectivity Analysis")

    config = st.session_state.get("config", {})
    if not config:
        st.error("No configuration loaded. Please check Settings.")
        return

    _render_hpc_status(config)
    selected_subjects, selected_sessions = _render_subject_session_selection(config)
    analysis_options = _render_analysis_options()
    resource_options = _render_hpc_resources(config)

    manager = ConnectivityWorkflowManager(config)
    options = _build_options(config, selected_sessions, analysis_options, resource_options)

    _render_preflight(manager, selected_subjects, options)
    _render_actions(manager, selected_subjects, options)
    _render_monitor(manager)

    st.caption(f"Last rendered: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    render()
