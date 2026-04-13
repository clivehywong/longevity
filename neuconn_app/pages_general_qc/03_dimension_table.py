"""
Dimension Consistency Table

Shows X/Y/Z/T dimensions for all images with filtering and export.

Implementation: Phase 2 ✅
"""

import streamlit as st
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.dimensions import scan_all_dimensions


@st.cache_data(ttl=None, show_spinner="Scanning image dimensions...")
def cached_dimension_scan(bids_dir: str, modalities: list):
    """Cache dimension scan until refresh."""
    return scan_all_dimensions(Path(bids_dir), modalities)


def render():
    st.header("📏 Dimension Consistency Table")

    # Get config
    config = st.session_state.get('config', {})
    bids_dir = Path(config.get('paths', {}).get('bids_dir', ''))

    if not bids_dir or not bids_dir.exists():
        st.warning("⚠️ BIDS directory not configured.")
        return

    # Sidebar controls
    with st.sidebar:
        st.markdown("---")
        st.subheader("Filters")

        # Modality filter
        all_modalities = ['anat', 'func', 'dwi', 'fmap']
        selected_modalities = st.multiselect(
            "Modalities:",
            all_modalities,
            default=all_modalities,
            key="dim_modalities"
        )

        # Status filter
        status_filter = st.radio(
            "Show:",
            ["All Images", "Inconsistent Only", "Errors Only"],
            key="dim_status_filter"
        )

        # Refresh button
        if st.button("🔄 Refresh Scan", key="refresh_dims"):
            cached_dimension_scan.clear()
            st.rerun()

    # Scan dimensions (cached)
    if not selected_modalities:
        st.warning("Please select at least one modality to scan")
        return

    df = cached_dimension_scan(str(bids_dir), selected_modalities)

    if df.empty:
        st.warning("No images found for selected modalities")
        return

    # Apply status filter
    if status_filter == "Inconsistent Only":
        df = df[df['status'] == 'WARN']
    elif status_filter == "Errors Only":
        df = df[df['status'] == 'ERROR']

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Images", len(df))
    with col2:
        ok_count = len(df[df['status'] == 'OK'])
        st.metric("✅ OK", ok_count)
    with col3:
        warn_count = len(df[df['status'] == 'WARN'])
        st.metric("⚠️ Inconsistent", warn_count)
    with col4:
        error_count = len(df[df['status'] == 'ERROR'])
        st.metric("❌ Errors", error_count)

    st.markdown("---")

    # Display table
    st.subheader("Dimension Table")

    # Color-code status
    def highlight_status(row):
        if row['status'] == 'WARN':
            return ['background-color: #fff3cd'] * len(row)
        elif row['status'] == 'ERROR':
            return ['background-color: #f8d7da'] * len(row)
        else:
            return [''] * len(row)

    # Select columns to display
    display_cols = ['subject', 'session', 'modality', 'run', 'x', 'y', 'z', 't', 'status']
    df_display = df[display_cols].copy()

    # Apply styling
    styled_df = df_display.style.apply(highlight_status, axis=1)

    st.dataframe(styled_df, use_container_width=True, height=600)

    # Export button
    st.markdown("---")
    col1, col2 = st.columns([1, 4])

    with col1:
        csv = df.to_csv(index=False)
        st.download_button(
            label="📥 Export CSV",
            data=csv,
            file_name="dimension_table.csv",
            mime="text/csv",
            use_container_width=True
        )

    with col2:
        if warn_count > 0:
            st.warning(f"⚠️ {warn_count} inconsistencies detected. Review highlighted rows.")
        elif error_count > 0:
            st.error(f"❌ {error_count} errors. Files may be corrupted.")
        else:
            st.success("✅ All dimensions consistent!")


if __name__ == "__main__":
    render()
