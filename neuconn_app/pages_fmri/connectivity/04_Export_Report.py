"""
HTML Report Export for Connectivity Analysis Results

Streamlit page for exporting interactive analysis results as standalone HTML files.

Features:
- Export group statistics with embedded Papaya viewers
- Export functional connectivity matrices
- Export local measures analysis
- Embedded Papaya 3D brain maps (works offline)
- Print-friendly HTML reports
"""

import sys
from pathlib import Path

import streamlit as st
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.report_exporter import (
    ReportBuilder,
    export_group_stats_report,
    export_connectivity_report,
    load_nifti_as_base64,
    get_nifti_stats,
)


def render():
    """Main render function for export page."""
    
    st.set_page_config(layout="wide", page_title="Export Report")
    
    st.title("📄 Export Analysis Results as HTML")
    
    st.markdown("""
    Generate standalone, print-friendly HTML reports with:
    - 🧠 Embedded Papaya 3D brain viewers
    - 📊 Interactive correlation matrices
    - 📈 Group statistics and cluster tables
    - 🖨️ Print-optimized CSS styling
    - 📥 All assets embedded (works offline)
    """)
    
    st.markdown("---")
    
    # Report type selection
    col1, col2 = st.columns(2)
    
    with col1:
        report_type = st.radio(
            "Select Report Type:",
            options=[
                "Group Statistics",
                "Connectivity Matrix",
                "Local Measures",
                "Custom Report",
            ],
            key="report_type_select",
        )
    
    # Initialize session state for output
    if 'report_path' not in st.session_state:
        st.session_state.report_path = None
    if 'report_ready' not in st.session_state:
        st.session_state.report_ready = False
    
    # Route based on report type
    if report_type == "Group Statistics":
        render_group_stats_export()
    
    elif report_type == "Connectivity Matrix":
        render_connectivity_export()
    
    elif report_type == "Local Measures":
        render_local_measures_export()
    
    elif report_type == "Custom Report":
        render_custom_report()
    
    # Display generated report info
    if st.session_state.report_ready and st.session_state.report_path:
        st.success(f"✅ Report generated successfully!")
        st.info(f"📁 Saved to: `{st.session_state.report_path}`")
        
        with st.expander("📖 View Report Information"):
            file_path = Path(st.session_state.report_path)
            if file_path.exists():
                file_size_mb = file_path.stat().st_size / (1024 * 1024)
                st.metric("File Size", f"{file_size_mb:.2f} MB")
                st.metric("Created", str(file_path.stat().st_mtime))


def render_group_stats_export():
    """Export group statistics as HTML report."""
    
    st.subheader("📊 Group Statistics Report")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Analysis Settings**")
        
        analysis_type = st.selectbox(
            "Analysis Type:",
            options=["seed_based", "local_measures", "network_connectivity"],
            key="group_analysis_type",
        )
        
        # Default directories
        default_dirs = {
            "seed_based": "/home/clivewong/proj/longevity/derivatives/connectivity-difumo256/group-level/seed_based/dlpfc_l",
            "local_measures": "/home/clivewong/proj/longevity/results/group_analysis/local_measures",
            "network_connectivity": "/home/clivewong/proj/longevity/results/group_analysis/network_connectivity",
        }
        
        use_custom = st.checkbox("Use custom directory", value=False, key="group_custom_dir")
        
        if use_custom:
            results_dir = st.text_input(
                "Results directory:",
                value=default_dirs.get(analysis_type, ""),
                key="group_results_dir_input",
            )
        else:
            results_dir = default_dirs.get(analysis_type, "")
            st.caption(f"Using: `{results_dir}`")
    
    with col2:
        st.markdown("**Report Settings**")
        
        report_title = st.text_input(
            "Report Title:",
            value=f"{analysis_type.replace('_', ' ').title()} - Group Analysis",
            key="group_report_title",
        )
        
        include_metadata = st.checkbox(
            "Include analysis metadata",
            value=True,
            key="group_include_metadata",
        )
        
        colormap = st.selectbox(
            "Brain map colormap:",
            options=["Hot", "Jet", "Viridis", "Gray"],
            key="group_colormap",
        )
    
    # Advanced options
    with st.expander("⚙️ Advanced Settings"):
        st.markdown("**Thresholding**")
        col_a, col_b = st.columns(2)
        
        with col_a:
            min_thresh = st.slider(
                "Min threshold (percentile):",
                min_value=0.0,
                max_value=100.0,
                value=0.0,
                key="group_min_thresh",
            )
        
        with col_b:
            max_thresh = st.slider(
                "Max threshold (percentile):",
                min_value=0.0,
                max_value=100.0,
                value=100.0,
                key="group_max_thresh",
            )
        
        overlay_alpha = st.slider(
            "Overlay transparency:",
            min_value=0.0,
            max_value=1.0,
            value=0.7,
            step=0.1,
            key="group_overlay_alpha",
        )
    
    # File selection
    st.markdown("**Select Files to Include**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        brain_map_path = st.text_input(
            "Statistical map (NIfTI):",
            placeholder="Path to .nii.gz file",
            key="group_brain_map",
        )
        
        if brain_map_path and Path(brain_map_path).exists():
            stats = get_nifti_stats(brain_map_path)
            st.caption(f"✓ Map loaded | Shape: {stats['shape']} | Range: [{stats['min']:.3f}, {stats['max']:.3f}]")
    
    with col2:
        clusters_csv = st.text_input(
            "Cluster table (CSV):",
            placeholder="Path to clusters.csv",
            key="group_clusters_csv",
        )
        
        if clusters_csv and Path(clusters_csv).exists():
            try:
                df = pd.read_csv(clusters_csv)
                st.caption(f"✓ Loaded | {len(df)} clusters")
            except Exception as e:
                st.error(f"Error loading clusters: {e}")
    
    # Export button
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        output_filename = st.text_input(
            "Output filename:",
            value="group_stats_report.html",
            key="group_output_filename",
        )
    
    with col2:
        if st.button("📥 Export Report", key="group_export_btn", use_container_width=True):
            if not brain_map_path or not Path(brain_map_path).exists():
                st.error("Please provide a valid statistical map path")
            else:
                try:
                    output_path = Path.home() / "Downloads" / output_filename
                    
                    metadata = {}
                    if include_metadata:
                        metadata = {
                            "Analysis Type": analysis_type,
                            "Colormap": colormap,
                            "Threshold": f"{min_thresh:.1f} - {max_thresh:.1f}%",
                        }
                    
                    # Build report
                    export_group_stats_report(
                        output_path=str(output_path),
                        group_results_dir=results_dir,
                        brain_map_path=brain_map_path,
                        clusters_csv=clusters_csv if clusters_csv and Path(clusters_csv).exists() else None,
                        title=report_title,
                        metadata=metadata,
                    )
                    
                    st.session_state.report_path = str(output_path)
                    st.session_state.report_ready = True
                    st.rerun()
                
                except Exception as e:
                    st.error(f"Error generating report: {e}")
                    import traceback
                    st.error(traceback.format_exc())


def render_connectivity_export():
    """Export functional connectivity matrix as HTML report."""
    
    st.subheader("🔗 Functional Connectivity Report")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Data Source**")
        
        data_source = st.radio(
            "Load connectivity data from:",
            options=["CSV File", "Subject Result", "Group Connectome"],
            key="fc_data_source",
        )
    
    with col2:
        st.markdown("**Report Settings**")
        
        report_title = st.text_input(
            "Report Title:",
            value="Functional Connectivity Report",
            key="fc_report_title",
        )
        
        threshold = st.slider(
            "Correlation threshold for highlighting:",
            min_value=0.0,
            max_value=1.0,
            value=0.3,
            step=0.05,
            key="fc_threshold",
        )
    
    # Load connectivity data based on source
    fc_matrix = None
    roi_labels = None
    fc_csv_path = None
    
    if data_source == "CSV File":
        fc_csv_path = st.text_input(
            "Path to CSV file (with ROI labels as index):",
            placeholder="Path to connectivity matrix CSV",
            key="fc_csv_path",
        )
        
        if fc_csv_path and Path(fc_csv_path).exists():
            try:
                df = pd.read_csv(fc_csv_path, index_col=0)
                fc_matrix = df.values
                roi_labels = df.columns.tolist()
                st.success(f"✓ Loaded {len(roi_labels)}×{len(roi_labels)} matrix")
                
                with st.expander("Preview matrix"):
                    st.dataframe(df.head(10), use_container_width=True)
            
            except Exception as e:
                st.error(f"Error loading CSV: {e}")
    
    elif data_source == "Subject Result":
        results_dir = Path("/home/clivewong/proj/longevity/results/connectivity/subject_fc_matrices")
        
        if results_dir.exists():
            csv_files = sorted(results_dir.glob("*.csv"))
            
            selected_file = st.selectbox(
                "Select subject result:",
                options=csv_files,
                format_func=lambda x: x.name,
                key="subject_result_select",
            )
            
            if selected_file:
                try:
                    df = pd.read_csv(selected_file, index_col=0)
                    fc_matrix = df.values
                    roi_labels = df.columns.tolist()
                    fc_csv_path = str(selected_file)
                    
                    st.success(f"✓ Loaded {selected_file.name}")
                except Exception as e:
                    st.error(f"Error loading file: {e}")
        else:
            st.warning("Subject results directory not found")
    
    elif data_source == "Group Connectome":
        group_file = Path("/home/clivewong/proj/longevity/results/connectivity/group_connectome.csv")
        
        if group_file.exists():
            try:
                df = pd.read_csv(group_file, index_col=0)
                fc_matrix = df.values
                roi_labels = df.columns.tolist()
                fc_csv_path = str(group_file)
                
                st.success(f"✓ Loaded group connectome ({len(roi_labels)} ROIs)")
            except Exception as e:
                st.error(f"Error loading group connectome: {e}")
        else:
            st.warning("Group connectome file not found")
    
    # Display matrix stats if loaded
    if fc_matrix is not None:
        st.markdown("**Matrix Statistics**")
        
        col_a, col_b, col_c, col_d = st.columns(4)
        
        with col_a:
            st.metric("ROIs", fc_matrix.shape[0])
        
        with col_b:
            st.metric("Min Correlation", f"{fc_matrix.min():.3f}")
        
        with col_c:
            st.metric("Max Correlation", f"{fc_matrix.max():.3f}")
        
        with col_d:
            mean_corr = fc_matrix[np.triu_indices_from(fc_matrix, k=1)].mean()
            st.metric("Mean Correlation", f"{mean_corr:.3f}")
    
    # Export button
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        output_filename = st.text_input(
            "Output filename:",
            value="connectivity_report.html",
            key="fc_output_filename",
        )
    
    with col2:
        if st.button("📥 Export Report", key="fc_export_btn", use_container_width=True):
            if fc_matrix is None:
                st.error("Please load connectivity data first")
            else:
                try:
                    output_path = Path.home() / "Downloads" / output_filename
                    
                    export_connectivity_report(
                        output_path=str(output_path),
                        fc_matrix=fc_matrix,
                        roi_labels=roi_labels,
                        title=report_title,
                        metadata={"Data Source": data_source, "Threshold": f"{threshold:.2f}"},
                    )
                    
                    st.session_state.report_path = str(output_path)
                    st.session_state.report_ready = True
                    st.rerun()
                
                except Exception as e:
                    st.error(f"Error generating report: {e}")
                    import traceback
                    st.error(traceback.format_exc())


def render_local_measures_export():
    """Export local measures analysis as HTML report."""
    
    st.subheader("📍 Local Measures Report")
    
    st.info("🚧 Local measures export coming soon")
    
    st.markdown("""
    This feature will support:
    - ReHo (Regional Homogeneity) maps
    - fALFF (Fractional Amplitude of Low Frequency Fluctuations)
    - Group-level local measures
    - Embedded 3D viewers for each measure
    """)


def render_custom_report():
    """Build custom report with selected components."""
    
    st.subheader("🔨 Custom Report Builder")
    
    st.markdown("Combine multiple analysis components into a single report.")
    
    # Title and metadata
    col1, col2 = st.columns(2)
    
    with col1:
        report_title = st.text_input(
            "Report Title:",
            value="Custom Analysis Report",
            key="custom_title",
        )
    
    with col2:
        output_filename = st.text_input(
            "Output filename:",
            value="custom_report.html",
            key="custom_filename",
        )
    
    # Component selection
    st.markdown("**Select Components to Include**")
    
    include_brain_map = st.checkbox(
        "Brain map viewer (Papaya)",
        value=False,
        key="custom_include_brain",
    )
    
    include_matrix = st.checkbox(
        "Correlation matrix",
        value=False,
        key="custom_include_matrix",
    )
    
    include_stats = st.checkbox(
        "Summary statistics",
        value=False,
        key="custom_include_stats",
    )
    
    include_clusters = st.checkbox(
        "Cluster table",
        value=False,
        key="custom_include_clusters",
    )
    
    if not any([include_brain_map, include_matrix, include_stats, include_clusters]):
        st.warning("Please select at least one component")
        return
    
    # Component-specific inputs
    brain_map_path = None
    if include_brain_map:
        brain_map_path = st.text_input(
            "Brain map (NIfTI):",
            key="custom_brain_path",
        )
    
    matrix_path = None
    if include_matrix:
        matrix_path = st.text_input(
            "Correlation matrix (CSV):",
            key="custom_matrix_path",
        )
    
    clusters_path = None
    if include_clusters:
        clusters_path = st.text_input(
            "Cluster table (CSV):",
            key="custom_clusters_path",
        )
    
    # Build button
    if st.button("🔨 Build Custom Report", use_container_width=True, key="custom_build"):
        try:
            output_path = Path.home() / "Downloads" / output_filename
            
            builder = ReportBuilder(
                title=report_title,
                analysis_type="custom",
                output_path=str(output_path),
            )
            
            builder.add_header()
            
            if include_brain_map and brain_map_path and Path(brain_map_path).exists():
                builder.add_papaya_viewer(
                    brain_map_path=brain_map_path,
                    title="Brain Map",
                )
            
            if include_matrix and matrix_path and Path(matrix_path).exists():
                try:
                    df = pd.read_csv(matrix_path, index_col=0)
                    builder.add_correlation_matrix(
                        matrix=df.values,
                        roi_labels=df.columns.tolist(),
                    )
                except Exception as e:
                    st.warning(f"Could not load matrix: {e}")
            
            if include_clusters and clusters_path and Path(clusters_path).exists():
                try:
                    df = pd.read_csv(clusters_path)
                    builder.add_cluster_table(df)
                except Exception as e:
                    st.warning(f"Could not load clusters: {e}")
            
            builder.build()
            
            st.session_state.report_path = str(output_path)
            st.session_state.report_ready = True
            st.rerun()
        
        except Exception as e:
            st.error(f"Error building report: {e}")
            import traceback
            st.error(traceback.format_exc())


if __name__ == "__main__":
    render()
