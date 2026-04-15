"""
Gated XCP-D pipeline page for FD inspection, execution, and QC review.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Dict, List

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.config import save_config
from utils.fd_inspection import build_fd_summary, generate_fd_plots, highlight_fd_rows
from utils.pipeline_state import (
    STEP_ORDER,
    append_pipeline_log,
    load_pipeline_state,
    save_pipeline_state,
    set_approval,
    set_step_status,
)
from utils.xcpd import (
    build_remote_xcpd_command,
    build_xcpd_command,
    generate_xcpd_slurm_script,
    refresh_xcpd_run,
    start_remote_xcpd_run,
    start_xcpd_run,
    stop_xcpd_run,
)
from utils.xcpd_atlases import (
    atlas_option_ids,
    build_xcpd_atlas_status_rows,
    format_xcpd_atlas_label,
    missing_xcpd_atlas_resources,
    normalize_xcpd_atlas_selection,
    recommended_xcpd_atlases,
)
from utils.xcpd_qc import render_xcpd_qc_reports


def render() -> None:
    st.header("🧪 XCP-D Pipeline")

    config = st.session_state.get("config", {})
    if not config:
        st.error("Configuration not loaded.")
        return

    state = load_pipeline_state(config)
    state = refresh_xcpd_run(config, "fc", state)
    state = refresh_xcpd_run(config, "fc_gsr", state)
    state = refresh_xcpd_run(config, "ec", state)
    save_pipeline_state(config, state)

    render_pipeline_progress(state)

    tab_fd, tab_run, tab_qc, tab_logs = st.tabs(
        ["FD Inspection", "XCP-D Runs", "Post-XCP-D QC", "Pipeline Logs"]
    )

    with tab_fd:
        render_fd_inspection(config, state)

    with tab_run:
        render_xcpd_runs(config, state)

    with tab_qc:
        render_xcpd_qc_reports(config, state)

    with tab_logs:
        render_logs(config, state)


def render_pipeline_progress(state: Dict) -> None:
    status_colors = {
        "not_started": "⚪",
        "running": "🟡",
        "completed": "🟢",
        "failed": "🔴",
        "awaiting_approval": "🟠",
    }
    st.subheader("Pipeline Progress")
    cols = st.columns(len(STEP_ORDER))
    for col, step in zip(cols, STEP_ORDER):
        info = state["steps"].get(step, {})
        status = info.get("status", "not_started")
        col.metric(step.replace("_", " ").title(), status)
        col.caption(status_colors.get(status, "⚪"))


def render_fd_inspection(config: Dict, state: Dict) -> None:
    paths = config["paths"]
    fmriprep_dir = Path(paths["fmriprep_dir"])
    output_dir = Path(paths["fd_inspection_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    st.caption(f"fMRIPrep source: `{fmriprep_dir}`")

    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button("Generate / Refresh FD Summary", width="stretch"):
            configured_tr = float(config.get("connectivity", {}).get("local_measures", {}).get("tr") or 0.8)
            summary = build_fd_summary(
                fmriprep_dir=fmriprep_dir,
                output_dir=output_dir,
                tr=configured_tr,
            )
            generate_fd_plots(fmriprep_dir, output_dir, summary)
            state = set_step_status(
                config,
                "fd_inspection",
                "completed",
                f"{len(summary)} subject-session rows",
                state=state,
            )
            append_pipeline_log(config, "Generated FD inspection summary", state=state)
            st.success("FD summary generated.")
            st.rerun()
    with col2:
        st.info(
            "Review mean FD, projected data retention, and exclusion thresholds here before either XCP-D run is enabled."
        )

    summary_path = output_dir / "fd_summary.csv"
    if not summary_path.exists():
        st.warning("No FD summary yet. Generate it first.")
        return

    summary = pd.read_csv(summary_path)
    if summary.empty:
        st.warning("No confounds files were found under the configured fMRIPrep directory.")
        return

    colm1, colm2, colm3 = st.columns(3)
    with colm1:
        st.metric("Subject-session runs", len(summary))
    with colm2:
        st.metric("Mean of mean FD", f"{summary['mean_fd'].mean():.4f}")
    with colm3:
        st.metric("Runs with mean FD > 0.5", int((summary["mean_fd"] > 0.5).sum()))

    current_fc_fd = float(config["xcpd"]["fc"].get("fd_thresh", 0.5))
    current_ec_exclusion = float(config["subject_exclusion"].get("mean_fd_threshold", 0.5))
    current_min_time = int(config["subject_exclusion"].get("min_scan_time", 100))
    existing_approval = state["approvals"].get("fd_gate", {})
    if existing_approval.get("approved"):
        st.info(
            f"Thresholds last approved at {existing_approval.get('approved_at')}."
            " Updating them will require re-running XCP-D."
        )

    with st.form("fd_gate_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            new_fc_fd = st.number_input(
                "FC Pipeline FD Threshold",
                min_value=0.0,
                max_value=2.0,
                value=current_fc_fd,
                step=0.05,
            )
        with col2:
            new_ec_exclusion = st.number_input(
                "EC Pipeline Exclusion Threshold",
                min_value=0.0,
                max_value=2.0,
                value=current_ec_exclusion,
                step=0.05,
            )
        with col3:
            new_min_time = st.number_input(
                "Minimum Remaining Scan Time (s)",
                min_value=0,
                max_value=2000,
                value=current_min_time,
                step=10,
            )

        preview = build_threshold_preview(
            summary,
            new_fc_fd,
            new_ec_exclusion,
            tr=float(config.get("connectivity", {}).get("local_measures", {}).get("tr") or 0.8),
        )
        styled = (
            preview.style.apply(
                lambda row: [
                    "background-color: #d9f2d9" if row["risk"] == "green"
                    else "background-color: #fff2cc" if row["risk"] == "amber"
                    else "background-color: #f4cccc"
                    for _ in row
                ],
                axis=1,
            )
            .format(
                {
                    "mean_fd": "{:.4f}",
                    "median_fd": "{:.4f}",
                    "peak_fd": "{:.4f}",
                    "fc_remaining_sec": "{:.1f}",
                }
            )
        )
        st.dataframe(styled, width="stretch", hide_index=True)

        for plot_name in (
            "fd_group_histogram.png",
            "fd_boxplot_by_session.png",
            "fd_timeseries_all_subjects.png",
        ):
            plot_path = output_dir / plot_name
            if plot_path.exists():
                st.image(str(plot_path), caption=plot_name)

        approved = st.form_submit_button("Approve Thresholds and Proceed", type="primary")
        if approved:
            config["xcpd"]["fc"]["fd_thresh"] = new_fc_fd
            config["subject_exclusion"]["mean_fd_threshold"] = new_ec_exclusion
            config["subject_exclusion"]["min_scan_time"] = new_min_time
            config["xcpd"]["fc"]["min_time"] = new_min_time

            save_runtime_config(config)
            state = set_approval(
                config,
                "fd_gate",
                True,
                payload={
                    "fc_fd_thresh": new_fc_fd,
                    "ec_mean_fd_threshold": new_ec_exclusion,
                    "min_scan_time": new_min_time,
                },
                state=state,
            )
            state = set_step_status(
                config,
                "fd_gate",
                "completed",
                f"FC FD={new_fc_fd}, EC mean FD={new_ec_exclusion}, min time={new_min_time}s",
                state=state,
            )
            append_pipeline_log(config, "Approved FD thresholds", state=state)
            st.success("Thresholds approved. XCP-D runs are now unlocked.")
            st.rerun()


def build_threshold_preview(
    summary: pd.DataFrame,
    fc_fd_thresh: float,
    ec_exclusion: float,
    tr: float | None = None,
) -> pd.DataFrame:
    preview_rows = []
    for _, row in summary.iterrows():
        confounds = pd.read_csv(row["confounds_file"], sep="\t")
        fd = confounds["framewise_displacement"].fillna(0.0)
        row_tr = tr
        if row_tr is None and "tr" in row.index and pd.notna(row["tr"]):
            row_tr = float(row["tr"])
        if row_tr is None:
            row_tr = 0.8
        preview_rows.append(
            {
                **row.to_dict(),
                "fc_remaining_sec": float((fd <= fc_fd_thresh).sum() * row_tr),
                "ec_included": bool(float(row["mean_fd"]) <= ec_exclusion),
            }
        )
    preview = pd.DataFrame(preview_rows)
    preview = highlight_fd_rows(preview)
    columns = [
        "subject_id",
        "session",
        "mean_fd",
        "median_fd",
        "peak_fd",
        "fc_remaining_sec",
        "ec_included",
        "risk",
    ]
    return preview[columns].sort_values(["subject_id", "session"])


def render_xcpd_runs(config: Dict, state: Dict) -> None:
    if not state["approvals"].get("fd_gate", {}).get("approved"):
        st.warning("Approve the FD thresholds first.")
        state = set_step_status(config, "fd_gate", "awaiting_approval", "Waiting for researcher approval", state=state)
        return

    subjects = available_subjects(Path(config["paths"]["bids_dir"]))
    selected_subjects = st.multiselect(
        "Participant labels",
        options=subjects,
        default=subjects[: min(8, len(subjects))],
        help="Leave empty to run all available subjects.",
    )
    sessions = st.multiselect(
        "Sessions",
        options=["ses-01", "ses-02"],
        default=["ses-01", "ses-02"],
    )
    run_on_hpc = st.checkbox(
        "Run on HPC",
        value=bool(config.get("hpc", {}).get("enabled", False)),
        help="Use the configured HPC SSH connection for long-running XCP-D jobs.",
    )

    fc_defaults = normalize_xcpd_atlas_selection(config["xcpd"]["fc"].get("atlases", [])) or recommended_xcpd_atlases()
    fc_gsr_defaults = normalize_xcpd_atlas_selection(config["xcpd"].get("fc_gsr", {}).get("atlases", [])) or recommended_xcpd_atlases()
    ec_defaults = normalize_xcpd_atlas_selection(config["xcpd"]["ec"].get("atlases", [])) or recommended_xcpd_atlases()
    atlas_options = atlas_option_ids(config, list(fc_defaults) + list(fc_gsr_defaults) + list(ec_defaults))

    st.markdown("### Atlas Selection")
    atlas_col1, atlas_col2, atlas_col3 = st.columns(3)
    with atlas_col1:
        selected_fc_atlases = st.multiselect(
            "FC atlases",
            options=atlas_options,
            default=[a for a in fc_defaults if a in atlas_options],
            format_func=lambda atlas_id: format_xcpd_atlas_label(config, atlas_id),
            key="xcpd_fc_run_atlases",
            help="Atlases for the FC (no-GSR) pipeline.",
        )
    with atlas_col2:
        selected_fc_gsr_atlases = st.multiselect(
            "FC+GSR atlases",
            options=atlas_options,
            default=[a for a in fc_gsr_defaults if a in atlas_options],
            format_func=lambda atlas_id: format_xcpd_atlas_label(config, atlas_id),
            key="xcpd_fc_gsr_run_atlases",
            help="Atlases for the FC + GSR comparison pipeline.",
        )
    with atlas_col3:
        selected_ec_atlases = st.multiselect(
            "EC atlases",
            options=atlas_options,
            default=[a for a in ec_defaults if a in atlas_options],
            format_func=lambda atlas_id: format_xcpd_atlas_label(config, atlas_id),
            key="xcpd_ec_run_atlases",
            help="Atlases for the effective connectivity pipeline.",
        )

    all_selected_atlases = list(selected_fc_atlases) + list(selected_fc_gsr_atlases) + list(selected_ec_atlases)
    atlas_rows = build_xcpd_atlas_status_rows(config, all_selected_atlases)
    if atlas_rows:
        with st.expander("Atlas availability", expanded=False):
            st.dataframe(atlas_rows, width="stretch", hide_index=True)

    fc_info = state.get("runs", {}).get("xcpd_fc", {})
    fc_gsr_info = state.get("runs", {}).get("xcpd_fc_gsr", {})
    ec_info = state.get("runs", {}).get("xcpd_ec", {})

    col1, col2, col3 = st.columns(3)
    with col1:
        _render_pipeline_panel(
            config, state, "fc", "FC (no GSR)", selected_fc_atlases,
            fc_info, run_on_hpc, selected_subjects, sessions,
        )
    with col2:
        _render_pipeline_panel(
            config, state, "fc_gsr", "FC + GSR", selected_fc_gsr_atlases,
            fc_gsr_info, run_on_hpc, selected_subjects, sessions,
            extra_note="36P regressors including global signal regression. Run alongside FC to compare.",
        )
    with col3:
        _render_pipeline_panel(
            config, state, "ec", "Effective Connectivity", selected_ec_atlases,
            ec_info, run_on_hpc, selected_subjects, sessions,
            extra_note="No scrubbing; interpolated output; no smoothing; wider bandpass.",
        )


def _render_pipeline_panel(
    config: Dict,
    state: Dict,
    pipeline_name: str,
    label: str,
    selected_atlases: List[str],
    run_info: Dict,
    run_on_hpc: bool,
    selected_subjects: List[str],
    sessions: List[str],
    extra_note: str = "",
) -> None:
    """Render the run/status panel for a single XCP-D pipeline."""
    step_key = f"xcpd_{pipeline_name}"
    st.subheader(label)
    st.caption(f"mode: `{config['xcpd'].get(pipeline_name, {}).get('mode', 'linc')}`")
    st.code(" ".join(selected_atlases) if selected_atlases else "(no atlases)", language="text")
    if extra_note:
        st.info(extra_note)

    step_status = state["steps"].get(step_key, {}).get("status", "not_started")
    st.caption(f"Status: {run_info.get('status', step_status)}")
    if run_info.get("job_id"):
        st.caption(f"SLURM job ID: {run_info['job_id']}")
    elif run_info.get("pid"):
        st.caption(f"PID: {run_info['pid']}")
    if run_info.get("local_script") and Path(run_info["local_script"]).exists():
        with st.expander("View SLURM Script"):
            st.code(Path(run_info["local_script"]).read_text(), language="bash")
    if run_info.get("remote_log_out"):
        st.caption(f"Remote log: {run_info['remote_log_out']}")

    if st.button(f"Start {label} XCP-D", key=f"start_{pipeline_name}", width="stretch"):
        missing = missing_xcpd_atlas_resources(config, selected_atlases)
        if missing:
            st.error("Missing atlas resources: " + ", ".join(str(p) for p in missing))
        else:
            try:
                config["xcpd"][pipeline_name]["atlases"] = normalize_xcpd_atlas_selection(selected_atlases)
                save_runtime_config(config)
                if run_on_hpc:
                    info = start_remote_xcpd_run(config, pipeline_name, selected_subjects or None, sessions or None)
                else:
                    info = start_xcpd_run(config, pipeline_name, selected_subjects or None, sessions or None)
                job_label = f"job {info.get('job_id', info.get('pid', '?'))}"
                st.success(f"Started {label} XCP-D ({job_label})")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to start {label} XCP-D: {e}")
    if run_info.get("status") == "running":
        if st.button(f"Stop {label} XCP-D", key=f"stop_{pipeline_name}", width="stretch"):
            stop_xcpd_run(config, pipeline_name, state)
            st.rerun()
    if run_info.get("log_file"):
        st.caption(run_info["log_file"])

    # Script / command preview — shown after the action buttons so the user can
    # verify exactly what will be (or was) submitted without cluttering the flow.
    expander_label = "Preview SLURM script" if run_on_hpc else "Preview command"
    with st.expander(expander_label, expanded=False):
        try:
            if run_on_hpc:
                script = generate_xcpd_slurm_script(
                    config, pipeline_name,
                    [s.removeprefix("sub-") for s in selected_subjects] if selected_subjects else None,
                    [s.removeprefix("ses-") for s in sessions] if sessions else None,
                )
                st.code(script, language="bash")
            else:
                cmd = build_xcpd_command(
                    config, pipeline_name,
                    selected_subjects or None,
                    sessions or None,
                )
                st.code(" \\\n  ".join(cmd), language="bash")
        except Exception as exc:
            st.warning(f"Cannot build preview: {exc}")


def render_logs(config: Dict, state: Dict) -> None:
    log_rows = pd.DataFrame(state.get("log", []))
    if log_rows.empty:
        st.caption("No pipeline log entries yet.")
    else:
        st.dataframe(log_rows, width="stretch", hide_index=True)

    for run_key in ("xcpd_fc", "xcpd_fc_gsr", "xcpd_ec"):
        run_info = state.get("runs", {}).get(run_key)
        if not run_info or not run_info.get("log_file"):
            continue
        log_file = Path(run_info["log_file"])
        st.markdown(f"**{run_key} log**")
        if run_info.get("remote_log"):
            st.caption(f"Remote log: {run_info['remote_log']}")
        if log_file.exists():
            tail = "\n".join(log_file.read_text(errors="ignore").splitlines()[-30:])
            st.code(tail or "(empty log)")
        else:
            st.caption("Log file not found yet.")


def available_subjects(bids_dir: Path) -> List[str]:
    return [path.name for path in sorted(bids_dir.glob("sub-*")) if path.is_dir()]


def save_runtime_config(config: Dict) -> None:
    config_path = Path.home() / "neuconn_projects" / "longevity.yaml"
    save_config(config, str(config_path))
    st.session_state.config = config


if __name__ == "__main__":
    render()
