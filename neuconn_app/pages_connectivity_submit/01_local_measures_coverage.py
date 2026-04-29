"""Local Measures Coverage dashboard.

ALFF & ReHo are produced by XCP-D — no separate submission required.
This page shows coverage and links to the viewer.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.config import load_config
from utils.xcpd_outputs import XcpdDiscovery, KNOWN_PIPELINES

STATE_PREFIX = "submit_local_"


@st.cache_data(ttl=60, show_spinner=False)
def _coverage_table(bids_root: str, pipeline: str) -> pd.DataFrame:
    """Cached wrapper around XcpdDiscovery.coverage_table."""
    disc = XcpdDiscovery(Path(bids_root), pipeline=pipeline)
    return disc.coverage_table(pipeline)


def _get_config() -> dict:
    return st.session_state.get("config") or load_config()


def _format_atlases(atlases: list) -> str:
    """Turn a list of atlas names into pill-like chips string."""
    if not atlases:
        return "—"
    return "  ".join(f"`{a}`" for a in atlases)


def render() -> None:
    st.title("📊 Local Measures Coverage")
    st.markdown(
        "> **ALFF & ReHo are produced by XCP-D — no separate submission required.**  \n"
        "> Use the pipeline selector to inspect which subjects/sessions have outputs."
    )

    # --- Session state defaults ---
    st.session_state.setdefault(f"{STATE_PREFIX}pipeline", "fc")

    config = _get_config()
    bids_root = config.get("paths", {}).get("bids_root", "bids")

    # --- Pipeline selector ---
    pipeline = st.selectbox(
        "Pipeline",
        KNOWN_PIPELINES,
        index=KNOWN_PIPELINES.index(
            st.session_state.get(f"{STATE_PREFIX}pipeline", "fc")
        ),
        key=f"{STATE_PREFIX}pipeline_widget",
    )
    st.session_state[f"{STATE_PREFIX}pipeline"] = pipeline

    st.markdown("---")

    with st.spinner("Scanning XCP-D outputs…"):
        try:
            df_raw = _coverage_table(str(bids_root), pipeline)
        except Exception as exc:
            st.error(f"Discovery failed: {exc}")
            return

    if df_raw.empty:
        st.warning(
            f"No XCP-D outputs found for pipeline **{pipeline}** under `{bids_root}`. "
            "Run XCP-D first."
        )
        return

    df_raw = df_raw.reset_index()

    # Build display dataframe
    display_df = pd.DataFrame(
        {
            "subject": df_raw["subject"],
            "session": df_raw["session"],
            "alff_map": df_raw["alff_map"].map({True: "✅", False: "❌"}),
            "reho_map": df_raw["reho_map"].map({True: "✅", False: "❌"}),
            "atlases_present": df_raw["atlases_present"].apply(_format_atlases),
        }
    )

    total = len(display_df)
    alff_ok = (df_raw["alff_map"] == True).sum()  # noqa: E712
    reho_ok = (df_raw["reho_map"] == True).sum()

    c1, c2, c3 = st.columns(3)
    c1.metric("Total scans", total)
    c2.metric("ALFF present", f"{alff_ok}/{total}")
    c3.metric("ReHo present", f"{reho_ok}/{total}")

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # Download button
    csv_bytes = display_df.to_csv(index=False).encode()
    st.download_button(
        "⬇️ Download as CSV",
        data=csv_bytes,
        file_name=f"local_measures_coverage_{pipeline}.csv",
        mime="text/csv",
    )

    st.markdown("---")
    st.info(
        "📺 **Viewer**: Go to **fMRI Analysis → Subject-Level → 📊 Local Measures Viewer** "
        "(`pages_connectivity/01_fALFF_ReHo.py`) to explore the maps interactively."
    )
