"""
fMRIPrep QC Reports & Summary

Inline viewer for fMRIPrep HTML reports with subject navigation.
"""

from __future__ import annotations

from pathlib import Path
import sys

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _find_fmriprep_reports(config: dict) -> dict[str, Path]:
    """Return a {subject_id: html_path} dict for all available fMRIPrep reports."""
    paths = config.get("paths", {})
    search_dirs = []
    for key in ("fmriprep_dir", "legacy_fmriprep_dir"):
        d = paths.get(key)
        if d:
            search_dirs.append(Path(d))

    reports: dict[str, Path] = {}
    for d in search_dirs:
        if not d.exists():
            continue
        for html_file in sorted(d.glob("sub-*.html")):
            sub_id = html_file.stem  # e.g. "sub-033"
            if sub_id not in reports:
                reports[sub_id] = html_file
    return reports


def render() -> None:
    st.header("📊 fMRIPrep Reports")

    config = st.session_state.get("config", {})
    if not config:
        st.error("Configuration not loaded.")
        return

    reports = _find_fmriprep_reports(config)
    if not reports:
        st.warning(
            "No fMRIPrep HTML reports found. Reports are expected at "
            "`fmriprep_dir/sub-*.html`."
        )
        return

    subject_ids = sorted(reports.keys())
    st.caption(f"Found **{len(subject_ids)}** report(s) across fMRIPrep output directories.")

    # Navigation: dropdown + prev/next buttons
    if "fmriprep_report_idx" not in st.session_state:
        st.session_state["fmriprep_report_idx"] = 0

    nav_col1, nav_col2, nav_col3 = st.columns([1, 4, 1])
    with nav_col1:
        if st.button("⬅ Prev", disabled=st.session_state["fmriprep_report_idx"] == 0):
            st.session_state["fmriprep_report_idx"] -= 1
            st.rerun()
    with nav_col2:
        chosen = st.selectbox(
            "Select subject",
            options=subject_ids,
            index=st.session_state["fmriprep_report_idx"],
            label_visibility="collapsed",
        )
        if chosen != subject_ids[st.session_state["fmriprep_report_idx"]]:
            st.session_state["fmriprep_report_idx"] = subject_ids.index(chosen)
            st.rerun()
    with nav_col3:
        if st.button("Next ➡", disabled=st.session_state["fmriprep_report_idx"] == len(subject_ids) - 1):
            st.session_state["fmriprep_report_idx"] += 1
            st.rerun()

    selected_sub = subject_ids[st.session_state["fmriprep_report_idx"]]
    html_path = reports[selected_sub]
    st.caption(f"Showing: `{html_path}`")

    try:
        html_content = html_path.read_text(encoding="utf-8", errors="replace")
        components.html(html_content, height=900, scrolling=True)
    except Exception as exc:
        st.error(f"Failed to load report: {exc}")


if __name__ == "__main__":
    render()
