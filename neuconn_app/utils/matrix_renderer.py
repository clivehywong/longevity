"""
Correlation Matrix Visualization Component

Interactive heatmap and network graph visualizations for correlation matrices
with Streamlit integration. Supports multiple colormaps, thresholding,
hierarchical clustering, and network layout algorithms.

Key Features:
- Interactive plotly heatmaps with hover and zoom/pan
- Network graph visualization with customizable layouts
- Threshold filtering and colormap selection
- Hierarchical clustering
- Export to PNG, SVG, or HTML
- Handles 256×256 DiFuMo and smaller network-level matrices
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple, List, Union
from pathlib import Path
import warnings

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import networkx as nx
from scipy.cluster.hierarchy import dendrogram, linkage
from scipy.spatial.distance import pdist, squareform


def validate_correlation_matrix(
    corr_matrix: np.ndarray,
    roi_labels: Optional[List[str]] = None
) -> Tuple[bool, str]:
    """
    Validate correlation matrix structure.

    Args:
        corr_matrix: (N, N) correlation matrix
        roi_labels: Optional list of N ROI labels

    Returns:
        (is_valid, error_message)
    """
    if not isinstance(corr_matrix, np.ndarray):
        return False, "Input must be numpy array"

    if len(corr_matrix.shape) != 2:
        return False, f"Expected 2D array, got {len(corr_matrix.shape)}D"

    n, m = corr_matrix.shape
    if n != m:
        return False, f"Matrix must be square, got {n}×{m}"

    # Check diagonal is ~1 (self-correlation)
    diag = np.diag(corr_matrix)
    if not np.allclose(diag, 1.0, atol=0.1):
        warnings.warn(f"Matrix diagonal not ~1.0 (range: {diag.min():.3f} to {diag.max():.3f})")

    # Check symmetry
    if not np.allclose(corr_matrix, corr_matrix.T, atol=1e-10):
        warnings.warn("Matrix not symmetric (may be directed connectivity)")

    if roi_labels is not None and len(roi_labels) != n:
        return False, f"ROI labels count ({len(roi_labels)}) != matrix size ({n})"

    return True, ""


def load_correlation_matrix(
    filepath: Union[str, Path]
) -> Tuple[np.ndarray, List[str]]:
    """
    Load correlation matrix from TSV or CSV file.

    Args:
        filepath: Path to TSV/CSV file with ROI labels as first column/row

    Returns:
        (correlation_matrix, roi_labels)
    """
    filepath = Path(filepath)

    if filepath.suffix == ".tsv":
        df = pd.read_csv(filepath, sep="\t", index_col=0)
    else:
        df = pd.read_csv(filepath, index_col=0)

    roi_labels = list(df.index)
    corr_matrix = df.values.astype(np.float32)

    return corr_matrix, roi_labels


def get_hierarchical_clustering_order(
    corr_matrix: np.ndarray
) -> List[int]:
    """
    Get hierarchical clustering order for reordering matrix rows/columns.

    Args:
        corr_matrix: (N, N) correlation matrix

    Returns:
        List of indices in clustered order
    """
    distance_matrix = 1 - np.abs(corr_matrix)
    condensed_dist = pdist(corr_matrix, metric="euclidean")
    linkage_matrix = linkage(condensed_dist, method="ward")

    dendro = dendrogram(linkage_matrix, no_plot=True)
    return dendro["leaves"]


def plot_correlation_heatmap(
    corr_matrix: np.ndarray,
    roi_labels: Optional[List[str]] = None,
    title: str = "Correlation Matrix",
    colormap: str = "RdBu",
    threshold: float = 0.0,
    sort_method: Optional[str] = None,
    figsize: Tuple[int, int] = (800, 800),
    auto_scale: bool = False
) -> go.Figure:
    """
    Create interactive correlation heatmap with plotly.

    Args:
        corr_matrix: (N, N) correlation matrix
        roi_labels: List of N ROI labels (auto-generated if None)
        title: Figure title
        colormap: 'RdBu', 'coolwarm', 'viridis', 'icefire', 'Spectral'
        threshold: Hide correlations with |r| < threshold (set to gray)
        sort_method: None, 'hierarchical', 'by_mean_connectivity'
        figsize: (width, height) in pixels
        auto_scale: If True, scale to actual data range; else use [-1, 1]

    Returns:
        plotly Figure object
    """
    is_valid, error_msg = validate_correlation_matrix(corr_matrix, roi_labels)
    if not is_valid:
        raise ValueError(error_msg)

    n = corr_matrix.shape[0]

    if roi_labels is None:
        roi_labels = [f"ROI-{i+1}" for i in range(n)]

    matrix_display = corr_matrix.copy()

    if sort_method == "hierarchical":
        order = get_hierarchical_clustering_order(corr_matrix)
        matrix_display = matrix_display[np.ix_(order, order)]
        roi_labels = [roi_labels[i] for i in order]
    elif sort_method == "by_mean_connectivity":
        mean_conn = np.abs(corr_matrix).mean(axis=1)
        order = np.argsort(-mean_conn)
        matrix_display = matrix_display[np.ix_(order, order)]
        roi_labels = [roi_labels[i] for i in order]

    mask = np.abs(matrix_display) < threshold
    matrix_display_masked = matrix_display.copy()
    matrix_display_masked[mask] = np.nan

    colorscale = {
        "RdBu": "RdBu",
        "coolwarm": "RdYlBu_r",
        "viridis": "Viridis",
        "icefire": "Icefire",
        "Spectral": "Spectral"
    }.get(colormap, "RdBu")

    if auto_scale:
        vmin, vmax = np.nanmin(matrix_display_masked), np.nanmax(matrix_display_masked)
    else:
        vmin, vmax = -1, 1

    hovertext = []
    for i, label_i in enumerate(roi_labels):
        row = []
        for j, label_j in enumerate(roi_labels):
            val = matrix_display[i, j]
            is_below_threshold = np.abs(val) < threshold
            status = "(below threshold)" if is_below_threshold else ""
            row.append(f"{label_i} → {label_j}<br>r = {val:.3f} {status}")
        hovertext.append(row)

    fig = go.Figure(data=go.Heatmap(
        z=matrix_display_masked,
        x=roi_labels,
        y=roi_labels,
        colorscale=colorscale,
        zmid=0,
        zmin=vmin,
        zmax=vmax,
        hovertext=hovertext,
        hoverinfo="text",
        colorbar=dict(title="Correlation"),
        showscale=True
    ))

    fig.update_layout(
        title=title,
        xaxis_title="ROI",
        yaxis_title="ROI",
        width=figsize[0],
        height=figsize[1],
        hovermode="closest",
        xaxis=dict(side="bottom"),
        yaxis=dict(autorange="reversed")
    )

    return fig


def plot_network_graph(
    corr_matrix: np.ndarray,
    roi_labels: Optional[List[str]] = None,
    title: str = "Network Graph",
    threshold: float = 0.3,
    node_size: int = 15,
    layout_type: str = "spring",
    figsize: Tuple[int, int] = (800, 800),
    show_labels: bool = True,
    edge_width_scale: float = 5.0
) -> go.Figure:
    """
    Create network graph visualization with networkx + plotly.

    Args:
        corr_matrix: (N, N) correlation matrix
        roi_labels: List of N ROI labels (auto-generated if None)
        title: Figure title
        threshold: Only show edges with |r| > threshold
        node_size: Node size in pixels
        layout_type: 'spring', 'circular', 'kamada_kawai'
        figsize: (width, height) in pixels
        show_labels: If True, show node labels
        edge_width_scale: Scale factor for edge width (width = |r| * scale)

    Returns:
        plotly Figure object
    """
    is_valid, error_msg = validate_correlation_matrix(corr_matrix, roi_labels)
    if not is_valid:
        raise ValueError(error_msg)

    n = corr_matrix.shape[0]

    if roi_labels is None:
        roi_labels = [f"ROI-{i+1}" for i in range(n)]

    G = nx.Graph()
    for i in range(n):
        G.add_node(i, label=roi_labels[i])

    for i in range(n):
        for j in range(i + 1, n):
            r = corr_matrix[i, j]
            if np.abs(r) > threshold:
                G.add_edge(i, j, weight=r, abs_weight=np.abs(r))

    if len(G.edges()) == 0:
        warnings.warn(f"No edges above threshold {threshold}. Consider lowering threshold.")

    if layout_type == "spring":
        pos = nx.spring_layout(G, k=0.5, iterations=50, seed=42)
    elif layout_type == "circular":
        pos = nx.circular_layout(G)
    elif layout_type == "kamada_kawai":
        pos = nx.kamada_kawai_layout(G)
    else:
        pos = nx.spring_layout(G, k=0.5, iterations=50, seed=42)

    edge_traces = []
    import matplotlib.cm as cm
    import matplotlib.colors as mcolors

    cmap = cm.get_cmap("RdBu")

    for i, j, data in G.edges(data=True):
        x0, y0 = pos[i]
        x1, y1 = pos[j]
        r = data["weight"]

        norm = mcolors.Normalize(vmin=-1, vmax=1)
        rgba = cmap(norm(r))
        color = f"rgba({int(rgba[0]*255)}, {int(rgba[1]*255)}, {int(rgba[2]*255)}, 0.8)"

        edge_trace = go.Scatter(
            x=[x0, x1],
            y=[y0, y1],
            mode="lines",
            line=dict(width=np.abs(r) * edge_width_scale, color=color),
            hoverinfo="text",
            text=f"r = {r:.3f}",
            showlegend=False
        )
        edge_traces.append(edge_trace)

    edge_trace = edge_traces if edge_traces else [go.Scatter()]

    node_x, node_y, node_label = [], [], []
    for node in G.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        node_label.append(roi_labels[node])

    node_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers+text" if show_labels else "markers",
        text=node_label if show_labels else None,
        textposition="top center",
        hoverinfo="text",
        hovertext=node_label,
        marker=dict(
            size=node_size,
            color="lightblue",
            line=dict(width=1, color="steelblue"),
        ),
        showlegend=False
    )

    fig = go.Figure(data=edge_trace + [node_trace])

    fig.update_layout(
        title=title,
        showlegend=False,
        hovermode="closest",
        margin=dict(b=0, l=0, r=0, t=40),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        width=figsize[0],
        height=figsize[1],
        plot_bgcolor="white"
    )

    return fig


def plot_network_and_heatmap_side_by_side(
    corr_matrix: np.ndarray,
    roi_labels: Optional[List[str]] = None,
    title: str = "Network Connectivity",
    threshold: float = 0.2,
    colormap: str = "RdBu",
    figsize: Tuple[int, int] = (1600, 700)
) -> go.Figure:
    """
    Create side-by-side heatmap and network graph visualization.

    Args:
        corr_matrix: (N, N) correlation matrix
        roi_labels: List of N ROI labels
        title: Figure title
        threshold: Threshold for both heatmap and network
        colormap: Colormap for heatmap
        figsize: (width, height) in pixels

    Returns:
        plotly Figure with subplots
    """
    is_valid, error_msg = validate_correlation_matrix(corr_matrix, roi_labels)
    if not is_valid:
        raise ValueError(error_msg)

    n = corr_matrix.shape[0]
    if roi_labels is None:
        roi_labels = [f"ROI-{i+1}" for i in range(n)]

    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=("Heatmap", "Network Graph"),
        specs=[[{"type": "heatmap"}, {"type": "scatter"}]]
    )

    matrix_display = corr_matrix.copy()
    mask = np.abs(matrix_display) < threshold
    matrix_display[mask] = np.nan

    colorscale_map = {
        "RdBu": "RdBu",
        "coolwarm": "RdYlBu_r",
        "viridis": "Viridis",
    }.get(colormap, "RdBu")

    fig.add_trace(go.Heatmap(
        z=matrix_display,
        x=roi_labels,
        y=roi_labels,
        colorscale=colorscale_map,
        zmid=0,
        zmin=-1,
        zmax=1,
        showscale=True,
        colorbar=dict(title="Correlation", x=0.46)
    ), row=1, col=1)

    G = nx.Graph()
    for i in range(n):
        G.add_node(i, label=roi_labels[i])

    for i in range(n):
        for j in range(i + 1, n):
            r = corr_matrix[i, j]
            if np.abs(r) > threshold:
                G.add_edge(i, j, weight=r)

    pos = nx.spring_layout(G, k=0.5, iterations=50, seed=42)

    import matplotlib.cm as cm
    import matplotlib.colors as mcolors

    cmap = cm.get_cmap("RdBu")
    norm = mcolors.Normalize(vmin=-1, vmax=1)

    for i, j, data in G.edges(data=True):
        x0, y0 = pos[i]
        x1, y1 = pos[j]
        r = data["weight"]

        rgba = cmap(norm(r))
        color = f"rgba({int(rgba[0]*255)}, {int(rgba[1]*255)}, {int(rgba[2]*255)}, 0.8)"

        fig.add_trace(go.Scatter(
            x=[x0, x1],
            y=[y0, y1],
            mode="lines",
            line=dict(width=2, color=color),
            hoverinfo="text",
            text=f"r = {r:.3f}",
            showlegend=False
        ), row=1, col=2)

    node_x, node_y, node_label = [], [], []
    for node in G.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        node_label.append(roi_labels[node])

    fig.add_trace(go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers+text",
        text=node_label,
        textposition="top center",
        hoverinfo="text",
        hovertext=node_label,
        marker=dict(size=12, color="lightblue", line=dict(width=1, color="steelblue")),
        showlegend=False
    ), row=1, col=2)

    fig.update_xaxes(title_text="ROI", row=1, col=1)
    fig.update_yaxes(title_text="ROI", row=1, col=1)
    fig.update_xaxes(showgrid=False, zeroline=False, showticklabels=False, row=1, col=2)
    fig.update_yaxes(showgrid=False, zeroline=False, showticklabels=False, row=1, col=2)

    fig.update_layout(
        title_text=title,
        height=figsize[1],
        width=figsize[0],
        showlegend=False,
        hovermode="closest"
    )

    return fig


def aggregate_to_networks(
    corr_matrix: np.ndarray,
    roi_labels: List[str],
    network_mapping: Optional[dict] = None
) -> Tuple[np.ndarray, List[str]]:
    """
    Aggregate 256×256 DiFuMo matrix to 7 Yeo networks or custom mapping.

    Args:
        corr_matrix: (N, N) correlation matrix
        roi_labels: List of N ROI labels
        network_mapping: Dict mapping {roi_label: network_name} or None for auto-Yeo

    Returns:
        (aggregated_matrix, network_names)
    """
    if network_mapping is None:
        yeo_networks = {
            "Visual": 0,
            "Somatomotor": 1,
            "Dorsal Attention": 2,
            "Salience/Ventral Attention": 3,
            "Limbic": 4,
            "Temporal Parietal": 5,
            "Default Mode": 6
        }

        network_mapping = {}
        for label in roi_labels:
            if "Vis" in label:
                network_mapping[label] = "Visual"
            elif "SomMot" in label:
                network_mapping[label] = "Somatomotor"
            elif "DorsAttn" in label:
                network_mapping[label] = "Dorsal Attention"
            elif "SalVentAttn" in label or "Salience" in label:
                network_mapping[label] = "Salience/Ventral Attention"
            elif "Limbic" in label:
                network_mapping[label] = "Limbic"
            elif "TempPar" in label:
                network_mapping[label] = "Temporal Parietal"
            elif "DMN" in label or "Default" in label:
                network_mapping[label] = "Default Mode"
            else:
                network_mapping[label] = "Unknown"

    networks = list(set(network_mapping.values()))
    networks.sort()
    n_networks = len(networks)

    aggregated = np.zeros((n_networks, n_networks))

    for i, net_i in enumerate(networks):
        for j, net_j in enumerate(networks):
            indices_i = [idx for idx, label in enumerate(roi_labels)
                        if network_mapping.get(label) == net_i]
            indices_j = [idx for idx, label in enumerate(roi_labels)
                        if network_mapping.get(label) == net_j]

            if indices_i and indices_j:
                aggregated[i, j] = corr_matrix[np.ix_(indices_i, indices_j)].mean()

    return aggregated, networks


# ============================================================================
# Streamlit Integration
# ============================================================================

def render_correlation_matrix_streamlit(
    corr_matrix: np.ndarray,
    roi_labels: Optional[List[str]] = None,
    analysis_type: str = "network_connectivity",
    subject_id: Optional[str] = None,
    session: Optional[str] = None
):
    """
    Streamlit-native widget wrapper for correlation matrix visualization.

    Creates two columns: left for heatmap, right for network graph.
    Bottom section contains controls (threshold, colormap, sort, layout, export).

    Args:
        corr_matrix: (N, N) correlation matrix
        roi_labels: List of N ROI labels
        analysis_type: 'network_connectivity', 'effective_connectivity', 'within_between'
        subject_id: Subject identifier for title
        session: Session identifier for title

    Returns:
        None (renders to streamlit app)
    """
    try:
        import streamlit as st
    except ImportError:
        raise ImportError("streamlit not installed. Install with: pip install streamlit")

    is_valid, error_msg = validate_correlation_matrix(corr_matrix, roi_labels)
    if not is_valid:
        st.error(f"Invalid correlation matrix: {error_msg}")
        return

    n = corr_matrix.shape[0]

    if roi_labels is None:
        roi_labels = [f"ROI-{i+1}" for i in range(n)]

    title = f"Correlation Matrix - {analysis_type.replace('_', ' ').title()}"
    if subject_id:
        title += f" (Sub-{subject_id}"
        if session:
            title += f", Ses-{session}"
        title += ")"

    st.subheader(title)

    st.markdown("---")

    col_left, col_right = st.columns([0.5, 0.5])

    with st.sidebar:
        st.markdown("### Visualization Controls")

        threshold = st.slider(
            "Correlation Threshold",
            min_value=0.0,
            max_value=1.0,
            value=0.2,
            step=0.05,
            help="Hide correlations with |r| < threshold"
        )

        colormap = st.selectbox(
            "Heatmap Colormap",
            options=["RdBu", "coolwarm", "viridis", "icefire", "Spectral"],
            help="Color scheme for heatmap"
        )

        sort_method = st.radio(
            "Heatmap Sorting",
            options=[None, "hierarchical", "by_mean_connectivity"],
            format_func=lambda x: {
                None: "No sorting",
                "hierarchical": "Hierarchical clustering",
                "by_mean_connectivity": "By mean connectivity"
            }.get(x, str(x))
        )

        layout_type = st.selectbox(
            "Network Graph Layout",
            options=["spring", "circular", "kamada_kawai"],
            format_func=lambda x: {
                "spring": "Spring (force-directed)",
                "circular": "Circular",
                "kamada_kawai": "Kamada-Kawai"
            }.get(x, x)
        )

        show_labels = st.checkbox("Show node labels", value=True)

        auto_scale = st.checkbox(
            "Auto-scale color range",
            value=False,
            help="If unchecked, scales to [-1, 1]"
        )

        st.markdown("---")
        st.markdown("### Export")

        export_format = st.selectbox(
            "Export Format",
            options=["PNG", "SVG", "HTML"]
        )

        if st.button("📥 Download Visualization"):
            fig = plot_correlation_heatmap(
                corr_matrix,
                roi_labels=roi_labels,
                title=title,
                colormap=colormap,
                threshold=threshold,
                sort_method=sort_method,
                auto_scale=auto_scale
            )

            if export_format == "PNG":
                img_bytes = fig.to_image(format="png")
                st.download_button(
                    label="Download PNG",
                    data=img_bytes,
                    file_name=f"correlation_matrix.png",
                    mime="image/png"
                )
            elif export_format == "SVG":
                img_bytes = fig.to_image(format="svg")
                st.download_button(
                    label="Download SVG",
                    data=img_bytes,
                    file_name=f"correlation_matrix.svg",
                    mime="image/svg+xml"
                )
            elif export_format == "HTML":
                html = fig.to_html()
                st.download_button(
                    label="Download HTML",
                    data=html,
                    file_name=f"correlation_matrix.html",
                    mime="text/html"
                )

    with col_left:
        st.markdown("**Heatmap**")
        fig_heatmap = plot_correlation_heatmap(
            corr_matrix,
            roi_labels=roi_labels,
            title="Correlation Heatmap",
            colormap=colormap,
            threshold=threshold,
            sort_method=sort_method,
            figsize=(700, 700),
            auto_scale=auto_scale
        )
        st.plotly_chart(fig_heatmap, use_container_width=True)

    with col_right:
        st.markdown("**Network Graph**")
        fig_network = plot_network_graph(
            corr_matrix,
            roi_labels=roi_labels,
            title="Network Graph",
            threshold=threshold,
            layout_type=layout_type,
            figsize=(700, 700),
            show_labels=show_labels
        )
        st.plotly_chart(fig_network, use_container_width=True)

    st.markdown("---")
    st.markdown("### Statistics")

    col_stats1, col_stats2, col_stats3 = st.columns(3)

    with col_stats1:
        n_above_threshold = np.sum(np.abs(corr_matrix) > threshold) - n
        st.metric("Connections Above Threshold", n_above_threshold // 2)

    with col_stats2:
        mean_corr = np.mean(corr_matrix[np.triu_indices_from(corr_matrix, k=1)])
        st.metric("Mean Correlation", f"{mean_corr:.3f}")

    with col_stats3:
        max_corr = np.max(corr_matrix[np.triu_indices_from(corr_matrix, k=1)])
        st.metric("Max Correlation", f"{max_corr:.3f}")
