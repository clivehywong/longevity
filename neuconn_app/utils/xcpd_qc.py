"""
Shared XCP-D QC rendering helpers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import streamlit as st

from utils.pipeline_state import append_pipeline_log, set_approval, set_step_status
from utils.subject_level_fc import load_connectome_table
from utils.xcpd import collect_qc_reports, download_xcpd_outputs_from_hpc


def ensure_xcpd_qc_dirs(config: Dict) -> Dict[str, Path]:
    fc_dir = Path(config["paths"]["xcpd_fc_qc_dir"])
    ec_dir = Path(config["paths"]["xcpd_ec_qc_dir"])
    fc_dir.mkdir(parents=True, exist_ok=True)
    ec_dir.mkdir(parents=True, exist_ok=True)
    return {"fc": fc_dir, "ec": ec_dir}


def render_xcpd_qc_reports(config: Dict, state: Dict, title: Optional[str] = None) -> None:
    if title:
        st.header(title)

    paths = config["paths"]
    qc_dirs = ensure_xcpd_qc_dirs(config)
    fc_dir = Path(paths["xcpd_fc_dir"])
    ec_dir = Path(paths["xcpd_ec_dir"])
    fc_qc = collect_qc_reports(fc_dir)
    ec_qc = collect_qc_reports(ec_dir)

    # HPC download helper
    runs = state.get("runs", {})
    fc_run = runs.get("xcpd_fc", {})
    ec_run = runs.get("xcpd_ec", {})
    if fc_run.get("backend") == "hpc" or ec_run.get("backend") == "hpc":
        with st.expander("📥 Download XCP-D outputs from HPC", expanded=False):
            st.caption("Sync finished HPC XCP-D results to your local machine for QC.")
            cols = st.columns(2)
            with cols[0]:
                if st.button("Download FC outputs", key="dl_fc_hpc"):
                    with st.spinner("Downloading FC outputs from HPC…"):
                        try:
                            out = download_xcpd_outputs_from_hpc(config, "fc")
                            st.success(f"FC outputs saved to {out}")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Download failed: {exc}")
            with cols[1]:
                if st.button("Download EC outputs", key="dl_ec_hpc"):
                    with st.spinner("Downloading EC outputs from HPC…"):
                        try:
                            out = download_xcpd_outputs_from_hpc(config, "ec")
                            st.success(f"EC outputs saved to {out}")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Download failed: {exc}")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("FC Pipeline QC")
        _render_pipeline_qc_column(fc_qc, qc_dirs["fc"], "fc")
    with col2:
        st.subheader("EC Pipeline QC")
        _render_pipeline_qc_column(ec_qc, qc_dirs["ec"], "ec")
        exclusions = build_ec_exclusion_table(config)
        if exclusions is not None:
            st.caption("EC exclusion preview (mean FD threshold applied)")
            st.dataframe(exclusions, use_container_width=True, hide_index=True)
            exclusions.to_csv(qc_dirs["ec"] / "ec_exclusions.csv", index=False)

    # QC-FC correlation metric
    qcfc_value = compute_qc_fc_summary(config)
    if qcfc_value is not None:
        st.metric("Mean |QC-FC|", f"{qcfc_value:.4f}")
        if qcfc_value > 0.2:
            st.warning("QC-FC exceeds 0.2 and should be reviewed carefully.")

    # FC motion stats table
    motion_df = collect_xcpd_motion_stats(fc_dir)
    if motion_df is not None and not motion_df.empty:
        st.subheader("FC Motion / Censoring Summary")
        st.dataframe(motion_df, use_container_width=True, hide_index=True)

    # QC gate — only FC is required; EC is optional
    fc_has_outputs = bool(fc_qc["exec_reports"] or fc_qc["bold"] or fc_qc["motion"])
    if fc_has_outputs:
        if state.get("approvals", {}).get("qc_gate", {}).get("approved"):
            st.success("✅ Post-XCP-D QC approved. Subject/group analysis stages are unlocked.")
        else:
            if st.button("Approve and Proceed", type="primary"):
                state = set_step_status(config, "post_xcpd_qc", "completed", "QC reviewed", state=state)
                state = set_approval(config, "qc_gate", True, state=state)
                append_pipeline_log(config, "Approved post-XCP-D QC", state=state)
                st.success("QC approved. Subject/group analysis stages are now unlocked.")
                st.rerun()
    else:
        st.info("Run FC XCP-D first to populate QC artifacts.")


def _render_pipeline_qc_column(qc_reports: Dict[str, List[Path]], qc_dir: Path, pipeline_key: str) -> None:
    """Render QC summary for one pipeline (FC or EC)."""
    counts = {k: len(v) for k, v in qc_reports.items()}
    non_empty = {k: v for k, v in counts.items() if v > 0}
    if not non_empty:
        st.caption("No outputs found yet.")
        return

    # Show output counts
    count_df = pd.DataFrame(
        [(k, v) for k, v in non_empty.items()],
        columns=["type", "count"],
    )
    st.dataframe(count_df, use_container_width=True, hide_index=True)

    # Subject-level HTML reports with download buttons
    exec_reports = qc_reports.get("exec_reports", [])
    if exec_reports:
        st.caption("Per-run QC reports:")
        for report in exec_reports[:20]:
            st.download_button(
                label=f"⬇ {report.parent.parent.name}/{report.parent.name}/{report.name}",
                data=report.read_bytes(),
                file_name=report.name,
                mime="text/html",
                key=f"dl_{pipeline_key}_{report.stem}",
            )


def qc_report_summary(qc_reports: Dict[str, List[Path]]) -> Dict[str, int]:
    return {key: len(value) for key, value in qc_reports.items()}


def render_exec_reports(exec_reports: List[Path]) -> None:
    """Render download buttons for XCP-D HTML QC reports."""
    if not exec_reports:
        st.caption("No HTML reports found yet.")
        return
    for report in exec_reports[:10]:
        st.download_button(
            label=f"⬇ {report.name}",
            data=report.read_bytes(),
            file_name=report.name,
            mime="text/html",
            key=f"dl_report_{report.stem}",
        )


def collect_xcpd_motion_stats(output_dir: Path) -> Optional[pd.DataFrame]:
    """Read per-run motion.tsv and outliers.tsv files and return a summary table."""
    if not output_dir.exists():
        return None

    rows = []
    for motion_file in sorted(output_dir.glob("**/*_motion.tsv")):
        try:
            df = pd.read_csv(motion_file, sep="\t")
            mean_fd = float(df["framewise_displacement"].mean()) if "framewise_displacement" in df.columns else float("nan")
        except Exception:
            mean_fd = float("nan")

        # Parse subject/session/run from path
        parts = motion_file.parts
        subject = next((p for p in parts if p.startswith("sub-")), "")
        session = next((p for p in parts if p.startswith("ses-")), "")
        # Parse run from filename
        name = motion_file.stem
        run = ""
        for part in name.split("_"):
            if part.startswith("run-"):
                run = part
                break

        # Count censored volumes from outliers file
        n_censored = 0
        n_total = 0
        stem_base = "_".join(
            p for p in name.split("_") if not p.startswith("desc-") and not p == "motion"
        )
        for outlier_file in motion_file.parent.glob(f"{stem_base}*_outliers.tsv"):
            try:
                out_df = pd.read_csv(outlier_file, sep="\t")
                n_total = len(out_df)
                n_censored = int(out_df.iloc[:, 0].sum()) if n_total > 0 else 0
            except Exception:
                pass

        pct_retained = round(100.0 * (n_total - n_censored) / n_total, 1) if n_total > 0 else float("nan")
        rows.append({
            "subject": subject,
            "session": session,
            "run": run,
            "mean_fd": round(mean_fd, 4),
            "n_censored": n_censored,
            "n_total": n_total,
            "pct_retained": pct_retained,
        })

    if not rows:
        return None
    return pd.DataFrame(rows).sort_values(["subject", "session", "run"]).reset_index(drop=True)


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

