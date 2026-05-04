"""
fALFF & ReHo Viewer — driven by XCP-D outputs.

Displays a single ALFF or ReHo voxel map via Papaya (MNI template background
+ hot-colormap overlay) and parcellated values as sortable bar charts.
Pipeline, measure, and subject/session are all selectable from the top bar,
with ◀ / ▶ buttons for quick subject navigation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.papaya_wrapper import render_papaya_viewer_streamlit
from utils.xcpd_outputs import XcpdDiscovery
from utils.connectivity_viewer import pipeline_picker
try:
    from utils.seed_catalog import SeedCatalog
    _HAS_SEED_CATALOG = True
except ImportError:
    _HAS_SEED_CATALOG = False

PAGE_KEY = "falff_reho"


# ============================================================================
# Cached helpers
# ============================================================================


@st.cache_data(ttl=60)
def _get_xcpd(bids_root_str: str, pipeline: str, subject: str, session: str):
    """Cached XCP-D output discovery for a single subject/session."""
    from utils.xcpd_outputs import XcpdDiscovery
    disc = XcpdDiscovery(Path(bids_root_str), pipeline=pipeline)
    return disc.get(subject, session, pipeline)


@st.cache_data(ttl=60)
def _load_parcel_tsv(tsv_str: str) -> Optional[pd.DataFrame]:
    path = Path(tsv_str)
    if not path.exists():
        return None
    try:
        return pd.read_csv(path, sep="\t")
    except Exception:
        return None


@st.cache_resource
def _get_mni_template() -> Optional[str]:
    """Return path to MNI152NLin6Asym res-2 brain T1w template."""
    try:
        from templateflow.api import get as tfl_get
        result = tfl_get(
            "MNI152NLin6Asym", resolution=2, desc="brain",
            suffix="T1w", extension=".nii.gz",
        )
        if isinstance(result, list):
            return str(result[0]) if result else None
        return str(result)
    except Exception:
        return None


# ============================================================================
# Voxel viewer
# ============================================================================


def _render_voxel_view(
    outputs, subject: str, session: str, pipeline: str, measure: str
) -> None:
    stat_map = outputs.alff_map if measure == "ALFF" else outputs.reho_map
    if stat_map is None:
        st.info(
            f"{measure} voxel map is not yet available for this selection.  "
            "Run the XCP-D pipeline to generate it."
        )
        return

    mni_path = _get_mni_template()

    overlays = [str(stat_map)]
    overlay_cmaps = ["Overlay (Positives)"]
    bg = mni_path if mni_path else str(stat_map)
    bg_cmap = "Grayscale" if mni_path else "Overlay (Positives)"
    if not mni_path:
        overlays = []
        overlay_cmaps = []

    render_papaya_viewer_streamlit(
        brain_map_path=bg,
        overlays=overlays,
        colormap=bg_cmap,
        overlay_colormaps=overlay_cmaps,
        overlay_alpha=0.7,
        title="",
        height=550,
        key=f"papaya_{measure}_{pipeline}_{subject}_{session}",
        enable_export=False,
        show_info=False,
    )


# ============================================================================
# Parcellated viewer
# ============================================================================


def _render_parcellated_view(
    outputs, subject: str, session: str, pipeline: str, measure: str
) -> None:
    atlases = outputs.list_atlases()
    if not atlases:
        st.info("No parcellated outputs available for this subject/session/pipeline.")
        return

    col_atlas, col_net, col_n = st.columns([2, 2, 1])
    with col_atlas:
        atlas = st.selectbox(
            "Atlas",
            options=atlases,
            key=f"parcel_atlas_{pipeline}_{subject}_{session}",
        )
    with col_n:
        top_n = st.number_input(
            "Top N",
            min_value=5,
            max_value=100,
            value=30,
            key=f"parcel_topn_{pipeline}_{subject}_{session}",
        )

    parcel_dict = outputs.alff_parcel if measure == "ALFF" else outputs.reho_parcel
    tsv_path = parcel_dict.get(atlas)
    if tsv_path is None:
        st.warning(f"No {measure} parcellated file for atlas {atlas}.")
        return

    df = _load_parcel_tsv(str(tsv_path))
    if df is None or df.empty:
        st.warning("Could not load parcellated file.")
        return

    values = df.iloc[0]
    parcel_df = pd.DataFrame({"parcel": values.index, "value": values.values})
    parcel_df["value"] = pd.to_numeric(parcel_df["value"], errors="coerce")
    parcel_df = parcel_df.dropna(subset=["value"])

    net_options: list[str] = ["(all)"]
    if _HAS_SEED_CATALOG:
        try:
            from utils.seed_catalog import _infer_network
            networks = sorted(
                {_infer_network(atlas, p) for p in parcel_df["parcel"]} - {None}
            )
            net_options += networks
        except Exception:
            pass

    with col_net:
        selected_net = st.selectbox(
            "Network",
            options=net_options,
            key=f"parcel_net_{pipeline}_{subject}_{session}",
        )

    if selected_net != "(all)" and _HAS_SEED_CATALOG:
        try:
            from utils.seed_catalog import _infer_network
            parcel_df = parcel_df[
                parcel_df["parcel"].apply(
                    lambda p: _infer_network(atlas, p) == selected_net
                )
            ]
        except Exception:
            pass

    top_df = parcel_df.nlargest(int(top_n), "value").sort_values("value")

    try:
        import plotly.express as px
        fig = px.bar(
            top_df,
            x="value",
            y="parcel",
            orientation="h",
            title=f"Top {top_n} parcels — {measure} / {atlas}",
            labels={"value": measure, "parcel": "Parcel"},
            height=max(400, int(top_n) * 18),
        )
        fig.update_layout(margin=dict(l=10, r=10, t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.bar_chart(top_df.set_index("parcel")["value"])

    with st.expander("📋 Full parcel table"):
        st.dataframe(
            parcel_df.sort_values("value", ascending=False).reset_index(drop=True),
            use_container_width=True,
        )


# ============================================================================
# Main render
# ============================================================================


def render() -> None:
    """Main page render function."""
    st.header("📊 Local Measures: fALFF & ReHo")

    config = st.session_state.get("config", {})
    project_root = Path(
        config.get("paths", {}).get("project_root", "")
        or Path(config.get("paths", {}).get("bids_dir", "") or "").parent
        or Path(__file__).resolve().parents[2]
    )

    disc = XcpdDiscovery(project_root)

    # ── Top control row: Pipeline | Measure | ◀ Subject ▶ | Session ─────
    col_pl, col_meas, col_nav = st.columns([1, 1, 5])

    with col_pl:
        pipeline = pipeline_picker(PAGE_KEY)

    with col_meas:
        measure = st.selectbox(
            "Measure",
            options=["ALFF", "ReHo"],
            key=f"measure_{PAGE_KEY}",
        )

    subjects = disc.list_subjects(pipeline)

    with col_nav:
        if not subjects:
            st.warning(f"No preprocessed subjects found for pipeline **{pipeline}**.")
            return

        # Subject navigation — callbacks write to the selectbox key directly
        subj_key = f"subj_sel_{PAGE_KEY}_{pipeline}"
        if subj_key not in st.session_state or st.session_state[subj_key] not in subjects:
            st.session_state[subj_key] = subjects[0]

        def _prev():
            idx = subjects.index(st.session_state[subj_key])
            if idx > 0:
                st.session_state[subj_key] = subjects[idx - 1]

        def _next():
            idx = subjects.index(st.session_state[subj_key])
            if idx < len(subjects) - 1:
                st.session_state[subj_key] = subjects[idx + 1]

        current_idx = subjects.index(st.session_state[subj_key])
        c_prev, c_sub, c_next, c_ses = st.columns([1, 3, 1, 2])
        with c_prev:
            st.button("◀", on_click=_prev, disabled=(current_idx == 0),
                      key=f"prev_{PAGE_KEY}", help="Previous subject")
        with c_sub:
            subject = st.selectbox(
                "Subject",
                options=subjects,
                format_func=lambda x: x.replace("sub-", "Sub "),
                key=subj_key,
            )
        with c_next:
            st.button("▶", on_click=_next, disabled=(current_idx == len(subjects) - 1),
                      key=f"next_{PAGE_KEY}", help="Next subject")
        with c_ses:
            sessions = disc.list_sessions(subject, pipeline)
            if not sessions:
                st.warning(f"No sessions for {subject}")
                return
            ses_key = f"ses_sel_{PAGE_KEY}_{pipeline}_{subject}"
            if ses_key not in st.session_state or st.session_state[ses_key] not in sessions:
                st.session_state[ses_key] = sessions[0]
            session = st.selectbox(
                "Session",
                options=sessions,
                format_func=lambda x: x.replace("ses-", "Ses "),
                key=ses_key,
            )

    st.caption(
        f"Pipeline: **{pipeline}** · Measure: **{measure}** · "
        f"Subject: **{subject}** · Session: **{session}** "
        f"({current_idx + 1} / {len(subjects)})"
    )

    # ── XCP-D outputs ─────────────────────────────────────────────────────
    outputs = _get_xcpd(str(project_root), pipeline, subject, session)

    # ── Voxel / Parcellated tabs ──────────────────────────────────────────
    tab_vox, tab_parcel = st.tabs(["🧠 Voxel map", "📊 Parcellated"])

    with tab_vox:
        _render_voxel_view(outputs, subject, session, pipeline, measure)

    with tab_parcel:
        _render_parcellated_view(outputs, subject, session, pipeline, measure)


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    render()
