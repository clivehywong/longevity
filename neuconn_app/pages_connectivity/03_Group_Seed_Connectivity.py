"""Group-Level Seed Connectivity Viewer.

Shows group-level FSL randomise results for seed-based connectivity analyses.

Two top-level tabs:
  📋 Dashboard  — completion matrix (pipeline × seed × measure → stat file presence)
  🔍 Viewer     — select seed/measure/contrast → display tstat + TFCE p-maps via nilearn

Output path convention (set by group_mixed_design_stats.py):
  derivatives/connectivity/{pipeline}/group/seed/{seed_dir}/measure-{measure}/
    randomise_outputs/
      randomise_tstat{N}.nii.gz
      randomise_tfce_corrp_tstat{N}.nii.gz
    design.mat  design.con  design.grp  design.fts
    stats_summary.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.connectivity_viewer import pipeline_picker
from utils.seed_viz import cli_token_to_seed_dir_name

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
            rand_dir = measure_dir / "randomise_outputs"
            tstats = sorted(rand_dir.glob("randomise_tstat*.nii.gz")) if rand_dir.exists() else []
            tfce = (
                sorted(rand_dir.glob("randomise_tfce_corrp_tstat*.nii.gz"))
                + sorted(rand_dir.glob("randomise_clustere_corrp_tstat*.nii.gz"))
                + sorted(rand_dir.glob("randomise_fdr_corrp_tstat*.nii.gz"))
            ) if rand_dir.exists() else []

            # lmm (parametric) outputs
            lmm_dir = measure_dir / "lmm_outputs"
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


def _list_contrasts(bids_root: Path, pipeline: str, seed_dir: str, measure: str,
                    source: str = "randomise") -> list[int]:
    """Return list of contrast indices (1-based) that have tstat files."""
    import re
    measure_dir = _group_base(bids_root, pipeline) / seed_dir / f"measure-{measure}"
    if source == "lmm":
        out_dir = measure_dir / "lmm_outputs"
        pattern = r"lmm_tstat(\d+)\.nii\.gz$"
        glob_pat = "lmm_tstat*.nii.gz"
    else:
        out_dir = measure_dir / "randomise_outputs"
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


# ============================================================================
# Dashboard tab
# ============================================================================

def _render_dashboard(bids_root: Path, pipeline: str) -> None:
    col_scan, col_metrics = st.columns([4, 1])
    with col_metrics:
        if st.button("🔄 Rescan", key=f"{PAGE_KEY}_rescan"):
            st.session_state[f"{PAGE_KEY}_scan_tick"] = (
                st.session_state.get(f"{PAGE_KEY}_scan_tick", 0) + 1
            )

    tick = st.session_state.get(f"{PAGE_KEY}_scan_tick", 0)
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


# ============================================================================
# Viewer tab
# ============================================================================

def _render_viewer(bids_root: Path, pipeline: str) -> None:
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
    has_rand = (measure_dir / "randomise_outputs").exists() and bool(
        list((measure_dir / "randomise_outputs").glob("randomise_tstat*.nii.gz"))
    )
    has_lmm = (measure_dir / "lmm_outputs").exists() and bool(
        list((measure_dir / "lmm_outputs").glob("lmm_tstat*.nii.gz"))
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
        out_dir = measure_dir / "lmm_outputs"
        tstat_path = out_dir / f"lmm_tstat{contrast_idx}.nii.gz"
        corrp_cand = out_dir / f"lmm_cluster_corrp_tstat{contrast_idx}.nii.gz"
        corrp_path = corrp_cand if corrp_cand.exists() else None
        corrp_label = "GRF cluster (parametric)"
        summary_json = out_dir / "lmm_summary.json"
    else:
        out_dir = measure_dir / "randomise_outputs"
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

    # ── T-stat map ────────────────────────────────────────────────────────
    st.markdown(f"**🧠 T-statistic map** — contrast #{contrast_idx}: {contrast_opts[contrast_idx]}")
    tstat_mtime = tstat_path.stat().st_mtime
    png_t = _render_stat_map_png(
        str(tstat_path), tstat_mtime, threshold=thr, vmax=vmax_t,
        cmap="cold_hot", title=f"tstat{contrast_idx}  [{seed_dir}  ·  {measure}]",
    )
    if png_t:
        st.image(png_t, use_container_width=True)
    else:
        st.warning("Could not render t-stat map.")

    # ── Corrected p-value map ─────────────────────────────────────────────
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
# Helpers
# ============================================================================

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
    st.title("👥 Group Seed Connectivity Viewer")

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

    tab_dash, tab_viewer = st.tabs(["📋 Dashboard", "🔍 Viewer"])

    with tab_dash:
        _render_dashboard(bids_root, pipeline)

    with tab_viewer:
        _render_viewer(bids_root, pipeline)


if __name__ == "__main__":
    render()
