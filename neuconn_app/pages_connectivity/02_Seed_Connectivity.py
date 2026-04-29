"""
Seed-Based Connectivity Viewer — driven by XCP-D outputs.

Cascading seed selector: source → atlas → seed.
Shows seed-to-voxel z-map in Papaya and seed-to-parcel bar chart.
Pipeline selector persists via ``viewer_pipeline_seed_conn`` session-state key.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.papaya_wrapper import render_papaya_viewer_streamlit
from utils.connectivity_viewer import (
    KNOWN_MEASURES,
    pipeline_picker,
    subject_session_pickers,
    list_available_seeds,
    list_available_measures_seed,
    load_seed_to_parcel,
    seed_dir,
)

PAGE_KEY = "seed_conn"


# ============================================================================
# Cached loaders
# ============================================================================


@st.cache_data(ttl=60)
def _list_seeds(bids_root_str: str, pipeline: str, subject: str, session: str) -> list[str]:
    return list_available_seeds(Path(bids_root_str), pipeline, subject, session)


@st.cache_data(ttl=60)
def _list_measures(
    bids_root_str: str, pipeline: str, subject: str, session: str,
    seed_id: str, atlas: str,
) -> list[str]:
    return list_available_measures_seed(
        Path(bids_root_str), pipeline, subject, session, seed_id, atlas
    )


@st.cache_data(ttl=60)
def _load_s2p(
    bids_root_str: str, pipeline: str, subject: str, session: str,
    seed_id: str, atlas: str, measure: str,
) -> Optional[pd.DataFrame]:
    return load_seed_to_parcel(
        bids_root_str, pipeline, subject, session, seed_id, atlas, measure
    )


# ============================================================================
# Seed selector helpers
# ============================================================================


def _source_display(source: str) -> str:
    return {
        "xcpd_atlas_parcel": "Atlas parcel (XCP-D)",
        "custom_nifti_roi": "Custom NIfTI ROI",
        "sphere": "Sphere (coordinates)",
    }.get(source, source)


def _build_seed_selector(bids_root: Path, pipeline: str) -> Optional[str]:
    """Cascading source → atlas → seed selector from SeedCatalog.

    Returns the selected seed_id or None.
    """
    try:
        from neuconn_app.utils.seed_catalog import SeedCatalog
    except ImportError:
        st.warning("SeedCatalog not available.")
        return None

    catalog = SeedCatalog(bids_root, xcpd_pipeline=pipeline)
    sources = catalog.list_sources()
    if not sources:
        st.warning("No seeds found in catalog.")
        return None

    col_src, col_atlas, col_seed = st.columns([1, 2, 3])

    with col_src:
        source = st.selectbox(
            "Source",
            options=sources,
            format_func=_source_display,
            key=f"seed_source_{PAGE_KEY}_{pipeline}",
        )

    atlas_for_source: Optional[str] = None
    if source == "xcpd_atlas_parcel":
        atlases = catalog.list_atlases()
        with col_atlas:
            atlas_for_source = st.selectbox(
                "Atlas",
                options=atlases,
                key=f"seed_atlas_{PAGE_KEY}_{pipeline}",
            )
    else:
        with col_atlas:
            st.markdown("")  # placeholder

    seeds = catalog.get_seeds(source=source, atlas=atlas_for_source)
    if not seeds:
        st.warning("No seeds for selected source/atlas.")
        return None

    seed_ids = [s.id for s in seeds]
    seed_names = {s.id: s.name for s in seeds}

    with col_seed:
        selected_id = st.selectbox(
            "Seed",
            options=seed_ids,
            format_func=lambda x: seed_names.get(x, x),
            key=f"seed_id_{PAGE_KEY}_{pipeline}",
        )

    return selected_id


# ============================================================================
# Voxel z-map viewer
# ============================================================================


def _render_zmap(
    bids_root: Path, pipeline: str, subject: str, session: str, seed_id: str
) -> None:
    sdir = seed_dir(bids_root, pipeline, subject, session, seed_id)
    if not sdir.exists():
        st.info(
            f"No outputs found for seed **{seed_id}**.  "
            "Submit this seed from the 'Connectivity Submit' section first."
        )
        return

    zmaps = sorted(sdir.glob("*_seed-to-voxel_zmap.nii.gz"))
    if not zmaps:
        st.info("Seed-to-voxel z-map not yet computed for this selection.")
        return

    zmap_path = zmaps[0]
    try:
        render_papaya_viewer_streamlit(
            brain_map_path=str(zmap_path),
            title="",
            colormap="Hot",
            height=500,
            key=f"papaya_zmap_{pipeline}_{subject}_{session}_{seed_id[:20]}",
            enable_export=True,
            show_info=True,
        )
    except Exception as exc:
        st.error(f"Viewer error: {exc}")


# ============================================================================
# Seed-to-parcel view
# ============================================================================


def _render_seed_to_parcel(
    bids_root: Path, pipeline: str, subject: str, session: str, seed_id: str
) -> None:
    sdir = seed_dir(bids_root, pipeline, subject, session, seed_id)
    if not sdir.exists():
        st.info("No seed-to-parcel outputs available for this selection.")
        return

    # Discover available atlases from file names
    tsv_files = sorted(sdir.glob("*_seed-to-parcel.tsv"))
    if not tsv_files:
        st.info("Seed-to-parcel TSV files not yet computed.")
        return

    import re
    available_atlas_measure: dict[str, list[str]] = {}
    for f in tsv_files:
        m = re.search(r"_atlas-([^_]+)_measure-([^_]+)_seed-to-parcel\.tsv$", f.name)
        if m:
            atl, meas = m.group(1), m.group(2)
            available_atlas_measure.setdefault(atl, []).append(meas)

    if not available_atlas_measure:
        st.info("No parseable seed-to-parcel TSV files found.")
        return

    col_a, col_m, col_n = st.columns([2, 2, 1])
    with col_a:
        atlas = st.selectbox(
            "Atlas",
            options=sorted(available_atlas_measure.keys()),
            key=f"s2p_atlas_{PAGE_KEY}_{pipeline}_{subject}_{session}_{seed_id[:15]}",
        )
    with col_m:
        measures = available_atlas_measure.get(atlas, [])
        measure = st.selectbox(
            "Measure",
            options=measures,
            key=f"s2p_measure_{PAGE_KEY}_{pipeline}_{subject}_{session}_{seed_id[:15]}",
        )
    with col_n:
        top_n = st.number_input(
            "Top N",
            min_value=5,
            max_value=100,
            value=30,
            key=f"s2p_topn_{PAGE_KEY}_{pipeline}_{subject}_{session}_{seed_id[:15]}",
        )

    df = _load_s2p(str(bids_root), pipeline, subject, session, seed_id, atlas, measure)
    if df is None or df.empty:
        st.warning("Could not load seed-to-parcel data.")
        return

    # Melt wide row → (parcel, value)
    values = df.iloc[0]
    parcel_df = pd.DataFrame({"parcel": values.index, "value": values.values})
    parcel_df["value"] = pd.to_numeric(parcel_df["value"], errors="coerce")
    parcel_df = parcel_df.dropna(subset=["value"])
    top_df = parcel_df.nlargest(int(top_n), "value").sort_values("value")

    try:
        import plotly.express as px
        fig = px.bar(
            top_df, x="value", y="parcel", orientation="h",
            title=f"Top {top_n} parcels — {measure} / {atlas}",
            labels={"value": f"Seed → parcel ({measure})", "parcel": "Parcel"},
            height=max(400, int(top_n) * 18),
        )
        fig.update_layout(margin=dict(l=10, r=10, t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.bar_chart(top_df.set_index("parcel")["value"])

    # Compare-across-measures expander
    with st.expander("🔍 Compare top-10 parcels across measures"):
        cols = st.columns(min(len(measures), 4))
        for i, meas in enumerate(measures):
            df_m = _load_s2p(
                str(bids_root), pipeline, subject, session, seed_id, atlas, meas
            )
            if df_m is None or df_m.empty:
                continue
            vals = df_m.iloc[0]
            pm = pd.DataFrame({"parcel": vals.index, "value": vals.values})
            pm["value"] = pd.to_numeric(pm["value"], errors="coerce")
            pm = pm.dropna().nlargest(10, "value")
            with cols[i % len(cols)]:
                st.markdown(f"**{meas}**")
                st.dataframe(pm[["parcel", "value"]].reset_index(drop=True), height=250)


# ============================================================================
# Main render
# ============================================================================


def render() -> None:
    """Main page render function."""
    st.header("🔗 Seed-Based Connectivity")

    config = st.session_state.get("config", {})
    bids_root = Path(
        config.get("paths", {}).get("bids_dir", "")
        or Path(__file__).resolve().parents[3]
    )

    # ── Top selector row ──────────────────────────────────────────────────
    pipeline = pipeline_picker(PAGE_KEY)
    subject, session = subject_session_pickers(bids_root, pipeline, PAGE_KEY)
    if subject is None or session is None:
        return

    st.divider()

    # ── Seed selector ─────────────────────────────────────────────────────
    st.markdown("#### Seed selection")
    seed_id = _build_seed_selector(bids_root, pipeline)
    if seed_id is None:
        return

    st.caption(
        f"Pipeline: **{pipeline}** | {subject} / {session} | Seed: `{seed_id}`"
    )
    st.divider()

    # ── Tabs ──────────────────────────────────────────────────────────────
    tab_vox, tab_parcel = st.tabs(["🧠 Voxel z-map", "📊 Seed-to-parcel"])

    with tab_vox:
        _render_zmap(bids_root, pipeline, subject, session, seed_id)

    with tab_parcel:
        _render_seed_to_parcel(bids_root, pipeline, subject, session, seed_id)


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    render()
