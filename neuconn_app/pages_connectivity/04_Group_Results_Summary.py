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
import base64
from datetime import datetime
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
from utils.group_cluster_analysis import (
    ClusterResult, parse_cluster_table,
    run_lmm_cluster, run_grf_cluster, run_tfce_cluster, fsl_available,
)

PAGE_KEY = "group_results_summary"

_DEFAULT_GRF_PARAMS = {"z_thr": 2.3, "p_thr": 0.05, "k": 1, "smoothness": "z", "tail": "both"}
_DEFAULT_TFCE_PARAMS = {"corrp_thr": 0.95, "cluster_z_thr": 0.0, "k": 50}

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


def _labels_cache_path(row: pd.Series, tail: str) -> Path:
    """Return disk-cache path for labeled cluster CSV."""
    out_dir = Path(row["out_dir"]) / "cluster_analysis" / f"contrast{int(row['contrast_idx'])}"
    prefix = "lmm" if row["source"] == "lmm" else f"grf_{tail}" if tail != "pos" or row["source"] != "lmm" else "lmm"
    if row["source"] == "lmm":
        return out_dir / "lmm_cluster_labeled.csv"
    else:
        return out_dir / f"{tail}_cluster_labeled.csv"


def _add_atlasq_labels(df: pd.DataFrame, cache_path: Optional[Path] = None) -> pd.DataFrame:
    """Add 'Label' column using AAL3v1 (fast batch) with Harvard-Oxford fallback for NAs.

    If cache_path is provided, loads from CSV if it exists; otherwise queries atlasq
    and saves the result to cache_path for subsequent renders.
    """
    from utils.group_cluster_analysis import query_atlasq_labels_batch
    if df.empty:
        return df
    if "Label" in df.columns:
        return df

    if cache_path and cache_path.exists():
        try:
            cached = pd.read_csv(cache_path)
            if "Label" in cached.columns and len(cached) == len(df):
                df = df.copy()
                df["Label"] = cached["Label"].values
                return df
        except Exception:
            pass

    coords = [
        (int(round(r.get("X(mm)", 0))), int(round(r.get("Y(mm)", 0))), int(round(r.get("Z(mm)", 0))))
        for _, r in df.iterrows()
    ]
    labels = query_atlasq_labels_batch(tuple(coords))
    df = df.copy()
    df["Label"] = labels

    if cache_path:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(cache_path, index=False)
        except Exception:
            pass
    return df


def _run_cluster_for_row(
    row: pd.Series,
    bids_root: Path,
    grf_params: dict | None = None,
    tfce_params: dict | None = None,
) -> ClusterResult:
    """Run appropriate cluster analysis for a result row.

    For LMM: uses run_lmm_cluster on cN_zthresh.nii.gz (already GRF-corrected).
    For randomise TFCE: uses run_tfce_cluster.
    For randomise GRF: uses run_grf_cluster.
    """
    if not fsl_available():
        return ClusterResult(error="FSL not available")

    source = row["source"]
    corrp_label = row.get("corrp_label", "")
    contrast_idx = int(row["contrast_idx"])
    out_dir = Path(row["out_dir"]) / "cluster_analysis" / f"contrast{contrast_idx}"

    if source == "lmm":
        zthresh_path = Path(row["out_dir"]) / f"c{contrast_idx}_zthresh.nii.gz"
        if not zthresh_path.exists():
            return ClusterResult(error=f"zthresh not found: {zthresh_path}")
        k = (grf_params or _DEFAULT_GRF_PARAMS).get("k", 1)
        return run_lmm_cluster(zthresh_path, out_dir, min_voxels=int(k))

    elif corrp_label == "TFCE" and row.get("corrp_path"):
        p = tfce_params or _DEFAULT_TFCE_PARAMS
        return run_tfce_cluster(
            corrp_path=Path(row["corrp_path"]),
            tstat_path=Path(row["tstat_path"]),
            out_dir=out_dir,
            corrp_thr=float(p.get("corrp_thr", 0.95)),
            cluster_z_thr=float(p.get("cluster_z_thr", 0.0)) or None,
            k=int(p.get("k", 50)),
        )

    else:
        p = grf_params or _DEFAULT_GRF_PARAMS
        mask_path = bids_root / "atlases" / "MNI152_T1_2mm_brain_mask_dil.nii.gz"
        if not mask_path.exists():
            return ClusterResult(error=f"Brain mask not found: {mask_path}")
        return run_grf_cluster(
            tstat_path=Path(row["tstat_path"]),
            mask_path=mask_path,
            out_dir=out_dir,
            z_thr=float(p.get("z_thr", 2.3)),
            p_thr=float(p.get("p_thr", 0.05)),
            k=int(p.get("k", 1)),
            smoothness=str(p.get("smoothness", "z")),
            tail=str(p.get("tail", "both")),
        )


def _load_cluster_from_disk(row: pd.Series) -> Optional[ClusterResult]:
    """Load existing cluster analysis results from the cluster_analysis directory on disk.

    Prefers labeled CSV (with 'Label' column) over raw cluster text, so atlas labels
    are never re-queried on subsequent renders.
    """
    contrast_idx = int(row["contrast_idx"])
    source = row["source"]
    out_dir = Path(row["out_dir"]) / "cluster_analysis" / f"contrast{contrast_idx}"

    def _try_labeled_csv(csv_path: Path, txt_path: Path) -> Optional[pd.DataFrame]:
        """Return labeled DataFrame from CSV if valid, else parse raw txt."""
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
                if not df.empty:
                    return df
            except Exception:
                pass
        if txt_path.exists():
            df = parse_cluster_table(txt_path)
            if "MAX" in df.columns and "Peak Z" not in df.columns:
                df = df.rename(columns={
                    "MAX": "Peak Z", "MAX X (mm)": "X(mm)",
                    "MAX Y (mm)": "Y(mm)", "MAX Z (mm)": "Z(mm)",
                })
            return df if not df.empty else None
        return None

    if source == "lmm":
        idx = out_dir / "lmm_cluster_index.nii.gz"
        table = _try_labeled_csv(out_dir / "lmm_cluster_labeled.csv", out_dir / "lmm_cluster.txt")
        if table is not None and idx.exists():
            return ClusterResult(
                tables={"pos": table},
                cluster_img={"pos": idx},
                params={"source": "lmm_zthresh"},
            )
    else:
        # GRF pos/neg
        tables, imgs = {}, {}
        for t in ("pos", "neg"):
            idx = out_dir / f"grf_{t}_cluster_index.nii.gz"
            table = _try_labeled_csv(out_dir / f"{t}_cluster_labeled.csv", out_dir / f"grf_{t}_cluster.txt")
            if table is not None:
                tables[t] = table
                imgs[t] = idx if idx.exists() else None
        if tables:
            return ClusterResult(tables=tables, cluster_img=imgs, params={"source": "grf_disk"})
        # TFCE
        idx = out_dir / "cluster_index.nii.gz"
        table = _try_labeled_csv(out_dir / "pos_cluster_labeled.csv", out_dir / "tstat_cluster.txt")
        if table is not None:
            return ClusterResult(
                tables={"pos": table},
                cluster_img={"pos": idx if idx.exists() else None},
                params={"source": "tfce_disk"},
            )
    return None


def _render_grf_controls_and_run(
    row_id: str,
    row: pd.Series,
    bids_root: Path,
) -> Optional[ClusterResult]:
    """Show cluster analysis controls and run button. Returns current ClusterResult if available."""
    source = row["source"]
    corrp_label = row.get("corrp_label", "")
    is_tfce = corrp_label == "TFCE"
    is_lmm = source == "lmm"
    state_key = f"{PAGE_KEY}_cluster_{row_id}"
    params_key = f"{PAGE_KEY}_cluster_params_{row_id}"

    # Load last-used params (default if not yet run)
    last_params: dict = st.session_state.get(params_key, {})

    with st.expander("🔧 Cluster Analysis Settings", expanded=False):
        if is_lmm:
            k_min = st.number_input(
                "Min cluster size (voxels)", value=int(last_params.get("k", 1)),
                min_value=1, max_value=5000, step=10,
                key=f"{PAGE_KEY}_k_{row_id}",
            )
            run_params = {"k": k_min}
        elif is_tfce:
            col1, col2, col3 = st.columns(3)
            corrp_thr = col1.slider(
                "Corrp threshold", 0.90, 0.99,
                float(last_params.get("corrp_thr", 0.95)), 0.01,
                key=f"{PAGE_KEY}_corrp_thr_{row_id}",
            )
            cluster_z_thr = col2.number_input(
                "Min cluster z", value=float(last_params.get("cluster_z_thr", 0.0)),
                min_value=0.0, max_value=5.0, step=0.1,
                key=f"{PAGE_KEY}_cluster_z_{row_id}",
            )
            k_min = col3.number_input(
                "Min cluster size (voxels)", value=int(last_params.get("k", 50)),
                min_value=1, max_value=5000, step=10,
                key=f"{PAGE_KEY}_k_{row_id}",
            )
            run_params = {"corrp_thr": corrp_thr, "cluster_z_thr": cluster_z_thr, "k": k_min}
        else:
            col1, col2, col3, col4, col5 = st.columns(5)
            z_thr = col1.number_input(
                "Z threshold", value=float(last_params.get("z_thr", 2.3)),
                min_value=0.5, max_value=6.0, step=0.1, key=f"{PAGE_KEY}_z_thr_{row_id}",
            )
            p_thr = col2.number_input(
                "p threshold", value=float(last_params.get("p_thr", 0.05)),
                min_value=0.001, max_value=0.1, step=0.005, format="%.3f",
                key=f"{PAGE_KEY}_p_thr_{row_id}",
            )
            k_min = col3.number_input(
                "Min voxels", value=int(last_params.get("k", 1)),
                min_value=1, max_value=5000, step=10, key=f"{PAGE_KEY}_k_{row_id}",
            )
            smoothness = col4.radio(
                "Smoothness", ["z", "r"],
                index=["z", "r"].index(last_params.get("smoothness", "z")),
                key=f"{PAGE_KEY}_smooth_{row_id}",
            )
            tail = col5.radio(
                "Tail", ["both", "pos", "neg"],
                index=["both", "pos", "neg"].index(last_params.get("tail", "both")),
                key=f"{PAGE_KEY}_tail_{row_id}",
            )
            run_params = {"z_thr": z_thr, "p_thr": p_thr, "k": k_min,
                          "smoothness": smoothness, "tail": tail}

        if st.button("▶ Re-run Cluster Analysis", key=f"{PAGE_KEY}_run_{row_id}"):
            with st.spinner("Running…"):
                result = _run_cluster_for_row(
                    row, bids_root,
                    grf_params=run_params if not is_tfce else None,
                    tfce_params=run_params if is_tfce else None,
                )
            st.session_state[state_key] = result
            st.session_state[params_key] = run_params
            if result.error:
                st.error(f"Error: {result.error}")
            else:
                n = sum(len(t) for t in result.tables.values() if t is not None and not t.empty)
                st.success(f"Found {n} cluster(s).")
            st.rerun()

    # Load from session state OR from disk
    result = st.session_state.get(state_key)
    if result is None:
        result = _load_cluster_from_disk(row)
        if result is not None:
            st.session_state[state_key] = result

    return result


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

        cache_path = _labels_cache_path(row, tail_name)
        if "Label" not in tdf.columns:
            if not cache_path.exists():
                # Labels not cached yet — don't block page render; let user trigger explicitly
                if st.button(
                    "🔍 Load atlas labels",
                    key=f"{PAGE_KEY}_labels_{row_id}_{tail_name}",
                    help="Query AAL3v1 + Harvard-Oxford for peak coordinates (~5–10s). Cached to disk afterwards.",
                ):
                    with st.spinner("Querying atlas labels (AAL3v1 + Harvard-Oxford)…"):
                        tdf_labeled = _add_atlasq_labels(tdf, cache_path=cache_path)
                    state_key = f"{PAGE_KEY}_cluster_{row_id}"
                    if state_key in st.session_state:
                        st.session_state[state_key].tables[tail_name] = tdf_labeled
                    st.rerun()
                else:
                    tdf_labeled = tdf.copy()
                    tdf_labeled["Label"] = "—"
            else:
                # Cache on disk — load instantly, no subprocess
                tdf_labeled = _add_atlasq_labels(tdf, cache_path=cache_path)
                state_key = f"{PAGE_KEY}_cluster_{row_id}"
                if state_key in st.session_state:
                    st.session_state[state_key].tables[tail_name] = tdf_labeled
        else:
            tdf_labeled = tdf

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

def _delete_group_analysis(row: pd.Series) -> None:
    """Delete the analysis output directory and clear session_state cluster cache."""
    import shutil
    out_dir = Path(row["out_dir"])
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    # Clear cluster cache for this row
    row_id = row.get("_row_id")
    if row_id:
        for key in [f"{PAGE_KEY}_cluster_{row_id}", f"{PAGE_KEY}_cluster_params_{row_id}"]:
            st.session_state.pop(key, None)
    # Invalidate filesystem scan cache
    _scan_all_results.clear()

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

    # ── Per-card delete ──────────────────────────────────────────────────────
    st.divider()
    confirm_key = f"{PAGE_KEY}_del_confirm_{row_id}"
    if st.session_state.get(confirm_key):
        st.warning(
            f"⚠️ This will permanently delete **{row['source']}** outputs for **{row['label']}** "
            f"(contrast #{row['contrast_idx']}). This cannot be undone."
        )
        col_yes, col_no, _ = st.columns([1, 1, 4])
        if col_yes.button("✅ Confirm delete", key=f"{PAGE_KEY}_del_yes_{row_id}"):
            _delete_group_analysis(row)
            st.session_state.pop(confirm_key, None)
            st.success("Deleted. Refreshing…")
            st.rerun()
        if col_no.button("❌ Cancel", key=f"{PAGE_KEY}_del_no_{row_id}"):
            st.session_state.pop(confirm_key, None)
            st.rerun()
    else:
        if st.button(
            "🗑️ Delete this analysis", key=f"{PAGE_KEY}_del_{row_id}",
            help="Remove the analysis output directory from disk. The analysis can be re-run afterwards.",
            type="secondary",
        ):
            st.session_state[confirm_key] = True
            st.rerun()


# ============================================================================
# Auto-run and HTML report
# ============================================================================

def _render_autorun_section(df: pd.DataFrame, bids_root: Path) -> None:
    """Auto-run button and HTML download."""
    needs_run = df.get("needs_cluster_run", df["significant"])
    eligible = df[df["significant"] | needs_run]
    n_eligible = len(eligible)

    col_run, col_dl = st.columns([2, 1])
    with col_run:
        if st.button(
            f"🚀 Auto-run cluster analysis ({n_eligible} results, default settings)",
            key=f"{PAGE_KEY}_autorun_all",
            help="Runs cluster analysis for all significant results using default parameters. "
                 "You can fine-tune per-result afterwards.",
        ):
            prog = st.progress(0, text="Running cluster analyses…")
            errors = []
            for i, (_, row) in enumerate(eligible.iterrows()):
                row_id = row["_row_id"]
                state_key = f"{PAGE_KEY}_cluster_{row_id}"
                label_short = str(row.get("label", ""))[:35]
                prog.progress(i / max(n_eligible, 1), text=f"[{i+1}/{n_eligible}] {label_short}…")
                result = _run_cluster_for_row(row, bids_root)
                st.session_state[state_key] = result
                if result.error:
                    errors.append(f"{label_short}: {result.error}")
            prog.progress(1.0, text=f"Done — {n_eligible} analyses completed.")
            if errors:
                st.warning(f"{len(errors)} error(s):\n" + "\n".join(errors[:5]))
            else:
                st.success("All cluster analyses complete. Fine-tune per-result below.")
            st.rerun()

    with col_dl:
        st.caption("HTML report available below after selecting analyses.")


def _img_to_b64(png_bytes: Optional[bytes]) -> str:
    """Convert PNG bytes to base64 data URI."""
    if not png_bytes:
        return ""
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode()


@st.cache_data(show_spinner=False)
def _render_cluster_mean_plot_png(df: pd.DataFrame, title: str) -> Optional[bytes]:
    """Render group×time mean plot as PNG bytes (for HTML export)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        session_labels = {"ses-01": "Pre", "ses-02": "Post"}
        groups = [("control", "#4C72B0", "#85A4D4"), ("walking", "#C44E52", "#E89A9C")]
        fig, ax = plt.subplots(figsize=(6, 4))

        x_pos = 0
        xticks, xlabels = [], []
        for gname, col_pre, col_post in groups:
            for ses, color, label in [("ses-01", col_pre, "Pre"), ("ses-02", col_post, "Post")]:
                subset = df[(df["group"] == gname) & (df["session"] == ses)]["mean_val"]
                if subset.empty:
                    x_pos += 1
                    continue
                ax.boxplot(subset, positions=[x_pos], patch_artist=True,
                           boxprops=dict(facecolor=color, alpha=0.7),
                           medianprops=dict(color="black", linewidth=2),
                           whiskerprops=dict(color="gray"),
                           capprops=dict(color="gray"),
                           flierprops=dict(marker="o", markersize=4, alpha=0.5))
                ax.scatter([x_pos] * len(subset), subset, color=color, alpha=0.6, s=20, zorder=5)
                xticks.append(x_pos)
                xlabels.append(f"{gname.capitalize()}\n{label}")
                x_pos += 1
            x_pos += 0.5

        ax.set_xticks(xticks)
        ax.set_xticklabels(xlabels, fontsize=9)
        ax.set_ylabel("Mean value in cluster", fontsize=10)
        ax.set_title(title, fontsize=11)
        ax.grid(axis="y", alpha=0.3)
        ax.spines[["top", "right"]].set_visible(False)
        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None


def _generate_html_report(selected_rows: pd.DataFrame, bids_root: Path,
                           max_cluster_detail: int = 10) -> str:
    """Generate a self-contained HTML report for selected rows with significant clusters.

    Args:
        max_cluster_detail: Maximum number of clusters per tail to render brain
            overlay + group×time plot for (full cluster table is always shown).
    """
    pipeline = selected_rows["pipeline"].iloc[0] if "pipeline" in selected_rows.columns and not selected_rows.empty else "unknown"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    rows_with_results = []
    for _, row in selected_rows.iterrows():
        state_key = f"{PAGE_KEY}_cluster_{row['_row_id']}"
        result = st.session_state.get(state_key)
        if result is None:
            result = _load_cluster_from_disk(row)
        # Only include rows with non-empty cluster tables (actual significant clusters)
        if result is not None and not result.error:
            has_clusters = any(
                t is not None and not t.empty
                for t in result.tables.values()
            )
            if has_clusters:
                rows_with_results.append((row, result))

    css = """
    body{font-family:Arial,sans-serif;max-width:1400px;margin:auto;padding:20px;background:#fff;color:#333}
    h1{color:#1a1a2e}h2{color:#16213e;border-bottom:2px solid #e94560;padding-bottom:6px}
    h3{color:#0f3460}h4{color:#533483}
    .card{border:1px solid #ddd;border-radius:8px;margin:24px 0;padding:20px;box-shadow:0 2px 4px rgba(0,0,0,.08)}
    .sig{color:#2e7d32;font-weight:bold}.label{color:#1565c0}
    .meta{color:#666;font-size:13px;margin-bottom:12px}
    table{border-collapse:collapse;width:100%;font-size:13px;margin:10px 0}
    th{background:#f0f4ff;border:1px solid #ccc;padding:7px 10px;text-align:left}
    td{border:1px solid #ddd;padding:6px 10px}tr:nth-child(even){background:#f9f9f9}
    .cluster-block{display:flex;gap:16px;margin:12px 0;align-items:flex-start;flex-wrap:wrap}
    .cluster-brain{flex:1;min-width:300px}.cluster-plot{flex:1;min-width:300px}
    img{max-width:100%;border-radius:4px;border:1px solid #eee}
    .toc{background:#f8f8f8;padding:15px;border-radius:6px;margin-bottom:24px}
    .toc a{color:#0f3460;text-decoration:none}.toc a:hover{text-decoration:underline}
    .badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold}
    .badge-lmm{background:#e8f5e9;color:#2e7d32}
    .badge-rand{background:#e3f2fd;color:#1565c0}
    """

    toc_items = []
    cards_html = []
    for i, (row, result) in enumerate(rows_with_results):
        anchor = f"result-{i}"
        type_ = row["type"]
        label = row["label"]
        cidx = int(row["contrast_idx"])
        clabel = row["contrast_label"]
        source = row["source"]
        badge_cls = "badge-lmm" if source == "lmm" else "badge-rand"
        toc_items.append(
            f'<li><a href="#{anchor}">{type_} · {label} · #{cidx} {clabel} '
            f'<span class="badge {badge_cls}">{source}</span></a></li>'
        )

        seed_roi_html = ""
        if type_ == "Seed FC" and row.get("seed_dir"):
            roi_png = _render_seed_roi_png(str(row["seed_dir"]), str(bids_root))
            if roi_png:
                seed_roi_html = f'<h3>Seed ROI</h3><img src="{_img_to_b64(roi_png)}" alt="Seed ROI">'

        tstat_html = ""
        try:
            mtime = Path(row["tstat_path"]).stat().st_mtime
            t_png = _render_tstat_thumb(row["tstat_path"], mtime)
            if t_png:
                tstat_html = f'<h3>T-statistic Map</h3><img src="{_img_to_b64(t_png)}" alt="T-stat">'
        except Exception:
            pass

        cluster_sections_html = ""
        for tail_name, tdf in result.tables.items():
            if tdf is None or tdf.empty:
                continue
            cluster_index_path = str(result.cluster_img.get(tail_name, "")) or None
            ci_exists = cluster_index_path and Path(cluster_index_path).exists()

            try:
                cache_path = _labels_cache_path(row, tail_name)
                tdf_labeled = _add_atlasq_labels(tdf, cache_path=cache_path)
            except Exception:
                tdf_labeled = tdf.copy()
                tdf_labeled["Label"] = "Unknown"

            display_cols = [c for c in ["Cluster", "Voxels", "Peak Z", "X(mm)", "Y(mm)", "Z(mm)", "Label"]
                            if c in tdf_labeled.columns]
            table_rows = ""
            for _, crow in tdf_labeled[display_cols].iterrows():
                table_rows += "<tr>" + "".join(f"<td>{v}</td>" for v in crow) + "</tr>"
            table_html = (
                "<table><thead><tr>"
                + "".join(f"<th>{c}</th>" for c in display_cols)
                + f"</tr></thead><tbody>{table_rows}</tbody></table>"
            )

            per_cluster_html = ""
            if ci_exists:
                ci_mtime = Path(cluster_index_path).stat().st_mtime
                ts_mtime = Path(row["tstat_path"]).stat().st_mtime
                # Only render visualizations for top N clusters (by voxels)
                detail_df = tdf_labeled.copy()
                if "Voxels" in detail_df.columns:
                    detail_df = detail_df.sort_values("Voxels", ascending=False)
                detail_rows = list(detail_df.iterrows())[:max_cluster_detail]
                if len(tdf_labeled) > max_cluster_detail:
                    per_cluster_html += (
                        f'<p style="color:#666;font-style:italic">'
                        f'Showing brain overlays and group×time plots for the top '
                        f'{max_cluster_detail} clusters by size '
                        f'(of {len(tdf_labeled)} total).</p>'
                    )
                for _, crow in detail_rows:
                    cluster_label = int(crow.get("Cluster", 1))
                    nvox = int(crow.get("Voxels", 0))
                    peak_z = float(crow.get("Peak Z", 0))
                    px, py, pz = crow.get("X(mm)", 0), crow.get("Y(mm)", 0), crow.get("Z(mm)", 0)
                    lname = crow.get("Label", "Unknown")

                    brain_img_html = ""
                    overlay_png = _render_single_cluster_png(
                        cluster_index_path, cluster_label,
                        row["tstat_path"], ci_mtime, ts_mtime,
                    )
                    if overlay_png:
                        brain_img_html = f'<img src="{_img_to_b64(overlay_png)}" alt="Cluster {cluster_label}">'

                    plot_img_html = ""
                    df_means = _extract_single_cluster_means(
                        cluster_index_path=cluster_index_path,
                        cluster_label=cluster_label,
                        ci_mtime=ci_mtime,
                        bids_root_str=str(bids_root),
                        pipeline=str(row.get("pipeline", "")),
                        map_type=type_,
                        seed_dir=str(row.get("seed_dir", "")) or None,
                        measure=str(row.get("measure", "")) or None,
                        summary_json_path=str(row.get("summary_json", "")),
                    )
                    if df_means is not None and not df_means.empty:
                        plot_png = _render_cluster_mean_plot_png(
                            df_means,
                            title=f"Cluster {cluster_label}: {lname}",
                        )
                        if plot_png:
                            plot_img_html = f'<img src="{_img_to_b64(plot_png)}" alt="Group×Time plot">'

                    per_cluster_html += f"""
                    <div style="margin:16px 0;border-left:3px solid #533483;padding-left:12px">
                      <h4>Cluster {cluster_label} — {nvox} voxels | Peak Z={peak_z:.2f} @ ({px:.0f},{py:.0f},{pz:.0f}) | {lname}</h4>
                      <div class="cluster-block">
                        <div class="cluster-brain">{brain_img_html}</div>
                        <div class="cluster-plot">{plot_img_html}</div>
                      </div>
                    </div>"""

            cluster_sections_html += f"""
            <h3>{tail_name.capitalize()} Clusters ({len(tdf)} clusters)</h3>
            {table_html}
            {per_cluster_html}
            """

        cards_html.append(f"""
        <div class="card" id="{anchor}">
          <h2><span class="sig">{"✅" if row["significant"] else "🔄"}</span>
            <span class="label"> {type_} · {label}</span></h2>
          <p class="meta">Contrast #{cidx}: {clabel} | Source: <span class="badge {badge_cls}">{source}</span></p>
          {seed_roi_html}
          {tstat_html}
          {cluster_sections_html}
        </div>""")

    toc_html = (
        '<div class="toc"><h3>Table of Contents</h3><ol>'
        + "".join(toc_items)
        + "</ol></div>"
    ) if toc_items else ""

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Group Results Report — {pipeline}</title>
<style>{css}</style>
</head>
<body>
<h1>Group Connectivity Analysis Report</h1>
<p><b>Pipeline:</b> {pipeline} | <b>Generated:</b> {now} | <b>Analyses with results:</b> {len(rows_with_results)}</p>
{toc_html}
{"".join(cards_html)}
</body></html>"""


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

    # Compute _row_id on full df so auto-run and disk-loading work before filtering
    df["_row_id"] = (
        df["type"] + "|" +
        df["label"].fillna("") + "|" +
        df["contrast_idx"].astype(str) + "|" +
        df["source"]
    )

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

    # ── Auto-run section (before filters) ──────────────────────────────────
    _render_autorun_section(df, bids_root)
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
    sel_col1, sel_col2, sel_col3 = st.columns([2, 1, 1])
    with sel_col1:
        st.caption("Default selection: all significant results. Uncheck to exclude.")
    with sel_col2:
        if st.button("✅ Select all", key=f"{PAGE_KEY}_sel_all"):
            st.session_state[f"{PAGE_KEY}_inclusion"] = {r["_row_id"]: True for _, r in filtered.iterrows()}
            st.rerun()
    with sel_col3:
        if st.button("⬜ Deselect all", key=f"{PAGE_KEY}_desel_all"):
            st.session_state[f"{PAGE_KEY}_inclusion"] = {r["_row_id"]: False for _, r in filtered.iterrows()}
            st.rerun()

    filtered = filtered.copy()

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

    # ── HTML report button (uses selected_rows, filters to non-empty clusters) ─
    results_available = any(
        f"{PAGE_KEY}_cluster_{row['_row_id']}" in st.session_state
        or _load_cluster_from_disk(row) is not None
        for _, row in selected_rows.iterrows()
    )
    if results_available:
        rpt_col1, rpt_col2 = st.columns([1, 1])
        with rpt_col1:
            max_cluster_detail = st.number_input(
                "Max clusters with brain overlay / plot per analysis",
                min_value=1, max_value=50, value=10, step=1,
                key=f"{PAGE_KEY}_max_cluster_detail",
                help="Full cluster table is always shown. This limits the heavier per-cluster rendering.",
            )
        with rpt_col2:
            st.write("")  # spacing
            if st.button("📥 Generate HTML Report", key=f"{PAGE_KEY}_gen_html",
                         help="Generates a report for selected analyses with significant clusters only."):
                with st.spinner("Generating report… (rendering up to "
                                f"{max_cluster_detail} cluster overlays per analysis)"):
                    html = _generate_html_report(selected_rows, bids_root,
                                                 max_cluster_detail=int(max_cluster_detail))
                st.download_button(
                    "⬇️ Download Report",
                    data=html.encode("utf-8"),
                    file_name=f"group_results_report_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                    mime="text/html",
                    key=f"{PAGE_KEY}_dl_html",
                )

    # ── Bulk delete ──────────────────────────────────────────────────────────
    bulk_confirm_key = f"{PAGE_KEY}_bulk_del_confirm"
    n_sel = len(selected_rows)
    if st.session_state.get(bulk_confirm_key):
        st.warning(
            f"⚠️ This will permanently delete **{n_sel} analysis output director{'y' if n_sel==1 else 'ies'}** "
            "from disk. This cannot be undone."
        )
        bc1, bc2, _ = st.columns([1, 1, 5])
        if bc1.button("✅ Confirm delete all selected", key=f"{PAGE_KEY}_bulk_del_yes"):
            for _, row in selected_rows.iterrows():
                _delete_group_analysis(row)
            st.session_state.pop(bulk_confirm_key, None)
            st.success(f"Deleted {n_sel} analyses. Refreshing…")
            st.rerun()
        if bc2.button("❌ Cancel", key=f"{PAGE_KEY}_bulk_del_no"):
            st.session_state.pop(bulk_confirm_key, None)
            st.rerun()
    else:
        if st.button(
            f"🗑️ Delete {n_sel} selected analysis result{'s' if n_sel!=1 else ''}",
            key=f"{PAGE_KEY}_bulk_del",
            help="Remove the output directories for all selected analyses. Can be re-run afterwards.",
            type="secondary",
        ):
            st.session_state[bulk_confirm_key] = True
            st.rerun()

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
