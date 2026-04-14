"""Subject-level seed connectivity exports derived from XCP-D FC outputs."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.pipeline_state import append_pipeline_log, load_pipeline_state, set_step_status
from utils.subject_level_fc import export_seed_level_outputs, load_manifest_table, refresh_subject_level_fc


def render() -> None:
    st.header("🎯 Seed Connectivity")

    config = st.session_state.get("config", {})
    if not config:
        st.error("Configuration not loaded.")
        return

    state = load_pipeline_state(config)
    qc_approved = bool(state["approvals"].get("qc_gate", {}).get("approved"))
    if not qc_approved:
        st.warning("Post-XCP-D QC is not approved yet. Seed export actions stay locked until the QC gate is approved.")

    st.caption(
        f"Seed definitions: `{config['paths']['roi_config_path']}`  \n"
        f"XCP-D FC source: `{config['paths']['xcpd_fc_dir']}`"
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Refresh FC manifests", use_container_width=True):
            manifests = refresh_subject_level_fc(config)
            append_pipeline_log(
                config,
                f"Refreshed FC manifests ({len(manifests['timeseries'])} timeseries, {len(manifests['connectomes'])} connectomes)",
            )
            st.success("FC manifests refreshed.")
            st.rerun()
    with col2:
        if st.button(
            "Export atlas-based seed summaries",
            type="primary",
            use_container_width=True,
            disabled=not qc_approved,
        ):
            exports = export_seed_level_outputs(config)
            set_step_status(
                config,
                "subject_level",
                "completed",
                (
                    f"{len(exports['seed_timeseries_manifest'])} seed timeseries exports, "
                    f"{len(exports['seed_connectivity_manifest'])} connectivity exports"
                ),
            )
            append_pipeline_log(
                config,
                (
                    "Exported atlas-based seed summaries from XCP-D FC outputs "
                    f"({len(exports['seed_timeseries_manifest'])} timeseries, "
                    f"{len(exports['seed_connectivity_manifest'])} matrices)"
                ),
            )
            st.success("Seed summaries exported to derivatives/subject_level/fc.")
            st.rerun()

    inventory = load_manifest_table(config, "artifact_inventory.csv")
    seed_support = load_manifest_table(config, "seed_support_manifest.csv")
    seed_timeseries = load_manifest_table(config, "seed_timeseries_manifest.csv")
    seed_connectivity = load_manifest_table(config, "seed_connectivity_manifest.csv")

    if not inventory.empty:
        st.subheader("Available FC inputs")
        st.dataframe(inventory, use_container_width=True, hide_index=True)
    else:
        st.info("No FC manifests yet. Refresh them after XCP-D FC completes.")
        return

    if not seed_support.empty:
        st.subheader("Seed support")
        st.dataframe(seed_support, use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Seed timeseries exports")
        if seed_timeseries.empty:
            st.caption("No seed timeseries exports yet.")
        else:
            st.dataframe(
                seed_timeseries[
                    ["subject_id", "session", "atlas", "seed_count", "seed_ids", "export_file"]
                ],
                use_container_width=True,
                hide_index=True,
            )
            preview_seed_timeseries(seed_timeseries)

    with col2:
        st.subheader("Seed connectivity exports")
        if seed_connectivity.empty:
            st.caption("No seed connectivity exports yet.")
        else:
            st.dataframe(
                seed_connectivity[
                    ["subject_id", "session", "atlas", "seed_count", "seed_ids", "matrix_file"]
                ],
                use_container_width=True,
                hide_index=True,
            )
            preview_seed_matrix(seed_connectivity)


def preview_seed_timeseries(seed_timeseries: pd.DataFrame) -> None:
    options = {
        f"{row.subject_id} {row.session} {row.atlas}".strip(): row.export_file
        for row in seed_timeseries.itertuples()
    }
    label = st.selectbox("Preview exported seed timeseries", list(options.keys()), key="seed_ts_preview")
    export_file = Path(options[label])
    if export_file.exists():
        preview = pd.read_csv(export_file, sep="\t").head(20)
        st.dataframe(preview, use_container_width=True, hide_index=True)


def preview_seed_matrix(seed_connectivity: pd.DataFrame) -> None:
    options = {
        f"{row.subject_id} {row.session} {row.atlas}".strip(): row.matrix_file
        for row in seed_connectivity.itertuples()
    }
    label = st.selectbox("Preview exported seed matrix", list(options.keys()), key="seed_matrix_preview")
    export_file = Path(options[label])
    if export_file.exists():
        preview = pd.read_csv(export_file, sep="\t", index_col=0)
        st.dataframe(preview, use_container_width=True)


if __name__ == "__main__":
    render()
