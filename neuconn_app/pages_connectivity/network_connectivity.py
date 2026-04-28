"""Network connectivity analysis page for DiFuMo 256 correlation matrices.

Interactive visualization of whole-brain correlation matrices with network
aggregation, within/between-network statistics, and group-level analysis.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.matrix_renderer import (
    load_correlation_matrix,
    plot_correlation_heatmap,
    plot_network_graph,
    aggregate_to_networks,
    validate_correlation_matrix,
)


# ============================================================================
# Utility Functions
# ============================================================================


def get_subject_session_pairs(results_dir: Path) -> list:
    """Get available subject-session pairs from connectivity results."""
    matrix_dir = results_dir / "connectivity" / "subject_fc_matrices"
    if not matrix_dir.exists():
        return []
    
    pairs = []
    for matrix_file in sorted(matrix_dir.glob("*_fc_pearson.csv")):
        # Extract subject and session from filename
        filename = matrix_file.stem
        parts = filename.split("_")
        if len(parts) >= 2:
            subject = parts[0]
            session = parts[1] if parts[1].startswith("ses") else "01"
            pairs.append((subject, session))
    
    return sorted(list(set(pairs)))


def load_subject_matrix(
    results_dir: Path,
    subject_id: str,
    session: str,
    metric: str = "pearson"
) -> Tuple[Optional[np.ndarray], Optional[list]]:
    """Load correlation matrix for subject-session pair."""
    matrix_path = (
        results_dir / "connectivity" / "subject_fc_matrices"
        / f"{subject_id}_{session}_fc_{metric}.csv"
    )
    
    if not matrix_path.exists():
        return None, None
    
    try:
        corr_matrix, roi_labels = load_correlation_matrix(matrix_path)
        return corr_matrix, roi_labels
    except Exception as e:
        st.error(f"Error loading matrix: {e}")
        return None, None


def load_group_matrix(results_dir: Path) -> Tuple[Optional[np.ndarray], Optional[list]]:
    """Load group-level correlation matrix."""
    matrix_path = results_dir / "connectivity" / "group_connectome.csv"
    
    if not matrix_path.exists():
        return None, None
    
    try:
        corr_matrix, roi_labels = load_correlation_matrix(matrix_path)
        return corr_matrix, roi_labels
    except Exception as e:
        st.error(f"Error loading group matrix: {e}")
        return None, None


def compute_network_stats(
    corr_matrix: np.ndarray,
    roi_labels: list,
    threshold: float = 0.1
) -> dict:
    """Compute within-network and between-network statistics."""
    # Extract network from ROI label (e.g., "LH_Vis_1" -> "Vis")
    def get_network(label: str) -> str:
        parts = label.split("_")
        if len(parts) >= 2:
            return parts[1]
        return "Unknown"
    
    networks = {}
    for i, label in enumerate(roi_labels):
        net = get_network(label)
        if net not in networks:
            networks[net] = []
        networks[net].append(i)
    
    stats = {}
    
    # Within-network connectivity
    for net_name, indices in networks.items():
        if len(indices) > 1:
            within_conn = corr_matrix[np.ix_(indices, indices)]
            # Exclude diagonal
            mask = ~np.eye(len(indices), dtype=bool)
            within_values = within_conn[mask]
            within_values = within_values[np.abs(within_values) >= threshold]
            
            if len(within_values) > 0:
                stats[f"within_{net_name}"] = {
                    "mean": float(np.mean(within_values)),
                    "std": float(np.std(within_values)),
                    "count": len(within_values),
                }
    
    # Between-network connectivity (average)
    net_names = sorted(networks.keys())
    between_stats = []
    for i, net1 in enumerate(net_names):
        for net2 in net_names[i+1:]:
            indices1 = networks[net1]
            indices2 = networks[net2]
            between_conn = corr_matrix[np.ix_(indices1, indices2)]
            between_values = between_conn.flatten()
            between_values = between_values[np.abs(between_values) >= threshold]
            
            if len(between_values) > 0:
                between_stats.append({
                    "network_pair": f"{net1} ↔ {net2}",
                    "mean": float(np.mean(between_values)),
                    "std": float(np.std(between_values)),
                    "count": len(between_values),
                })
    
    stats["between_network"] = pd.DataFrame(between_stats)
    
    return stats


def render() -> None:
    """Main page render function."""
    st.header("🧠 Network Connectivity")
    
    config = st.session_state.get("config", {})
    if not config:
        st.error("Configuration not loaded.")
        return
    
    results_dir = Path(config["paths"].get("results_dir", "results"))
    
    # Check data availability
    subject_pairs = get_subject_session_pairs(results_dir)
    group_matrix, group_labels = load_group_matrix(results_dir)
    
    if not subject_pairs and group_matrix is None:
        st.warning("No connectivity data available. Run the connectivity pipeline first.")
        return
    
    st.caption(
        f"Source: `{results_dir / 'connectivity'}`  \n"
        f"Atlas: DiFuMo 256 | Space: MNI152NLin2009cAsym:res-2"
    )
    
    # ========================================================================
    # Tab Selection: Subject vs Group
    # ========================================================================
    
    tab_subject, tab_group, tab_comparison = st.tabs([
        "📊 Subject-Level",
        "👥 Group-Level",
        "📈 Comparison"
    ])
    
    # ========================================================================
    # TAB 1: Subject-Level Analysis
    # ========================================================================
    
    with tab_subject:
        if not subject_pairs:
            st.info("No subject-level connectivity data available.")
        else:
            # Subject and session selection
            col1, col2, col3 = st.columns([2, 2, 1])
            
            with col1:
                selected_pair = st.selectbox(
                    "Select Subject-Session",
                    options=subject_pairs,
                    format_func=lambda x: f"{x[0]} - {x[1]}",
                    key="subject_pair_selector"
                )
            
            with col2:
                metric = st.selectbox(
                    "Correlation Metric",
                    options=["pearson", "fisherz"],
                    key="metric_selector"
                )
            
            with col3:
                if st.button("🔄 Refresh", key="refresh_subject"):
                    st.rerun()
            
            subject_id, session = selected_pair
            corr_matrix, roi_labels = load_subject_matrix(
                results_dir, subject_id, session, metric
            )
            
            if corr_matrix is not None:
                # Validation
                is_valid, error_msg = validate_correlation_matrix(corr_matrix, roi_labels)
                if not is_valid:
                    st.error(f"Invalid matrix: {error_msg}")
                else:
                    # Visualization controls in sidebar
                    st.sidebar.markdown("### Subject Visualization Controls")
                    
                    threshold = st.sidebar.slider(
                        "Correlation Threshold",
                        min_value=0.0,
                        max_value=1.0,
                        value=0.2,
                        step=0.05,
                        help="Hide correlations with |r| < threshold",
                        key="subject_threshold"
                    )
                    
                    colormap = st.sidebar.selectbox(
                        "Heatmap Colormap",
                        options=["RdBu", "coolwarm", "viridis", "icefire", "Spectral"],
                        value="RdBu",
                        key="subject_colormap"
                    )
                    
                    sort_method = st.sidebar.radio(
                        "Heatmap Sorting",
                        options=[None, "hierarchical", "by_mean_connectivity"],
                        format_func=lambda x: {
                            None: "No sorting",
                            "hierarchical": "Hierarchical clustering",
                            "by_mean_connectivity": "By mean connectivity"
                        }.get(x, str(x)),
                        key="subject_sort"
                    )
                    
                    layout_type = st.sidebar.selectbox(
                        "Network Graph Layout",
                        options=["spring", "circular", "kamada_kawai"],
                        format_func=lambda x: {
                            "spring": "Spring (force-directed)",
                            "circular": "Circular",
                            "kamada_kawai": "Kamada-Kawai"
                        }.get(x, x),
                        key="subject_layout"
                    )
                    
                    show_labels = st.sidebar.checkbox(
                        "Show node labels in graph",
                        value=True,
                        key="subject_labels"
                    )
                    
                    # Display visualizations
                    st.subheader(f"{subject_id} - {session} ({metric})")
                    
                    col_heat, col_graph = st.columns([0.5, 0.5])
                    
                    with col_heat:
                        st.markdown("**Correlation Heatmap**")
                        try:
                            heatmap_fig = plot_correlation_heatmap(
                                corr_matrix,
                                roi_labels=roi_labels,
                                title=f"Full DiFuMo 256 Matrix",
                                colormap=colormap,
                                threshold=threshold,
                                sort_method=sort_method,
                                figsize=(700, 700),
                                auto_scale=False
                            )
                            st.plotly_chart(heatmap_fig, use_container_width=True)
                        except Exception as e:
                            st.error(f"Error rendering heatmap: {e}")
                    
                    with col_graph:
                        st.markdown("**Network Graph**")
                        try:
                            graph_fig = plot_network_graph(
                                corr_matrix,
                                roi_labels=roi_labels,
                                title=f"Network Connectivity",
                                threshold=threshold,
                                layout_type=layout_type,
                                figsize=(700, 700),
                                show_labels=show_labels,
                                edge_width_scale=5.0
                            )
                            st.plotly_chart(graph_fig, use_container_width=True)
                        except Exception as e:
                            st.error(f"Error rendering graph: {e}")
                    
                    # Network-level aggregation
                    st.markdown("---")
                    st.subheader("Network-Level Analysis")
                    
                    col_net_mat, col_net_graph = st.columns([0.5, 0.5])
                    
                    with col_net_mat:
                        st.markdown("**Inter-Network Matrix**")
                        try:
                            net_corr, net_labels = aggregate_to_networks(
                                corr_matrix, roi_labels
                            )
                            net_fig = plot_correlation_heatmap(
                                net_corr,
                                roi_labels=net_labels,
                                title="Inter-Network Correlation",
                                colormap=colormap,
                                threshold=0.0,
                                sort_method=None,
                                figsize=(600, 600),
                                auto_scale=True
                            )
                            st.plotly_chart(net_fig, use_container_width=True)
                        except Exception as e:
                            st.error(f"Error aggregating networks: {e}")
                    
                    with col_net_graph:
                        st.markdown("**Inter-Network Graph**")
                        try:
                            net_graph_fig = plot_network_graph(
                                net_corr,
                                roi_labels=net_labels,
                                title="Network-Level Connectivity",
                                threshold=0.1,
                                layout_type="spring",
                                figsize=(600, 600),
                                show_labels=True,
                                edge_width_scale=5.0
                            )
                            st.plotly_chart(net_graph_fig, use_container_width=True)
                        except Exception as e:
                            st.error(f"Error rendering network graph: {e}")
                    
                    # Within/Between statistics
                    st.markdown("---")
                    st.subheader("Within/Between-Network Statistics")
                    
                    try:
                        stats = compute_network_stats(corr_matrix, roi_labels, threshold=0.05)
                        
                        # Within-network stats
                        col1, col2 = st.columns(2)
                        within_stats = {k: v for k, v in stats.items() if k.startswith("within_")}
                        
                        if within_stats:
                            with col1:
                                st.markdown("**Within-Network Connectivity**")
                                within_df = pd.DataFrame([
                                    {
                                        "Network": k.replace("within_", ""),
                                        "Mean r": v["mean"],
                                        "Std": v["std"],
                                        "N edges": v["count"],
                                    }
                                    for k, v in within_stats.items()
                                ]).sort_values("Mean r", ascending=False)
                                st.dataframe(within_df, use_container_width=True, hide_index=True)
                        
                        # Between-network stats
                        if not stats["between_network"].empty:
                            with col2:
                                st.markdown("**Between-Network Connectivity**")
                                between_df = stats["between_network"].sort_values("mean", ascending=False)
                                st.dataframe(between_df, use_container_width=True, hide_index=True)
                    
                    except Exception as e:
                        st.error(f"Error computing statistics: {e}")
                    
                    # Matrix statistics summary
                    st.markdown("---")
                    st.subheader("Matrix Summary Statistics")
                    
                    col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
                    
                    with col_stat1:
                        diag_mean = np.mean(np.diag(corr_matrix))
                        st.metric("Diagonal (self-corr)", f"{diag_mean:.3f}")
                    
                    with col_stat2:
                        off_diag = corr_matrix[~np.eye(len(corr_matrix), dtype=bool)]
                        st.metric("Mean off-diagonal", f"{np.mean(off_diag):.3f}")
                    
                    with col_stat3:
                        st.metric("Matrix range", f"[{np.min(corr_matrix):.3f}, {np.max(corr_matrix):.3f}]")
                    
                    with col_stat4:
                        high_corr = np.sum(np.abs(off_diag) > 0.5)
                        pct = 100 * high_corr / len(off_diag)
                        st.metric("|r| > 0.5", f"{pct:.1f}%")
    
    # ========================================================================
    # TAB 2: Group-Level Analysis
    # ========================================================================
    
    with tab_group:
        if group_matrix is None:
            st.info("No group-level connectivity data available.")
        else:
            st.subheader("Group-Level Network Connectivity")
            st.caption(f"N = {len(subject_pairs)} subjects")
            
            # Visualization controls
            st.sidebar.markdown("### Group Visualization Controls")
            
            threshold = st.sidebar.slider(
                "Correlation Threshold",
                min_value=0.0,
                max_value=1.0,
                value=0.2,
                step=0.05,
                help="Hide correlations with |r| < threshold",
                key="group_threshold"
            )
            
            colormap = st.sidebar.selectbox(
                "Heatmap Colormap",
                options=["RdBu", "coolwarm", "viridis", "icefire", "Spectral"],
                value="RdBu",
                key="group_colormap"
            )
            
            sort_method = st.sidebar.radio(
                "Heatmap Sorting",
                options=[None, "hierarchical", "by_mean_connectivity"],
                format_func=lambda x: {
                    None: "No sorting",
                    "hierarchical": "Hierarchical clustering",
                    "by_mean_connectivity": "By mean connectivity"
                }.get(x, str(x)),
                key="group_sort"
            )
            
            layout_type = st.sidebar.selectbox(
                "Network Graph Layout",
                options=["spring", "circular", "kamada_kawai"],
                format_func=lambda x: {
                    "spring": "Spring (force-directed)",
                    "circular": "Circular",
                    "kamada_kawai": "Kamada-Kawai"
                }.get(x, x),
                key="group_layout"
            )
            
            show_labels = st.sidebar.checkbox(
                "Show node labels in graph",
                value=False,
                key="group_labels"
            )
            
            col_heat, col_graph = st.columns([0.5, 0.5])
            
            with col_heat:
                st.markdown("**Group Correlation Heatmap**")
                try:
                    heatmap_fig = plot_correlation_heatmap(
                        group_matrix,
                        roi_labels=group_labels,
                        title="Group-Level DiFuMo 256 Matrix",
                        colormap=colormap,
                        threshold=threshold,
                        sort_method=sort_method,
                        figsize=(700, 700),
                        auto_scale=False
                    )
                    st.plotly_chart(heatmap_fig, use_container_width=True)
                except Exception as e:
                    st.error(f"Error rendering heatmap: {e}")
            
            with col_graph:
                st.markdown("**Group Network Graph**")
                try:
                    graph_fig = plot_network_graph(
                        group_matrix,
                        roi_labels=group_labels,
                        title="Group-Level Network",
                        threshold=threshold,
                        layout_type=layout_type,
                        figsize=(700, 700),
                        show_labels=show_labels,
                        edge_width_scale=5.0
                    )
                    st.plotly_chart(graph_fig, use_container_width=True)
                except Exception as e:
                    st.error(f"Error rendering graph: {e}")
            
            # Group network-level analysis
            st.markdown("---")
            st.subheader("Group Network-Level Analysis")
            
            col_net_mat, col_net_graph = st.columns([0.5, 0.5])
            
            with col_net_mat:
                st.markdown("**Inter-Network Matrix**")
                try:
                    net_corr, net_labels = aggregate_to_networks(
                        group_matrix, group_labels
                    )
                    net_fig = plot_correlation_heatmap(
                        net_corr,
                        roi_labels=net_labels,
                        title="Group Inter-Network Correlation",
                        colormap=colormap,
                        threshold=0.0,
                        sort_method=None,
                        figsize=(600, 600),
                        auto_scale=True
                    )
                    st.plotly_chart(net_fig, use_container_width=True)
                except Exception as e:
                    st.error(f"Error aggregating networks: {e}")
            
            with col_net_graph:
                st.markdown("**Inter-Network Graph**")
                try:
                    net_graph_fig = plot_network_graph(
                        net_corr,
                        roi_labels=net_labels,
                        title="Group Network-Level Connectivity",
                        threshold=0.1,
                        layout_type="spring",
                        figsize=(600, 600),
                        show_labels=True,
                        edge_width_scale=5.0
                    )
                    st.plotly_chart(net_graph_fig, use_container_width=True)
                except Exception as e:
                    st.error(f"Error rendering network graph: {e}")
            
            # Group statistics
            st.markdown("---")
            st.subheader("Group Within/Between-Network Statistics")
            
            try:
                stats = compute_network_stats(group_matrix, group_labels, threshold=0.05)
                
                col1, col2 = st.columns(2)
                within_stats = {k: v for k, v in stats.items() if k.startswith("within_")}
                
                if within_stats:
                    with col1:
                        st.markdown("**Within-Network Connectivity**")
                        within_df = pd.DataFrame([
                            {
                                "Network": k.replace("within_", ""),
                                "Mean r": v["mean"],
                                "Std": v["std"],
                                "N edges": v["count"],
                            }
                            for k, v in within_stats.items()
                        ]).sort_values("Mean r", ascending=False)
                        st.dataframe(within_df, use_container_width=True, hide_index=True)
                
                if not stats["between_network"].empty:
                    with col2:
                        st.markdown("**Between-Network Connectivity**")
                        between_df = stats["between_network"].sort_values("mean", ascending=False)
                        st.dataframe(between_df, use_container_width=True, hide_index=True)
            
            except Exception as e:
                st.error(f"Error computing statistics: {e}")
    
    # ========================================================================
    # TAB 3: Subject Comparison
    # ========================================================================
    
    with tab_comparison:
        if len(subject_pairs) < 2:
            st.info("Need at least 2 subjects for comparison.")
        else:
            st.subheader("Subject-to-Group Comparison")
            
            col1, col2 = st.columns(2)
            
            with col1:
                selected_pair = st.selectbox(
                    "Select Subject for Comparison",
                    options=subject_pairs,
                    format_func=lambda x: f"{x[0]} - {x[1]}",
                    key="comparison_subject_pair"
                )
            
            with col2:
                metric = st.selectbox(
                    "Correlation Metric",
                    options=["pearson", "fisherz"],
                    key="comparison_metric"
                )
            
            subject_id, session = selected_pair
            subject_matrix, subject_labels = load_subject_matrix(
                results_dir, subject_id, session, metric
            )
            
            if subject_matrix is not None and group_matrix is not None:
                # Compute subject vs group difference
                difference = subject_matrix - group_matrix
                
                st.markdown("---")
                col_sub, col_grp, col_diff = st.columns(3)
                
                with col_sub:
                    st.markdown("**Subject Matrix**")
                    subject_fig = plot_correlation_heatmap(
                        subject_matrix,
                        roi_labels=subject_labels,
                        title=f"{subject_id}-{session}",
                        colormap="RdBu",
                        threshold=0.0,
                        sort_method=None,
                        figsize=(500, 500),
                        auto_scale=False
                    )
                    st.plotly_chart(subject_fig, use_container_width=True)
                
                with col_grp:
                    st.markdown("**Group Mean Matrix**")
                    group_fig = plot_correlation_heatmap(
                        group_matrix,
                        roi_labels=group_labels,
                        title="Group Mean",
                        colormap="RdBu",
                        threshold=0.0,
                        sort_method=None,
                        figsize=(500, 500),
                        auto_scale=False
                    )
                    st.plotly_chart(group_fig, use_container_width=True)
                
                with col_diff:
                    st.markdown("**Difference (Subject - Group)**")
                    diff_fig = plot_correlation_heatmap(
                        difference,
                        roi_labels=subject_labels,
                        title="Subject - Group",
                        colormap="coolwarm",
                        threshold=0.0,
                        sort_method=None,
                        figsize=(500, 500),
                        auto_scale=True
                    )
                    st.plotly_chart(diff_fig, use_container_width=True)
                
                # Comparison statistics
                st.markdown("---")
                col_stat1, col_stat2, col_stat3 = st.columns(3)
                
                with col_stat1:
                    mean_diff = np.mean(difference[~np.eye(len(difference), dtype=bool)])
                    st.metric("Mean difference", f"{mean_diff:.4f}")
                
                with col_stat2:
                    max_diff = np.max(np.abs(difference))
                    st.metric("Max |difference|", f"{max_diff:.4f}")
                
                with col_stat3:
                    corr_sim = np.corrcoef(
                        subject_matrix.flatten(),
                        group_matrix.flatten()
                    )[0, 1]
                    st.metric("Correlation with group", f"{corr_sim:.4f}")


if __name__ == "__main__":
    render()
