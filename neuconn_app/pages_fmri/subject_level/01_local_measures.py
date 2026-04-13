"""Subject-level local-measure inventory derived from XCP-D outputs."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.pipeline_state import append_pipeline_log, load_pipeline_state, set_step_status
from utils.subject_level_fc import load_manifest_table, refresh_subject_level_fc


def render() -> None:
    st.header("📊 Local Measures")

    config = st.session_state.get("config", {})
    if not config:
        st.error("Configuration not loaded.")
        return

    st.caption(
        f"Source XCP-D FC derivatives: `{config['paths']['xcpd_fc_dir']}`  \n"
        f"Subject-level outputs: `{config['paths']['subject_level_fc_dir']}`"
    )

    if st.button("Refresh local-measure manifests", type="primary"):
        manifests = refresh_subject_level_fc(config)
        local_measures = manifests["local_measures"]
        set_step_status(
            config,
            "subject_level",
            "completed" if not local_measures.empty else "not_started",
            f"{len(local_measures)} local-measure artifacts indexed",
        )
        append_pipeline_log(
            config,
            f"Refreshed subject-level FC manifests ({len(local_measures)} local measures)",
        )
        st.success("Subject-level FC manifests refreshed.")
        st.rerun()

    state = load_pipeline_state(config)
    if not state["approvals"].get("qc_gate", {}).get("approved"):
        st.warning("Post-XCP-D QC has not been approved yet. Review is recommended before using these outputs.")

    inventory = load_manifest_table(config, "artifact_inventory.csv")
    local_measures = load_manifest_table(config, "local_measures_manifest.csv")

    if inventory.empty and local_measures.empty:
        st.info("No subject-level manifests yet. Refresh them after FC XCP-D produces outputs.")
        return

    if not inventory.empty:
        counts = inventory[inventory["artifact_type"].isin(["alff", "falff", "reho"])]
        if not counts.empty:
            cols = st.columns(min(3, len(counts)))
            for col, (_, row) in zip(cols, counts.iterrows()):
                label = row["artifact_type"].upper()
                atlas_text = f" ({row['atlas']})" if isinstance(row["atlas"], str) and row["atlas"] else ""
                col.metric(f"{label}{atlas_text}", int(row["count"]))

    if local_measures.empty:
        st.info("No fALFF / ALFF / ReHo outputs were found in the configured XCP-D FC directory.")
        return

    st.subheader("Indexed local-measure files")
    display = local_measures[
        ["measure", "subject_id", "session", "atlas", "space", "source_file"]
    ].copy()
    st.dataframe(display, use_container_width=True, hide_index=True)

    subjects = sorted(display["subject_id"].dropna().unique().tolist())
    measures = sorted(display["measure"].dropna().unique().tolist())
    st.subheader("Coverage")
    coverage = (
        display.groupby(["subject_id", "session", "measure"])
        .size()
        .reset_index(name="count")
        .pivot_table(
            index=["subject_id", "session"],
            columns="measure",
            values="count",
            fill_value=0,
        )
        .reset_index()
    )
    if subjects and measures:
        st.dataframe(coverage, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    render()
