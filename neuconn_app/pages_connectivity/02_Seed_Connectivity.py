"""
Seed-Based Connectivity Viewer — driven by XCP-D outputs.

Cascading seed selector: source → atlas → seed.
Shows seed-to-voxel z-map in Papaya and seed-to-parcel bar chart.
Pipeline selector persists via ``viewer_pipeline_seed_conn`` session-state key.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np
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


@st.cache_data(ttl=60)
def _load_meta(meta_path_str: str, mtime: float) -> Optional[dict]:
    """Load seed metadata JSON; keyed on path + mtime for freshness."""
    try:
        return json.loads(Path(meta_path_str).read_text())
    except Exception:
        return None


@st.cache_data(ttl=60)
def _compute_zmap_stats(
    zmap_path_str: str, mtime: float
) -> Optional[dict]:
    """Load zmap NIfTI and compute in-brain z-score statistics."""
    try:
        import nibabel as nib
        img = nib.load(zmap_path_str)
        data = img.get_fdata(dtype=np.float32).ravel()
        # Non-zero finite voxels approximate in-brain (background is exactly 0)
        brain = data[np.isfinite(data) & (data != 0)]
        if brain.size == 0:
            return None
        return {
            "n_voxels": int(brain.size),
            "mean": float(np.mean(brain)),
            "std": float(np.std(brain)),
            "pct_positive": float(100 * np.mean(brain > 0)),
            "pct_strong_pos": float(100 * np.mean(brain > 0.5)),
            "pct_strong_neg": float(100 * np.mean(brain < -0.5)),
        }
    except Exception:
        return None


# ============================================================================
# Seed selector helpers
# ============================================================================


@st.cache_data(ttl=30)
def _discover_computed_seeds(
    bids_root_str: str, pipeline: str, subject: str, session: str
) -> list[dict]:
    """Return list of {id, display_name} for seeds with computed outputs."""
    seed_ids = list_available_seeds(Path(bids_root_str), pipeline, subject, session)
    results = []
    for sid in seed_ids:
        sdir = seed_dir(Path(bids_root_str), pipeline, subject, session, sid)
        # Try meta.json for a friendly name
        meta_files = sorted(sdir.glob("*_meta.json"))
        display_name = sid  # fallback
        if meta_files:
            try:
                meta = json.loads(meta_files[0].read_text())
                spec = meta.get("seed_spec", {})
                display_name = spec.get("name") or sid
            except Exception:
                pass
        has_zmap = any(sdir.glob("*_seed-to-voxel_zmap.nii.gz"))
        results.append({
            "id": sid,
            "display_name": display_name,
            "has_zmap": has_zmap,
        })
    return results


def _build_seed_selector(
    bids_root: Path, pipeline: str, subject: str, session: str
) -> Optional[str]:
    """Seed selector driven by file-system discovery of computed outputs.

    Returns the selected seed_id or None.
    """
    computed = _discover_computed_seeds(str(bids_root), pipeline, subject, session)

    if not computed:
        st.info(
            f"No computed seed outputs found for **{subject} / {session}** "
            f"(pipeline: `{pipeline}`).  \n"
            "Submit seeds from the **📤 Submit Seed Connectivity** section, "
            "then return here to view results."
        )
        return None

    options = [s["id"] for s in computed]
    names = {s["id"]: s["display_name"] for s in computed}
    zmap_flag = {s["id"]: s["has_zmap"] for s in computed}

    def _fmt(sid: str) -> str:
        icon = "🧠" if zmap_flag.get(sid) else "📊"
        return f"{icon} {names.get(sid, sid)}"

    selected_id = st.selectbox(
        "Seed",
        options=options,
        format_func=_fmt,
        key=f"seed_id_{PAGE_KEY}_{pipeline}_{subject}_{session}",
        help="Shows seeds with computed outputs. 🧠 = has voxel z-map, 📊 = parcel only.",
    )
    return selected_id


# ============================================================================
# Quality metrics panel
# ============================================================================


def _render_quality_metrics(sdir: Path, prefix: str) -> None:
    """Render provenance + z-score quality metrics in an expander."""
    meta_path = sdir / f"{prefix}_meta.json"
    zmap_path = sdir / f"{prefix}_seed-to-voxel_zmap.nii.gz"

    if not meta_path.exists() and not zmap_path.exists():
        return

    with st.expander("🔬 Quality metrics & provenance", expanded=False):
        # ── Provenance from meta.json ─────────────────────────────────────
        if meta_path.exists():
            mtime = meta_path.stat().st_mtime
            meta = _load_meta(str(meta_path), mtime)
            if meta:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Pipeline", meta.get("pipeline", "—"))
                c2.metric("BOLD variant", meta.get("bold_variant", "—"))
                c3.metric("TR (s)", meta.get("tr", "—"))
                c4.metric("Timepoints", meta.get("n_timepoints") or "—")

                mask_path = meta.get("brain_mask_path")
                n_bvox = meta.get("n_brain_voxels")
                if mask_path:
                    mask_label = Path(mask_path).name
                    st.success(
                        f"✅ Brain mask applied: `{mask_label}` — "
                        f"{n_bvox:,} voxels" if n_bvox else f"✅ Brain mask applied: `{mask_label}`"
                    )
                else:
                    st.warning(
                        "⚠️ Brain mask provenance not recorded — "
                        "this output may have been generated without masking."
                    )

                zmap_shape = meta.get("zmap_shape")
                expected = [91, 109, 91]
                if zmap_shape and list(zmap_shape) != expected:
                    st.warning(
                        f"Unexpected zmap shape {zmap_shape} (expected {expected}). "
                        "Check MNI space / resolution."
                    )

                rt = meta.get("runtime_seconds")
                ts = meta.get("timestamp", "")
                if rt or ts:
                    st.caption(
                        f"Computed in {rt:.1f}s" if rt else ""
                        + (f"  ·  {ts}" if ts else "")
                    )

        # ── Z-score statistics from zmap ─────────────────────────────────
        if zmap_path.exists():
            mtime_z = zmap_path.stat().st_mtime
            stats = _compute_zmap_stats(str(zmap_path), mtime_z)
            if stats:
                st.markdown("**Z-score distribution (in-brain voxels)**")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Mean z", f"{stats['mean']:.3f}")
                c2.metric("Std z", f"{stats['std']:.3f}")
                c3.metric("% z > 0", f"{stats['pct_positive']:.1f}%")
                c4.metric("% |z| > 0.5", f"{stats['pct_strong_pos'] + stats['pct_strong_neg']:.1f}%")
                if stats["pct_strong_neg"] > 0.5:
                    st.caption(
                        f"Strong positive (z>0.5): {stats['pct_strong_pos']:.1f}%  "
                        f"· Strong negative (z<−0.5): {stats['pct_strong_neg']:.1f}%"
                    )


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

    prefix = f"{subject}_{session}_seed-{seed_id}"
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

    _render_quality_metrics(sdir, prefix)


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
    bids_root_value = (
        config.get("project_root")
        or config.get("paths", {}).get("project_root")
        or config.get("paths", {}).get("bids_root")
        or config.get("paths", {}).get("bids_dir")
    )
    bids_root = (
        Path(bids_root_value).expanduser()
        if bids_root_value and "${" not in str(bids_root_value)
        else Path(__file__).resolve().parents[2]
    )

    # ── Top selector row ──────────────────────────────────────────────────
    pipeline = pipeline_picker(PAGE_KEY)
    subject, session = subject_session_pickers(bids_root, pipeline, PAGE_KEY)
    if subject is None or session is None:
        return

    st.divider()

    # ── Seed selector ─────────────────────────────────────────────────────
    st.markdown("#### Seed selection")
    seed_id = _build_seed_selector(bids_root, pipeline, subject, session)
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
