"""
Gated XCP-D pipeline page for FD inspection, execution, and QC review.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Dict, List

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.config import save_config
from utils.fd_inspection import build_fd_summary, generate_fd_plots, highlight_fd_rows
from utils.hpc import HPCConfig, HPCConnection
from utils.pipeline_state import (
    STEP_ORDER,
    append_pipeline_log,
    load_pipeline_state,
    save_pipeline_state,
    set_approval,
    set_step_status,
)
from utils.xcpd import (
    build_xcpd_command,
    check_fmriprep_on_hpc,
    cleanup_xcpd_hpc_files,
    download_xcpd_outputs_from_hpc,
    fetch_hpc_xcpd_log,
    generate_xcpd_slurm_script,
    parse_xcpd_progress,
    refresh_xcpd_run,
    start_remote_xcpd_run,
    start_xcpd_chain,
    start_xcpd_run,
    stop_xcpd_run,
    sync_fmriprep_to_hpc,
)
from utils.xcpd_atlases import (
    atlas_option_ids,
    all_builtin_atlas_ids,
    build_xcpd_atlas_status_rows,
    format_xcpd_atlas_label,
    missing_xcpd_atlas_resources,
    normalize_xcpd_atlas_selection,
    recommended_xcpd_atlases,
)
from utils.xcpd_qc import render_xcpd_qc_reports, get_xcpd_subject_status


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
        "queued": "🕐",
        "running": "🟡",
        "completed": "🟢",
        "failed": "🔴",
        "cancelled": "⛔",
        "stopped": "🔴",
        "awaiting_approval": "🟠",
    }
    step_labels = {
        "fmriprep": "fMRIPrep",
        "fd_inspection": "FD Inspection",
        "fd_gate": "FD Gate",
        "xcpd_fc": "XCP-D FC",
        "xcpd_fc_gsr": "XCP-D FC+GSR",
        "xcpd_ec": "XCP-D EC",
        "post_xcpd_qc": "Post-QC",
        "qc_gate": "QC Gate",
        "subject_level": "Subject",
        "group_level": "Group",
    }
    st.subheader("fMRI Pipeline Status")
    cols = st.columns(len(STEP_ORDER))
    for col, step in zip(cols, STEP_ORDER):
        info = state["steps"].get(step, {})
        status = info.get("status", "not_started")
        label = step_labels.get(step, step.replace("_", " ").title())
        col.metric(label, status_colors.get(status, "⚪"))
        col.caption(status)


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


def _has_complete_fmriprep(fmriprep_dir: Path, subject: str) -> bool:
    """Check that the fMRIPrep output for a subject is complete enough for XCP-D.

    XCP-D (NIfTI mode) requires a MNI152NLin6Asym brain mask in the top-level
    anat/ directory.  Subjects that only have partial fMRIPrep outputs (e.g. the
    HTML report was generated but MNI normalisation failed) must be excluded.
    """
    mask_pattern = f"{subject}_space-MNI152NLin6Asym_*_desc-brain_mask.nii.gz"
    return any((fmriprep_dir / subject / "anat").glob(mask_pattern))


def _has_sufficient_low_motion_data(
    fmriprep_dir: Path, subject: str, fd_threshold: float, min_seconds: float = 100.0, tr: float = 0.8
) -> bool:
    """Return True if at least one session has enough low-motion volumes.

    XCP-D will abort the entire workflow (RuntimeError) when no runs survive
    scrubbing for a subject.  This pre-check mirrors XCP-D's criterion so we
    can exclude such subjects before submission.
    """
    import pandas as pd  # local import to avoid slow startup

    sub_dir = fmriprep_dir / subject
    found_any = False
    for tsv in sub_dir.glob("ses-*/func/*desc-confounds_timeseries.tsv"):
        found_any = True
        try:
            df = pd.read_csv(tsv, sep="\t")
            fd = df.get("framewise_displacement", pd.Series(dtype=float)).dropna()
            remaining_sec = (fd <= fd_threshold).sum() * tr
            if remaining_sec >= min_seconds:
                return True
        except Exception:
            continue
    # If no confound files were found locally, assume the subject is fine
    # (data may only exist on HPC).
    return not found_any


def _get_incomplete_xcpd_subjects(config: Dict, pipeline: str) -> List[str]:
    """Return subjects that have fMRIPrep output but have not completed the given XCP-D pipeline."""
    dir_key = f"xcpd_{pipeline}_dir"
    out_dir = Path(config["paths"].get(dir_key, ""))
    # Only consider subjects that have a complete fMRIPrep output (HTML report +
    # required MNI152NLin6Asym anat mask for XCP-D NIfTI mode).
    fmriprep_dir = Path(config["paths"].get("fmriprep_dir", ""))
    all_bids = available_subjects(Path(config["paths"]["bids_dir"]))

    # Determine FD threshold and min_time for this pipeline
    pipeline_cfg = config.get("xcpd", {}).get(pipeline, {})
    fd_threshold = float(pipeline_cfg.get("fd_thresh", 0.5))
    min_seconds = float(pipeline_cfg.get("min_time", 240.0))

    if fmriprep_dir.exists():
        fmriprep_subjects = {p.stem for p in fmriprep_dir.glob("sub-*.html")}
        subjects = [
            s for s in all_bids
            if s in fmriprep_subjects
            and _has_complete_fmriprep(fmriprep_dir, s)
            and _has_sufficient_low_motion_data(fmriprep_dir, s, fd_threshold, min_seconds)
        ]
    else:
        subjects = all_bids
    if not out_dir.exists():
        return subjects
    df = get_xcpd_subject_status(out_dir, subjects)
    return df[~df["status"].str.startswith("✅")]["subject"].tolist()


def render_xcpd_runs(config: Dict, state: Dict) -> None:
    if not state["approvals"].get("fd_gate", {}).get("approved"):
        st.warning("Approve the FD thresholds first.")
        state = set_step_status(config, "fd_gate", "awaiting_approval", "Waiting for researcher approval", state=state)
        return

    subjects = available_subjects(Path(config["paths"]["bids_dir"]))

    # Initialise the multiselect state on first load
    if "xcpd_selected_subjects" not in st.session_state:
        st.session_state["xcpd_selected_subjects"] = subjects[: min(8, len(subjects))]

    # Auto-select buttons — each sets session_state then reruns so the multiselect updates
    auto_cols = st.columns(4)
    with auto_cols[0]:
        if st.button("🎯 FC incomplete", help="Select subjects that have not completed the FC (no-GSR) pipeline"):
            st.session_state["xcpd_selected_subjects"] = _get_incomplete_xcpd_subjects(config, "fc")
            st.rerun()
    with auto_cols[1]:
        if st.button("🎯 FC+GSR incomplete", help="Select subjects that have not completed the FC+GSR pipeline"):
            st.session_state["xcpd_selected_subjects"] = _get_incomplete_xcpd_subjects(config, "fc_gsr")
            st.rerun()
    with auto_cols[2]:
        if st.button("🎯 EC incomplete", help="Select subjects that have not completed the EC pipeline"):
            st.session_state["xcpd_selected_subjects"] = _get_incomplete_xcpd_subjects(config, "ec")
            st.rerun()
    with auto_cols[3]:
        if st.button("↩ Reset", help="Reset subject selection to the first 8 subjects"):
            st.session_state["xcpd_selected_subjects"] = subjects[: min(8, len(subjects))]
            st.rerun()

    selected_subjects = st.multiselect(
        "Participant labels",
        options=subjects,
        key="xcpd_selected_subjects",
        help=(
            "Subjects to include in this XCP-D run, sourced from the local BIDS directory. "
            "Leave empty to run all available subjects. "
            "New subjects appear here automatically after adding them to the BIDS folder. "
            "Use the 🎯 buttons above to auto-select subjects that are incomplete for a given pipeline."
        ),
    )
    sessions = st.multiselect(
        "Sessions",
        options=["ses-01", "ses-02"],
        default=["ses-01", "ses-02"],
        help="Select which sessions to process. Both sessions are selected by default.",
    )
    run_on_hpc = st.checkbox(
        "Run on HPC",
        value=bool(config.get("hpc", {}).get("enabled", False)),
        help="Submit the XCP-D job to the configured HPC cluster via SSH instead of running locally.",
    )

    # --- SLURM Resources (shared across pipelines) ---
    hpc_cfg_dict = config.get("hpc", {}).get("slurm", {})
    xcpd_max_cpus = int(hpc_cfg_dict.get("xcpd_max_cpus", 15))
    with st.expander("⚙️ SLURM Resources", expanded=False):
        st.caption("Controls the parallelism and scheduling of the XCP-D workflow. Applies to all three pipelines.")
        res_col1, res_col2 = st.columns(2)
        with res_col1:
            nprocs = st.slider(
                "nprocs",
                min_value=1, max_value=xcpd_max_cpus,
                value=int(config.get("xcpd", {}).get("fc", {}).get("nprocs", 8)),
                help=(
                    "Number of parallel Nipype processes per XCP-D job. "
                    "Higher values speed up the workflow but consume more CPU on the compute node."
                ),
            )
        with res_col2:
            omp_nthreads = st.slider(
                "omp_nthreads",
                min_value=1, max_value=4,
                value=int(config.get("xcpd", {}).get("fc", {}).get("omp_nthreads", 1)),
                help=(
                    "OpenMP threads per process. "
                    "Total CPUs = nprocs × omp_nthreads. "
                    "Leave at 1 unless your compute node has many cores."
                ),
            )
        total_cpus = nprocs * omp_nthreads
        st.caption(f"Total CPUs requested per SLURM job: **{total_cpus}**")
        if total_cpus > xcpd_max_cpus:
            st.warning(
                f"⚠️ {total_cpus} CPUs exceeds the recommended maximum of {xcpd_max_cpus}. "
                "Check your cluster QOS limits before submitting."
            )

        st.divider()

        max_concurrent = st.slider(
            "Max concurrent jobs",
            min_value=1,
            max_value=16,
            value=int(hpc_cfg_dict.get("max_concurrent_jobs", 4)),
            key="xcpd_max_concurrent",
            help=(
                "Maximum number of SLURM array tasks running simultaneously "
                "(generates #SBATCH --array=1-N%K). "
                "Reduce this if the cluster has tight QOS limits."
            ),
        )

        st.markdown("**Partition**")
        _available_parts = st.session_state.get("xcpd_available_partitions", [])
        _config_partition = config.get("hpc", {}).get("slurm", {}).get("partition", "shared_cpu")
        part_col, btn_col = st.columns([3, 1])
        with btn_col:
            if st.button("Fetch", key="xcpd_fetch_partitions", help="Query HPC via SSH to get available partitions"):
                try:
                    with st.spinner("Connecting to HPC…"):
                        _hpc_cfg_obj = HPCConfig.from_config(config)
                        _conn = HPCConnection(_hpc_cfg_obj)
                        _conn.connect()
                        _stdout, _stderr, _code = _conn.execute(
                            "sinfo -h -o '%P %a %D %C' | tr -d '*'", timeout=20
                        )
                        _conn.disconnect()
                    if _code == 0 and _stdout.strip():
                        _parsed = [ln.split()[0] for ln in _stdout.strip().splitlines() if ln.strip()]
                        st.session_state["xcpd_available_partitions"] = _parsed
                        _available_parts = _parsed
                        st.success(f"Found {len(_parsed)} partitions")
                    else:
                        st.error(f"sinfo failed: {_stderr.strip() or 'unknown error'}")
                except Exception as _e:
                    st.error(f"Could not fetch partitions: {_e}")
        with part_col:
            if _available_parts:
                _opts = _available_parts if _config_partition in _available_parts else [_config_partition] + _available_parts
                partition = st.selectbox(
                    "Partition",
                    options=_opts,
                    index=_opts.index(_config_partition) if _config_partition in _opts else 0,
                    key="xcpd_partition",
                    help="SLURM partition name for the XCP-D array jobs.",
                )
            else:
                partition = st.selectbox(
                    "Partition",
                    options=[_config_partition],
                    key="xcpd_partition",
                    help="SLURM partition name. Click 'Fetch' to load available partitions from HPC.",
                )

    if run_on_hpc:
        with st.expander("📤 Upload fMRIPrep to HPC", expanded=False):
            st.caption(
                "If fMRIPrep derivatives have been removed from the HPC, "
                "upload them from your local machine before starting XCP-D."
            )
            if st.button("Upload fMRIPrep derivatives", key="upload_fmriprep_global", width="stretch"):
                try:
                    with st.spinner("Uploading fMRIPrep derivatives to HPC…"):
                        remote_dir = sync_fmriprep_to_hpc(
                            config,
                            selected_subjects or None,
                            sessions or None,
                        )
                    st.success(f"fMRIPrep uploaded to `{remote_dir}`.")
                except Exception as upload_err:
                    st.error(f"Upload failed: {upload_err}")

    fc_defaults = normalize_xcpd_atlas_selection(config["xcpd"]["fc"].get("atlases", [])) or recommended_xcpd_atlases()
    fc_gsr_defaults = normalize_xcpd_atlas_selection(config["xcpd"].get("fc_gsr", {}).get("atlases", [])) or recommended_xcpd_atlases()
    ec_defaults = normalize_xcpd_atlas_selection(config["xcpd"]["ec"].get("atlases", [])) or recommended_xcpd_atlases()
    atlas_options = atlas_option_ids(config, list(fc_defaults) + list(fc_gsr_defaults) + list(ec_defaults))

    st.markdown("### Atlas Selection")
    st.caption(
        "📦 = XCP-D built-in atlas (no local files needed) · "
        "🔧 = Project-local custom atlas (requires atlas files on disk)"
    )
    atlas_col1, atlas_col2, atlas_col3 = st.columns(3)
    with atlas_col1:
        selected_fc_atlases = st.multiselect(
            "FC atlases",
            options=atlas_options,
            default=[a for a in fc_defaults if a in atlas_options],
            format_func=lambda atlas_id: format_xcpd_atlas_label(config, atlas_id),
            key="xcpd_fc_run_atlases",
            help=(
                "Atlases for the FC (no-GSR) pipeline. "
                "Built-in 4S atlases combine Schaefer cortical + subcortical parcels. "
                "E.g. 4S256Parcels = Schaefer 200 cortical + 56 subcortical."
            ),
        )
    with atlas_col2:
        selected_fc_gsr_atlases = st.multiselect(
            "FC+GSR atlases",
            options=atlas_options,
            default=[a for a in fc_gsr_defaults if a in atlas_options],
            format_func=lambda atlas_id: format_xcpd_atlas_label(config, atlas_id),
            key="xcpd_fc_gsr_run_atlases",
            help=(
                "Atlases for the FC + GSR comparison pipeline. "
                "Typically the same set as FC for direct comparison."
            ),
        )
    with atlas_col3:
        selected_ec_atlases = st.multiselect(
            "EC atlases",
            options=atlas_options,
            default=[a for a in ec_defaults if a in atlas_options],
            format_func=lambda atlas_id: format_xcpd_atlas_label(config, atlas_id),
            key="xcpd_ec_run_atlases",
            help=(
                "Atlases for the effective connectivity pipeline. "
                "Typically the same set as FC."
            ),
        )

    all_selected_atlases = list(selected_fc_atlases) + list(selected_fc_gsr_atlases) + list(selected_ec_atlases)

    # Atlas reference table
    from utils.xcpd_atlases import get_xcpd_atlas_catalog
    full_catalog = get_xcpd_atlas_catalog(config)
    with st.expander("ℹ️ Atlas reference", expanded=False):
        atlas_table_rows = []
        for aid, spec in full_catalog.items():
            atlas_table_rows.append({
                "Type": "📦 Built-in" if spec.source_type == "builtin" else "🔧 Custom",
                "ID": aid,
                "Label": spec.label,
                "Description": spec.description,
            })
        st.dataframe(atlas_table_rows, width="stretch", hide_index=True)

    atlas_rows = build_xcpd_atlas_status_rows(config, all_selected_atlases)
    if atlas_rows:
        with st.expander("Atlas availability", expanded=False):
            st.dataframe(atlas_rows, width="stretch", hide_index=True)

    fc_info = state.get("runs", {}).get("xcpd_fc", {})
    fc_gsr_info = state.get("runs", {}).get("xcpd_fc_gsr", {})
    ec_info = state.get("runs", {}).get("xcpd_ec", {})

    # --- Master "Submit all incomplete" chain button ---
    if run_on_hpc:
        any_active = any(
            info.get("status") in ("running", "queued")
            for info in (fc_info, fc_gsr_info, ec_info)
        )
        chain_help = (
            "Submit FC → FC+GSR → EC as a SLURM dependency chain for subjects that are "
            "incomplete in *any* of the three pipelines. Each pipeline starts automatically "
            "after the previous one succeeds."
            if not any_active
            else "Cannot submit — one or more pipelines are currently running or queued."
        )
        if st.button(
            "🚀 Submit all incomplete (FC → FC+GSR → EC chain)",
            disabled=any_active,
            help=chain_help,
            key="submit_xcpd_chain_btn",
        ):
            # Union of subjects incomplete in any pipeline
            incomplete: set = set()
            for pipeline in ("fc", "fc_gsr", "ec"):
                incomplete |= set(_get_incomplete_xcpd_subjects(config, pipeline))
            if not incomplete:
                st.info("All subjects are complete across all pipelines — nothing to submit.")
            else:
                labels = sorted(incomplete)
                st.info(f"Submitting chain for {len(labels)} subjects: {', '.join(labels)}")
                try:
                    with st.spinner("Submitting SLURM chain (FC → FC+GSR → EC)…"):
                        chain_result = start_xcpd_chain(
                            config,
                            participant_labels=labels,
                            session_ids=sessions or None,
                            nprocs=nprocs,
                            omp_nthreads=omp_nthreads,
                            max_concurrent=max_concurrent,
                            partition=partition,
                        )
                    job_ids = {p: info["job_id"] for p, info in chain_result.items()}
                    st.success(
                        f"✅ SLURM chain submitted — "
                        f"FC: {job_ids.get('fc')} → "
                        f"FC+GSR: {job_ids.get('fc_gsr')} (dep) → "
                        f"EC: {job_ids.get('ec')} (dep)"
                    )
                    st.rerun()
                except Exception as chain_err:
                    st.error(f"Chain submission failed: {chain_err}")

    # --- Remove all preprocessed XCP-D outputs ---
    st.markdown("---")
    remove_col1, remove_col2 = st.columns([3, 1])
    with remove_col1:
        st.caption(
            "⚠️ Remove **all** XCP-D preprocessed outputs (local and optionally HPC). "
            "Pipeline state will be reset to `not_started`."
        )
    with remove_col2:
        confirm_key = "confirm_remove_xcpd_outputs"
        st.session_state.setdefault(confirm_key, False)
        if not st.session_state[confirm_key]:
            if st.button("🗑️ Remove all XCP-D outputs", key="remove_xcpd_btn", type="secondary"):
                st.session_state[confirm_key] = True
                st.rerun()
        else:
            st.warning("Are you sure? This will delete all local XCP-D outputs.")
            also_hpc = st.checkbox(
                "Also remove HPC files (work dirs, SLURM scripts, logs)",
                value=False, key="remove_xcpd_also_hpc",
                help="Connects to HPC and removes remote work directories and scripts for all 3 pipelines.",
            )
            yes_col, no_col = st.columns(2)
            with yes_col:
                if st.button("✅ Yes, delete", key="confirm_remove_xcpd_yes", type="primary"):
                    import shutil
                    # HPC cleanup first (needs run_info still in state)
                    hpc_errors = []
                    if also_hpc:
                        for pname in ("fc", "fc_gsr", "ec"):
                            try:
                                cleanup_xcpd_hpc_files(config, pname)
                            except Exception as hpc_err:
                                hpc_errors.append(f"{pname}: {hpc_err}")
                    # Remove local dirs
                    paths = config.get("paths", {})
                    removed_dirs = []
                    for dir_key in ("xcpd_fc_dir", "xcpd_fc_gsr_dir", "xcpd_ec_dir"):
                        d = paths.get(dir_key, "")
                        if d and os.path.isdir(d):
                            shutil.rmtree(d)
                            removed_dirs.append(dir_key)
                    # Reset pipeline state
                    for step_key in ("xcpd_fc", "xcpd_fc_gsr", "xcpd_ec", "post_xcpd_qc", "qc_gate"):
                        state = set_step_status(config, step_key, "not_started", "", state=state)
                    # Clear run info
                    runs = state.get("runs", {})
                    for run_key in ("xcpd_fc", "xcpd_fc_gsr", "xcpd_ec"):
                        runs.pop(run_key, None)
                    save_pipeline_state(config, state)
                    st.session_state[confirm_key] = False
                    msg = f"Removed local XCP-D outputs: {', '.join(removed_dirs) or 'none found'}. Pipeline state reset."
                    if also_hpc and not hpc_errors:
                        msg += " HPC files removed."
                    if hpc_errors:
                        msg += f" HPC errors: {'; '.join(hpc_errors)}"
                    st.success(msg)
                    st.rerun()
            with no_col:
                if st.button("❌ Cancel", key="confirm_remove_xcpd_no"):
                    st.session_state[confirm_key] = False
                    st.rerun()

    col1, col2, col3 = st.columns(3)
    with col1:
        _render_pipeline_panel(
            config, state, "fc", "FC (no GSR)", selected_fc_atlases,
            fc_info, run_on_hpc, selected_subjects, sessions,
            extra_note="aCompCor nuisance regression without global signal removal. Primary FC pipeline.",
            nprocs=nprocs, omp_nthreads=omp_nthreads,
            max_concurrent=max_concurrent, partition=partition,
        )
    with col2:
        _render_pipeline_panel(
            config, state, "fc_gsr", "FC + GSR", selected_fc_gsr_atlases,
            fc_gsr_info, run_on_hpc, selected_subjects, sessions,
            extra_note="36P regressors including global signal regression. Run alongside FC to compare.",
            nprocs=nprocs, omp_nthreads=omp_nthreads,
            max_concurrent=max_concurrent, partition=partition,
        )
    with col3:
        _render_pipeline_panel(
            config, state, "ec", "Effective Connectivity", selected_ec_atlases,
            ec_info, run_on_hpc, selected_subjects, sessions,
            extra_note="Censored timeseries; no smoothing; wider bandpass (0.008–0.09 Hz). For effective connectivity estimation.",
            nprocs=nprocs, omp_nthreads=omp_nthreads,
            max_concurrent=max_concurrent, partition=partition,
        )

    # --- Per-subject completion status ---
    st.markdown("---")
    with st.expander("📋 Subject Completion Status", expanded=False):
        st.caption(
            "Scans the local XCP-D output directories for each pipeline. "
            "Status is read from a `status` sentinel file written when the run finishes, "
            "or detected from the presence of XCP-D HTML output reports."
        )
        refresh_col, _ = st.columns([1, 3])
        with refresh_col:
            rescan = st.button("🔄 Rescan", key="rescan_subject_status", help="Re-read the output directories from disk")

        bids_subjects = available_subjects(Path(config["paths"]["bids_dir"]))
        tab_fc_s, tab_gsr_s, tab_ec_s = st.tabs(["FC", "FC+GSR", "EC"])
        for tab, pname, dir_key in [
            (tab_fc_s, "fc", "xcpd_fc_dir"),
            (tab_gsr_s, "fc_gsr", "xcpd_fc_gsr_dir"),
            (tab_ec_s, "ec", "xcpd_ec_dir"),
        ]:
            with tab:
                out_dir = Path(config["paths"].get(dir_key, ""))
                if not out_dir.exists():
                    st.info(f"Output directory not found: `{out_dir}`")
                else:
                    df = get_xcpd_subject_status(out_dir, bids_subjects)
                    n_done = (df["status"].str.startswith("✅")).sum()
                    st.caption(f"**{n_done}/{len(df)}** subjects completed — `{out_dir}`")
                    st.dataframe(df, width="stretch", hide_index=True)


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
    nprocs: int = 8,
    omp_nthreads: int = 1,
    max_concurrent: int = 4,
    partition: str = "shared_cpu",
) -> None:
    """Render the run/status panel for a single XCP-D pipeline."""
    step_key = f"xcpd_{pipeline_name}"
    st.subheader(label)
    st.caption(f"mode: `{config['xcpd'].get(pipeline_name, {}).get('mode', 'linc')}`")
    st.code(" ".join(selected_atlases) if selected_atlases else "(no atlases)", language="text")
    if extra_note:
        st.info(extra_note)

    step_status = state["steps"].get(step_key, {}).get("status", "not_started")
    current_status = run_info.get("status", step_status)
    st.caption(f"Status: {current_status}")
    if run_info.get("job_id"):
        st.caption(f"SLURM job ID: {run_info['job_id']}")
    elif run_info.get("pid"):
        st.caption(f"PID: {run_info['pid']}")
    if run_info.get("remote_log_out"):
        st.caption(f"Remote log: {run_info['remote_log_out']}")

    # Show last-submitted script (separate from live preview below)
    if run_info.get("local_script") and Path(run_info["local_script"]).exists():
        with st.expander("📂 Last submitted script (read-only)", expanded=False):
            st.code(Path(run_info["local_script"]).read_text(), language="bash")

    is_running = current_status in ("running", "queued")

    # --- Queued state: show cancel button ---
    if current_status == "queued":
        slurm_reason = run_info.get("slurm_reason", "")
        reason_note = f" — {slurm_reason}" if slurm_reason and slurm_reason.upper() not in ("NONE", "") else ""
        st.info(f"⏳ Queued — SLURM job {run_info.get('job_id')}{reason_note}")
        if st.button(f"🚫 Cancel queued job", key=f"cancel_{pipeline_name}", width="stretch"):
            state = stop_xcpd_run(config, pipeline_name, state)
            st.rerun()

    if not is_running:
        # Safety: warn when re-running a completed pipeline
        already_completed = step_status == "completed"
        qc_approved = state.get("approvals", {}).get("qc_gate", {}).get("approved", False)
        if already_completed:
            if qc_approved:
                st.warning(
                    f"⚠️ {label} outputs already exist and the QC gate has been approved. "
                    "Re-running will invalidate the QC approval — you must re-review QC afterwards."
                )
            else:
                st.info(f"ℹ️ {label} outputs already exist. Re-running will overwrite them.")

        confirm_key = f"confirm_rerun_{pipeline_name}"
        btn_label = f"↺ Re-run {label} XCP-D" if already_completed else f"▶ Start {label} XCP-D"
        btn_help = (
            f"Re-run the {label} pipeline from scratch, overwriting existing outputs."
            if already_completed
            else f"Launch the {label} XCP-D denoising pipeline for the selected subjects and sessions."
        )
        btn_type = "secondary" if already_completed else "primary"
        if st.button(btn_label, key=f"start_{pipeline_name}", width="stretch", type=btn_type, help=btn_help):
            missing = missing_xcpd_atlas_resources(config, selected_atlases)
            if missing:
                st.error("Missing atlas resources: " + ", ".join(str(p) for p in missing))
            else:
                try:
                    config["xcpd"][pipeline_name]["atlases"] = normalize_xcpd_atlas_selection(selected_atlases)
                    config["xcpd"][pipeline_name]["nprocs"] = nprocs
                    config["xcpd"][pipeline_name]["omp_nthreads"] = omp_nthreads
                    save_runtime_config(config)
                    if run_on_hpc:
                        info = start_remote_xcpd_run(
                            config, pipeline_name,
                            selected_subjects or None, sessions or None,
                            max_concurrent=max_concurrent, partition=partition,
                        )
                    else:
                        info = start_xcpd_run(config, pipeline_name, selected_subjects or None, sessions or None)
                    # Invalidate QC gate when re-running a completed pipeline
                    if already_completed and qc_approved:
                        from utils.pipeline_state import set_approval
                        _state = load_pipeline_state(config)
                        _state = set_approval(config, "qc_gate", False, state=_state)
                        _state = set_step_status(config, "qc_gate", "not_started", "Invalidated by re-run", state=_state)
                        _state = set_step_status(config, "post_xcpd_qc", "not_started", "", state=_state)
                        save_pipeline_state(config, _state)
                    job_label = f"job {info.get('job_id', info.get('pid', '?'))}"
                    st.success(f"Started {label} XCP-D ({job_label})")
                    st.rerun()
                except RuntimeError as e:
                    err_msg = str(e)
                    if "no remote fMRIPrep directory" in err_msg and run_on_hpc:
                        st.error(f"Failed to start {label} XCP-D: {err_msg}")
                        st.warning(
                            "fMRIPrep derivatives are not present on the HPC. "
                            "Use the button below to upload your local fMRIPrep outputs first."
                        )
                        if st.button(
                            f"📤 Upload fMRIPrep to HPC",
                            key=f"upload_fmriprep_{pipeline_name}",
                            width="stretch",
                        ):
                            try:
                                with st.spinner("Uploading fMRIPrep derivatives to HPC…"):
                                    remote_dir = sync_fmriprep_to_hpc(
                                        config,
                                        selected_subjects or None,
                                        sessions or None,
                                    )
                                st.success(f"fMRIPrep uploaded to {remote_dir}. Try starting XCP-D again.")
                                st.rerun()
                            except Exception as upload_err:
                                st.error(f"Upload failed: {upload_err}")
                    else:
                        st.error(f"Failed to start {label} XCP-D: {e}")
                except Exception as e:
                    st.error(f"Failed to start {label} XCP-D: {e}")

    if current_status == "running":
        if st.button(f"Stop {label} XCP-D", key=f"stop_{pipeline_name}", width="stretch"):
            stop_xcpd_run(config, pipeline_name, state)
            st.rerun()

    # --- Live monitoring (shown when running or recently completed/failed) ---
    if current_status in ("running", "completed", "failed"):
        log_file = run_info.get("log_file")
        stored_total = run_info.get("nodes_total")
        n_tasks = len(run_info.get("participant_labels") or []) or None
        progress = parse_xcpd_progress(
            Path(log_file) if log_file else None,
            stored_total=stored_total,
            n_expected_tasks=n_tasks,
        )

        # Persist nodes_total back into run_info so we don't lose it on log refetch
        if progress["nodes_total"] and not stored_total:
            run_info["nodes_total"] = progress["nodes_total"]
            from utils.pipeline_state import set_run_info as _set_run_info
            _set_run_info(config, f"xcpd_{pipeline_name}", run_info)

        # HPC log fetch — shown prominently when running so user knows to refresh
        is_hpc = run_info.get("backend") == "hpc"
        if is_hpc and run_info.get("remote_log_out"):
            log_is_empty = not log_file or not Path(log_file).exists() or Path(log_file).stat().st_size == 0 if log_file else True
            if log_is_empty and current_status == "running":
                st.info("ℹ️ HPC log is stored remotely — click **Fetch HPC log** to see latest progress.")
            fetch_col, refresh_col = st.columns(2)
            with fetch_col:
                if st.button("📥 Fetch HPC log", key=f"fetch_log_{pipeline_name}"):
                    with st.spinner("Fetching remote log…"):
                        fetched = fetch_hpc_xcpd_log(config, run_info)
                    if fetched:
                        st.success(f"Log saved to {fetched.name}")
                    else:
                        st.warning("Could not fetch remote log.")
                    st.rerun()
            with refresh_col:
                if st.button("🔄 Refresh status", key=f"refresh_{pipeline_name}"):
                    # Auto-fetch log then refresh for HPC runs
                    if is_hpc and run_info.get("remote_log_out"):
                        fetch_hpc_xcpd_log(config, run_info)
                    st.rerun()
        else:
            if st.button("🔄 Refresh status", key=f"refresh_{pipeline_name}"):
                st.rerun()

        if progress["nodes_total"]:
            pct = min(progress["nodes_done"] / progress["nodes_total"], 1.0)
            n_subjects = len(run_info.get("participant_labels") or [])
            if n_subjects > 0:
                nodes_per_subject = progress["nodes_total"] / n_subjects
                est_done = min(int(progress["nodes_done"] / nodes_per_subject), n_subjects)
                progress_text = (
                    f"~{est_done}/{n_subjects} subjects completed "
                    f"({progress['nodes_done']}/{progress['nodes_total']} processing steps)"
                )
            else:
                progress_text = f"{progress['nodes_done']}/{progress['nodes_total']} processing steps"
            st.progress(
                pct,
                text=progress_text,
            )
        elif current_status == "running":
            st.progress(0.0, text="Waiting for workflow to initialise…")

        if progress["current_node"] and current_status == "running":
            st.caption(f"▶ `{progress['current_node']}`")

        if progress["has_error"]:
            st.error("⚠ Error detected in log")
        elif progress["is_done"]:
            st.success("✅ Workflow finished successfully")

        with st.expander("📋 Log tail", expanded=False):
            tail = "\n".join(progress["last_lines"][-25:]) if progress["last_lines"] else "(no log content)"
            st.code(tail, language="text")

        # Download outputs from HPC when job completed
        if is_hpc and current_status == "completed":
            with st.expander("📥 Download XCP-D outputs from HPC", expanded=False):
                st.caption("Rsync XCP-D outputs from HPC to local machine.")
                dl_subjects = run_info.get("participant_labels") or []
                dl_col, cleanup_col = st.columns(2)
                with dl_col:
                    if st.button(
                        f"⬇️ Download {label} outputs",
                        key=f"download_{pipeline_name}",
                    ):
                        with st.spinner("Downloading XCP-D outputs from HPC (this may take a while)…"):
                            try:
                                local_dir = download_xcpd_outputs_from_hpc(
                                    config, pipeline_name, dl_subjects or None
                                )
                                st.success(f"Downloaded to `{local_dir}`")
                            except Exception as dl_err:
                                st.error("Download failed")
                                st.code(str(dl_err), language="text")
                with cleanup_col:
                    if st.button(
                        "🗑️ Clean up HPC files",
                        key=f"cleanup_hpc_{pipeline_name}",
                        help="Remove the XCP-D work directory and SLURM logs from the HPC after a successful download.",
                    ):
                        with st.spinner("Removing HPC files…"):
                            try:
                                cleanup_xcpd_hpc_files(config, pipeline_name)
                                st.success("HPC files removed.")
                            except Exception as cl_err:
                                st.error(f"Cleanup failed: {cl_err}")

    if run_info.get("log_file"):
        st.caption(run_info["log_file"])

    # Script preview — always shown so user can verify what will be submitted
    expander_label = "🔍 Preview script with current settings" if run_on_hpc else "🔍 Preview command (current settings)"
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
