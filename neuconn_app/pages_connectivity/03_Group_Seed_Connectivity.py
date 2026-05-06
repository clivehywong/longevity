"""Group Results Viewer.

Shows group-level FSL randomise / parametric (LMM) results for:
  • Seed-based FC maps
  • ALFF / ReHo voxelwise maps

Two top-level tabs:
  📋 Dashboard  — completion matrix (pipeline × result type → stat file presence)
  🔍 Viewer     — select result, contrast → display tstat + corrp maps via nilearn

Output path conventions:
  Seed FC:   derivatives/connectivity/{pipeline}/group/seed/{seed_dir}/measure-{measure}/
  ALFF/ReHo: derivatives/connectivity/{pipeline}/group/{stat}/          (stat = alff | reho)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.connectivity_viewer import pipeline_picker
from utils.seed_viz import cli_token_to_seed_dir_name

try:
    from utils.group_cluster_analysis import (
        ClusterResult,
        fsl_available,
        run_grf_cluster,
        run_tfce_cluster,
    )
    _HAS_CLUSTER_UTILS = True
except ImportError:
    _HAS_CLUSTER_UTILS = False

PAGE_KEY = "group_seed"

# ── Contrast labels (from MixedDesignBuilder._build_contrasts) ───────────────
# contrasts[0]=Interaction, contrasts[1]=Time, contrasts[2]=Group
# randomise writes these as tstat1, tstat2, tstat3
_CONTRAST_LABELS = {
    1: "Group × Time interaction",
    2: "Time effect (ses-01 > ses-02)",
    3: "Group effect (walking > control)",
}


# ============================================================================
# Filesystem helpers
# ============================================================================

def _group_base(bids_root: Path, pipeline: str) -> Path:
    return bids_root / "derivatives" / "connectivity" / pipeline / "group" / "seed"


@st.cache_data(ttl=30)
def _scan_group_results(bids_root_str: str, pipeline: str, _tick: int) -> pd.DataFrame:
    """Scan group output dirs; returns DataFrame with cols:
    seed_dir, measure, has_tstat, has_tfce, has_summary, n_contrasts, has_lmm."""
    base = _group_base(Path(bids_root_str), pipeline)
    rows = []
    if not base.exists():
        return pd.DataFrame(columns=["seed_dir", "measure", "has_tstat", "has_tfce", "has_summary", "n_contrasts", "has_lmm"])

    for seed_dir in sorted(base.iterdir()):
        if not seed_dir.is_dir():
            continue
        for measure_dir in sorted(seed_dir.iterdir()):
            if not measure_dir.is_dir() or not measure_dir.name.startswith("measure-"):
                continue
            measure = measure_dir.name.removeprefix("measure-")

            # randomise outputs
            rand_dir = measure_dir / "2x2_mixed" / "randomise_outputs"
            tstats = sorted(rand_dir.glob("randomise_tstat*.nii.gz")) if rand_dir.exists() else []
            tfce = (
                sorted(rand_dir.glob("randomise_tfce_corrp_tstat*.nii.gz"))
                + sorted(rand_dir.glob("randomise_clustere_corrp_tstat*.nii.gz"))
                + sorted(rand_dir.glob("randomise_fdr_corrp_tstat*.nii.gz"))
            ) if rand_dir.exists() else []

            # lmm (parametric) outputs
            lmm_dir = measure_dir / "2x2_mixed" / "lmm_outputs"
            lmm_tstats = sorted(lmm_dir.glob("lmm_tstat*.nii.gz")) if lmm_dir.exists() else []

            summary = measure_dir / "stats_summary.json"
            has_tstat = len(tstats) > 0 or len(lmm_tstats) > 0
            n_contrasts = max(len(tstats), len(lmm_tstats))
            rows.append({
                "seed_dir": seed_dir.name,
                "measure": measure,
                "has_tstat": has_tstat,
                "has_tfce": len(tfce) > 0,
                "has_summary": summary.exists(),
                "n_contrasts": n_contrasts,
                "has_lmm": len(lmm_tstats) > 0,
            })

    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["seed_dir", "measure", "has_tstat", "has_tfce", "has_summary", "n_contrasts", "has_lmm"]
    )


def _group_base_alff_reho(bids_root: Path, pipeline: str, stat: str) -> Path:
    return bids_root / "derivatives" / "connectivity" / pipeline / "group" / stat


@st.cache_data(ttl=30)
def _scan_alff_reho_results(bids_root_str: str, pipeline: str, stat: str, _tick: int) -> dict:
    """Returns dict with keys: exists, has_tstat, has_corrp, has_lmm, has_rand, n_rand, n_lmm."""
    base = _group_base_alff_reho(Path(bids_root_str), pipeline, stat)
    rand_dir = base / "2x2_mixed" / "randomise_outputs"
    lmm_dir = base / "2x2_mixed" / "lmm_outputs"
    tstats_rand = sorted(rand_dir.glob("randomise_tstat*.nii.gz")) if rand_dir.exists() else []
    tstats_lmm = sorted(lmm_dir.glob("lmm_tstat*.nii.gz")) if lmm_dir.exists() else []
    corrp = (
        sorted(rand_dir.glob("randomise_tfce_corrp_tstat*.nii.gz"))
        + sorted(rand_dir.glob("randomise_clustere_corrp_tstat*.nii.gz"))
        + sorted(rand_dir.glob("randomise_fdr_corrp_tstat*.nii.gz"))
    ) if rand_dir.exists() else []
    lmm_cluster = sorted(lmm_dir.glob("lmm_cluster_corrp_tstat*.nii.gz")) if lmm_dir.exists() else []
    return {
        "exists": base.exists(),
        "has_tstat": len(tstats_rand) > 0 or len(tstats_lmm) > 0,
        "has_corrp": len(corrp) > 0 or len(lmm_cluster) > 0,
        "has_lmm": len(tstats_lmm) > 0,
        "has_rand": len(tstats_rand) > 0,
        "n_rand": len(tstats_rand),
        "n_lmm": len(tstats_lmm),
    }


def _list_contrasts_alff_reho(bids_root: Path, pipeline: str, stat: str, source: str) -> list[int]:
    """Return list of contrast indices for ALFF/ReHo outputs."""
    import re  # noqa: PLC0415
    base = _group_base_alff_reho(bids_root, pipeline, stat)
    if source == "lmm":
        out_dir = base / "2x2_mixed" / "lmm_outputs"
        pattern = r"lmm_tstat(\d+)\.nii\.gz$"
        glob_pat = "lmm_tstat*.nii.gz"
    else:
        out_dir = base / "2x2_mixed" / "randomise_outputs"
        pattern = r"randomise_tstat(\d+)\.nii\.gz$"
        glob_pat = "randomise_tstat*.nii.gz"
    if not out_dir.exists():
        return []
    return sorted(
        int(m.group(1))
        for f in out_dir.glob(glob_pat)
        if (m := re.search(pattern, f.name))
    )


def _list_contrasts(bids_root: Path, pipeline: str, seed_dir: str, measure: str,
                    source: str = "randomise") -> list[int]:
    """Return list of contrast indices (1-based) that have tstat files."""
    import re
    measure_dir = _group_base(bids_root, pipeline) / seed_dir / f"measure-{measure}"
    if source == "lmm":
        out_dir = measure_dir / "2x2_mixed" / "lmm_outputs"
        pattern = r"lmm_tstat(\d+)\.nii\.gz$"
        glob_pat = "lmm_tstat*.nii.gz"
    else:
        out_dir = measure_dir / "2x2_mixed" / "randomise_outputs"
        pattern = r"randomise_tstat(\d+)\.nii\.gz$"
        glob_pat = "randomise_tstat*.nii.gz"

    if not out_dir.exists():
        return []
    indices = []
    for f in sorted(out_dir.glob(glob_pat)):
        m = re.search(pattern, f.name)
        if m:
            indices.append(int(m.group(1)))
    return sorted(indices)


# ============================================================================
# NIfTI rendering
# ============================================================================

@st.cache_data(show_spinner=False, ttl=120)
def _render_stat_map_png(
    nifti_path_str: str,
    mtime: float,
    threshold: float,
    vmax: float,
    cmap: str,
    title: str,
) -> bytes | None:
    """Render a stat map PNG via nilearn. Returns None on failure."""
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    from nilearn import plotting  # noqa: PLC0415

    try:
        fig = plt.figure(figsize=(12, 3.5), facecolor="black")
        plotting.plot_stat_map(
            nifti_path_str,
            threshold=threshold,
            vmax=vmax,
            cmap=cmap,
            display_mode="ortho",
            figure=fig,
            title=title,
            colorbar=True,
        )
        import io  # noqa: PLC0415
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight", facecolor="black")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        plt.close("all")
        return None


@st.cache_data(show_spinner=False, ttl=120)
def _render_interactive_viewer_html(
    nifti_path_str: str,
    mtime: float,
    threshold: float,
    vmax: float,
    title: str,
    cmap: str = "cold_hot",
) -> str | None:
    """Render interactive nilearn view_img HTML. Returns HTML string or None on failure."""
    from nilearn import plotting  # noqa: PLC0415

    try:
        view = plotting.view_img(
            nifti_path_str,
            threshold=threshold,
            vmax=vmax,
            bg_img="MNI152",
            colorbar=True,
            title=title,
            cmap=cmap,
            symmetric_cmap=True,
        )
        return view._repr_html_()
    except Exception:
        return None


# ============================================================================
# Dashboard tab
# ============================================================================

def _render_dashboard(bids_root: Path, pipeline: str, map_type: str = "Seed FC") -> None:
    col_scan, col_metrics = st.columns([4, 1])
    with col_metrics:
        if st.button("🔄 Rescan", key=f"{PAGE_KEY}_rescan"):
            st.session_state[f"{PAGE_KEY}_scan_tick"] = (
                st.session_state.get(f"{PAGE_KEY}_scan_tick", 0) + 1
            )

    tick = st.session_state.get(f"{PAGE_KEY}_scan_tick", 0)

    if map_type != "Seed FC":
        _render_dashboard_alff_reho(bids_root, pipeline, map_type.lower(), tick)
        return

    df = _scan_group_results(str(bids_root), pipeline, tick)

    if df.empty:
        base = _group_base(bids_root, pipeline)
        st.info(
            f"No group results found under `{base.relative_to(bids_root)}/`.\n\n"
            "Run a group analysis via **📤 Submit Group Statistics** first."
        )
        return

    # Summary metrics
    total = len(df)
    with_tstat = (df["has_tstat"]).sum()
    with_tfce = (df["has_tfce"]).sum()
    m1, m2, m3 = st.columns(3)
    m1.metric("Total runs", total)
    m2.metric("✅ Has t-stat", int(with_tstat))
    m3.metric("✅ Has TFCE corrp", int(with_tfce))

    st.divider()

    # Status table
    def _status(row: pd.Series) -> str:
        if row["has_tstat"] and row["has_tfce"]:
            return "✅ Complete (randomise)"
        if row.get("has_lmm", False) and row["has_tstat"]:
            return "✅ Complete (parametric)"
        if row["has_tstat"]:
            return "⚠️ No corrp"
        if row["has_summary"]:
            return "🔄 Running?"
        return "❌ No outputs"

    display = df.copy()
    display["Status"] = df.apply(_status, axis=1)
    display["Contrasts"] = df["n_contrasts"].apply(lambda n: str(n) if n > 0 else "—")
    display["Source"] = df.apply(
        lambda r: ("randomise+LMM" if (r["has_tstat"] and r.get("has_lmm", False))
                   else ("LMM" if r.get("has_lmm", False) else "randomise")),
        axis=1,
    )
    display = display.rename(columns={"seed_dir": "Seed directory", "measure": "Measure"})
    st.dataframe(
        display[["Seed directory", "Measure", "Source", "Status", "Contrasts"]],
        use_container_width=True,
        hide_index=True,
    )


def _render_dashboard_alff_reho(bids_root: Path, pipeline: str, stat: str, tick: int) -> None:
    info = _scan_alff_reho_results(str(bids_root), pipeline, stat, tick)
    if not info["exists"] or not info["has_tstat"]:
        st.info(f"No group {stat.upper()} results found. Run a group analysis first.")
        return
    m1, m2, m3 = st.columns(3)
    m1.metric("Contrasts (randomise)", info["n_rand"])
    m2.metric("Contrasts (LMM)", info["n_lmm"])
    m3.metric("Has corrp", "✅" if info["has_corrp"] else "❌")


# ============================================================================
# Viewer tab
# ============================================================================

def _render_viewer(bids_root: Path, pipeline: str, map_type: str = "Seed FC") -> None:
    if map_type != "Seed FC":
        _render_viewer_alff_reho(bids_root, pipeline, map_type.lower())
        return

    tick = st.session_state.get(f"{PAGE_KEY}_scan_tick", 0)
    df = _scan_group_results(str(bids_root), pipeline, tick)

    if df.empty or not df["has_tstat"].any():
        st.info("No group results with stat maps found. Run a group analysis first.")
        return

    completed = df[df["has_tstat"]]

    # ── Selectors ─────────────────────────────────────────────────────────
    col_seed, col_meas, col_contrast = st.columns(3)

    with col_seed:
        seed_dirs = sorted(completed["seed_dir"].unique())
        seed_dir = st.selectbox(
            "Seed",
            seed_dirs,
            key=f"{PAGE_KEY}_viewer_seed",
            format_func=_seed_dir_display,
        )

    with col_meas:
        measures = sorted(completed.loc[completed["seed_dir"] == seed_dir, "measure"].unique())
        measure = st.selectbox("Measure", measures, key=f"{PAGE_KEY}_viewer_measure")

    # ── Source selector (randomise vs LMM) ────────────────────────────────
    measure_dir = _group_base(bids_root, pipeline) / seed_dir / f"measure-{measure}"
    has_rand = (measure_dir / "2x2_mixed" / "randomise_outputs").exists() and bool(
        list((measure_dir / "2x2_mixed" / "randomise_outputs").glob("randomise_tstat*.nii.gz"))
    )
    has_lmm = (measure_dir / "2x2_mixed" / "lmm_outputs").exists() and bool(
        list((measure_dir / "2x2_mixed" / "lmm_outputs").glob("lmm_tstat*.nii.gz"))
    )

    if has_rand and has_lmm:
        source = st.radio(
            "Result source",
            ["randomise (permutation)", "parametric (fast)"],
            horizontal=True,
            key=f"{PAGE_KEY}_viewer_source",
        )
        source = "lmm" if "parametric" in source else "randomise"
    elif has_lmm:
        source = "lmm"
        st.caption("Source: parametric (fast)")
    else:
        source = "randomise"

    with col_contrast:
        contrast_indices = _list_contrasts(bids_root, pipeline, seed_dir, measure, source)
        contrast_opts = {i: _CONTRAST_LABELS.get(i, f"Contrast {i}") for i in contrast_indices}
        if not contrast_opts:
            st.warning("No contrast files found.")
            return
        contrast_idx = st.selectbox(
            "Contrast",
            list(contrast_opts.keys()),
            key=f"{PAGE_KEY}_viewer_contrast",
            format_func=lambda i: f"#{i}  {contrast_opts[i]}",
        )

    # ── Resolve paths based on source ─────────────────────────────────────
    if source == "lmm":
        out_dir = measure_dir / "2x2_mixed" / "lmm_outputs"
        tstat_path = out_dir / f"lmm_tstat{contrast_idx}.nii.gz"
        corrp_cand = out_dir / f"lmm_cluster_corrp_tstat{contrast_idx}.nii.gz"
        corrp_path = corrp_cand if corrp_cand.exists() else None
        corrp_label = "GRF cluster (parametric)"
        summary_json = out_dir / "lmm_summary.json"
    else:
        out_dir = measure_dir / "2x2_mixed" / "randomise_outputs"
        tstat_path = out_dir / f"randomise_tstat{contrast_idx}.nii.gz"
        tfce_path = out_dir / f"randomise_tfce_corrp_tstat{contrast_idx}.nii.gz"
        grf_path = out_dir / f"randomise_clustere_corrp_tstat{contrast_idx}.nii.gz"
        fdr_path = out_dir / f"randomise_fdr_corrp_tstat{contrast_idx}.nii.gz"
        if tfce_path.exists():
            corrp_path, corrp_label = tfce_path, "TFCE"
        elif grf_path.exists():
            corrp_path, corrp_label = grf_path, "GRF cluster"
        elif fdr_path.exists():
            corrp_path, corrp_label = fdr_path, "FDR (BH)"
        else:
            corrp_path, corrp_label = None, ""
        summary_json = measure_dir / "stats_summary.json"

    if not tstat_path.exists():
        st.error(f"T-stat file not found: `{tstat_path}`")
        return

    # ── Thresholds ────────────────────────────────────────────────────────
    st.divider()
    col_thresh, col_vmax, _ = st.columns([1, 1, 2])
    with col_thresh:
        thr = st.slider(
            "T-stat threshold", min_value=0.0, max_value=10.0, value=2.3, step=0.1,
            key=f"{PAGE_KEY}_thresh",
        )
    with col_vmax:
        vmax_t = st.slider(
            "T-stat vmax", min_value=1.0, max_value=20.0, value=6.0, step=0.5,
            key=f"{PAGE_KEY}_vmax",
        )

    # ── T-stat map (interactive nilearn viewer) ───────────────────────────
    st.markdown(f"**🧠 T-statistic map** — contrast #{contrast_idx}: {contrast_opts[contrast_idx]}")
    tstat_mtime = tstat_path.stat().st_mtime
    html_t = _render_interactive_viewer_html(
        str(tstat_path), tstat_mtime,
        threshold=thr, vmax=vmax_t,
        title=f"tstat{contrast_idx}  [{seed_dir}  ·  {measure}]",
        cmap="cold_hot",
    )
    if html_t:
        components.html(html_t, height=500, scrolling=False)
    else:
        st.warning("Could not render interactive t-stat map.")

    # ── Corrected p-value map (static PNG) ───────────────────────────────
    if corrp_path:
        st.markdown(f"**📊 {corrp_label} corrected p-values** (p < 0.05 threshold → 1 − p > 0.95)")
        corrp_mtime = corrp_path.stat().st_mtime
        png_tfce = _render_stat_map_png(
            str(corrp_path), corrp_mtime, threshold=0.95, vmax=1.0,
            cmap="autumn", title=f"{corrp_label} corrp  [{seed_dir}  ·  {measure}]",
        )
        if png_tfce:
            st.image(png_tfce, use_container_width=True)
        else:
            st.warning(f"Could not render {corrp_label} map.")
    else:
        st.info("Corrected p-value map not found (analysis may still be running).")

    # ── Cluster Analysis ──────────────────────────────────────────────────
    st.markdown("#### 📊 Cluster Analysis")

    if not _HAS_CLUSTER_UTILS:
        st.warning("Cluster utilities not available (import error in group_cluster_analysis).")
    else:
        use_tfce_controls = corrp_label in ("TFCE", "GRF cluster (parametric)") and corrp_path is not None
        cluster_key = (
            f"{PAGE_KEY}_cluster_result_{source}_{seed_dir}_{measure}_{contrast_idx}"
        )

        if use_tfce_controls:
            col_c1, col_c2, col_c3 = st.columns(3)
            with col_c1:
                corrp_thr_preset = st.selectbox(
                    "Corrp threshold",
                    ["0.95 (p<0.05)", "0.99 (p<0.01)", "Custom"],
                    key=f"{PAGE_KEY}_cluster_corrp_preset",
                )
                if corrp_thr_preset == "Custom":
                    corrp_thr = st.number_input(
                        "Custom corrp threshold",
                        min_value=0.0, max_value=1.0, value=0.95, step=0.01,
                        key=f"{PAGE_KEY}_cluster_corrp_custom",
                    )
                else:
                    corrp_thr = 0.99 if "0.99" in corrp_thr_preset else 0.95
            with col_c2:
                cz_raw = st.number_input(
                    "Cluster Z threshold (0 = auto-detect)",
                    min_value=0.0, max_value=10.0, value=0.0, step=0.1,
                    key=f"{PAGE_KEY}_cluster_cz_thr",
                )
                cluster_z_thr: float | None = None if cz_raw <= 0.0 else cz_raw
            with col_c3:
                k_tfce = int(st.number_input(
                    "Min cluster voxels", min_value=1, value=50,
                    key=f"{PAGE_KEY}_cluster_k_tfce",
                ))
        else:
            col_g1, col_g2, col_g3 = st.columns(3)
            with col_g1:
                z_thr = st.number_input(
                    "Z threshold", min_value=0.0, max_value=10.0, value=2.3, step=0.1,
                    key=f"{PAGE_KEY}_cluster_z_thr",
                )
            with col_g2:
                p_thr = st.number_input(
                    "FWE p threshold",
                    min_value=0.001, max_value=0.1, value=0.05, step=0.01,
                    key=f"{PAGE_KEY}_cluster_p_thr",
                )
            with col_g3:
                k_grf = int(st.number_input(
                    "Min cluster voxels", min_value=1, value=1,
                    key=f"{PAGE_KEY}_cluster_k_grf",
                ))

            col_sm, col_tail = st.columns(2)
            with col_sm:
                smoothness_raw = st.radio(
                    "Smoothness estimation",
                    ["From z-stat (recommended)", "From residuals (res4d/dof)"],
                    key=f"{PAGE_KEY}_cluster_smoothness",
                )
                smoothness = "z" if "z-stat" in smoothness_raw else "r"
            with col_tail:
                tail_raw = st.radio(
                    "Tail",
                    ["Both (pos + neg)", "Positive only", "Negative only"],
                    key=f"{PAGE_KEY}_cluster_tail",
                )
                match tail_raw:
                    case "Positive only":
                        tail = "pos"
                    case "Negative only":
                        tail = "neg"
                    case _:
                        tail = "both"

        if st.button("🔍 Run Cluster Analysis", key=f"{PAGE_KEY}_run_cluster"):
            mask_path = (
                bids_root / "atlases"
                / "MNI152_T1_2mm_brain_mask_dil.nii.gz"
            )
            if not mask_path.exists():
                import os  # noqa: PLC0415
                fsl_dir = os.environ.get("FSLDIR", "")
                if fsl_dir:
                    mask_path = (
                        Path(fsl_dir) / "data" / "standard"
                        / "MNI152_T1_2mm_brain_mask_dil.nii.gz"
                    )

            cluster_out_dir = out_dir / "cluster_analysis" / f"contrast{contrast_idx}"

            if use_tfce_controls:
                with st.spinner("Running TFCE cluster analysis…"):
                    result = run_tfce_cluster(
                        corrp_path=corrp_path,
                        tstat_path=tstat_path,
                        out_dir=cluster_out_dir,
                        corrp_thr=corrp_thr,
                        cluster_z_thr=cluster_z_thr,
                        k=k_tfce,
                    )
            else:
                with st.spinner("Running GRF cluster analysis…"):
                    result = run_grf_cluster(
                        tstat_path=tstat_path,
                        mask_path=mask_path,
                        out_dir=cluster_out_dir,
                        z_thr=z_thr,
                        p_thr=p_thr,
                        k=k_grf,
                        smoothness=smoothness,
                        tail=tail,
                    )
            st.session_state[cluster_key] = result

        # Show cached cluster result
        if cluster_key in st.session_state:
            result: ClusterResult = st.session_state[cluster_key]
            if result.error:
                st.error(f"Cluster analysis error: {result.error}")
            else:
                _render_cluster_tables(result)

    # ── Metadata ──────────────────────────────────────────────────────────
    summary_path = summary_json
    if summary_path.exists():
        with st.expander("📄 Analysis metadata"):
            try:
                meta = json.loads(summary_path.read_text())
                st.json(meta)
            except Exception:
                st.text(summary_path.read_text()[:2000])


# ============================================================================
# Cluster result display
# ============================================================================

def _render_cluster_tables(result: "ClusterResult") -> None:  # noqa: F821
    """Display cluster result tables with NeuroSynth links."""
    _TAIL_LABELS = {"pos": "Activation (positive)", "neg": "Deactivation (negative)"}

    for tail_key, df in result.tables.items():
        label = _TAIL_LABELS.get(tail_key, tail_key.capitalize())
        st.markdown(f"**{label}**")

        if df.empty:
            st.info("No significant clusters")
            continue

        # Add NeuroSynth link column from peak coordinates
        if {"X(mm)", "Y(mm)", "Z(mm)"}.issubset(df.columns):
            df = df.copy()
            df["NeuroSynth"] = df.apply(
                lambda r: (
                    f"https://neurosynth.org/locations/"
                    f"{int(r['X(mm)'])}_{int(r['Y(mm)'])}_{int(r['Z(mm)'])}_6/"
                ),
                axis=1,
            )

        # Build column config
        col_cfg: dict = {}
        if "Cluster" in df.columns:
            col_cfg["Cluster"] = st.column_config.NumberColumn("Cluster", width="small", format="%d")
        if "Voxels" in df.columns:
            col_cfg["Voxels"] = st.column_config.NumberColumn("Voxels", width="small", format="%d")
        for p_col in ("p(FWE)", "p"):
            if p_col in df.columns:
                col_cfg[p_col] = st.column_config.NumberColumn(p_col, format="%.4f")
        if "Peak Z" in df.columns:
            col_cfg["Peak Z"] = st.column_config.NumberColumn("Peak Z", format="%.2f")
        for coord in ("X(mm)", "Y(mm)", "Z(mm)"):
            if coord in df.columns:
                col_cfg[coord] = st.column_config.NumberColumn(coord, format="%.1f")
        if "NeuroSynth" in df.columns:
            col_cfg["NeuroSynth"] = st.column_config.LinkColumn(
                "NeuroSynth", display_text="🔗 View"
            )

        st.dataframe(df, use_container_width=True, hide_index=True, column_config=col_cfg)


# ============================================================================
# Helpers
# ============================================================================

def _render_viewer_alff_reho(bids_root: Path, pipeline: str, stat: str) -> None:
    tick = st.session_state.get(f"{PAGE_KEY}_scan_tick", 0)
    info = _scan_alff_reho_results(str(bids_root), pipeline, stat, tick)
    if not info["has_tstat"]:
        st.info(f"No group {stat.upper()} results found. Run a group analysis first.")
        return
    base = _group_base_alff_reho(bids_root, pipeline, stat)
    # Source selector
    if info["has_rand"] and info["has_lmm"]:
        src_raw = st.radio(
            "Result source", ["randomise (permutation)", "parametric (fast)"],
            horizontal=True, key=f"{PAGE_KEY}_alff_reho_source_{stat}",
        )
        source = "lmm" if "parametric" in src_raw else "randomise"
    elif info["has_lmm"]:
        source = "lmm"
        st.caption("Source: parametric (fast)")
    else:
        source = "randomise"
    # Contrast selector
    contrast_indices = _list_contrasts_alff_reho(bids_root, pipeline, stat, source)
    if not contrast_indices:
        st.warning("No contrast files found.")
        return
    contrast_opts = {i: _CONTRAST_LABELS.get(i, f"Contrast {i}") for i in contrast_indices}
    contrast_idx = st.selectbox(
        "Contrast", list(contrast_opts.keys()),
        key=f"{PAGE_KEY}_alff_reho_contrast_{stat}",
        format_func=lambda i: f"#{i}  {contrast_opts[i]}",
    )
    # Resolve paths
    if source == "lmm":
        out_dir = base / "2x2_mixed" / "lmm_outputs"
        tstat_path = out_dir / f"lmm_tstat{contrast_idx}.nii.gz"
        corrp_cand = out_dir / f"lmm_cluster_corrp_tstat{contrast_idx}.nii.gz"
        corrp_path = corrp_cand if corrp_cand.exists() else None
        corrp_label = "GRF cluster (parametric)" if corrp_path else ""
        summary_json = out_dir / "lmm_summary.json"
    else:
        out_dir = base / "2x2_mixed" / "randomise_outputs"
        tstat_path = out_dir / f"randomise_tstat{contrast_idx}.nii.gz"
        tfce_path = out_dir / f"randomise_tfce_corrp_tstat{contrast_idx}.nii.gz"
        grf_path = out_dir / f"randomise_clustere_corrp_tstat{contrast_idx}.nii.gz"
        fdr_path = out_dir / f"randomise_fdr_corrp_tstat{contrast_idx}.nii.gz"
        if tfce_path.exists():
            corrp_path, corrp_label = tfce_path, "TFCE"
        elif grf_path.exists():
            corrp_path, corrp_label = grf_path, "GRF cluster"
        elif fdr_path.exists():
            corrp_path, corrp_label = fdr_path, "FDR (BH)"
        else:
            corrp_path, corrp_label = None, ""
        summary_json = base / "stats_summary.json"
    if not tstat_path.exists():
        st.error(f"T-stat file not found: `{tstat_path}`")
        return
    # Thresholds
    st.divider()
    col_thresh, col_vmax, _ = st.columns([1, 1, 2])
    with col_thresh:
        thr = st.slider("T-stat threshold", 0.0, 10.0, 2.3, 0.1, key=f"{PAGE_KEY}_alff_reho_thresh_{stat}")
    with col_vmax:
        vmax_t = st.slider("T-stat vmax", 1.0, 20.0, 6.0, 0.5, key=f"{PAGE_KEY}_alff_reho_vmax_{stat}")
    # T-stat interactive viewer
    st.markdown(f"**🧠 T-statistic map** — {stat.upper()} contrast #{contrast_idx}: {contrast_opts[contrast_idx]}")
    tstat_mtime = tstat_path.stat().st_mtime
    html_t = _render_interactive_viewer_html(
        str(tstat_path), tstat_mtime, threshold=thr, vmax=vmax_t,
        title=f"tstat{contrast_idx}  [{stat.upper()}]", cmap="cold_hot",
    )
    if html_t:
        components.html(html_t, height=500, scrolling=False)
    else:
        st.warning("Could not render interactive t-stat map.")
    # Corrp map
    if corrp_path:
        st.markdown(f"**📊 {corrp_label} corrected p-values**")
        corrp_mtime = corrp_path.stat().st_mtime
        png = _render_stat_map_png(
            str(corrp_path), corrp_mtime, threshold=0.95, vmax=1.0,
            cmap="autumn", title=f"{corrp_label} corrp  [{stat.upper()}]",
        )
        if png:
            st.image(png, use_container_width=True)
    else:
        st.info("Corrected p-value map not available.")
    # Cluster analysis (reuse existing logic)
    st.markdown("#### 📊 Cluster Analysis")
    if not _HAS_CLUSTER_UTILS:
        st.warning("Cluster utilities not available.")
    else:
        use_tfce_controls = corrp_label in ("TFCE", "GRF cluster (parametric)") and corrp_path is not None
        cluster_key = f"{PAGE_KEY}_cluster_result_alff_reho_{stat}_{source}_{contrast_idx}"
        if use_tfce_controls:
            col_c1, col_c2, col_c3 = st.columns(3)
            with col_c1:
                corrp_thr_preset = st.selectbox(
                    "Corrp threshold", ["0.95 (p<0.05)", "0.99 (p<0.01)", "Custom"],
                    key=f"{PAGE_KEY}_alff_reho_corrp_preset_{stat}",
                )
                corrp_thr = 0.99 if "0.99" in corrp_thr_preset else (
                    st.number_input("Custom corrp threshold", 0.0, 1.0, 0.95, 0.01,
                                    key=f"{PAGE_KEY}_alff_reho_corrp_custom_{stat}")
                    if corrp_thr_preset == "Custom" else 0.95
                )
            with col_c2:
                cz_raw = st.number_input("Cluster Z threshold (0=auto)", 0.0, 10.0, 0.0, 0.1,
                                         key=f"{PAGE_KEY}_alff_reho_cz_{stat}")
                cluster_z_thr = None if cz_raw <= 0.0 else cz_raw
            with col_c3:
                k_tfce = int(st.number_input("Min cluster voxels", 1, value=50,
                                             key=f"{PAGE_KEY}_alff_reho_k_tfce_{stat}"))
        else:
            col_g1, col_g2, col_g3 = st.columns(3)
            with col_g1:
                z_thr = st.number_input("Z threshold", 0.0, 10.0, 2.3, 0.1,
                                        key=f"{PAGE_KEY}_alff_reho_zthr_{stat}")
            with col_g2:
                p_thr = st.number_input("FWE p threshold", 0.001, 0.1, 0.05, 0.01,
                                        key=f"{PAGE_KEY}_alff_reho_pthr_{stat}")
            with col_g3:
                k_grf = int(st.number_input("Min cluster voxels", 1, value=1,
                                            key=f"{PAGE_KEY}_alff_reho_kgrf_{stat}"))
            col_sm, col_tail = st.columns(2)
            with col_sm:
                sm_raw = st.radio("Smoothness", ["From z-stat (recommended)", "From residuals"],
                                  key=f"{PAGE_KEY}_alff_reho_sm_{stat}")
                smoothness = "z" if "z-stat" in sm_raw else "r"
            with col_tail:
                tail_raw = st.radio("Tail", ["Both (pos + neg)", "Positive only", "Negative only"],
                                    key=f"{PAGE_KEY}_alff_reho_tail_{stat}")
                match tail_raw:
                    case "Positive only": tail = "pos"
                    case "Negative only": tail = "neg"
                    case _: tail = "both"
        if st.button("🔍 Run Cluster Analysis", key=f"{PAGE_KEY}_alff_reho_run_cluster_{stat}"):
            mask_path = bids_root / "atlases" / "MNI152_T1_2mm_brain_mask_dil.nii.gz"
            if not mask_path.exists():
                import os  # noqa: PLC0415
                fsl_dir = os.environ.get("FSLDIR", "")
                if fsl_dir:
                    mask_path = Path(fsl_dir) / "data" / "standard" / "MNI152_T1_2mm_brain_mask_dil.nii.gz"
            cluster_out_dir = out_dir / "cluster_analysis" / f"contrast{contrast_idx}"
            if use_tfce_controls:
                with st.spinner("Running TFCE cluster analysis…"):
                    result = run_tfce_cluster(
                        corrp_path=corrp_path, tstat_path=tstat_path,
                        out_dir=cluster_out_dir, corrp_thr=corrp_thr,
                        cluster_z_thr=cluster_z_thr, k=k_tfce,
                    )
            else:
                with st.spinner("Running GRF cluster analysis…"):
                    result = run_grf_cluster(
                        tstat_path=tstat_path, mask_path=mask_path,
                        out_dir=cluster_out_dir, z_thr=z_thr, p_thr=p_thr,
                        k=k_grf, smoothness=smoothness, tail=tail,
                    )
            st.session_state[cluster_key] = result
        if cluster_key in st.session_state:
            result = st.session_state[cluster_key]
            if result.error:
                st.error(f"Cluster analysis error: {result.error}")
            else:
                _render_cluster_tables(result)
    # Metadata
    if summary_json.exists():
        with st.expander("📄 Analysis metadata"):
            try:
                meta = json.loads(summary_json.read_text())
                st.json(meta)
            except Exception:
                st.text(summary_json.read_text()[:2000])


def _seed_dir_display(dir_name: str) -> str:
    """Human-readable label from seed directory name."""
    import re  # noqa: PLC0415
    m = re.match(r"sphere-([-\d]+)_([-\d]+)_([-\d]+)_r([\d]+)$", dir_name)
    if m:
        return f"🔵 ({m.group(1)}, {m.group(2)}, {m.group(3)})  r={m.group(4)} mm"
    m = re.match(r"atlas-([^_]+)_parcel-(.+)$", dir_name)
    if m:
        return f"🟠 {m.group(2)}  [{m.group(1)}]"
    return dir_name


# ============================================================================
# Entry point
# ============================================================================

def render() -> None:
    st.title("👥 Group Results Viewer")

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

    map_type = st.radio(
        "Map type",
        ["Seed FC", "ALFF", "ReHo"],
        horizontal=True,
        key=f"{PAGE_KEY}_map_type",
    )

    tab_dash, tab_viewer = st.tabs(["📋 Dashboard", "🔍 Viewer"])

    with tab_dash:
        _render_dashboard(bids_root, pipeline, map_type)

    with tab_viewer:
        _render_viewer(bids_root, pipeline, map_type)


if __name__ == "__main__":
    render()
