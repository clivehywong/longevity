"""
Unit tests for correlation matrix visualization component.

Tests cover:
- Matrix validation
- Loading from TSV/CSV
- Heatmap generation
- Network graph generation
- Side-by-side visualization
- Network aggregation
"""

import pytest
import numpy as np
import pandas as pd
from pathlib import Path
import tempfile

# Add parent dir to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.matrix_renderer import (
    validate_correlation_matrix,
    load_correlation_matrix,
    get_hierarchical_clustering_order,
    plot_correlation_heatmap,
    plot_network_graph,
    plot_network_and_heatmap_side_by_side,
    aggregate_to_networks,
)


class TestMatrixValidation:
    """Tests for correlation matrix validation."""

    def test_valid_matrix(self):
        """Test valid correlation matrix."""
        corr_matrix = np.array([[1.0, 0.5], [0.5, 1.0]])
        is_valid, msg = validate_correlation_matrix(corr_matrix)
        assert is_valid
        assert msg == ""

    def test_non_square_matrix(self):
        """Test non-square matrix raises error."""
        corr_matrix = np.array([[1.0, 0.5, 0.3], [0.5, 1.0, 0.2]])
        is_valid, msg = validate_correlation_matrix(corr_matrix)
        assert not is_valid
        assert "square" in msg.lower()

    def test_wrong_label_count(self):
        """Test mismatched ROI label count."""
        corr_matrix = np.array([[1.0, 0.5], [0.5, 1.0]])
        roi_labels = ["ROI1", "ROI2", "ROI3"]
        is_valid, msg = validate_correlation_matrix(corr_matrix, roi_labels)
        assert not is_valid
        assert "labels count" in msg.lower()

    def test_non_array_input(self):
        """Test non-array input."""
        is_valid, msg = validate_correlation_matrix([[1, 0.5], [0.5, 1]])
        assert not is_valid
        assert "numpy array" in msg.lower()


class TestMatrixLoading:
    """Tests for loading correlation matrices from files."""

    def test_load_tsv(self):
        """Test loading TSV file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False) as f:
            f.write("Node\tROI1\tROI2\n")
            f.write("ROI1\t1.0\t0.5\n")
            f.write("ROI2\t0.5\t1.0\n")
            temp_path = f.name

        try:
            corr_matrix, roi_labels = load_correlation_matrix(temp_path)
            assert corr_matrix.shape == (2, 2)
            assert roi_labels == ["ROI1", "ROI2"]
            assert np.allclose(corr_matrix, np.array([[1.0, 0.5], [0.5, 1.0]]))
        finally:
            Path(temp_path).unlink()

    def test_load_csv(self):
        """Test loading CSV file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("Node,ROI1,ROI2\n")
            f.write("ROI1,1.0,0.5\n")
            f.write("ROI2,0.5,1.0\n")
            temp_path = f.name

        try:
            corr_matrix, roi_labels = load_correlation_matrix(temp_path)
            assert corr_matrix.shape == (2, 2)
            assert roi_labels == ["ROI1", "ROI2"]
        finally:
            Path(temp_path).unlink()


class TestClustering:
    """Tests for hierarchical clustering."""

    def test_clustering_order(self):
        """Test that clustering returns valid order."""
        corr_matrix = np.array([
            [1.0, 0.9, 0.1, 0.2],
            [0.9, 1.0, 0.2, 0.1],
            [0.1, 0.2, 1.0, 0.8],
            [0.2, 0.1, 0.8, 1.0]
        ])

        order = get_hierarchical_clustering_order(corr_matrix)
        assert len(order) == 4
        assert set(order) == {0, 1, 2, 3}


class TestHeatmapGeneration:
    """Tests for heatmap visualization."""

    def test_heatmap_basic(self):
        """Test basic heatmap generation."""
        corr_matrix = np.array([[1.0, 0.5], [0.5, 1.0]])
        fig = plot_correlation_heatmap(corr_matrix)
        assert fig is not None
        assert len(fig.data) > 0

    def test_heatmap_with_labels(self):
        """Test heatmap with custom labels."""
        corr_matrix = np.array([[1.0, 0.5], [0.5, 1.0]])
        roi_labels = ["MotorCtx", "PrefrontalCtx"]
        fig = plot_correlation_heatmap(corr_matrix, roi_labels=roi_labels)
        assert fig is not None

    def test_heatmap_with_threshold(self):
        """Test heatmap with threshold masking."""
        corr_matrix = np.array([[1.0, 0.1], [0.1, 1.0]])
        fig = plot_correlation_heatmap(corr_matrix, threshold=0.3)
        assert fig is not None

    def test_heatmap_colormaps(self):
        """Test different colormaps."""
        corr_matrix = np.array([[1.0, 0.5], [0.5, 1.0]])

        for colormap in ["RdBu", "coolwarm", "viridis", "icefire"]:
            fig = plot_correlation_heatmap(corr_matrix, colormap=colormap)
            assert fig is not None

    def test_heatmap_sorting(self):
        """Test heatmap sorting methods."""
        corr_matrix = np.array([
            [1.0, 0.9, 0.1],
            [0.9, 1.0, 0.2],
            [0.1, 0.2, 1.0]
        ])

        for sort_method in [None, "hierarchical", "by_mean_connectivity"]:
            fig = plot_correlation_heatmap(corr_matrix, sort_method=sort_method)
            assert fig is not None


class TestNetworkGraphGeneration:
    """Tests for network graph visualization."""

    def test_network_graph_basic(self):
        """Test basic network graph generation."""
        corr_matrix = np.array([[1.0, 0.5, 0.1], [0.5, 1.0, 0.3], [0.1, 0.3, 1.0]])
        fig = plot_network_graph(corr_matrix, threshold=0.2)
        assert fig is not None

    def test_network_graph_with_labels(self):
        """Test network graph with custom labels."""
        corr_matrix = np.array([[1.0, 0.5, 0.1], [0.5, 1.0, 0.3], [0.1, 0.3, 1.0]])
        roi_labels = ["A", "B", "C"]
        fig = plot_network_graph(corr_matrix, roi_labels=roi_labels)
        assert fig is not None

    def test_network_graph_layouts(self):
        """Test different layout algorithms."""
        corr_matrix = np.array([[1.0, 0.5, 0.1], [0.5, 1.0, 0.3], [0.1, 0.3, 1.0]])

        for layout_type in ["spring", "circular", "kamada_kawai"]:
            fig = plot_network_graph(corr_matrix, layout_type=layout_type)
            assert fig is not None

    def test_network_graph_threshold(self):
        """Test that threshold filters edges."""
        corr_matrix = np.array([[1.0, 0.1, 0.2], [0.1, 1.0, 0.3], [0.2, 0.3, 1.0]])
        fig = plot_network_graph(corr_matrix, threshold=0.5)
        assert fig is not None


class TestSideBySideVisualization:
    """Tests for combined heatmap + network visualization."""

    def test_side_by_side_basic(self):
        """Test basic side-by-side visualization."""
        corr_matrix = np.array([[1.0, 0.5, 0.2], [0.5, 1.0, 0.3], [0.2, 0.3, 1.0]])
        fig = plot_network_and_heatmap_side_by_side(corr_matrix)
        assert fig is not None
        assert len(fig.data) > 0


class TestNetworkAggregation:
    """Tests for network aggregation."""

    def test_aggregate_to_networks_custom_mapping(self):
        """Test aggregation with custom network mapping."""
        corr_matrix = np.random.rand(4, 4)
        np.fill_diagonal(corr_matrix, 1.0)
        corr_matrix = (corr_matrix + corr_matrix.T) / 2

        roi_labels = ["ROI_A1", "ROI_A2", "ROI_B1", "ROI_B2"]
        network_mapping = {
            "ROI_A1": "NetworkA",
            "ROI_A2": "NetworkA",
            "ROI_B1": "NetworkB",
            "ROI_B2": "NetworkB"
        }

        agg_matrix, networks = aggregate_to_networks(corr_matrix, roi_labels, network_mapping)
        assert agg_matrix.shape == (2, 2)
        assert set(networks) == {"NetworkA", "NetworkB"}


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_zero_threshold(self):
        """Test with zero threshold (shows all correlations)."""
        corr_matrix = np.array([[1.0, 0.0], [0.0, 1.0]])
        fig = plot_correlation_heatmap(corr_matrix, threshold=0.0)
        assert fig is not None

    def test_high_threshold(self):
        """Test with very high threshold (shows only strongest correlations)."""
        corr_matrix = np.array([[1.0, 0.1, 0.9], [0.1, 1.0, 0.2], [0.9, 0.2, 1.0]])
        fig = plot_correlation_heatmap(corr_matrix, threshold=0.9)
        assert fig is not None

    def test_large_matrix_small_sample(self):
        """Test with moderately large matrix (256×256)."""
        np.random.seed(42)
        corr_matrix = np.random.randn(256, 256)
        corr_matrix = (corr_matrix + corr_matrix.T) / 2
        np.fill_diagonal(corr_matrix, 1.0)

        fig = plot_correlation_heatmap(corr_matrix, threshold=0.5)
        assert fig is not None


def test_integration_load_and_visualize(tmp_path):
    """Integration test: load matrix from file and visualize."""
    csv_file = tmp_path / "test_matrix.csv"
    with open(csv_file, 'w') as f:
        f.write("Node,ROI1,ROI2,ROI3\n")
        f.write("ROI1,1.0,0.6,0.2\n")
        f.write("ROI2,0.6,1.0,0.4\n")
        f.write("ROI3,0.2,0.4,1.0\n")

    corr_matrix, roi_labels = load_correlation_matrix(csv_file)
    assert corr_matrix.shape == (3, 3)
    assert roi_labels == ["ROI1", "ROI2", "ROI3"]

    fig_heatmap = plot_correlation_heatmap(corr_matrix, roi_labels=roi_labels)
    fig_network = plot_network_graph(corr_matrix, roi_labels=roi_labels)

    assert fig_heatmap is not None
    assert fig_network is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
