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
    collect_qc_reports,
    refresh_xcpd_run,
    start_remote_xcpd_run,
    start_xcpd_run,
    stop_xcpd_run,
)
from utils.subject_level_fc import load_connectome_table


def render() -> None:
    st.header("🧪 XCP-D Pipeline")

    config = st.session_state.get("config", {})
    if not config:
        st.error("Configuration not loaded.")
        return

    state = load_pipeline_state(config)
    state = refresh_xcpd_run(config, "fc", state)
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
        render_post_xcpd_qc(config, state)

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
        if st.button("Generate / Refresh FD Summary", use_container_width=True):
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
        st.dataframe(styled, use_container_width=True, hide_index=True)

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

    fc_info = state.get("runs", {}).get("xcpd_fc", {})
    ec_info = state.get("runs", {}).get("xcpd_ec", {})

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("FC Pipeline")
        st.code(" ".join(config["xcpd"]["fc"].get("atlases", [])), language="text")
        st.caption(f"Status: {fc_info.get('status', state['steps']['xcpd_fc']['status'])}")
        if st.button("Start FC XCP-D", use_container_width=True):
            if run_on_hpc:
                run_info = start_remote_xcpd_run(config, "fc", selected_subjects or None, sessions or None)
            else:
                run_info = start_xcpd_run(config, "fc", selected_subjects or None, sessions or None)
            st.success(f"Started FC XCP-D (pid={run_info['pid']})")
            st.rerun()
        if fc_info.get("status") == "running":
            if st.button("Stop FC XCP-D", use_container_width=True):
                stop_xcpd_run(config, "fc", state)
                st.rerun()
        if fc_info.get("log_file"):
            st.caption(fc_info["log_file"])

    with col2:
        st.subheader("EC Pipeline")
        st.code(" ".join(config["xcpd"]["ec"].get("atlases", [])), language="text")
        st.caption(f"Status: {ec_info.get('status', state['steps']['xcpd_ec']['status'])}")
        st.info("EC pipeline runs without scrubbing and uses interpolated output.")
        if st.button("Start EC XCP-D", use_container_width=True):
            if run_on_hpc:
                run_info = start_remote_xcpd_run(config, "ec", selected_subjects or None, sessions or None)
            else:
                run_info = start_xcpd_run(config, "ec", selected_subjects or None, sessions or None)
            st.success(f"Started EC XCP-D (pid={run_info['pid']})")
            st.rerun()
        if ec_info.get("status") == "running":
            if st.button("Stop EC XCP-D", use_container_width=True):
                stop_xcpd_run(config, "ec", state)
                st.rerun()
        if ec_info.get("log_file"):
            st.caption(ec_info["log_file"])


def render_post_xcpd_qc(config: Dict, state: Dict) -> None:
    paths = config["paths"]
    fc_qc = collect_qc_reports(Path(paths["xcpd_fc_dir"]))
    ec_qc = collect_qc_reports(Path(paths["xcpd_ec_dir"]))

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("FC Pipeline QC")
        st.write(qc_report_summary(fc_qc))
        render_exec_reports(fc_qc["exec_reports"])
    with col2:
        st.subheader("EC Pipeline QC")
        st.write(qc_report_summary(ec_qc))
        exclusions = build_ec_exclusion_table(config)
        if exclusions is not None:
            st.dataframe(exclusions, use_container_width=True, hide_index=True)
            exclusions.to_csv(Path(paths["xcpd_ec_qc_dir"]) / "ec_exclusions.csv", index=False)

    qcfc_value = compute_qc_fc_summary(config)
    if qcfc_value is not None:
        st.metric("Mean |QC-FC|", f"{qcfc_value:.4f}")
        if qcfc_value > 0.2:
            st.warning("QC-FC exceeds 0.2 and should be reviewed carefully.")

    ready_for_qc_gate = bool(fc_qc["qc_csv"] or fc_qc["exec_reports"]) and bool(
        ec_qc["qc_csv"] or ec_qc["timeseries"]
    )
    if ready_for_qc_gate:
        if st.button("Approve and Proceed", type="primary"):
            state = set_step_status(config, "post_xcpd_qc", "completed", "QC reviewed", state=state)
            state = set_approval(config, "qc_gate", True, state=state)
            append_pipeline_log(config, "Approved post-XCP-D QC", state=state)
            st.success("QC approved. Subject/group analysis stages are now unlocked.")
            st.rerun()
    else:
        st.info("Run FC and EC XCP-D first to populate QC artifacts.")


def qc_report_summary(qc_reports: Dict[str, List[Path]]) -> Dict[str, int]:
    return {key: len(value) for key, value in qc_reports.items()}


def render_exec_reports(exec_reports: List[Path]) -> None:
    if not exec_reports:
        st.caption("No HTML reports found yet.")
        return
    for report in exec_reports[:10]:
        st.markdown(f"- [{report.name}]({report.as_uri()})")


def build_ec_exclusion_table(config: Dict) -> pd.DataFrame | None:
    summary_path = Path(config["paths"]["fd_inspection_dir"]) / "fd_summary.csv"
    if not summary_path.exists():
        return None
    summary = pd.read_csv(summary_path)
    threshold = float(config["subject_exclusion"]["mean_fd_threshold"])
    table = summary[["subject_id", "session", "mean_fd", "peak_fd"]].copy()
    table["included"] = table["mean_fd"] <= threshold
    table["exclusion_reason"] = table["included"].map(
        lambda included: "" if included else f"mean FD > {threshold:.2f}"
    )
    return table


def compute_qc_fc_summary(config: Dict) -> float | None:
    summary_path = Path(config["paths"]["fd_inspection_dir"]) / "fd_summary.csv"
    connectome_paths = sorted(Path(config["paths"]["xcpd_fc_dir"]).glob("**/*connectome*.tsv"))
    if not summary_path.exists() or not connectome_paths:
        return None

    summary = pd.read_csv(summary_path).set_index(["subject_id", "session"])
    fd_values = []
    edge_means = []
    for connectome_path in connectome_paths:
        try:
            parts = connectome_path.parts
            subject = next(part for part in parts if part.startswith("sub-"))
            session = next(part for part in parts if part.startswith("ses-"))
            if (subject, session) not in summary.index:
                continue
            matrix = load_connectome_table(connectome_path)
            values = matrix.to_numpy(dtype=float)
            if values.shape[0] == values.shape[1] and values.shape[0] > 1:
                values = values[~np.eye(values.shape[0], dtype=bool)]
            fd_values.append(float(summary.loc[(subject, session), "mean_fd"]))
            edge_means.append(float(np.nanmean(np.abs(values))))
        except Exception:
            continue

    if len(fd_values) < 3:
        return None
    return float(abs(pd.Series(fd_values).corr(pd.Series(edge_means))))


def render_logs(config: Dict, state: Dict) -> None:
    log_rows = pd.DataFrame(state.get("log", []))
    if log_rows.empty:
        st.caption("No pipeline log entries yet.")
    else:
        st.dataframe(log_rows, use_container_width=True, hide_index=True)

    for run_key in ("xcpd_fc", "xcpd_ec"):
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
