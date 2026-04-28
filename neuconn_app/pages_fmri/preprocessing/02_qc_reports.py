"""
fMRIPrep QC Reports & Summary

Inline viewer for fMRIPrep HTML reports with subject navigation.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

_LOCAL_ASSET_ATTR_RE = re.compile(
    r'(?<![\w:-])(?P<attr>(?:src|href|data))=(?P<quote>["\'])(?P<url>.*?)(?P=quote)',
    flags=re.IGNORECASE,
)


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


def _as_embedded_asset_url(url: str, html_dir: Path) -> str | None:
    """Return a data URI for local report assets, or None for untouched URLs."""
    if not url or url.startswith(("#", "data:", "http://", "https://", "mailto:", "javascript:")):
        return None

    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None

    html_dir_resolved = html_dir.resolve()
    asset_path = (html_dir_resolved / unquote(parsed.path)).resolve()
    try:
        asset_path.relative_to(html_dir_resolved)
    except ValueError:
        return None

    if not asset_path.is_file():
        return None

    mime_type = mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(asset_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


@st.cache_data(show_spinner=False)
def _load_fmriprep_report_html(report_path: str, mtime_ns: int) -> str:
    """Load fMRIPrep HTML and embed relative image/object assets for Streamlit."""
    del mtime_ns  # cache key invalidates when the source report changes
    html_file = Path(report_path)
    html_dir = html_file.parent.resolve()
    html_content = html_file.read_text(encoding="utf-8", errors="replace")

    def replace_asset(match: re.Match[str]) -> str:
        attr = match.group("attr")
        quote = match.group("quote")
        url = match.group("url")
        embedded = _as_embedded_asset_url(url, html_dir)
        if embedded is None:
            return match.group(0)
        return f"{attr}={quote}{embedded}{quote}"

    return _LOCAL_ASSET_ATTR_RE.sub(replace_asset, html_content)


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
        html_content = _load_fmriprep_report_html(
            str(html_path),
            html_path.stat().st_mtime_ns,
        )
        components.html(html_content, height=900, scrolling=True)
    except Exception as exc:
        st.error(f"Failed to load report: {exc}")


if __name__ == "__main__":
    render()
