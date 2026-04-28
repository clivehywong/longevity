#!/usr/bin/env python
"""
Integration test: Load real correlation matrix and verify rendering.
"""

import sys
from pathlib import Path
import numpy as np

# Add utils to path
sys.path.insert(0, str(Path(__file__).parent))

from utils.matrix_renderer import (
    load_correlation_matrix,
    validate_correlation_matrix,
    plot_correlation_heatmap,
    plot_network_graph,
    aggregate_to_networks,
)

def test_real_data():
    """Load and visualize real correlation matrix from project."""
    
    derivatives_root = Path("/home/clivewong/proj/longevity/derivatives/preprocessing/xcpd/ec")
    
    # Find first available correlation matrix
    correlation_files = list(derivatives_root.glob("*/*/func/*4S256Parcels*relmat.tsv"))
    
    if not correlation_files:
        print("❌ No correlation matrices found")
        return False
    
    filepath = correlation_files[0]
    print(f"✓ Loading: {filepath}")
    
    # Load matrix
    corr_matrix, roi_labels = load_correlation_matrix(filepath)
    print(f"✓ Matrix shape: {corr_matrix.shape}")
    print(f"✓ ROI labels: {len(roi_labels)}")
    
    # Validate
    is_valid, msg = validate_correlation_matrix(corr_matrix, roi_labels)
    if not is_valid:
        print(f"❌ Validation failed: {msg}")
        return False
    print(f"✓ Matrix validation passed")
    
    # Check statistics
    print(f"\nMatrix Statistics:")
    print(f"  Diagonal mean: {np.mean(np.diag(corr_matrix)):.3f}")
    print(f"  Mean correlation: {np.mean(corr_matrix[np.triu_indices_from(corr_matrix, k=1)]):.3f}")
    print(f"  Max correlation: {np.max(corr_matrix[np.triu_indices_from(corr_matrix, k=1)]):.3f}")
    print(f"  Min correlation: {np.min(corr_matrix[np.triu_indices_from(corr_matrix, k=1)]):.3f}")
    
    # Test heatmap generation
    print(f"\n✓ Generating heatmap...")
    fig_heatmap = plot_correlation_heatmap(
        corr_matrix,
        roi_labels=roi_labels,
        title="Test Heatmap",
        threshold=0.3
    )
    assert fig_heatmap is not None
    print(f"✓ Heatmap generated successfully")
    
    # Test network graph
    print(f"✓ Generating network graph...")
    fig_network = plot_network_graph(
        corr_matrix,
        roi_labels=roi_labels,
        threshold=0.4,
        layout_type="spring"
    )
    assert fig_network is not None
    print(f"✓ Network graph generated successfully")
    
    # Test network aggregation
    print(f"✓ Aggregating to networks...")
    agg_matrix, networks = aggregate_to_networks(corr_matrix, roi_labels)
    print(f"✓ Aggregated to {len(networks)} networks: {', '.join(networks)}")
    print(f"  Aggregated matrix shape: {agg_matrix.shape}")
    
    print(f"\n✅ All integration tests passed!")
    return True

if __name__ == "__main__":
    success = test_real_data()
    sys.exit(0 if success else 1)
