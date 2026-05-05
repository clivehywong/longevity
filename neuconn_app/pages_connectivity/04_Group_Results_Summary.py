"""Group Results Summary.

Consolidates all group-level statistical results (Seed FC + ALFF + ReHo) for a pipeline.
Scans outputs, detects significance, lets the user select which analyses to review,
then renders thumbnails, cluster maps, and per-cluster mean-value plots.
"""
from __future__ import annotations

import io
import json
import sys
import re
from pathlib import Path
from typing import Optional

import nibabel as nib
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.connectivity_viewer import pipeline_picker

PAGE_KEY = "group_results_summary"

_CONTRAST_LABELS = {
    1: "Group × Time interaction",
    2: "Time effect (ses-01 > ses-02)",
    3: "Group effect (walking > control)",
}

_GROUP_COLORS = {
    "control": {"pre": "#4C72B0", "post": "#85A4D4"},
    "walking": {"pre": "#C44E52", "post": "#E89A9C"},
}


# ============================================================================
# Filesystem scan
# ============================================================================

@st.cache_data(ttl=60)
def _scan_all_results(bids_root_str: str, pipeline: str, _tick: int) -> pd.DataFrame:
    """Scan all group results → DataFrame, one row per (analysis × contrast × source)."""
    bids_root = Path(bids_root_str)
    group_base = bids_root / "derivatives" / "connectivity" / pipeline / "group"
    rows = []

    def _add_rows(type_: str, label: str, seed_dir: Optional[str], measure: Optional[str],
                  stat: Optional[str], out_dir: Path, source: str) -> None:
        if source == "lmm":
            tstats = sorted(out_dir.glob("lmm_tstat*.nii.gz"))
            pat = r"lmm_tstat(\d+)\.nii\.gz$"
        else:
            tstats = sorted(out_dir.glob("randomise_tstat*.nii.gz"))
            pat = r"randomise_tstat(\d+)\.nii\.gz$"
        for f in tstats:
            m = re.search(pat, f.name)
            if not m:
                continue
            idx = int(m.group(1))
            # Find best corrp
            if source == "lmm":
                corrp_cand = out_dir / f"lmm_cluster_corrp_tstat{idx}.nii.gz"
                corrp_path = str(corrp_cand) if corrp_cand.exists() else None
                corrp_label = "GRF cluster (parametric)" if corrp_path else ""
            else:
                tfce = out_dir / f"randomise_tfce_corrp_tstat{idx}.nii.gz"
                grf = out_dir / f"randomise_clustere_corrp_tstat{idx}.nii.gz"
                fdr = out_dir / f"randomise_fdr_corrp_tstat{idx}.nii.gz"
                if tfce.exists():
                    corrp_path, corrp_label = str(tfce), "TFCE"
                elif grf.exists():
                    corrp_path, corrp_label = str(grf), "GRF cluster"
                elif fdr.exists():
                    corrp_path, corrp_label = str(fdr), "FDR (BH)"
                else:
                    corrp_path, corrp_label = None, ""
            # Compute max corrp for significance detection (use dataobj for lazy IO)
            max_corrp = float("nan")
            if corrp_path:
                try:
                    img = nib.load(corrp_path)
                    max_corrp = float(np.nanmax(np.asanyarray(img.dataobj)))
                except Exception:
                    pass
            # zthresh for cluster ROI (LMM: cN_zthresh.nii.gz)
            if source == "lmm":
                zthresh_path = out_dir / f"c{idx}_zthresh.nii.gz"
                cluster_roi_path = str(zthresh_path) if zthresh_path.exists() else None
            else:
                cluster_roi_path = corrp_path  # use corrp thresholded image
            rows.append({
                "type": type_,
                "label": label,
                "seed_dir": seed_dir,
                "measure": measure,
                "stat": stat,
                "contrast_idx": idx,
                "contrast_label": _CONTRAST_LABELS.get(idx, f"Contrast {idx}"),
                "source": source,
                "tstat_path": str(f),
                "corrp_path": corrp_path,
                "corrp_label": corrp_label,
                "max_corrp": max_corrp,
                "significant": max_corrp > 0.95 if not np.isnan(max_corrp) else False,
                "cluster_roi_path": cluster_roi_path,
                "summary_json": str(out_dir / ("lmm_summary.json" if source == "lmm" else "stats_summary.json")),
                "out_dir": str(out_dir),
            })

    # Seed FC
    seed_base = group_base / "seed"
    if seed_base.exists():
        for seed_dir in sorted(seed_base.iterdir()):
            if not seed_dir.is_dir():
                continue
            for mdir in sorted(seed_dir.iterdir()):
                if not mdir.is_dir() or not mdir.name.startswith("measure-"):
                    continue
                measure = mdir.name.removeprefix("measure-")
                label = f"{_seed_dir_label(seed_dir.name)} / {measure}"
                for src, odir in [("randomise", mdir / "randomise_outputs"), ("lmm", mdir / "lmm_outputs")]:
                    if odir.exists():
                        _add_rows("Seed FC", label, seed_dir.name, measure, None, odir, src)

    # ALFF / ReHo
    for stat in ("alff", "reho"):
        stat_base = group_base / stat
        for src, odir in [("randomise", stat_base / "randomise_outputs"), ("lmm", stat_base / "lmm_outputs")]:
            if odir.exists():
                _add_rows(stat.upper(), stat.upper(), None, None, stat, odir, src)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _seed_dir_label(dir_name: str) -> str:
    m = re.match(r"sphere-([-\d]+)_([-\d]+)_([-\d]+)_r([\d]+)$", dir_name)
    if m:
        return f"Sphere ({m.group(1)},{m.group(2)},{m.group(3)}) r={m.group(4)}mm"
    m = re.match(r"atlas-([^_]+)_parcel-(.+)$", dir_name)
    if m:
        return f"{m.group(2)} [{m.group(1)}]"
    return dir_name


# ============================================================================
# Seed ROI visualization
# ============================================================================

@st.cache_data(show_spinner=False)
def _render_seed_roi_png(seed_dir: str, atlas_nii_path: str, atlas_labels_path: str) -> Optional[bytes]:
    """Render seed parcel ROI as PNG using nilearn plot_roi."""
    try:
        from nilearn import plotting, image  # noqa: PLC0415
        import matplotlib  # noqa: PLC0415
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415

        m = re.match(r"atlas-([^_]+)_parcel-(.+)$", seed_dir)
        if m:
            parcel_label = m.group(2)
            with open(atlas_labels_path) as f:
                labels = [l.strip() for l in f.readlines()]
            if parcel_label not in labels:
                return None
            label_idx = labels.index(parcel_label) + 1  # 1-indexed
            atlas_img = nib.load(atlas_nii_path)
            atlas_data = atlas_img.get_fdata()
            roi_data = (atlas_data == label_idx).astype(np.float32)
            roi_img = nib.Nifti1Image(roi_data, atlas_img.affine)
        else:
            # Sphere seed
            ms = re.match(r"sphere-([-\d]+)_([-\d]+)_([-\d]+)_r(\d+)$", seed_dir)
            if not ms:
                return None
            x, y, z, r = int(ms.group(1)), int(ms.group(2)), int(ms.group(3)), int(ms.group(4))
            from nilearn.image import new_img_like  # noqa: PLC0415
            from nilearn.datasets import load_mni152_template  # noqa: PLC0415
            ref = load_mni152_template(resolution=2)
            from nilearn.maskers import NiftiSpheresMasker  # noqa: PLC0415
            coords = np.array([[x, y, z]])
            masker = NiftiSpheresMasker(seeds=coords, radius=r, mask_img=ref)
            masker.fit()
            roi_img = masker.inverse_transform(np.ones((1, 1)))

        fig, ax = plt.subplots(figsize=(8, 2))
        display = plotting.plot_roi(
            roi_img, bg_img="MNI152", axes=ax,
            title=f"Seed: {seed_dir}", display_mode="ortho",
            cut_coords=None, alpha=0.7,
        )
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None


# ============================================================================
# T-stat thumbnail
# ============================================================================

@st.cache_data(show_spinner=False)
def _render_tstat_thumb(tstat_path: str, mtime: float, threshold: float = 2.3) -> Optional[bytes]:
    """Render a compact T-stat map thumbnail as PNG bytes."""
    try:
        from nilearn import plotting  # noqa: PLC0415
        import matplotlib  # noqa: PLC0415
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415

        img = nib.load(tstat_path)
        fig, ax = plt.subplots(figsize=(8, 2.5))
        plotting.plot_stat_map(
            img, threshold=threshold, display_mode="z", cut_coords=6,
            colorbar=True, cmap="cold_hot", axes=ax,
        )
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=90)
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def _render_corrp_thumb(corrp_path: str, mtime: float) -> Optional[bytes]:
    """Render corrp map thumbnail as PNG bytes (threshold at 0.95)."""
    try:
        from nilearn import plotting  # noqa: PLC0415
        import matplotlib  # noqa: PLC0415
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415

        img = nib.load(corrp_path)
        fig, ax = plt.subplots(figsize=(8, 2.5))
        plotting.plot_stat_map(
            img, threshold=0.95, vmax=1.0, display_mode="z", cut_coords=6,
            colorbar=True, cmap="autumn", axes=ax,
        )
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=90)
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None


# ============================================================================
# Per-cluster mean value extraction + plot
# ============================================================================

@st.cache_data(show_spinner=False)
def _extract_cluster_means(
    cluster_roi_path: str,
    cluster_roi_mtime: float,
    bids_root_str: str,
    pipeline: str,
    map_type: str,          # "Seed FC", "ALFF", "ReHo"
    seed_dir: Optional[str],
    measure: Optional[str],
    source: str,
    contrast_idx: int,
    summary_json_path: str,
) -> Optional[pd.DataFrame]:
    """Extract mean map value within the significant cluster ROI for each subject × session.

    Returns DataFrame with columns: subject, session, group, mean_val
    or None if extraction fails.
    """
    try:
        bids_root = Path(bids_root_str)

        # Load cluster ROI mask (binary)
        roi_img = nib.load(cluster_roi_path)
        roi_data = np.asanyarray(roi_img.dataobj)
        roi_mask = roi_data > 0
        if roi_mask.sum() == 0:
            return None

        # Get group membership from summary JSON
        subjects_control, subjects_walking = [], []
        summary_path = Path(summary_json_path)
        if summary_path.exists():
            meta = json.loads(summary_path.read_text())
            subjects_control = meta.get("subjects_control", [])
            subjects_walking = meta.get("subjects_walking", [])
        # Fallback: bids/participants.tsv
        if not subjects_control and not subjects_walking:
            tsv = bids_root / "bids" / "participants.tsv"
            if tsv.exists():
                ptdf = pd.read_csv(tsv, sep="\t")
                subjects_control = ptdf[ptdf["group"].str.lower() == "control"]["participant_id"].tolist()
                subjects_walking = ptdf[ptdf["group"].str.lower() == "walking"]["participant_id"].tolist()

        group_map = {s: "control" for s in subjects_control}
        group_map.update({s: "walking" for s in subjects_walking})

        rows = []
        for subject, group in group_map.items():
            for session in ("ses-01", "ses-02"):
                if map_type == "Seed FC":
                    # Look for zmap
                    map_dir = (bids_root / "derivatives" / "connectivity" / pipeline
                               / subject / session / "seed" / seed_dir)
                    candidates = sorted(map_dir.glob(f"*_measure-{measure}_seed-to-voxel_zmap.nii.gz")) if map_dir.exists() else []
                elif map_type in ("ALFF", "ReHo"):
                    stat_name = map_type.lower()
                    func_dir = (bids_root / "derivatives" / "preprocessing" / "xcpd"
                                / pipeline / subject / session / "func")
                    pattern = f"*_space-MNI152NLin6Asym_res-2_stat-{stat_name}_boldmap.nii.gz"
                    candidates = sorted(func_dir.glob(pattern)) if func_dir.exists() else []
                else:
                    candidates = []

                if not candidates:
                    continue
                try:
                    subj_img = nib.load(str(candidates[0]))
                    subj_data = np.asanyarray(subj_img.dataobj)
                    # Resample ROI if shape differs
                    if subj_data.shape != roi_mask.shape:
                        from nilearn.image import resample_to_img  # noqa: PLC0415
                        roi_r = resample_to_img(roi_img, subj_img, interpolation="nearest")
                        roi_mask_use = np.asanyarray(roi_r.dataobj) > 0
                    else:
                        roi_mask_use = roi_mask
                    mean_val = float(subj_data[roi_mask_use].mean())
                    rows.append({
                        "subject": subject,
                        "session": session,
                        "group": group,
                        "mean_val": mean_val,
                    })
                except Exception:
                    continue
        if not rows:
            return None
        return pd.DataFrame(rows)
    except Exception:
        return None


def _render_cluster_mean_plot(df: pd.DataFrame, title: str) -> None:
    """Render a plotly grouped box/strip plot: group × session → mean value."""
    if df is None or df.empty:
        st.info("No subject data available for mean value plot.")
        return

    session_label = {"ses-01": "Pre", "ses-02": "Post"}
    group_order = ["control", "walking"]
    session_order = ["ses-01", "ses-02"]

    fig = go.Figure()
    for group in group_order:
        for session in session_order:
            subset = df[(df["group"] == group) & (df["session"] == session)]
            if subset.empty:
                continue
            color = _GROUP_COLORS.get(group, {}).get("pre" if session == "ses-01" else "post", "#888")
            name = f"{group.capitalize()} {session_label.get(session, session)}"
            fig.add_trace(go.Box(
                y=subset["mean_val"].tolist(),
                name=name,
                marker_color=color,
                boxpoints="all",
                jitter=0.3,
                pointpos=-1.8,
                line=dict(width=2),
                marker=dict(size=6, opacity=0.7),
            ))

    fig.update_layout(
        title=dict(text=title, font=dict(size=13)),
        yaxis_title="Mean value in cluster ROI",
        xaxis_title="",
        height=380,
        margin=dict(l=50, r=20, t=50, b=40),
        legend=dict(orientation="h", y=-0.15),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    fig.update_yaxes(showgrid=True, gridcolor="#eee")
    st.plotly_chart(fig, use_container_width=True)


# ============================================================================
# Per-result card renderer
# ============================================================================

def _render_result_card(row: pd.Series, bids_root: Path) -> None:
    """Render one result row as an expanded card."""
    label = f"{row['type']}  ·  {row['label']}  ·  Contrast #{row['contrast_idx']}: {row['contrast_label']}  [{row['source']}]"
    st.markdown(f"##### {label}")

    # Seed ROI visualization (Seed FC only)
    if row["type"] == "Seed FC" and row["seed_dir"]:
        atlas_nii = str(bids_root / "atlases" / "schaefer200_7net.nii")
        atlas_txt = str(bids_root / "atlases" / "schaefer200_7net.txt")
        if Path(atlas_nii).exists():
            roi_png = _render_seed_roi_png(row["seed_dir"], atlas_nii, atlas_txt)
            if roi_png:
                st.image(roi_png, caption="Seed ROI", use_container_width=True)

    col_tstat, col_corrp = st.columns(2)
    with col_tstat:
        st.markdown("**T-statistic map**")
        try:
            mtime = Path(row["tstat_path"]).stat().st_mtime
            thumb = _render_tstat_thumb(row["tstat_path"], mtime)
            if thumb:
                st.image(thumb, use_container_width=True)
            else:
                st.warning("Could not render t-stat map.")
        except Exception as e:
            st.error(str(e))

    with col_corrp:
        if row.get("corrp_path"):
            st.markdown(f"**{row.get('corrp_label', 'Corrected p')} map**")
            try:
                mtime = Path(row["corrp_path"]).stat().st_mtime
                thumb = _render_corrp_thumb(row["corrp_path"], mtime)
                if thumb:
                    st.image(thumb, use_container_width=True)
            except Exception:
                st.warning("Could not render corrp map.")
        else:
            st.info("No corrected p-value map available.")

    # Cluster mean value plot
    if row.get("cluster_roi_path") and Path(str(row["cluster_roi_path"])).exists():
        st.markdown("**📈 Cluster ROI mean value (group × time)**")
        try:
            roi_mtime = Path(row["cluster_roi_path"]).stat().st_mtime
        except Exception:
            roi_mtime = 0.0

        mean_df = _extract_cluster_means(
            cluster_roi_path=str(row["cluster_roi_path"]),
            cluster_roi_mtime=roi_mtime,
            bids_root_str=str(bids_root),
            pipeline=row.get("pipeline", ""),
            map_type=row["type"],
            seed_dir=row.get("seed_dir"),
            measure=row.get("measure"),
            source=row["source"],
            contrast_idx=int(row["contrast_idx"]),
            summary_json_path=str(row.get("summary_json", "")),
        )
        _render_cluster_mean_plot(
            mean_df,
            title=f"Contrast #{row['contrast_idx']}: {row['contrast_label']}",
        )
    else:
        st.caption("ℹ️ Run cluster analysis in Group Results Viewer to enable mean-value plot.")

    st.divider()


# ============================================================================
# Main render
# ============================================================================

def render() -> None:
    st.title("📊 Group Results Summary")

    config = st.session_state.get("config") or {}
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

    pipeline = pipeline_picker(PAGE_KEY)

    # ── Scan controls ──────────────────────────────────────────────────────
    col_rescan, col_sigonly = st.columns([1, 1])
    with col_rescan:
        if st.button("🔄 Rescan results", key=f"{PAGE_KEY}_rescan"):
            st.session_state[f"{PAGE_KEY}_scan_tick"] = (
                st.session_state.get(f"{PAGE_KEY}_scan_tick", 0) + 1
            )
            st.session_state.pop(f"{PAGE_KEY}_inclusion", None)
    with col_sigonly:
        show_sig_only = st.toggle("Show significant only (p<0.05)", value=True,
                                  key=f"{PAGE_KEY}_sig_only")

    tick = st.session_state.get(f"{PAGE_KEY}_scan_tick", 0)

    with st.spinner("Scanning group results…"):
        df = _scan_all_results(str(bids_root), pipeline, tick)

    if df.empty:
        st.info(
            f"No group results found under `derivatives/connectivity/{pipeline}/group/`.\n\n"
            "Run group analyses via **📤 Submit Group Statistics** first."
        )
        return

    # Add pipeline column (for _extract_cluster_means)
    df["pipeline"] = pipeline

    # ── Summary metrics ────────────────────────────────────────────────────
    sig_count = int(df["significant"].sum())
    total_count = len(df)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total analyses", total_count)
    m2.metric("✅ Significant (p<0.05)", sig_count)
    m3.metric("Seed FC", int((df["type"] == "Seed FC").sum()))
    m4.metric("ALFF / ReHo", int(((df["type"] == "ALFF") | (df["type"] == "ReHo")).sum()))

    st.divider()

    # ── Filters ─────────────────────────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        type_filter = st.multiselect(
            "Map type", sorted(df["type"].unique()), default=sorted(df["type"].unique()),
            key=f"{PAGE_KEY}_type_filter",
        )
    with col_f2:
        contrast_filter = st.multiselect(
            "Contrast", sorted(df["contrast_idx"].unique()),
            default=sorted(df["contrast_idx"].unique()),
            format_func=lambda i: f"#{i} {_CONTRAST_LABELS.get(i, '')}",
            key=f"{PAGE_KEY}_contrast_filter",
        )
    with col_f3:
        source_filter = st.multiselect(
            "Source", ["randomise", "lmm"], default=["randomise", "lmm"],
            key=f"{PAGE_KEY}_source_filter",
        )

    filtered = df.copy()
    if type_filter:
        filtered = filtered[filtered["type"].isin(type_filter)]
    if contrast_filter:
        filtered = filtered[filtered["contrast_idx"].isin(contrast_filter)]
    if source_filter:
        filtered = filtered[filtered["source"].isin(source_filter)]
    if show_sig_only:
        filtered = filtered[filtered["significant"]]

    if filtered.empty:
        st.info("No results match the current filters.")
        return

    # ── Selection table ──────────────────────────────────────────────────────
    st.markdown("### Select analyses to view")
    st.caption("Default selection: all significant results. Uncheck to exclude.")

    filtered = filtered.copy()
    filtered["_row_id"] = (
        filtered["type"] + "|" +
        filtered["label"].fillna("") + "|" +
        filtered["contrast_idx"].astype(str) + "|" +
        filtered["source"]
    )

    inclusion_state: dict = st.session_state.get(f"{PAGE_KEY}_inclusion", {})
    filtered["Include"] = filtered.apply(
        lambda r: inclusion_state.get(r["_row_id"], bool(r["significant"])),
        axis=1,
    )

    display_cols = ["Include", "type", "label", "contrast_idx", "contrast_label", "source", "significant", "max_corrp"]
    col_rename = {
        "type": "Type", "label": "Analysis", "contrast_idx": "#",
        "contrast_label": "Contrast", "source": "Source",
        "significant": "Sig.", "max_corrp": "Peak corrp",
    }
    editor_df = filtered[display_cols].rename(columns=col_rename).copy()
    editor_df["Peak corrp"] = editor_df["Peak corrp"].round(3)

    edited = st.data_editor(
        editor_df,
        column_config={
            "Include": st.column_config.CheckboxColumn("Include", default=True, width="small"),
            "#": st.column_config.NumberColumn("#", width="small", format="%d"),
            "Sig.": st.column_config.CheckboxColumn("Sig.", disabled=True, width="small"),
            "Peak corrp": st.column_config.NumberColumn("Peak corrp", format="%.3f"),
        },
        use_container_width=True,
        hide_index=True,
        key=f"{PAGE_KEY}_editor",
        disabled=["Type", "Analysis", "#", "Contrast", "Source", "Sig.", "Peak corrp"],
    )

    # Persist inclusion state
    new_inclusion = dict(zip(filtered["_row_id"], edited["Include"]))
    st.session_state[f"{PAGE_KEY}_inclusion"] = new_inclusion

    # ── Render selected results ──────────────────────────────────────────────
    selected_ids = set(k for k, v in new_inclusion.items() if v)
    selected_rows = filtered[filtered["_row_id"].isin(selected_ids)]

    if selected_rows.empty:
        st.info("No analyses selected. Check 'Include' boxes above to view results.")
        return

    st.markdown(f"### Results ({len(selected_rows)} selected)")

    for _, row in selected_rows.iterrows():
        with st.expander(
            f"{'✅' if row['significant'] else '⚠️'}  {row['type']}  ·  "
            f"{row['label']}  ·  #{row['contrast_idx']} {row['contrast_label']}  [{row['source']}]",
            expanded=True,
        ):
            _render_result_card(row, bids_root)


if __name__ == "__main__":
    render()
