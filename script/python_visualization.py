#!/usr/bin/env python3
"""
Visualization Module for Connectivity Analysis Results

Creates publication-ready figures:
- Connectivity matrices (network-ordered, with significance overlays)
- Network graphs (force-directed, circular layouts)
- Effect size distributions
- Statistical summary plots

Usage:
    python python_visualization.py \\
        --results results/connectivity_analysis/connectivity_anova_results.csv \\
        --networks difumo256_network_definitions.json \\
        --output figures/

Dependencies:
    pip install matplotlib seaborn networkx pandas numpy
"""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap

# Optional: networkx for graph layouts
try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False
    print("Warning: networkx not available, skipping network graph visualizations")


# Publication-quality defaults
plt.rcParams['figure.dpi'] = 150
plt.rcParams['savefig.dpi'] = 300
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans']
plt.rcParams['font.size'] = 10
plt.rcParams['axes.linewidth'] = 1.2
plt.rcParams['axes.labelsize'] = 11
plt.rcParams['axes.titlesize'] = 12
plt.rcParams['xtick.labelsize'] = 9
plt.rcParams['ytick.labelsize'] = 9
plt.rcParams['legend.fontsize'] = 9


# Yeo 7-Network colors (standard in neuroscience)
YEO_COLORS = {
    'Visual': '#781286',
    'Somatomotor': '#4682B4',
    'DorsalAttention': '#00760E',
    'SalienceVentralAttention': '#C43AFA',
    'Limbic': '#DCF8A4',
    'FrontoParietal': '#E69422',
    'DefaultMode': '#CD3E4E',
    'Subcortical': '#888888',
    'Cerebellar_Motor': '#FF6B6B',
    'Cerebellar_Cognitive': '#4ECDC4',
    'Cerebellar_Vestibular': '#FFE66D'
}


def load_network_definitions(network_file):
    """Load network definitions and ROI-to-network mapping."""
    with open(network_file, 'r') as f:
        net_defs = json.load(f)

    # Create ROI index to network mapping
    roi_to_network = {}
    for component in net_defs['components']:
        roi_idx = component['index']
        network = component['network']
        roi_to_network[roi_idx] = network

    return net_defs, roi_to_network


def create_network_ordered_indices(roi_to_network):
    """
    Create ROI ordering by network for matrix visualization.

    Returns:
        sorted_indices: ROI indices sorted by network
        network_boundaries: Indices where networks change (for grid lines)
    """
    # Group ROIs by network
    network_to_rois = {}
    for roi_idx, network in roi_to_network.items():
        if network not in network_to_rois:
            network_to_rois[network] = []
        network_to_rois[network].append(roi_idx)

    # Sort ROIs within each network
    for network in network_to_rois:
        network_to_rois[network] = sorted(network_to_rois[network])

    # Concatenate in network order (consistent order for visualization)
    network_order = sorted(network_to_rois.keys())

    sorted_indices = []
    network_boundaries = [0]

    for network in network_order:
        rois = network_to_rois[network]
        sorted_indices.extend(rois)
        network_boundaries.append(network_boundaries[-1] + len(rois))

    return sorted_indices, network_boundaries, network_order


def plot_connectivity_matrix(results_df, roi_to_network, output_file, effect='interaction',
                              alpha=0.05, reorder_by_network=True):
    """
    Plot connectivity matrix with significance overlay.

    Parameters:
        results_df: DataFrame with connectivity results
        roi_to_network: dict mapping ROI index to network
        output_file: output path
        effect: 'interaction', 'group', or 'time'
        alpha: significance threshold (FDR-corrected)
        reorder_by_network: if True, reorder ROIs by network
    """
    print(f"Plotting connectivity matrix ({effect} effect)...")

    n_rois = max(max(results_df['roi_i']), max(results_df['roi_j'])) + 1

    # Initialize matrices
    coef_matrix = np.zeros((n_rois, n_rois))
    pval_matrix = np.ones((n_rois, n_rois))
    sig_matrix = np.zeros((n_rois, n_rois), dtype=bool)

    # Fill matrices
    for idx, row in results_df.iterrows():
        i, j = row['roi_i'], row['roi_j']
        coef = row[f'{effect}_coef']
        pval = row[f'{effect}_pval_fdr']
        sig = row[f'{effect}_significant_fdr']

        # Symmetric matrix
        coef_matrix[i, j] = coef
        coef_matrix[j, i] = coef
        pval_matrix[i, j] = pval
        pval_matrix[j, i] = pval
        sig_matrix[i, j] = sig
        sig_matrix[j, i] = sig

    # Reorder by network if requested
    if reorder_by_network:
        sorted_indices, network_boundaries, network_order = create_network_ordered_indices(roi_to_network)

        # Reorder matrices
        coef_matrix = coef_matrix[sorted_indices, :][:, sorted_indices]
        sig_matrix = sig_matrix[sorted_indices, :][:, sorted_indices]

    # Plot
    fig, ax = plt.subplots(figsize=(10, 9))

    # Plot coefficient matrix
    vmax = np.abs(coef_matrix).max()
    im = ax.imshow(coef_matrix, cmap='RdBu_r', vmin=-vmax, vmax=vmax, aspect='auto')

    # Overlay significance (white dots or borders)
    sig_coords = np.argwhere(sig_matrix)
    if len(sig_coords) > 0:
        ax.scatter(sig_coords[:, 1], sig_coords[:, 0], s=1, c='black', alpha=0.5, marker='.')

    # Network boundaries (grid lines)
    if reorder_by_network:
        for boundary in network_boundaries[1:-1]:  # Skip first and last
            ax.axhline(boundary - 0.5, color='white', linewidth=1.5, alpha=0.7)
            ax.axvline(boundary - 0.5, color='white', linewidth=1.5, alpha=0.7)

        # Network labels
        for i, network in enumerate(network_order):
            start = network_boundaries[i]
            end = network_boundaries[i + 1]
            mid = (start + end) / 2
            color = YEO_COLORS.get(network, '#888888')

            # Left side labels
            ax.text(-5, mid, network, va='center', ha='right', fontsize=8,
                    color=color, weight='bold')

            # Top labels (rotated)
            ax.text(mid, -5, network, va='bottom', ha='center', fontsize=8,
                    color=color, weight='bold', rotation=45)

    # Colorbar
    cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label(f'{effect.capitalize()} Effect (Coefficient)', fontsize=10)

    # Title
    n_sig = sig_matrix.sum() // 2  # Divide by 2 for symmetry
    ax.set_title(f'Connectivity Matrix: {effect.capitalize()} Effect\\n'
                 f'{n_sig} significant connections (FDR q<{alpha})',
                 fontsize=12, weight='bold')

    # Clean up axes
    ax.set_xlabel('ROI Index (network-ordered)', fontsize=10)
    ax.set_ylabel('ROI Index (network-ordered)', fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])

    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  Saved: {output_file}")


def plot_connectivity_matrix_with_significance(connectivity_df, significant_df,
                                                 network_definitions, output_path,
                                                 effect='interaction', alpha=0.05):
    """
    Plot connectivity matrix with black dots on significant connections.

    Designed for HTML report embedding with enhanced significance visualization.

    Parameters
    ----------
    connectivity_df : pd.DataFrame
        Full connectivity results with roi_i, roi_j, and effect columns
    significant_df : pd.DataFrame
        Significant connections only (FDR-corrected)
    network_definitions : dict or str
        Network definitions dict or path to JSON file
    output_path : str or Path
        Output file path
    effect : str
        Effect to plot ('interaction', 'group', 'time')
    alpha : float
        FDR threshold used

    Returns
    -------
    None (saves figure to output_path)
    """
    print(f"Creating connectivity matrix with significance overlay ({effect})...")

    # Load network definitions if path provided
    if isinstance(network_definitions, (str, Path)):
        net_defs, roi_to_network = load_network_definitions(network_definitions)
    else:
        net_defs = network_definitions
        roi_to_network = {comp['index']: comp['network']
                          for comp in network_definitions.get('components', [])}

    # Get all ROI indices
    all_rois = sorted(set(connectivity_df['roi_i'].tolist() + connectivity_df['roi_j'].tolist()))
    n_rois = len(all_rois)

    # Initialize matrices
    coef_matrix = np.zeros((n_rois, n_rois))
    sig_matrix = np.zeros((n_rois, n_rois), dtype=bool)

    # ROI index to matrix index mapping
    roi_to_idx = {roi: idx for idx, roi in enumerate(all_rois)}

    # Fill coefficient matrix
    for _, row in connectivity_df.iterrows():
        i_idx = roi_to_idx.get(row['roi_i'])
        j_idx = roi_to_idx.get(row['roi_j'])

        if i_idx is not None and j_idx is not None:
            coef = row[f'{effect}_coef']
            coef_matrix[i_idx, j_idx] = coef
            coef_matrix[j_idx, i_idx] = coef  # Symmetric

    # Mark significant connections
    for _, row in significant_df.iterrows():
        i_idx = roi_to_idx.get(row['roi_i'])
        j_idx = roi_to_idx.get(row['roi_j'])

        if i_idx is not None and j_idx is not None:
            sig_matrix[i_idx, j_idx] = True
            sig_matrix[j_idx, i_idx] = True

    # Reorder by network
    roi_to_net_dict = {roi: roi_to_network.get(roi, 'Unknown') for roi in all_rois}
    sorted_indices, network_boundaries, network_order = create_network_ordered_indices(roi_to_net_dict)

    coef_matrix_reordered = coef_matrix[sorted_indices, :][:, sorted_indices]
    sig_matrix_reordered = sig_matrix[sorted_indices, :][:, sorted_indices]

    # Create figure
    fig, ax = plt.subplots(figsize=(12, 11))

    # Plot matrix
    vmax = np.abs(coef_matrix_reordered).max()
    if vmax == 0:
        vmax = 1

    im = ax.imshow(coef_matrix_reordered, cmap='RdBu_r',
                   vmin=-vmax, vmax=vmax, aspect='auto', interpolation='nearest')

    # Overlay significance with black circles
    sig_coords = np.argwhere(sig_matrix_reordered)
    if len(sig_coords) > 0:
        ax.scatter(sig_coords[:, 1], sig_coords[:, 0],
                   s=2, c='black', alpha=0.8, marker='o', linewidths=0)

    # Network grid lines
    for boundary in network_boundaries[1:-1]:
        ax.axhline(boundary - 0.5, color='white', linewidth=2, alpha=0.9)
        ax.axvline(boundary - 0.5, color='white', linewidth=2, alpha=0.9)

    # Network labels (color-coded)
    label_fontsize = 9 if len(network_order) <= 7 else 7

    for i, network in enumerate(network_order):
        start = network_boundaries[i]
        end = network_boundaries[i + 1]
        mid = (start + end) / 2
        color = YEO_COLORS.get(network, '#888888')

        # Left labels
        ax.text(-2, mid, network, va='center', ha='right',
                fontsize=label_fontsize, color=color, weight='bold')

        # Top labels
        ax.text(mid, -2, network, va='bottom', ha='center',
                fontsize=label_fontsize, color=color, weight='bold',
                rotation=45, rotation_mode='anchor')

    # Colorbar
    cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, shrink=0.8)
    cbar.set_label(f'{effect.capitalize()} Effect (Beta Coefficient)', fontsize=11)

    # Title with significance count
    n_sig = sig_matrix_reordered.sum() // 2
    ax.set_title(f'Functional Connectivity Matrix: {effect.capitalize()} Effect\n'
                 f'{n_sig} Significant Connections (FDR q < {alpha})',
                 fontsize=13, weight='bold', pad=15)

    # Clean axes
    ax.set_xlabel('ROI Index (Network-Ordered)', fontsize=11)
    ax.set_ylabel('ROI Index (Network-Ordered)', fontsize=11)
    ax.set_xticks([])
    ax.set_yticks([])

    # Add legend for significance marker
    from matplotlib.lines import Line2D
    legend_elements = [Line2D([0], [0], marker='o', color='w',
                              markerfacecolor='black', markersize=5,
                              label=f'Significant (FDR q<{alpha})')]
    ax.legend(handles=legend_elements, loc='lower right', fontsize=9, framealpha=0.9)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  Saved connectivity matrix: {output_path}")


def plot_significant_connections_network_graph(results_df, roi_to_network, network_defs,
                                                 output_file, effect='interaction', alpha=0.05,
                                                 top_n=50):
    """
    Plot network graph of significant connections.

    Parameters:
        results_df: DataFrame with connectivity results
        roi_to_network: dict mapping ROI index to network
        network_defs: network definitions dict
        output_file: output path
        effect: 'interaction', 'group', or 'time'
        alpha: significance threshold
        top_n: show only top N strongest connections
    """
    if not HAS_NETWORKX:
        print("  Skipping network graph (networkx not available)")
        return

    print(f"Plotting network graph ({effect} effect, top {top_n} connections)...")

    # Filter significant connections
    sig_df = results_df[results_df[f'{effect}_significant_fdr']].copy()

    if len(sig_df) == 0:
        print(f"  No significant connections for {effect} effect, skipping")
        return

    # Sort by absolute effect size and take top N
    sig_df['abs_coef'] = sig_df[f'{effect}_coef'].abs()
    sig_df = sig_df.sort_values('abs_coef', ascending=False).head(top_n)

    # Create graph
    G = nx.Graph()

    # Add edges (connections)
    for idx, row in sig_df.iterrows():
        roi_i, roi_j = row['roi_i'], row['roi_j']
        weight = row['abs_coef']

        G.add_edge(roi_i, roi_j, weight=weight)

    # Node colors by network
    node_colors = [YEO_COLORS.get(roi_to_network.get(node, 'Unknown'), '#888888')
                   for node in G.nodes()]

    # Node sizes by degree
    node_sizes = [300 + 100 * G.degree(node) for node in G.nodes()]

    # Edge widths by weight
    edge_weights = [G[u][v]['weight'] for u, v in G.edges()]
    edge_widths = [1 + 3 * (w / max(edge_weights)) for w in edge_weights]

    # Layout
    pos = nx.spring_layout(G, k=0.5, iterations=50, seed=42)

    # Plot
    fig, ax = plt.subplots(figsize=(12, 10))

    # Draw network
    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=node_sizes,
                            alpha=0.8, ax=ax)
    nx.draw_networkx_edges(G, pos, width=edge_widths, alpha=0.4, ax=ax)

    # Add ROI labels (optional, can be crowded)
    if len(G.nodes()) < 30:
        # Get ROI names if available
        roi_labels = {}
        for component in network_defs.get('components', []):
            roi_idx = component['index']
            if roi_idx in G.nodes():
                # Abbreviate long names
                name = component['name']
                if len(name) > 20:
                    name = name[:17] + '...'
                roi_labels[roi_idx] = f"{roi_idx}:{name}"

        nx.draw_networkx_labels(G, pos, labels=roi_labels, font_size=7, ax=ax)

    # Legend for networks
    legend_patches = []
    networks_in_graph = set(roi_to_network.get(node, 'Unknown') for node in G.nodes())
    for network in sorted(networks_in_graph):
        color = YEO_COLORS.get(network, '#888888')
        legend_patches.append(mpatches.Patch(color=color, label=network))

    ax.legend(handles=legend_patches, loc='upper left', fontsize=8,
              title='Network', framealpha=0.9)

    ax.set_title(f'Significant Connectivity Network: {effect.capitalize()} Effect\\n'
                 f'Top {len(sig_df)} connections (FDR q<{alpha})',
                 fontsize=12, weight='bold')
    ax.axis('off')

    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  Saved: {output_file}")


def plot_effect_size_distribution(effect_df, output_file):
    """Plot distribution of effect sizes (Cohen's d)."""
    print("Plotting effect size distribution...")

    fig, ax = plt.subplots(figsize=(8, 5))

    # Histogram
    cohens_d = effect_df['cohens_d_interaction'].dropna()
    ax.hist(cohens_d, bins=30, color='#4682B4', alpha=0.7, edgecolor='black')

    # Mean line
    mean_d = cohens_d.mean()
    ax.axvline(mean_d, color='red', linestyle='--', linewidth=2,
               label=f'Mean d = {mean_d:.3f}')

    # Zero line
    ax.axvline(0, color='black', linestyle='-', linewidth=1, alpha=0.3)

    # Effect size thresholds (Cohen's conventions)
    ax.axvline(0.2, color='green', linestyle=':', linewidth=1, alpha=0.5, label='Small (d=0.2)')
    ax.axvline(0.5, color='orange', linestyle=':', linewidth=1, alpha=0.5, label='Medium (d=0.5)')
    ax.axvline(0.8, color='red', linestyle=':', linewidth=1, alpha=0.5, label='Large (d=0.8)')

    ax.set_xlabel("Cohen's d (Interaction Effect)", fontsize=11)
    ax.set_ylabel('Frequency', fontsize=11)
    ax.set_title('Effect Size Distribution for Significant Interactions', fontsize=12, weight='bold')
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  Saved: {output_file}")


def plot_top_connections_table(results_df, network_defs, output_file, effect='interaction', top_n=20):
    """Create a table figure with top connections."""
    print(f"Creating top connections table ({effect} effect)...")

    sig_df = results_df[results_df[f'{effect}_significant_fdr']].copy()

    if len(sig_df) == 0:
        print(f"  No significant connections for {effect} effect, skipping")
        return

    # Sort and take top N
    sig_df = sig_df.sort_values(f'{effect}_pval_fdr').head(top_n)

    # Prepare table data
    roi_labels = {comp['index']: comp['name'] for comp in network_defs.get('components', [])}

    table_data = []
    for idx, row in sig_df.iterrows():
        roi_i_name = roi_labels.get(row['roi_i'], f"ROI {row['roi_i']}")
        roi_j_name = roi_labels.get(row['roi_j'], f"ROI {row['roi_j']}")

        # Abbreviate long names
        if len(roi_i_name) > 30:
            roi_i_name = roi_i_name[:27] + '...'
        if len(roi_j_name) > 30:
            roi_j_name = roi_j_name[:27] + '...'

        table_data.append([
            f"{roi_i_name}\\n↔\\n{roi_j_name}",
            f"{row[f'{effect}_coef']:.4f}",
            f"{row[f'{effect}_pval_fdr']:.2e}"
        ])

    # Create figure
    fig, ax = plt.subplots(figsize=(10, top_n * 0.4))
    ax.axis('tight')
    ax.axis('off')

    table = ax.table(cellText=table_data,
                     colLabels=['Connection', 'Coefficient', 'p-value (FDR)'],
                     cellLoc='left',
                     loc='center',
                     colWidths=[0.6, 0.2, 0.2])

    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 2)

    # Style header
    for (i, j), cell in table.get_celld().items():
        if i == 0:  # Header row
            cell.set_facecolor('#4682B4')
            cell.set_text_props(weight='bold', color='white')
        else:
            if i % 2 == 0:
                cell.set_facecolor('#F0F0F0')

    ax.set_title(f'Top {top_n} Connections: {effect.capitalize()} Effect',
                 fontsize=12, weight='bold', pad=20)

    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"  Saved: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Visualization for connectivity analysis results"
    )
    parser.add_argument('--results', required=True,
                        help='CSV file with connectivity ANOVA results')
    parser.add_argument('--networks', required=True,
                        help='JSON file with network definitions')
    parser.add_argument('--effect-sizes',
                        help='CSV file with effect sizes (optional)')
    parser.add_argument('--output', required=True,
                        help='Output directory for figures')
    parser.add_argument('--alpha', type=float, default=0.05,
                        help='FDR alpha level (default: 0.05)')
    parser.add_argument('--top-n', type=int, default=50,
                        help='Number of top connections to show in graphs (default: 50)')

    args = parser.parse_args()

    # Load data
    results_df = pd.read_csv(args.results)
    network_defs, roi_to_network = load_network_definitions(args.networks)

    # Create output directory
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "="*60)
    print("CONNECTIVITY VISUALIZATION")
    print("="*60)

    # 1. Connectivity matrices
    for effect in ['interaction', 'group', 'time']:
        plot_connectivity_matrix(
            results_df, roi_to_network,
            output_dir / f'connectivity_matrix_{effect}.png',
            effect=effect, alpha=args.alpha
        )

    # 2. Network graphs (significant connections)
    for effect in ['interaction', 'group', 'time']:
        plot_significant_connections_network_graph(
            results_df, roi_to_network, network_defs,
            output_dir / f'network_graph_{effect}.png',
            effect=effect, alpha=args.alpha, top_n=args.top_n
        )

    # 3. Top connections tables
    for effect in ['interaction', 'group', 'time']:
        plot_top_connections_table(
            results_df, network_defs,
            output_dir / f'top_connections_{effect}.png',
            effect=effect, top_n=20
        )

    # 4. Effect size distribution (if available)
    if args.effect_sizes and Path(args.effect_sizes).exists():
        effect_df = pd.read_csv(args.effect_sizes)
        plot_effect_size_distribution(effect_df, output_dir / 'effect_size_distribution.png')

    print("\nVisualization complete!")
    print(f"Figures saved to: {output_dir}")


if __name__ == '__main__':
    main()
