"""
Group-Level Statistics UI Component

Comprehensive Streamlit UI for group-level analysis results with:
- Correction method selection (GRF/TFCE/FDR)
- Interactive threshold controls
- Cluster table visualization with anatomy
- Statistical summary panels
- Export and comparison capabilities
- Performance-optimized with caching

Implementation: Phase 10
"""

import streamlit as st
from pathlib import Path
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
import json
import nibabel as nib
from datetime import datetime
import plotly.graph_objects as go
from io import BytesIO


# ==============================================================================
# Caching & Data Loading
# ==============================================================================

@st.cache_data(ttl=3600)
def load_cluster_table(csv_path: str) -> Optional[pd.DataFrame]:
    """
    Load cluster table from CSV with caching.
    
    Handles various cluster table formats from different analysis pipelines.
    Expected columns: cluster_id, size_voxels, peak_t, peak_x, peak_y, peak_z,
                      anatomical_region, direction, (optional) p_value, q_value
    """
    csv_path_obj = Path(csv_path)
    if not csv_path_obj.exists():
        return None
    
    try:
        df = pd.read_csv(csv_path_obj)
        # Ensure required columns exist
        required_cols = ['cluster_id', 'size_voxels', 'peak_t', 'peak_x', 'peak_y', 'peak_z']
        if not all(col in df.columns for col in required_cols):
            st.warning(f"Cluster table missing expected columns. Found: {df.columns.tolist()}")
            return None
        return df
    except Exception as e:
        st.error(f"Error loading cluster table: {e}")
        return None


@st.cache_data(ttl=3600)
def load_statistical_map(nifti_path: str) -> Optional[Tuple[np.ndarray, nib.Nifti1Image]]:
    """Load statistical map NIfTI with caching."""
    nifti_path_obj = Path(nifti_path)
    if not nifti_path_obj.exists():
        return None
    
    try:
        img = nib.load(nifti_path_obj)
        data = img.get_fdata()
        return data, img
    except Exception as e:
        st.error(f"Error loading NIfTI file: {e}")
        return None


@st.cache_data(ttl=3600)
def load_model_info(json_path: str) -> Optional[Dict]:
    """Load model metadata from JSON."""
    json_path_obj = Path(json_path)
    if not json_path_obj.exists():
        return None
    
    try:
        with open(json_path_obj, 'r') as f:
            return json.load(f)
    except Exception as e:
        st.warning(f"Could not load model info: {e}")
        return None


def validate_results_directory(results_dir: str) -> Tuple[bool, str, Optional[Path]]:
    """
    Validate results directory and find cluster table.
    
    Returns:
        (is_valid, message, cluster_csv_path)
    """
    results_path = Path(results_dir)
    
    if not results_path.exists():
        return False, f"❌ Directory not found: {results_dir}", None
    
    if not results_path.is_dir():
        return False, f"❌ Path is not a directory: {results_dir}", None
    
    # Look for cluster table
    cluster_csv = results_path / "clusters_interaction.csv"
    if not cluster_csv.exists():
        csv_files = list(results_path.glob("clusters_*.csv"))
        if not csv_files:
            return False, "❌ No cluster CSV files found in results directory", None
        cluster_csv = csv_files[0]
    
    return True, f"✓ Valid results directory with {len(list(results_path.glob('*.csv')))} CSV files", cluster_csv


# ==============================================================================
# Filtering & Processing
# ==============================================================================

def apply_threshold_filters(
    df: pd.DataFrame,
    method: str,
    thresholds: Dict[str, float],
    direction: str = 'both'
) -> pd.DataFrame:
    """
    Apply statistical thresholds based on correction method.
    
    Args:
        df: Cluster table DataFrame
        method: 'GRF' | 'TFCE' | 'FDR'
        thresholds: Method-specific threshold dict
        direction: 'positive' | 'negative' | 'both'
    
    Returns:
        Filtered DataFrame
    """
    filtered_df = df.copy()
    
    # Direction filter
    if direction == 'positive':
        filtered_df = filtered_df[filtered_df['peak_t'] > 0]
    elif direction == 'negative':
        filtered_df = filtered_df[filtered_df['peak_t'] < 0]
    
    # Method-specific thresholds
    if method == 'GRF':
        voxel_threshold = thresholds.get('voxel_tstat', 2.5)
        cluster_size = thresholds.get('cluster_size', 50)
        
        filtered_df = filtered_df[
            (filtered_df['peak_t'].abs() >= voxel_threshold) &
            (filtered_df['size_voxels'] >= cluster_size)
        ]
    
    elif method == 'TFCE':
        p_threshold = thresholds.get('p_value', 0.05)
        if 'p_value' in filtered_df.columns:
            filtered_df = filtered_df[filtered_df['p_value'] <= p_threshold]
        elif 'q_value' in filtered_df.columns:
            # If only q-value available, use that
            filtered_df = filtered_df[filtered_df['q_value'] <= p_threshold * 0.1]
    
    elif method == 'FDR':
        q_threshold = thresholds.get('q_value', 0.05)
        if 'q_value' in filtered_df.columns:
            filtered_df = filtered_df[filtered_df['q_value'] <= q_threshold]
        elif 'p_value' in filtered_df.columns:
            # Conservative estimate: use stricter p-value for FDR
            filtered_df = filtered_df[filtered_df['p_value'] <= q_threshold / len(df)]
    
    return filtered_df.reset_index(drop=True)


def compute_summary_statistics(df: pd.DataFrame, raw_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute summary statistics for results panel.
    
    Args:
        df: Filtered DataFrame (after thresholding)
        raw_df: Original unfiltered DataFrame
    
    Returns:
        Dictionary with summary metrics
    """
    summary = {
        'n_clusters': len(df),
        'n_total_clusters': len(raw_df),
        'peak_t_max': df['peak_t'].max() if len(df) > 0 else 0,
        'peak_t_min': df['peak_t'].min() if len(df) > 0 else 0,
        'cluster_size_max': df['size_voxels'].max() if len(df) > 0 else 0,
        'cluster_size_mean': df['size_voxels'].mean() if len(df) > 0 else 0,
        'total_voxels': df['size_voxels'].sum() if len(df) > 0 else 0,
    }
    
    # Add p-value stats if available
    if 'p_value' in df.columns and len(df) > 0:
        summary['p_value_min'] = df['p_value'].min()
        summary['p_value_max'] = df['p_value'].max()
    
    if 'q_value' in df.columns and len(df) > 0:
        summary['q_value_min'] = df['q_value'].min()
        summary['q_value_max'] = df['q_value'].max()
    
    return summary


def format_anatomical_region(region_str: Optional[str]) -> str:
    """Format anatomical region string for display."""
    if pd.isna(region_str) or region_str is None or region_str == '':
        return 'N/A'
    return str(region_str).strip()


# ==============================================================================
# UI Components
# ==============================================================================

def render_method_selector() -> Tuple[str, Dict[str, float], str]:
    """
    Render method selection panel with threshold controls.
    
    Returns:
        (method, thresholds_dict, direction)
    """
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.subheader("📊 Correction Method")
        method = st.radio(
            "Select correction:",
            options=['GRF', 'TFCE', 'FDR'],
            horizontal=True,
            key='correction_method'
        )
    
    with col2:
        st.subheader("🎯 Direction")
        direction = st.radio(
            "Effect direction:",
            options=['Both', 'Positive', 'Negative'],
            horizontal=True,
            key='effect_direction'
        )
        direction_map = {'Both': 'both', 'Positive': 'positive', 'Negative': 'negative'}
        direction = direction_map[direction]
    
    with col3:
        st.subheader("⚙️ Thresholds")
        thresholds = {}
        
        if method == 'GRF':
            thresholds['voxel_tstat'] = st.slider(
                "Voxel t-stat threshold:",
                min_value=1.0,
                max_value=5.0,
                value=2.5,
                step=0.1,
                key='grf_voxel_tstat'
            )
            thresholds['cluster_size'] = st.slider(
                "Cluster size (voxels):",
                min_value=10,
                max_value=500,
                value=50,
                step=10,
                key='grf_cluster_size'
            )
        
        elif method == 'TFCE':
            thresholds['p_value'] = st.slider(
                "p-value threshold:",
                min_value=0.001,
                max_value=0.1,
                value=0.05,
                step=0.001,
                format="%.4f",
                key='tfce_p_value'
            )
        
        elif method == 'FDR':
            thresholds['q_value'] = st.slider(
                "q-value threshold (FDR):",
                min_value=0.01,
                max_value=0.2,
                value=0.05,
                step=0.01,
                format="%.3f",
                key='fdr_q_value'
            )
    
    return method, thresholds, direction


def render_summary_panels(summary: Dict[str, Any]) -> None:
    """Render summary statistics panels."""
    st.markdown("### 📈 Statistical Summary")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Significant Clusters",
            summary['n_clusters'],
            f"of {summary['n_total_clusters']} total"
        )
    
    with col2:
        peak_t = summary['peak_t_max']
        st.metric(
            "Peak t-statistic",
            f"{peak_t:.3f}",
            f"Min: {summary['peak_t_min']:.3f}"
        )
    
    with col3:
        st.metric(
            "Largest Cluster",
            f"{summary['cluster_size_max']:.0f} vox",
            f"Mean: {summary['cluster_size_mean']:.0f} vox"
        )
    
    with col4:
        st.metric(
            "Total Significant Voxels",
            f"{summary['total_voxels']:.0f}",
            "across all clusters"
        )
    
    # Additional p-value stats if available
    if 'p_value_min' in summary:
        st.caption(
            f"p-value range: [{summary['p_value_min']:.1e}, {summary['p_value_max']:.1e}]"
        )


def render_cluster_table(
    df: pd.DataFrame,
    max_display: int = 50,
    sort_by: str = 'peak_t'
) -> Tuple[pd.DataFrame, Optional[int]]:
    """
    Render interactive cluster table.
    
    Args:
        df: Cluster DataFrame
        max_display: Max clusters to display initially
        sort_by: Column to sort by
    
    Returns:
        (displayed_df, selected_cluster_idx)
    """
    if len(df) == 0:
        st.info("No significant clusters found with current thresholds.")
        return pd.DataFrame(), None
    
    # Prepare display DataFrame
    display_cols = ['cluster_id', 'peak_t', 'size_voxels', 'peak_x', 'peak_y', 'peak_z']
    if 'anatomical_region' in df.columns:
        display_cols.append('anatomical_region')
    if 'p_value' in df.columns:
        display_cols.append('p_value')
    if 'direction' in df.columns:
        display_cols.append('direction')
    
    display_cols = [c for c in display_cols if c in df.columns]
    display_df = df[display_cols].copy()
    
    # Sort
    sort_col = 'peak_t' if sort_by not in display_cols else sort_by
    display_df = display_df.sort_values(by=sort_col, ascending=False, key=abs)
    
    # Format numeric columns
    for col in ['peak_t', 'p_value', 'peak_x', 'peak_y', 'peak_z']:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(
                lambda x: f"{x:.4f}" if isinstance(x, (int, float)) else x
            )
    
    display_df['size_voxels'] = display_df['size_voxels'].astype(int)
    
    # Display info
    st.markdown(f"### 🧠 Cluster Table ({len(df)} clusters)")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        sort_options = [c for c in ['peak_t', 'size_voxels', 'p_value'] if c in df.columns]
        sort_by = st.selectbox(
            "Sort by:",
            options=sort_options if sort_options else ['cluster_id'],
            key='sort_by_select'
        )
    with col2:
        st.write("")  # Spacer
    
    # Pagination info
    if len(df) > max_display:
        st.info(f"Showing first {max_display} of {len(df)} clusters (sorted by {sort_by})")
        display_df_truncated = display_df.head(max_display)
    else:
        display_df_truncated = display_df
    
    # Display dataframe
    st.dataframe(
        display_df_truncated,
        use_container_width=True,
        hide_index=True,
        key='cluster_table'
    )
    
    return df, None


def render_cluster_distribution_plot(df: pd.DataFrame) -> None:
    """Render visualization of cluster distributions."""
    if len(df) == 0:
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### T-statistic Distribution")
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=df['peak_t'],
            nbinsx=30,
            name='Peak t-stats',
            marker_color='rgba(55, 83, 109, 0.8)'
        ))
        fig.update_layout(
            xaxis_title="Peak t-statistic",
            yaxis_title="Frequency",
            height=300,
            showlegend=False
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.markdown("### Cluster Size Distribution")
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=df['size_voxels'],
            nbinsx=30,
            name='Cluster sizes',
            marker_color='rgba(55, 109, 83, 0.8)'
        ))
        fig.update_layout(
            xaxis_title="Cluster size (voxels)",
            yaxis_title="Frequency",
            height=300,
            showlegend=False
        )
        st.plotly_chart(fig, use_container_width=True)


def render_anatomical_summary(df: pd.DataFrame) -> None:
    """Render summary of anatomical regions found."""
    if len(df) == 0 or 'anatomical_region' not in df.columns:
        return
    
    st.markdown("### 🗺️ Anatomical Distribution")
    
    # Count regions
    region_counts = df['anatomical_region'].value_counts()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Top Regions:**")
        for region, count in region_counts.head(10).items():
            if pd.notna(region) and region != 'N/A':
                st.caption(f"• {region}: {count} clusters")
    
    with col2:
        if len(region_counts) > 0:
            fig = go.Figure()
            fig.add_trace(go.Bar(
                y=region_counts.head(10).index,
                x=region_counts.head(10).values,
                orientation='h',
                marker_color='rgba(55, 83, 109, 0.8)'
            ))
            fig.update_layout(
                xaxis_title="Number of Clusters",
                yaxis_title="Region",
                height=300,
                showlegend=False,
                margin=dict(l=200)
            )
            st.plotly_chart(fig, use_container_width=True)


# ==============================================================================
# Export Functions
# ==============================================================================

def export_cluster_table_csv(df: pd.DataFrame) -> bytes:
    """Export cluster table to CSV."""
    return df.to_csv(index=False).encode()


def export_summary_report(
    summary: Dict[str, Any],
    method: str,
    thresholds: Dict[str, float],
    direction: str,
    analysis_type: str,
    seed_name: Optional[str] = None
) -> str:
    """Generate text summary report."""
    report_lines = [
        "GROUP-LEVEL STATISTICS REPORT",
        "=" * 50,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "ANALYSIS PARAMETERS",
        "-" * 50,
        f"Analysis Type: {analysis_type}",
        f"Seed/Region: {seed_name or 'N/A'}",
        f"Correction Method: {method}",
        f"Effect Direction: {direction}",
        f"Thresholds: {thresholds}",
        "",
        "RESULTS SUMMARY",
        "-" * 50,
        f"Significant Clusters: {summary['n_clusters']} / {summary['n_total_clusters']}",
        f"Peak t-statistic: {summary['peak_t_max']:.4f} (min: {summary['peak_t_min']:.4f})",
        f"Largest Cluster: {summary['cluster_size_max']:.0f} voxels",
        f"Mean Cluster Size: {summary['cluster_size_mean']:.1f} voxels",
        f"Total Significant Voxels: {summary['total_voxels']:.0f}",
        "",
    ]
    
    if 'p_value_min' in summary:
        report_lines.extend([
            "P-VALUE STATISTICS",
            "-" * 50,
            f"P-value range: [{summary['p_value_min']:.1e}, {summary['p_value_max']:.1e}]",
            "",
        ])
    
    return "\n".join(report_lines)


def render_export_panel(
    df: pd.DataFrame,
    summary: Dict[str, Any],
    method: str,
    thresholds: Dict[str, float],
    direction: str,
    analysis_type: str,
    seed_name: Optional[str] = None
) -> None:
    """Render export options panel."""
    with st.expander("📥 Export Options"):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("Download Cluster Table (CSV)", key='export_csv'):
                csv_data = export_cluster_table_csv(df)
                st.download_button(
                    label="CSV File",
                    data=csv_data,
                    file_name=f"clusters_{method}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    key='download_csv'
                )
        
        with col2:
            if st.button("Generate Report (TXT)", key='export_report'):
                report = export_summary_report(
                    summary, method, thresholds, direction, analysis_type, seed_name
                )
                st.download_button(
                    label="Text Report",
                    data=report.encode(),
                    file_name=f"report_{method}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                    mime="text/plain",
                    key='download_report'
                )
        
        with col3:
            st.info("📊 Additional export formats (NIfTI, XLSX) coming soon")


# ==============================================================================
# Comparison Functions
# ==============================================================================

def compare_methods(
    base_df: pd.DataFrame,
    method_dfs: Dict[str, pd.DataFrame]
) -> Dict[str, Any]:
    """
    Compare clusters across different correction methods.
    
    Returns statistics on overlap and unique findings.
    """
    comparison = {
        'method_sizes': {m: len(df) for m, df in method_dfs.items()},
        'overlapping_clusters': None,
        'unique_by_method': {}
    }
    
    # Find overlaps (simplified: same peak location within 5mm)
    # This is a placeholder; full implementation would use spatial distance
    
    return comparison


def render_comparison_view(
    group_results_dir: Path,
    analysis_type: str
) -> None:
    """
    Render side-by-side comparison of different correction methods.
    """
    st.markdown("### 🔄 Method Comparison")
    
    with st.expander("Compare Correction Methods"):
        st.info(
            "Load results from different correction methods to compare "
            "cluster detection sensitivity and specificity."
        )
        
        # Try to load comparison data
        csv_files = list(group_results_dir.glob("clusters_*.csv"))
        if len(csv_files) > 1:
            st.markdown("**Available cluster tables:**")
            
            comparison_dfs = {}
            for csv_file in csv_files:
                method_name = csv_file.stem.replace('clusters_', '')
                df = load_cluster_table(str(csv_file))
                if df is not None:
                    comparison_dfs[method_name] = df
                    st.caption(f"• {method_name}: {len(df)} clusters")
            
            if len(comparison_dfs) > 1:
                st.markdown("**Cluster counts by method:**")
                comparison_df = pd.DataFrame(
                    {name: [len(df)] for name, df in comparison_dfs.items()},
                    index=['Cluster Count']
                ).T
                st.bar_chart(comparison_df)
        else:
            st.markdown(
                """
                **Comparison features (coming soon):**
                - Venn diagram of overlapping clusters
                - Consensus table (clusters found by multiple methods)
                - Sensitivity/specificity comparison
                """
            )


# ==============================================================================
# Main Rendering Function
# ==============================================================================

def render_group_stats_ui(
    group_results_dir: str,
    analysis_type: str = 'seed_based',
    title: str = "Group-Level Statistics"
) -> None:
    """
    Main rendering function for group-level statistics UI.
    
    Args:
        group_results_dir: Path to group analysis results directory
                          (e.g., path to seed_based/DiFuMo256/dlpfc_l/)
        analysis_type: 'local_measures' | 'seed_based' | 'network_connectivity'
        title: Page title
    
    Example directory structure:
        group_results_dir/
        ├── clusters_*.csv (various correction methods)
        ├── *_tstat_map.nii.gz
        ├── *_pval_map.nii.gz
        ├── model_info.json
        └── (optional) cluster_masks/
    """
    
    # Page setup
    st.set_page_config(layout="wide", page_title=title)
    st.title(title)
    
    # Initialize session state
    if 'selected_method' not in st.session_state:
        st.session_state.selected_method = 'GRF'
    if 'selected_cluster' not in st.session_state:
        st.session_state.selected_cluster = None
    
    # Validate directory
    results_path = Path(group_results_dir)
    is_valid, message, cluster_csv = validate_results_directory(group_results_dir)
    
    if not is_valid:
        st.error(message)
        with st.expander("💡 Help"):
            st.markdown("""
            **Expected directory structure:**
            ```
            results_dir/
            ├── clusters_*.csv          (required)
            ├── *_tstat_map.nii.gz      (optional)
            ├── *_pval_map.nii.gz       (optional)
            └── model_info.json         (optional)
            ```
            
            **Common fixes:**
            - Ensure cluster CSV files are present
            - Check directory permissions
            - Verify analysis has been run to completion
            """)
        return
    
    st.info(message)
    
    # Load model info if available
    model_info_path = results_path / "model_info.json"
    model_info = load_model_info(str(model_info_path))
    
    if model_info:
        with st.expander("ℹ️ Analysis Information"):
            st.json(model_info)
    
    st.markdown("---")
    
    # Method selector panel
    method, thresholds, direction = render_method_selector()
    
    st.markdown("---")
    
    # Load cluster table (using validated path)
    df_raw = load_cluster_table(str(cluster_csv))
    if df_raw is None or len(df_raw) == 0:
        st.error("❌ Could not load cluster table or table is empty")
        with st.expander("💡 Debugging"):
            st.write(f"Attempted path: {cluster_csv}")
            st.write(f"File exists: {cluster_csv.exists()}")
            st.write(f"File size: {cluster_csv.stat().st_size} bytes")
        return
    
    # Apply filters
    df_filtered = apply_threshold_filters(df_raw, method, thresholds, direction)
    
    # Compute summary
    summary = compute_summary_statistics(df_filtered, df_raw)
    
    # Render summary panels
    render_summary_panels(summary)
    
    st.markdown("---")
    
    # Render cluster table
    df_display, selected_idx = render_cluster_table(df_filtered)
    
    st.markdown("---")
    
    # Render distribution plots
    if len(df_filtered) > 0:
        render_cluster_distribution_plot(df_filtered)
        render_anatomical_summary(df_filtered)
        st.markdown("---")
    
    # Export panel
    render_export_panel(
        df_filtered,
        summary,
        method,
        thresholds,
        direction,
        analysis_type,
        seed_name=results_path.name if results_path.name.startswith('seed_') else None
    )
    
    st.markdown("---")
    
    # Comparison view
    render_comparison_view(results_path, analysis_type)
    
    # Footer
    st.markdown("---")
    st.caption(
        f"Rendered {len(df_filtered)} clusters from {len(df_raw)} total | "
        f"Method: {method} | Direction: {direction}"
    )
