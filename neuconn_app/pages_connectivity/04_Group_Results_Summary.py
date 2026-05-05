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
from utils.group_cluster_analysis import ClusterResult, parse_cluster_table

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
                significant = False
                needs_cluster_run = False
                if cluster_roi_path:
                    try:
                        zd = np.asanyarray(nib.load(cluster_roi_path).dataobj)
                        significant = bool((zd > 0).sum() > 0)
                        needs_cluster_run = significant
                    except Exception:
                        pass
            else:
                cluster_roi_path = corrp_path  # use corrp thresholded image
                significant = max_corrp > 0.95 if not np.isnan(max_corrp) else False
                needs_cluster_run = (corrp_label == "GRF cluster" and not significant)
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
                "significant": significant,
                "needs_cluster_run": needs_cluster_run,
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
def _render_seed_roi_png(seed_dir: str, bids_root_str: str) -> Optional[bytes]:
    """Render seed ROI using make_seed_preview_png from seed_viz."""
    from utils.seed_viz import make_seed_preview_png
    m = re.match(r"atlas-([^_]+)_parcel-(.+)$", seed_dir)
    if m:
        token = f"atlas-{m.group(1)}:{m.group(2)}"
    else:
        ms = re.match(r"sphere-([-\d]+)_([-\d]+)_([-\d]+)_r(\d+)$", seed_dir)
        if ms:
            token = f"sphere:{ms.group(1)},{ms.group(2)},{ms.group(3)},r={ms.group(4)}"
        else:
            return None
    return make_seed_preview_png(token, bids_root_str)


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
# Per-cluster PNG overlay
# ============================================================================

@st.cache_data(show_spinner=False)
def _render_single_cluster_png(
    cluster_index_path: str,
    cluster_label: int,
    tstat_path: str,
    ci_mtime: float,
    ts_mtime: float,
    threshold: float = 2.3,
) -> Optional[bytes]:
    """Render a single cluster overlaid on t-stat map."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from nilearn import plotting
        from nibabel.affines import apply_affine

        ci_img = nib.load(cluster_index_path)
        ci_data = np.asanyarray(ci_img.dataobj)
        mask_data = (ci_data == cluster_label).astype(np.float32)
        if mask_data.sum() == 0:
            return None
        mask_img = nib.Nifti1Image(mask_data, ci_img.affine)

        tstat_img = nib.load(tstat_path)

        vox_coords = np.argwhere(mask_data > 0)
        centroid_vox = vox_coords.mean(axis=0)
        cx, cy, cz = apply_affine(ci_img.affine, centroid_vox)

        fig = plt.figure(figsize=(10, 3))
        display = plotting.plot_stat_map(
            tstat_img,
            threshold=threshold,
            display_mode="ortho",
            cut_coords=(float(cx), float(cy), float(cz)),
            colorbar=True,
            cmap="cold_hot",
            figure=fig,
        )
        display.add_contours(mask_img, levels=[0.5], colors=["yellow"], linewidths=[1.5])

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=90)
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def _extract_single_cluster_means(
    cluster_index_path: str,
    cluster_label: int,
    ci_mtime: float,
    bids_root_str: str,
    pipeline: str,
    map_type: str,
    seed_dir: Optional[str],
    measure: Optional[str],
    summary_json_path: str,
) -> Optional[pd.DataFrame]:
    """Extract mean map value within one specific cluster for each subject × session."""
    try:
        bids_root = Path(bids_root_str)
        ci_img = nib.load(cluster_index_path)
        ci_data = np.asanyarray(ci_img.dataobj)
        roi_mask = (ci_data == cluster_label)
        if roi_mask.sum() == 0:
            return None

        subjects_control, subjects_walking = [], []
        summary_path = Path(summary_json_path)
        if summary_path.exists():
            meta = json.loads(summary_path.read_text())
            subjects_control = meta.get("subjects_control", [])
            subjects_walking = meta.get("subjects_walking", [])
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
                    if subj_data.shape != roi_mask.shape:
                        from nilearn.image import resample_to_img
                        roi_r = resample_to_img(
                            nib.Nifti1Image(roi_mask.astype(np.float32), ci_img.affine),
                            subj_img, interpolation="nearest"
                        )
                        roi_mask_use = np.asanyarray(roi_r.dataobj) > 0
                    else:
                        roi_mask_use = roi_mask
                    mean_val = float(subj_data[roi_mask_use].mean())
                    rows.append({"subject": subject, "session": session,
                                 "group": group, "mean_val": mean_val})
                except Exception:
                    continue
        if not rows:
            return None
        return pd.DataFrame(rows)
    except Exception:
        return None


def _add_atlasq_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Add 'Label' column to cluster table using Harvard-Oxford atlasquery."""
    from utils.group_cluster_analysis import query_atlasq_label
    if df.empty:
        return df
    df = df.copy()
    labels = []
    for _, row in df.iterrows():
        try:
            x = int(round(row.get("X(mm)", 0)))
            y = int(round(row.get("Y(mm)", 0)))
            z = int(round(row.get("Z(mm)", 0)))
            labels.append(query_atlasq_label(x, y, z))
        except Exception:
            labels.append("Unknown")
    df["Label"] = labels
    return df


def _render_grf_controls_and_run(
    row_id: str,
    row: pd.Series,
    bids_root: Path,
) -> Optional[ClusterResult]:
    """Show cluster analysis parameter controls and run button.

    Returns ClusterResult if one is stored in session state, else None.
    """
    from utils.group_cluster_analysis import run_grf_cluster, run_tfce_cluster, fsl_available

    corrp_label = row.get("corrp_label", "")
    is_tfce = corrp_label == "TFCE"

    with st.expander("🔧 Cluster Analysis Settings", expanded=False):
        if is_tfce:
            col1, col2, col3 = st.columns(3)
            corrp_thr = col1.slider(
                "Corrp threshold", 0.90, 0.99, 0.95, 0.01,
                key=f"{PAGE_KEY}_corrp_thr_{row_id}",
                help="TFCE corrected p-value threshold (1-p). 0.95 = p<0.05",
            )
            cluster_z_thr = col2.number_input(
                "Min cluster z", value=0.0, min_value=0.0, max_value=5.0, step=0.1,
                key=f"{PAGE_KEY}_cluster_z_{row_id}",
                help="Minimum z within cluster (0 = auto from tstat range)",
            )
            k_min = col3.number_input(
                "Min cluster size (voxels)", value=50, min_value=1, max_value=5000, step=10,
                key=f"{PAGE_KEY}_k_{row_id}",
            )
            params_key = f"tfce_{corrp_thr:.2f}_{cluster_z_thr:.1f}_{int(k_min)}"
        else:
            col1, col2, col3, col4, col5 = st.columns(5)
            z_thr = col1.number_input(
                "Z threshold", value=2.3, min_value=0.5, max_value=6.0, step=0.1,
                key=f"{PAGE_KEY}_z_thr_{row_id}",
            )
            p_thr = col2.number_input(
                "p threshold (FWE)", value=0.05, min_value=0.001, max_value=0.1, step=0.005,
                format="%.3f", key=f"{PAGE_KEY}_p_thr_{row_id}",
            )
            k_min = col3.number_input(
                "Min cluster size (voxels)", value=1, min_value=1, max_value=5000, step=10,
                key=f"{PAGE_KEY}_k_{row_id}",
            )
            smoothness = col4.radio(
                "Smoothness est.", ["z", "r"], index=0,
                key=f"{PAGE_KEY}_smooth_{row_id}",
                help="'z': from z/t-stat map | 'r': from residuals (if available)",
            )
            tail = col5.radio(
                "Tail", ["both", "pos", "neg"], index=0,
                key=f"{PAGE_KEY}_tail_{row_id}",
            )
            params_key = f"grf_{z_thr:.2f}_{p_thr:.3f}_{int(k_min)}_{smoothness}_{tail}"

        state_key = f"{PAGE_KEY}_cluster_{row_id}_{params_key}"

        mask_path = bids_root / "atlases" / "MNI152_T1_2mm_brain_mask_dil.nii.gz"
        if not mask_path.exists():
            st.warning(f"Brain mask not found: {mask_path}")

        if st.button("▶ Run Cluster Analysis", key=f"{PAGE_KEY}_run_{row_id}"):
            if not fsl_available():
                st.error("FSL not available on this machine.")
                st.session_state[state_key] = ClusterResult(error="FSL not available")
            elif not mask_path.exists():
                st.error(f"Brain mask not found: {mask_path}")
                st.session_state[state_key] = ClusterResult(error=f"Mask not found: {mask_path}")
            else:
                tstat_path = Path(row["tstat_path"])
                out_dir = Path(row["out_dir"]) / "cluster_analysis" / f"contrast{int(row['contrast_idx'])}"
                with st.spinner("Running cluster analysis…"):
                    if is_tfce and row.get("corrp_path"):
                        result = run_tfce_cluster(
                            corrp_path=Path(row["corrp_path"]),
                            tstat_path=tstat_path,
                            out_dir=out_dir,
                            corrp_thr=corrp_thr,
                            cluster_z_thr=cluster_z_thr if cluster_z_thr > 0 else None,
                            k=int(k_min),
                        )
                    else:
                        result = run_grf_cluster(
                            tstat_path=tstat_path,
                            mask_path=mask_path,
                            out_dir=out_dir,
                            z_thr=float(z_thr),
                            p_thr=float(p_thr),
                            k=int(k_min),
                            smoothness=smoothness,
                            tail=tail,
                        )
                if result.error:
                    st.error(f"Cluster analysis error: {result.error}")
                else:
                    n_clusters = sum(len(t) for t in result.tables.values() if t is not None)
                    if n_clusters == 0:
                        st.info("No significant clusters found with these parameters.")
                    else:
                        st.success(f"Found {n_clusters} cluster(s).")
                st.session_state[state_key] = result
                st.rerun()

    return st.session_state.get(state_key)


def _render_cluster_details(
    result: ClusterResult, row_id: str, row: pd.Series, bids_root: Path
) -> None:
    """Show cluster table with labels + per-cluster overlay and mean plot."""
    for tail_name, tdf in result.tables.items():
        if tdf is None or tdf.empty:
            continue
        cluster_index_path = (
            str(result.cluster_img.get(tail_name))
            if result.cluster_img.get(tail_name)
            else None
        )

        st.markdown(f"**{tail_name.capitalize()} clusters** — {len(tdf)} clusters")

        with st.spinner("Querying atlas labels…"):
            tdf_labeled = _add_atlasq_labels(tdf)

        display_cols = [
            c for c in ["Cluster", "Voxels", "p(FWE)", "Peak Z", "X(mm)", "Y(mm)", "Z(mm)", "Label"]
            if c in tdf_labeled.columns
        ]
        st.dataframe(tdf_labeled[display_cols], use_container_width=True, hide_index=True)

        if cluster_index_path and Path(cluster_index_path).exists():
            ci_mtime = Path(cluster_index_path).stat().st_mtime
            ts_mtime = Path(row["tstat_path"]).stat().st_mtime

            for _, crow in tdf_labeled.iterrows():
                cluster_label = int(crow.get("Cluster", 1))
                nvox = int(crow.get("Voxels", 0))
                peak_z = float(crow.get("Peak Z", 0))
                peak_x = crow.get("X(mm)", 0)
                peak_y = crow.get("Y(mm)", 0)
                peak_z_coord = crow.get("Z(mm)", 0)
                label_name = crow.get("Label", "Unknown")

                with st.expander(
                    f"Cluster {cluster_label} — {nvox} voxels  |  Peak Z={peak_z:.2f} @ "
                    f"({peak_x:.0f},{peak_y:.0f},{peak_z_coord:.0f})  |  {label_name}",
                    expanded=False,
                ):
                    col_brain, col_plot = st.columns(2)
                    with col_brain:
                        st.markdown("**Brain overlay**")
                        brain_png = _render_single_cluster_png(
                            cluster_index_path, cluster_label,
                            row["tstat_path"], ci_mtime, ts_mtime,
                        )
                        if brain_png:
                            st.image(brain_png, use_container_width=True)
                        else:
                            st.info("Could not render cluster overlay.")

                    with col_plot:
                        st.markdown("**Group × Time plot**")
                        df_means = _extract_single_cluster_means(
                            cluster_index_path=cluster_index_path,
                            cluster_label=cluster_label,
                            ci_mtime=ci_mtime,
                            bids_root_str=str(bids_root),
                            pipeline=row.get("pipeline", ""),
                            map_type=row["type"],
                            seed_dir=row.get("seed_dir"),
                            measure=row.get("measure"),
                            summary_json_path=str(row.get("summary_json", "")),
                        )
                        if df_means is not None:
                            _render_cluster_mean_plot(
                                df_means,
                                title=f"Cluster {cluster_label}: {label_name}",
                            )
                        else:
                            st.info("No subject data available.")
        else:
            st.info("Run cluster analysis above to see per-cluster details.")


# ============================================================================
# Per-result card renderer
# ============================================================================

def _render_result_card(row_id: str, row: pd.Series, bids_root: Path) -> None:
    """Render one result row as an expanded card."""
    label = (
        f"{row['type']}  ·  {row['label']}  ·  "
        f"Contrast #{row['contrast_idx']}: {row['contrast_label']}  [{row['source']}]"
    )
    st.markdown(f"##### {label}")

    col_roi, col_tstat = st.columns([1, 2])
    with col_roi:
        if row["type"] == "Seed FC" and row.get("seed_dir"):
            st.markdown("**Seed ROI**")
            roi_png = _render_seed_roi_png(str(row["seed_dir"]), str(bids_root))
            if roi_png:
                st.image(roi_png, use_container_width=True)
            else:
                st.caption("Could not render seed ROI.")

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

    if row.get("corrp_path"):
        col_corrp, _ = st.columns([2, 1])
        with col_corrp:
            st.markdown(f"**{row.get('corrp_label', 'Corrected p')} map**")
            try:
                mtime = Path(row["corrp_path"]).stat().st_mtime
                thumb = _render_corrp_thumb(row["corrp_path"], mtime)
                if thumb:
                    st.image(thumb, use_container_width=True)
            except Exception:
                st.warning("Could not render corrp map.")

    st.divider()
    result = _render_grf_controls_and_run(row_id, row, bids_root)
    if result is not None and not result.error:
        _render_cluster_details(result, row_id, row, bids_root)
    elif result is None:
        # Load existing cluster analysis from disk if already run
        out_dir = Path(row["out_dir"])
        ci_dir = out_dir / "cluster_analysis" / f"contrast{int(row['contrast_idx'])}"
        has_existing = (
            any(ci_dir.glob("grf_*_cluster_index.nii.gz")) if ci_dir.exists() else False
        )
        if has_existing:
            tables: dict = {}
            imgs: dict = {}
            for t in ("pos", "neg"):
                txt = ci_dir / f"grf_{t}_cluster.txt"
                idx_nii = ci_dir / f"grf_{t}_cluster_index.nii.gz"
                if txt.exists():
                    tables[t] = parse_cluster_table(txt)
                    imgs[t] = idx_nii if idx_nii.exists() else None
            if tables:
                cached_result = ClusterResult(tables=tables, cluster_img=imgs)
                _render_cluster_details(cached_result, row_id, row, bids_root)

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
    needs_run_count = int(df["needs_cluster_run"].sum()) if "needs_cluster_run" in df.columns else 0
    total_count = len(df)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total analyses", total_count)
    m2.metric("✅ Significant (p<0.05)", sig_count)
    m3.metric("🔄 Needs cluster run", needs_run_count)
    m4.metric("Seed FC", int((df["type"] == "Seed FC").sum()))
    m5.metric("ALFF / ReHo", int(((df["type"] == "ALFF") | (df["type"] == "ReHo")).sum()))

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
        filtered = filtered[filtered["significant"] | filtered["needs_cluster_run"]]

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
        lambda r: inclusion_state.get(r["_row_id"], bool(r["significant"] or r.get("needs_cluster_run", False))),
        axis=1,
    )

    display_cols = ["Include", "type", "label", "contrast_idx", "contrast_label", "source", "significant", "needs_cluster_run", "max_corrp"]
    col_rename = {
        "type": "Type", "label": "Analysis", "contrast_idx": "#",
        "contrast_label": "Contrast", "source": "Source",
        "significant": "Sig.", "needs_cluster_run": "Needs run", "max_corrp": "Peak corrp",
    }
    editor_df = filtered[display_cols].rename(columns=col_rename).copy()
    editor_df["Peak corrp"] = editor_df["Peak corrp"].round(3)

    edited = st.data_editor(
        editor_df,
        column_config={
            "Include": st.column_config.CheckboxColumn("Include", default=True, width="small"),
            "#": st.column_config.NumberColumn("#", width="small", format="%d"),
            "Sig.": st.column_config.CheckboxColumn("Sig.", disabled=True, width="small"),
            "Needs run": st.column_config.CheckboxColumn("Needs run", disabled=True, width="small"),
            "Peak corrp": st.column_config.NumberColumn("Peak corrp", format="%.3f"),
        },
        use_container_width=True,
        hide_index=True,
        key=f"{PAGE_KEY}_editor",
        disabled=["Type", "Analysis", "#", "Contrast", "Source", "Sig.", "Needs run", "Peak corrp"],
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
        row_id = row["_row_id"]
        sig_icon = "✅" if row["significant"] else ("🔄" if row.get("needs_cluster_run") else "⚠️")
        with st.expander(
            f"{sig_icon}  {row['type']}  ·  "
            f"{row['label']}  ·  #{row['contrast_idx']} {row['contrast_label']}  [{row['source']}]",
            expanded=False,
        ):
            _render_result_card(row_id, row, bids_root)


if __name__ == "__main__":
    render()
