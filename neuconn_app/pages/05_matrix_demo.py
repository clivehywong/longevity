"""
Demo page for correlation matrix visualization component.

Showcases:
- Loading real correlation matrices from project data
- Interactive heatmap with various colormaps and thresholds
- Network graph with different layout algorithms
- Side-by-side visualization
- Network-level aggregation
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.matrix_renderer import (
    load_correlation_matrix,
    plot_correlation_heatmap,
    plot_network_graph,
    plot_network_and_heatmap_side_by_side,
    aggregate_to_networks,
    render_correlation_matrix_streamlit,
)


def load_sample_data():
    """Load sample correlation matrix from project derivatives."""
    derivatives_root = Path("/home/clivewong/proj/longevity/derivatives/preprocessing/xcpd/ec")

    subject_dirs = sorted(derivatives_root.glob("sub-*/"))
    if not subject_dirs:
        return None

    subject_dir = subject_dirs[0]
    session_dirs = sorted(subject_dir.glob("ses-*/"))
    if not session_dirs:
        return None

    session_dir = session_dirs[0]
    func_dir = session_dir / "func"

    correlation_files = list(func_dir.glob("*4S256Parcels*relmat.tsv"))
    if not correlation_files:
        return None

    return correlation_files[0], subject_dir.name, session_dir.name


def render():
    """Main render function for demo page."""

    st.set_page_config(layout="wide", page_title="Correlation Matrix Viewer")

    st.title("🧠 Correlation Matrix Visualization Demo")

    st.markdown("""
    Interactive visualization of correlation matrices from functional connectivity analysis.
    
    **Features:**
    - Interactive heatmap with hover and zoom
    - Network graph with multiple layout algorithms
    - Threshold filtering for edge display
    - Colormap selection
    - Hierarchical clustering
    - Export to PNG/SVG/HTML
    """)

    st.markdown("---")

    mode = st.radio(
        "**Select Demo Mode:**",
        options=["Load Real Data", "Generate Test Data", "Side-by-Side Comparison"],
        horizontal=True
    )

    if mode == "Load Real Data":
        st.subheader("📊 Real Correlation Matrix from Project")

        sample_file = load_sample_data()
        if sample_file is None:
            st.warning("No correlation matrices found in derivatives. Please run preprocessing first.")
            return

        filepath, subject_id, session = sample_file

        st.info(f"📁 Loaded: {subject_id}/{session}/func/{filepath.name}")

        try:
            corr_matrix, roi_labels = load_correlation_matrix(filepath)
            st.success(f"✓ Matrix shape: {corr_matrix.shape[0]}×{corr_matrix.shape[1]}")

            render_correlation_matrix_streamlit(
                corr_matrix,
                roi_labels=roi_labels,
                analysis_type="network_connectivity",
                subject_id=subject_id.split("-")[1],
                session=session.split("-")[1]
            )

        except Exception as e:
            st.error(f"Error loading matrix: {e}")

    elif mode == "Generate Test Data":
        st.subheader("🧪 Test Data Generator")

        col1, col2, col3 = st.columns(3)

        with col1:
            matrix_size = st.slider("Matrix Size", min_value=5, max_value=256, value=20, step=5)

        with col2:
            sparsity = st.slider("Sparsity (% zeros)", min_value=0, max_value=90, value=30, step=10)

        with col3:
            seed = st.number_input("Random Seed", min_value=0, value=42)

        np.random.seed(seed)
        corr_matrix = np.random.randn(matrix_size, matrix_size)
        corr_matrix = (corr_matrix + corr_matrix.T) / 2
        np.fill_diagonal(corr_matrix, 1.0)

        mask = np.random.rand(matrix_size, matrix_size) < (sparsity / 100)
        corr_matrix = np.where(mask, 0, corr_matrix)
        corr_matrix = (corr_matrix + corr_matrix.T) / 2

        roi_labels = [f"ROI-{i+1}" for i in range(matrix_size)]

        st.success(f"✓ Generated {matrix_size}×{matrix_size} test matrix with {sparsity}% sparsity")

        render_correlation_matrix_streamlit(
            corr_matrix,
            roi_labels=roi_labels,
            analysis_type="test_connectivity",
            subject_id="test",
        )

    elif mode == "Side-by-Side Comparison":
        st.subheader("🔀 Side-by-Side Heatmap + Network Visualization")

        st.markdown("""
        This mode demonstrates the combined heatmap + network graph visualization.
        Useful for simultaneously viewing correlation strength and network topology.
        """)

        np.random.seed(42)
        matrix_size = st.slider("Matrix Size", min_value=5, max_value=50, value=15, step=5)

        corr_matrix = np.random.randn(matrix_size, matrix_size)
        corr_matrix = (corr_matrix + corr_matrix.T) / 2
        np.fill_diagonal(corr_matrix, 1.0)

        corr_matrix = np.clip(corr_matrix, -1, 1)

        roi_labels = [f"ROI-{i+1}" for i in range(matrix_size)]

        col1, col2 = st.columns(2)

        with col1:
            threshold = st.slider("Correlation Threshold", 0.0, 1.0, 0.3)

        with col2:
            colormap = st.selectbox("Colormap", ["RdBu", "coolwarm", "viridis"])

        st.info(f"Matrix size: {matrix_size}×{matrix_size} | Threshold: {threshold}")

        fig = plot_network_and_heatmap_side_by_side(
            corr_matrix,
            roi_labels=roi_labels,
            title="Network Connectivity Analysis",
            threshold=threshold,
            colormap=colormap,
            figsize=(1400, 600)
        )

        st.plotly_chart(fig, use_container_width=True)

        col_stats1, col_stats2, col_stats3 = st.columns(3)

        with col_stats1:
            n_edges = np.sum(np.abs(corr_matrix) > threshold) - matrix_size
            st.metric("Edges Above Threshold", n_edges // 2)

        with col_stats2:
            mean_corr = np.mean(corr_matrix[np.triu_indices_from(corr_matrix, k=1)])
            st.metric("Mean Correlation", f"{mean_corr:.3f}")

        with col_stats3:
            max_corr = np.max(corr_matrix[np.triu_indices_from(corr_matrix, k=1)])
            st.metric("Max Correlation", f"{max_corr:.3f}")

    st.markdown("---")

    st.markdown("""
    ### 📖 Documentation

    **Heatmap Controls:**
    - Hover over cells to see correlation values
    - Scroll to zoom, drag to pan
    - Use threshold slider to hide weak correlations
    - Select different colormaps (RdBu, coolwarm, viridis)
    - Sort by hierarchical clustering for pattern discovery

    **Network Graph:**
    - Node size indicates hub importance
    - Edge width represents correlation strength
    - Edge color shows correlation sign (red=positive, blue=negative)
    - Adjust threshold to reduce edge clutter
    - Try different layout algorithms

    **Color Interpretation:**
    - 🔴 Red: Strong positive correlation
    - 🔵 Blue: Strong negative correlation
    - White: Near-zero correlation
    - Gray: Below threshold (masked)
    """)


if __name__ == "__main__":
    render()
