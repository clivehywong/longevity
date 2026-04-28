"""
Local Measures Visualization and Results Browser

Interactive page for browsing fALFF and ReHo results:
- Subject/session selection with dropdowns
- Side-by-side fALFF + ReHo maps via Papaya viewer
- Group-level statistics display
- QC metrics (mean, std, range)
- Export functionality for results

Author: NeuConn
License: MIT
"""

import streamlit as st
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import os
from typing import Optional, Dict, Any, Tuple

# Add utils to path
sys.path.insert(0, str(Path(__file__).parent.parent / "utils"))

from papaya_wrapper import (
    render_papaya_viewer_streamlit,
    get_nifti_stats,
)


# ============================================================================
# Configuration & Paths
# ============================================================================

DERIVATIVES_BASE = Path("/home/clivewong/proj/longevity/derivatives")
CONNECTIVITY_BASE = DERIVATIVES_BASE / "connectivity-difumo256"
LOCAL_MEASURES_DIR = CONNECTIVITY_BASE / "subject-level" / "local_measures"
SUMMARY_CSV = LOCAL_MEASURES_DIR / "local_measures_summary.csv"


# ============================================================================
# Data Loading Functions
# ============================================================================

@st.cache_data
def load_summary_csv() -> Optional[pd.DataFrame]:
    """Load local measures summary CSV."""
    if not SUMMARY_CSV.exists():
        return None
    try:
        df = pd.read_csv(SUMMARY_CSV)
        return df
    except Exception as e:
        st.error(f"Error loading summary CSV: {e}")
        return None


@st.cache_data
def get_available_subjects_sessions() -> Dict[str, list]:
    """Get available subjects and sessions from summary."""
    df = load_summary_csv()
    if df is None or df.empty:
        return {"subjects": [], "sessions": {}}
    
    subjects = sorted(df["subject"].unique().tolist())
    sessions_by_subject = {}
    for subj in subjects:
        sessions = sorted(df[df["subject"] == subj]["session"].unique().tolist())
        sessions_by_subject[subj] = sessions
    
    return {
        "subjects": subjects,
        "sessions": sessions_by_subject
    }


def get_local_measures_paths(subject: str, session: str) -> Dict[str, str]:
    """Get fALFF and ReHo file paths for a subject-session."""
    df = load_summary_csv()
    if df is None or df.empty:
        return {}
    
    row = df[(df["subject"] == subject) & (df["session"] == session)]
    if row.empty:
        return {}
    
    return {
        "fALFF": row.iloc[0].get("fALFF_file", ""),
        "ReHo": row.iloc[0].get("ReHo_file", ""),
    }


def get_stats_for_measure(subject: str, session: str, measure: str) -> Dict[str, Any]:
    """Get statistics for a specific measure."""
    df = load_summary_csv()
    if df is None or df.empty:
        return {}
    
    row = df[(df["subject"] == subject) & (df["session"] == session)]
    if row.empty:
        return {}
    
    row = row.iloc[0]
    
    stats = {}
    if measure == "fALFF":
        stats = {
            "mean": row.get("fALFF_mean", 0),
            "std": row.get("fALFF_std", 0),
            "median": row.get("fALFF_median", 0),
        }
    elif measure == "ReHo":
        stats = {
            "mean": row.get("ReHo_mean", 0),
            "std": row.get("ReHo_std", 0),
            "median": row.get("ReHo_median", 0),
        }
    
    return stats


# ============================================================================
# Computation Functions
# ============================================================================

@st.cache_data
def compute_group_stats() -> Dict[str, Any]:
    """Compute group-level statistics for fALFF and ReHo."""
    df = load_summary_csv()
    if df is None or df.empty:
        return {}
    
    group_stats = {
        "fALFF": {
            "mean": float(df["fALFF_mean"].mean()),
            "std": float(df["fALFF_std"].mean()),
            "min": float(df["fALFF_mean"].min()),
            "max": float(df["fALFF_mean"].max()),
            "n_subjects": len(df),
        },
        "ReHo": {
            "mean": float(df["ReHo_mean"].mean()),
            "std": float(df["ReHo_std"].mean()),
            "min": float(df["ReHo_mean"].min()),
            "max": float(df["ReHo_mean"].max()),
            "n_subjects": len(df),
        },
    }
    
    return group_stats


# ============================================================================
# UI Components
# ============================================================================

def render_subject_session_selector() -> Tuple[Optional[str], Optional[str]]:
    """Render subject and session selection dropdowns."""
    col1, col2 = st.columns(2)
    
    metadata = get_available_subjects_sessions()
    subjects = metadata.get("subjects", [])
    
    selected_subject = None
    selected_session = None
    
    with col1:
        if subjects:
            selected_subject = st.selectbox(
                "Select Subject",
                options=subjects,
                format_func=lambda x: f"{x.replace('sub-', '')}",
                key="subject_selector"
            )
        else:
            st.warning("No subjects found in local measures data")
            return None, None
    
    with col2:
        if selected_subject:
            sessions = metadata["sessions"].get(selected_subject, [])
            if sessions:
                selected_session = st.selectbox(
                    "Select Session",
                    options=sessions,
                    format_func=lambda x: x.replace("ses-", ""),
                    key="session_selector"
                )
            else:
                st.warning(f"No sessions found for {selected_subject}")
                return selected_subject, None
    
    return selected_subject, selected_session


def render_qc_metrics(subject: str, session: str):
    """Render QC metrics for fALFF and ReHo."""
    st.markdown("### 📊 QC Metrics")
    
    col1, col2 = st.columns(2)
    
    # fALFF metrics
    with col1:
        st.markdown("**fALFF**")
        falff_stats = get_stats_for_measure(subject, session, "fALFF")
        if falff_stats:
            st.metric("Mean", f"{falff_stats.get('mean', 0):.4f}")
            st.metric("Std Dev", f"{falff_stats.get('std', 0):.4f}")
            st.metric("Median", f"{falff_stats.get('median', 0):.4f}")
        else:
            st.info("No fALFF stats available")
    
    # ReHo metrics
    with col2:
        st.markdown("**ReHo**")
        reho_stats = get_stats_for_measure(subject, session, "ReHo")
        if reho_stats:
            st.metric("Mean", f"{reho_stats.get('mean', 0):.4f}")
            st.metric("Std Dev", f"{reho_stats.get('std', 0):.4f}")
            st.metric("Median", f"{reho_stats.get('median', 0):.4f}")
        else:
            st.info("No ReHo stats available")


def render_group_statistics():
    """Render group-level statistics display."""
    st.markdown("### 👥 Group-Level Statistics")
    
    group_stats = compute_group_stats()
    
    if not group_stats:
        st.info("No group statistics available")
        return
    
    col1, col2 = st.columns(2)
    
    # fALFF group stats
    with col1:
        st.markdown("**fALFF Group Stats**")
        falff = group_stats.get("fALFF", {})
        st.metric("Mean (across subjects)", f"{falff.get('mean', 0):.4f}")
        st.metric("Avg Std Dev", f"{falff.get('std', 0):.4f}")
        st.metric("Range", f"{falff.get('min', 0):.4f} - {falff.get('max', 0):.4f}")
        st.metric("N Subjects", falff.get("n_subjects", 0))
    
    # ReHo group stats
    with col2:
        st.markdown("**ReHo Group Stats**")
        reho = group_stats.get("ReHo", {})
        st.metric("Mean (across subjects)", f"{reho.get('mean', 0):.4f}")
        st.metric("Avg Std Dev", f"{reho.get('std', 0):.4f}")
        st.metric("Range", f"{reho.get('min', 0):.4f} - {reho.get('max', 0):.4f}")
        st.metric("N Subjects", reho.get("n_subjects", 0))
    
    # Distribution info
    with st.expander("📈 Show Distribution Details"):
        df = load_summary_csv()
        if df is not None and not df.empty:
            tab1, tab2 = st.tabs(["fALFF", "ReHo"])
            
            with tab1:
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Q1", f"{df['fALFF_mean'].quantile(0.25):.4f}")
                with col2:
                    st.metric("Median", f"{df['fALFF_mean'].median():.4f}")
                with col3:
                    st.metric("Q3", f"{df['fALFF_mean'].quantile(0.75):.4f}")
            
            with tab2:
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Q1", f"{df['ReHo_mean'].quantile(0.25):.4f}")
                with col2:
                    st.metric("Median", f"{df['ReHo_mean'].median():.4f}")
                with col3:
                    st.metric("Q3", f"{df['ReHo_mean'].quantile(0.75):.4f}")


def render_papaya_viewers(subject: str, session: str):
    """Render side-by-side Papaya viewers for fALFF and ReHo."""
    st.markdown("### 🧠 Brain Maps")
    
    paths = get_local_measures_paths(subject, session)
    
    if not paths or not paths.get("fALFF") or not paths.get("ReHo"):
        st.warning("Maps not available for this subject-session")
        return
    
    falff_path = paths["fALFF"]
    reho_path = paths["ReHo"]
    
    # Verify files exist
    if not os.path.exists(falff_path) or not os.path.exists(reho_path):
        st.error("Map files not found on disk")
        return
    
    # Create two columns for side-by-side viewers
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### fALFF")
        try:
            render_papaya_viewer_streamlit(
                brain_map_path=falff_path,
                title="",
                colormap="Hot",
                height=500,
                key=f"papaya_falff_{subject}_{session}",
                enable_export=True,
                show_info=True,
            )
        except Exception as e:
            st.error(f"Error rendering fALFF viewer: {e}")
    
    with col2:
        st.markdown("#### ReHo")
        try:
            render_papaya_viewer_streamlit(
                brain_map_path=reho_path,
                title="",
                colormap="Spectrum",
                height=500,
                key=f"papaya_reho_{subject}_{session}",
                enable_export=True,
                show_info=True,
            )
        except Exception as e:
            st.error(f"Error rendering ReHo viewer: {e}")


def render_export_section(subject: str, session: str):
    """Render export options for results."""
    st.markdown("### 📥 Export Results")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("📊 Export Subject Stats as CSV"):
            stats_data = {
                "Subject": subject,
                "Session": session,
                **get_stats_for_measure(subject, session, "fALFF"),
                **{f"ReHo_{k}": v for k, v in get_stats_for_measure(subject, session, "ReHo").items()},
            }
            csv_str = pd.DataFrame([stats_data]).to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv_str,
                file_name=f"{subject}_{session}_local_measures.csv",
                mime="text/csv",
            )
    
    with col2:
        if st.button("📋 Export Group Statistics"):
            group_stats = compute_group_stats()
            df = pd.DataFrame({
                "Measure": ["fALFF", "ReHo"],
                "Group Mean": [group_stats["fALFF"]["mean"], group_stats["ReHo"]["mean"]],
                "Group Std": [group_stats["fALFF"]["std"], group_stats["ReHo"]["std"]],
                "N Subjects": [group_stats["fALFF"]["n_subjects"], group_stats["ReHo"]["n_subjects"]],
            })
            csv_str = df.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv_str,
                file_name="group_local_measures_stats.csv",
                mime="text/csv",
            )
    
    with col3:
        if st.button("📄 Export Full Summary"):
            df = load_summary_csv()
            if df is not None and not df.empty:
                # Remove file paths for cleaner export
                export_df = df.drop(columns=["fALFF_file", "ReHo_file"], errors="ignore")
                csv_str = export_df.to_csv(index=False)
                st.download_button(
                    label="Download CSV",
                    data=csv_str,
                    file_name="all_subjects_local_measures_summary.csv",
                    mime="text/csv",
                )


def render_results_table():
    """Render browsable results table with filtering."""
    st.markdown("### 📋 Results Browser")
    
    df = load_summary_csv()
    if df is None or df.empty:
        st.info("No results available")
        return
    
    # Create display dataframe without file paths
    display_df = df.drop(columns=["fALFF_file", "ReHo_file"], errors="ignore").copy()
    
    # Add formatting
    for col in ["fALFF_mean", "fALFF_std", "fALFF_median", "ReHo_mean", "ReHo_std", "ReHo_median"]:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(lambda x: f"{x:.4f}")
    
    # Search/filter
    col1, col2 = st.columns([2, 1])
    with col1:
        search_subject = st.text_input("Search subject (e.g., 'sub-033'):", "")
    with col2:
        show_n = st.number_input("Show rows:", min_value=5, max_value=len(display_df), value=10)
    
    # Filter results
    if search_subject:
        filtered_df = display_df[display_df["subject"].str.contains(search_subject, case=False)]
    else:
        filtered_df = display_df
    
    # Display table
    st.dataframe(
        filtered_df.head(show_n),
        use_container_width=True,
        hide_index=True,
    )
    
    st.caption(f"Showing {min(show_n, len(filtered_df))} of {len(filtered_df)} results")


# ============================================================================
# Main Render Function
# ============================================================================

def render():
    """Main page render function."""
    st.set_page_config(
        page_title="📊 fALFF & ReHo",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    
    st.header("📊 Local Measures: fALFF & ReHo")
    
    st.markdown("""
    Browse fractional Amplitude of Low Frequency Fluctuations (fALFF) and Regional Homogeneity (ReHo) results:
    
    - **fALFF**: Measures the power of low-frequency oscillations relative to total power
    - **ReHo**: Quantifies the synchronization of brain activity between neighboring voxels
    
    Select a subject and session to visualize brain maps and QC metrics.
    """)
    
    # Sidebar configuration
    with st.sidebar:
        st.markdown("### Navigation")
        page_section = st.radio(
            "Go to section:",
            ["Viewer", "Statistics", "Results Table"],
            label_visibility="collapsed"
        )
    
    # Main content based on selection
    if page_section == "Viewer":
        render_viewer_section()
    elif page_section == "Statistics":
        render_statistics_section()
    elif page_section == "Results Table":
        render_table_section()


def render_viewer_section():
    """Render the main viewer section."""
    st.markdown("## 🔍 Brain Map Viewer")
    
    # Subject/session selector
    subject, session = render_subject_session_selector()
    
    if not subject or not session:
        st.info("Please select a subject and session to continue")
        return
    
    # Display selected
    st.success(f"Selected: {subject} / {session}")
    
    # Tabs for different views
    tab1, tab2, tab3, tab4 = st.tabs(["Maps", "QC Metrics", "Subject Stats", "Export"])
    
    with tab1:
        render_papaya_viewers(subject, session)
    
    with tab2:
        render_qc_metrics(subject, session)
    
    with tab3:
        st.markdown("### 📈 Subject-Level Statistics")
        col1, col2 = st.columns(2)
        with col1:
            falff_stats = get_stats_for_measure(subject, session, "fALFF")
            st.markdown("**fALFF**")
            st.json(falff_stats)
        with col2:
            reho_stats = get_stats_for_measure(subject, session, "ReHo")
            st.markdown("**ReHo**")
            st.json(reho_stats)
    
    with tab4:
        render_export_section(subject, session)


def render_statistics_section():
    """Render the group statistics section."""
    st.markdown("## 👥 Group Statistics")
    render_group_statistics()


def render_table_section():
    """Render the results table section."""
    st.markdown("## 📋 Browse All Results")
    render_results_table()


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    render()
