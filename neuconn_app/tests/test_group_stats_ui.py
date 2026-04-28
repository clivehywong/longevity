"""
Unit tests for group_stats_ui component.

Tests core filtering logic, summary computation, and data validation.
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import sys
import tempfile
import json

# Add utils to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.group_stats_ui import (
    apply_threshold_filters,
    compute_summary_statistics,
    format_anatomical_region,
    validate_results_directory,
    export_summary_report,
    load_cluster_table,
)


# ==============================================================================
# Test Fixtures
# ==============================================================================

@pytest.fixture
def sample_cluster_df():
    """Create sample cluster DataFrame for testing."""
    return pd.DataFrame({
        'cluster_id': [1, 2, 3, 4, 5],
        'size_voxels': [100, 50, 200, 150, 75],
        'peak_t': [3.5, -2.1, 4.2, 2.8, -3.1],
        'peak_x': [10, 20, 30, 40, 50],
        'peak_y': [15, 25, 35, 45, 55],
        'peak_z': [5, 10, 15, 20, 25],
        'anatomical_region': ['Region A', 'Region B', 'Region C', 'Region D', 'Region E'],
        'direction': ['positive', 'negative', 'positive', 'positive', 'negative'],
        'p_value': [0.001, 0.01, 0.0001, 0.005, 0.008],
        'q_value': [0.01, 0.05, 0.001, 0.02, 0.04]
    })


@pytest.fixture
def temp_results_dir(sample_cluster_df):
    """Create temporary results directory with sample data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        
        # Write cluster CSV
        csv_path = tmppath / "clusters_interaction.csv"
        sample_cluster_df.to_csv(csv_path, index=False)
        
        # Write model info
        model_info_path = tmppath / "model_info.json"
        with open(model_info_path, 'w') as f:
            json.dump({
                'analysis': 'seed_based',
                'seed': 'dlpfc_l',
                'method': 'interaction'
            }, f)
        
        yield tmppath


# ==============================================================================
# Test Filtering Logic
# ==============================================================================

class TestThresholdFiltering:
    """Test threshold filtering for different methods."""
    
    def test_grf_both_direction(self, sample_cluster_df):
        """Test GRF filtering with both directions."""
        filtered = apply_threshold_filters(
            sample_cluster_df, 'GRF',
            {'voxel_tstat': 2.5, 'cluster_size': 50},
            'both'
        )
        # Should keep clusters with |t| >= 2.5 and size >= 50
        assert len(filtered) == 4
        assert all(filtered['size_voxels'] >= 50)
        assert all(filtered['peak_t'].abs() >= 2.5)
    
    def test_grf_positive_direction(self, sample_cluster_df):
        """Test GRF filtering with positive direction only."""
        filtered = apply_threshold_filters(
            sample_cluster_df, 'GRF',
            {'voxel_tstat': 2.5, 'cluster_size': 50},
            'positive'
        )
        assert all(filtered['peak_t'] > 0)
        assert len(filtered) == 3  # Clusters 1, 3, 4 have positive t-stat >= 2.5
    
    def test_grf_negative_direction(self, sample_cluster_df):
        """Test GRF filtering with negative direction only."""
        filtered = apply_threshold_filters(
            sample_cluster_df, 'GRF',
            {'voxel_tstat': 2.5, 'cluster_size': 50},
            'negative'
        )
        assert all(filtered['peak_t'] < 0)
        assert len(filtered) == 1  # Only cluster 5
    
    def test_grf_strict_threshold(self, sample_cluster_df):
        """Test GRF with strict thresholds."""
        filtered = apply_threshold_filters(
            sample_cluster_df, 'GRF',
            {'voxel_tstat': 4.0, 'cluster_size': 150},
            'both'
        )
        assert len(filtered) == 1  # Only cluster 3 (t=4.2, size=200)
    
    def test_tfce_filtering(self, sample_cluster_df):
        """Test TFCE p-value filtering."""
        filtered = apply_threshold_filters(
            sample_cluster_df, 'TFCE',
            {'p_value': 0.005},
            'both'
        )
        assert len(filtered) == 3  # Clusters with p <= 0.005
        assert all(filtered['p_value'] <= 0.005)
    
    def test_fdr_filtering(self, sample_cluster_df):
        """Test FDR q-value filtering."""
        filtered = apply_threshold_filters(
            sample_cluster_df, 'FDR',
            {'q_value': 0.02},
            'both'
        )
        assert all(filtered['q_value'] <= 0.02)


# ==============================================================================
# Test Summary Computation
# ==============================================================================

class TestSummaryStatistics:
    """Test summary statistics computation."""
    
    def test_basic_summary(self, sample_cluster_df):
        """Test basic summary computation."""
        summary = compute_summary_statistics(sample_cluster_df, sample_cluster_df)
        
        assert summary['n_clusters'] == 5
        assert summary['n_total_clusters'] == 5
        assert summary['peak_t_max'] == pytest.approx(4.2)
        assert summary['peak_t_min'] == pytest.approx(-3.1)
        assert summary['cluster_size_max'] == 200
        assert summary['cluster_size_mean'] == pytest.approx(115.0)
        assert summary['total_voxels'] == 575
    
    def test_empty_summary(self):
        """Test summary with empty filtered DataFrame."""
        empty_df = pd.DataFrame({
            'peak_t': [], 'size_voxels': []
        })
        raw_df = pd.DataFrame({
            'peak_t': [1, 2], 'size_voxels': [10, 20]
        })
        
        summary = compute_summary_statistics(empty_df, raw_df)
        
        assert summary['n_clusters'] == 0
        assert summary['n_total_clusters'] == 2
        assert summary['peak_t_max'] == 0
    
    def test_summary_with_filtered(self, sample_cluster_df):
        """Test summary with filtered vs raw DataFrame."""
        filtered = sample_cluster_df[sample_cluster_df['peak_t'] > 0]
        summary = compute_summary_statistics(filtered, sample_cluster_df)
        
        assert summary['n_clusters'] == 3  # Only positive clusters
        assert summary['n_total_clusters'] == 5


# ==============================================================================
# Test Data Formatting
# ==============================================================================

class TestDataFormatting:
    """Test data formatting utilities."""
    
    def test_format_region_valid(self):
        """Test formatting valid anatomical region."""
        assert format_anatomical_region("Superior Prefrontal Cortex") == "Superior Prefrontal Cortex"
    
    def test_format_region_nan(self):
        """Test formatting NaN anatomical region."""
        assert format_anatomical_region(np.nan) == "N/A"
        assert format_anatomical_region(None) == "N/A"
    
    def test_format_region_empty_string(self):
        """Test formatting empty string."""
        assert format_anatomical_region("") == "N/A"
    
    def test_format_region_whitespace(self):
        """Test formatting region with whitespace."""
        result = format_anatomical_region("  Region A  ")
        assert result == "Region A"


# ==============================================================================
# Test Directory Validation
# ==============================================================================

class TestDirectoryValidation:
    """Test directory validation and error handling."""
    
    def test_valid_directory(self, temp_results_dir):
        """Test validation with valid directory."""
        is_valid, msg, csv_path = validate_results_directory(str(temp_results_dir))
        
        assert is_valid is True
        assert csv_path is not None
        assert csv_path.exists()
    
    def test_nonexistent_directory(self):
        """Test validation with nonexistent directory."""
        is_valid, msg, csv_path = validate_results_directory("/nonexistent/path")
        
        assert is_valid is False
        assert "not found" in msg.lower()
        assert csv_path is None
    
    def test_directory_without_csv(self):
        """Test validation with directory containing no CSV files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            is_valid, msg, csv_path = validate_results_directory(tmpdir)
            
            assert is_valid is False
            # Message contains the cross mark, so strip it for comparison
            msg_clean = msg.lower().replace('❌', '')
            assert "cluster csv" in msg_clean or "not found" in msg_clean


# ==============================================================================
# Test Export Functions
# ==============================================================================

class TestExportFunctions:
    """Test export and report generation."""
    
    def test_summary_report_generation(self, sample_cluster_df):
        """Test summary report generation."""
        summary = compute_summary_statistics(sample_cluster_df, sample_cluster_df)
        
        report = export_summary_report(
            summary=summary,
            method='GRF',
            thresholds={'voxel_tstat': 2.5, 'cluster_size': 50},
            direction='both',
            analysis_type='seed_based',
            seed_name='dlpfc_l'
        )
        
        assert "GROUP-LEVEL STATISTICS REPORT" in report
        assert "dlpfc_l" in report
        assert "GRF" in report
        assert "Significant Clusters: 5" in report
        assert "Peak t-statistic: 4.2000" in report
    
    def test_report_includes_pvalues(self, sample_cluster_df):
        """Test that report includes p-value statistics."""
        summary = compute_summary_statistics(sample_cluster_df, sample_cluster_df)
        
        report = export_summary_report(
            summary=summary,
            method='TFCE',
            thresholds={'p_value': 0.05},
            direction='both',
            analysis_type='seed_based'
        )
        
        assert "P-VALUE STATISTICS" in report


# ==============================================================================
# Test Data Loading
# ==============================================================================

class TestDataLoading:
    """Test cluster table loading."""
    
    def test_load_valid_csv(self, temp_results_dir):
        """Test loading valid cluster CSV."""
        csv_path = temp_results_dir / "clusters_interaction.csv"
        df = load_cluster_table(str(csv_path))
        
        assert df is not None
        assert len(df) == 5
        assert 'cluster_id' in df.columns
    
    def test_load_nonexistent_file(self):
        """Test loading nonexistent file."""
        df = load_cluster_table("/nonexistent/path.csv")
        assert df is None


# ==============================================================================
# Test Edge Cases
# ==============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_single_cluster(self):
        """Test with single cluster."""
        df = pd.DataFrame({
            'cluster_id': [1],
            'size_voxels': [100],
            'peak_t': [3.5],
            'peak_x': [10],
            'peak_y': [15],
            'peak_z': [5],
            'anatomical_region': ['Region A'],
            'direction': ['positive']
        })
        
        filtered = apply_threshold_filters(
            df, 'GRF',
            {'voxel_tstat': 2.5, 'cluster_size': 50},
            'both'
        )
        assert len(filtered) == 1
    
    def test_very_strict_thresholds(self, sample_cluster_df):
        """Test with very strict thresholds."""
        filtered = apply_threshold_filters(
            sample_cluster_df, 'GRF',
            {'voxel_tstat': 10.0, 'cluster_size': 1000},
            'both'
        )
        assert len(filtered) == 0
    
    def test_zero_cluster_filtering(self, sample_cluster_df):
        """Test filtering that results in zero clusters."""
        filtered = apply_threshold_filters(
            sample_cluster_df, 'TFCE',
            {'p_value': 0.00001},
            'both'
        )
        assert len(filtered) == 0
    
    def test_very_permissive_thresholds(self, sample_cluster_df):
        """Test with very permissive thresholds."""
        filtered = apply_threshold_filters(
            sample_cluster_df, 'GRF',
            {'voxel_tstat': 0.1, 'cluster_size': 1},
            'both'
        )
        assert len(filtered) == 5  # All clusters


# ==============================================================================
# Run Tests
# ==============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
