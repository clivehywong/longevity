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
from utils.xcpd import collect_qc_reports


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
            exclusions.to_csv(qc_dirs["ec"] / "ec_exclusions.csv", index=False)

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
