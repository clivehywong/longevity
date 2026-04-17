"""
fMRI Preprocessing Dashboard

Quick-glance table of all subjects showing completion status for each
preprocessing step (fMRIPrep, XCP-D FC, XCP-D FC+GSR, XCP-D EC).

The page scans local output directories on demand and shows a concise
per-subject traffic-light view.  A "Rescan" button re-reads the disk so
newly added subjects and freshly completed runs are reflected immediately.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ── helpers ──────────────────────────────────────────────────────────────────

def _fmriprep_status(fmriprep_dir: Path, sub: str) -> str:
    """Return traffic-light emoji for fMRIPrep completion."""
    sub_dir = fmriprep_dir / sub
    if not sub_dir.exists():
        return "⚪"
    # XCP-D HTML report is the canonical completion indicator
    html_files = list(sub_dir.rglob("*.html"))
    if html_files:
        return "✅"
    return "🔄"


def _xcpd_status(xcpd_out_dir: Path, sub: str) -> str:
    """Return traffic-light emoji for an XCP-D pipeline completion."""
    sub_dir = xcpd_out_dir / sub
    if not sub_dir.exists():
        return "⚪"
    status_file = sub_dir / "status"
    if status_file.exists():
        content = status_file.read_text().strip()
        if content.startswith("completed"):
            return "✅"
        if content.startswith("failed"):
            return "❌"
    # Fallback: look for any HTML output
    html_files = list(sub_dir.rglob("*.html"))
    if html_files:
        return "✅"
    return "🔄"


def _build_dashboard(config: Dict) -> pd.DataFrame:
    paths = config.get("paths", {})
    bids_dir = Path(paths.get("bids_dir", "")).expanduser()
    fmriprep_dir = Path(paths.get("fmriprep_dir", "")).expanduser()
    legacy_dir = Path(paths.get("legacy_fmriprep_dir", "")).expanduser()
    xcpd_fc_dir = Path(paths.get("xcpd_fc_dir", "")).expanduser()
    xcpd_gsr_dir = Path(paths.get("xcpd_fc_gsr_dir", "")).expanduser()
    xcpd_ec_dir = Path(paths.get("xcpd_ec_dir", "")).expanduser()

    # Use whichever fMRIPrep directory actually exists
    if not fmriprep_dir.exists() and legacy_dir.exists():
        fmriprep_dir = legacy_dir

    subjects = sorted(p.name for p in bids_dir.glob("sub-*") if p.is_dir()) if bids_dir.exists() else []

    rows = []
    for sub in subjects:
        # Detect sessions
        sub_bids = bids_dir / sub
        sessions = sorted(p.name for p in sub_bids.glob("ses-*") if p.is_dir()) or ["—"]

        rows.append({
            "Subject": sub,
            "Sessions": ", ".join(sessions),
            "fMRIPrep": _fmriprep_status(fmriprep_dir, sub),
            "XCP-D FC": _xcpd_status(xcpd_fc_dir, sub),
            "XCP-D FC+GSR": _xcpd_status(xcpd_gsr_dir, sub),
            "XCP-D EC": _xcpd_status(xcpd_ec_dir, sub),
        })

    return pd.DataFrame(rows)


# ── render ────────────────────────────────────────────────────────────────────

def render() -> None:
    st.header("📊 fMRI Preprocessing Dashboard")

    config = st.session_state.get("config", {})
    paths = config.get("paths", {})

    col_info, col_btn = st.columns([3, 1])
    with col_info:
        st.caption(
            "Status is determined by scanning local output directories. "
            "⚪ = not started · 🔄 = in progress / incomplete · ✅ = completed · ❌ = failed"
        )
    with col_btn:
        if st.button("🔄 Rescan", help="Re-read all output directories from disk to reflect new subjects or completed runs"):
            if "fmri_dashboard_df" in st.session_state:
                del st.session_state["fmri_dashboard_df"]
            st.rerun()

    # Build (or use cached) dataframe
    if "fmri_dashboard_df" not in st.session_state:
        with st.spinner("Scanning output directories…"):
            st.session_state.fmri_dashboard_df = _build_dashboard(config)

    df: pd.DataFrame = st.session_state.fmri_dashboard_df

    if df.empty:
        st.warning("No BIDS subjects found. Check the BIDS directory in Settings.")
        return

    # ── Summary metrics ──────────────────────────────────────────────────────
    total = len(df)
    mcol1, mcol2, mcol3, mcol4, mcol5 = st.columns(5)
    mcol1.metric("Subjects", total)
    for mcol, col in zip([mcol2, mcol3, mcol4, mcol5], ["fMRIPrep", "XCP-D FC", "XCP-D FC+GSR", "XCP-D EC"]):
        n_done = (df[col] == "✅").sum()
        mcol.metric(col, f"{n_done}/{total}")

    # ── Filter ───────────────────────────────────────────────────────────────
    filter_opts = ["All", "fMRIPrep incomplete", "XCP-D FC incomplete", "Any incomplete"]
    sel_filter = st.selectbox("Filter", filter_opts, index=0, label_visibility="collapsed")

    view = df.copy()
    if sel_filter == "fMRIPrep incomplete":
        view = view[view["fMRIPrep"] != "✅"]
    elif sel_filter == "XCP-D FC incomplete":
        view = view[view["XCP-D FC"] != "✅"]
    elif sel_filter == "Any incomplete":
        status_cols = ["fMRIPrep", "XCP-D FC", "XCP-D FC+GSR", "XCP-D EC"]
        view = view[(view[status_cols] != "✅").any(axis=1)]

    st.dataframe(view, use_container_width=True, hide_index=True)

    # ── Path info ────────────────────────────────────────────────────────────
    with st.expander("🗂️ Scanned directories", expanded=False):
        for label, key in [
            ("fMRIPrep", "fmriprep_dir"),
            ("XCP-D FC", "xcpd_fc_dir"),
            ("XCP-D FC+GSR", "xcpd_fc_gsr_dir"),
            ("XCP-D EC", "xcpd_ec_dir"),
        ]:
            p = Path(paths.get(key, "")).expanduser()
            exists = "✅" if p.exists() else "⚪"
            st.caption(f"{exists} **{label}**: `{p}`")
