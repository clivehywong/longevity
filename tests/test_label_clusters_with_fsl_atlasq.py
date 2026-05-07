"""
Unit and integration tests for FSL atlasq cluster labeling.

Tests cover:
- atlasq availability checking
- Atlas validation
- Output parsing
- CSV I/O
- Edge cases (missing coords, invalid atlases, etc.)
"""

import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
import numpy as np

# Add script directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'script'))

from label_clusters_with_fsl_atlasq import (
    check_atlasq_available,
    list_available_atlases,
    validate_atlases,
    query_atlasq,
    query_atlasq_probabilistic,
    label_clusters_with_atlasq
)


class TestAtlasqAvailability(unittest.TestCase):
    """Test FSL atlasq availability checking."""

    @patch('subprocess.run')
    def test_atlasq_available(self, mock_run):
        """Test when atlasq is available."""
        mock_run.return_value = Mock(returncode=0)
        assert check_atlasq_available() is True

    @patch('subprocess.run')
    def test_atlasq_not_available(self, mock_run):
        """Test when atlasq is not available."""
        mock_run.side_effect = FileNotFoundError()
        assert check_atlasq_available() is False

    @patch('subprocess.run')
    def test_atlasq_command_fails(self, mock_run):
        """Test when atlasq command fails."""
        mock_run.return_value = Mock(returncode=1)
        assert check_atlasq_available() is False


class TestListAtlases(unittest.TestCase):
    """Test listing available atlases."""

    @patch('subprocess.run')
    def test_list_atlases_success(self, mock_run):
        """Test successful listing of atlases."""
        output = """ID                                | Full name
aal3v1                            | AAL3v1
talairach                         | Talairach Daemon Labels
harvardoxford-cortical            | Harvard-Oxford Cortical Atlas"""

        mock_run.return_value = Mock(returncode=0, stdout=output, stderr='')

        atlases = list_available_atlases()
        assert 'aal3v1' in atlases
        assert 'talairach' in atlases
        assert 'harvardoxford-cortical' in atlases

    @patch('subprocess.run')
    def test_list_atlases_empty(self, mock_run):
        """Test when no atlases are returned."""
        mock_run.return_value = Mock(returncode=0, stdout='', stderr='')
        atlases = list_available_atlases()
        assert len(atlases) == 0

    @patch('subprocess.run')
    def test_list_atlases_failure(self, mock_run):
        """Test when atlasq list command fails."""
        mock_run.return_value = Mock(returncode=1, stderr='Error')
        atlases = list_available_atlases()
        assert len(atlases) == 0


class TestValidateAtlases(unittest.TestCase):
    """Test atlas validation."""

    @patch('label_clusters_with_fsl_atlasq.list_available_atlases')
    def test_validate_all_valid(self, mock_list):
        """Test when all atlases are valid."""
        mock_list.return_value = ['talairach', 'aal3v1', 'harvardoxford-cortical']

        valid, invalid = validate_atlases(['talairach', 'aal3v1'])
        assert set(valid) == {'talairach', 'aal3v1'}
        assert len(invalid) == 0

    @patch('label_clusters_with_fsl_atlasq.list_available_atlases')
    def test_validate_mixed(self, mock_list):
        """Test with mix of valid and invalid atlases."""
        mock_list.return_value = ['talairach', 'aal3v1']

        valid, invalid = validate_atlases(['talairach', 'invalid_atlas'])
        assert 'talairach' in valid
        assert 'invalid_atlas' in invalid

    @patch('label_clusters_with_fsl_atlasq.list_available_atlases')
    def test_validate_all_invalid(self, mock_list):
        """Test when no atlases are valid."""
        mock_list.return_value = ['talairach']

        valid, invalid = validate_atlases(['invalid1', 'invalid2'])
        assert len(valid) == 0
        assert len(invalid) == 2


class TestQueryAtlasq(unittest.TestCase):
    """Test individual atlasq queries."""

    @patch('subprocess.run')
    def test_query_label_atlas_success(self, mock_run):
        """Test successful query of label atlas."""
        output = "coordinate\t-37.00 -22.00 58.00\tLeft Cerebrum.Frontal Lobe.Precentral Gyrus.Gray Matter.Brodmann area 4"
        mock_run.return_value = Mock(returncode=0, stdout=output, stderr='')

        result = query_atlasq(-37, -22, 58, 'talairach')
        assert result is not None
        assert 'region' in result
        assert result['region'] == 'Precentral Gyrus'

    @patch('subprocess.run')
    def test_query_empty_response(self, mock_run):
        """Test query with empty response."""
        mock_run.return_value = Mock(returncode=0, stdout='', stderr='')
        result = query_atlasq(-37, -22, 58, 'talairach')
        assert result is None

    @patch('subprocess.run')
    def test_query_command_fails(self, mock_run):
        """Test when atlasq command fails."""
        mock_run.return_value = Mock(returncode=1, stderr='Error')
        result = query_atlasq(-37, -22, 58, 'talairach')
        assert result is None

    @patch('subprocess.run')
    def test_query_timeout(self, mock_run):
        """Test query timeout."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired('atlasq', 10)
        result = query_atlasq(-37, -22, 58, 'talairach')
        assert result is None


class TestQueryAtlasqProbabilistic(unittest.TestCase):
    """Test probabilistic atlasq queries."""

    @patch('subprocess.run')
    def test_query_probabilistic_success(self, mock_run):
        """Test successful probabilistic query."""
        output = """----------------------------------
| coordinate -37.00 -22.00 58.00 |
----------------------------------

name              | index | summary value | proportion
----------------- | ----- | ------------- | ----------
Precentral Gyrus  | 6     | 7             | 43.0000
Postcentral Gyrus | 16    | 17            | 17.0000"""

        mock_run.return_value = Mock(returncode=0, stdout=output, stderr='')

        results = query_atlasq_probabilistic(-37, -22, 58, 'harvardoxford-cortical', top_n=1)
        assert results is not None
        assert len(results) == 1
        assert results[0]['region'] == 'Precentral Gyrus'
        assert abs(results[0]['proportion'] - 0.43) < 0.01

    @patch('subprocess.run')
    def test_query_probabilistic_multiple_results(self, mock_run):
        """Test getting multiple results from probabilistic query."""
        output = """name              | index | summary value | proportion
Precentral Gyrus  | 6     | 7             | 43.0000
Postcentral Gyrus | 16    | 17            | 17.0000"""

        mock_run.return_value = Mock(returncode=0, stdout=output, stderr='')

        results = query_atlasq_probabilistic(-37, -22, 58, 'harvardoxford-cortical', top_n=2)
        assert results is not None
        assert len(results) == 2

    @patch('subprocess.run')
    def test_query_probabilistic_empty(self, mock_run):
        """Test probabilistic query with no results."""
        mock_run.return_value = Mock(returncode=0, stdout='', stderr='')
        results = query_atlasq_probabilistic(-37, -22, 58, 'invalid_atlas')
        assert results is None


class TestCSVHandling(unittest.TestCase):
    """Test CSV input/output handling."""

    def setUp(self):
        """Create temporary directory for test files."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_load_valid_csv(self):
        """Test loading valid cluster CSV."""
        csv_path = os.path.join(self.temp_dir, 'clusters.csv')
        data = {
            'x': [-37, 12],
            'y': [-22, 45],
            'z': [58, 30],
            't_stat': [3.2, 2.8],
            'p_value': [0.001, 0.002],
            'n_voxels': [145, 120]
        }
        df = pd.DataFrame(data)
        df.to_csv(csv_path, index=False)

        # Load and verify
        loaded_df = pd.read_csv(csv_path)
        assert len(loaded_df) == 2
        assert all(col in loaded_df.columns for col in ['x', 'y', 'z'])

    def test_missing_required_columns(self):
        """Test loading CSV with missing required columns."""
        csv_path = os.path.join(self.temp_dir, 'clusters_bad.csv')
        data = {
            'x': [-37, 12],
            'y': [-22, 45],
            # Missing 'z' column
            't_stat': [3.2, 2.8]
        }
        df = pd.DataFrame(data)
        df.to_csv(csv_path, index=False)

        # Load and verify
        loaded_df = pd.read_csv(csv_path)
        assert 'z' not in loaded_df.columns

    @patch('label_clusters_with_fsl_atlasq.check_atlasq_available')
    @patch('label_clusters_with_fsl_atlasq.validate_atlases')
    @patch('label_clusters_with_fsl_atlasq.query_atlasq_probabilistic')
    def test_output_csv_with_labels(self, mock_query, mock_validate, mock_check):
        """Test that output CSV includes label columns."""
        mock_check.return_value = True
        mock_validate.return_value = (['talairach'], [])
        mock_query.return_value = [{'region': 'Test Region', 'proportion': 0.8}]

        # Create input CSV
        input_csv = os.path.join(self.temp_dir, 'clusters_input.csv')
        data = {
            'x': [-37],
            'y': [-22],
            'z': [58],
            't_stat': [3.2],
            'p_value': [0.001],
            'n_voxels': [145]
        }
        df = pd.DataFrame(data)
        df.to_csv(input_csv, index=False)

        # Run labeling
        output_csv = os.path.join(self.temp_dir, 'clusters_output.csv')
        result_df = label_clusters_with_atlasq(
            input_csv,
            atlases=['talairach'],
            output_csv=output_csv
        )

        # Verify output
        assert 'region_talairach' in result_df.columns
        assert 'confidence_talairach' in result_df.columns
        assert os.path.exists(output_csv)

        # Verify saved file
        saved_df = pd.read_csv(output_csv)
        assert 'region_talairach' in saved_df.columns


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def setUp(self):
        """Create temporary directory for test files."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_missing_input_file(self):
        """Test handling of missing input CSV."""
        with self.assertRaises(FileNotFoundError):
            label_clusters_with_atlasq(
                cluster_csv='/nonexistent/path/clusters.csv'
            )

    def test_missing_required_columns(self):
        """Test handling of missing required columns."""
        input_csv = os.path.join(self.temp_dir, 'bad_clusters.csv')
        data = {
            'x': [-37],
            'y': [-22]
            # Missing 'z'
        }
        df = pd.DataFrame(data)
        df.to_csv(input_csv, index=False)

        with self.assertRaises(ValueError):
            label_clusters_with_atlasq(cluster_csv=input_csv)

    def test_empty_dataframe(self):
        """Test handling of empty dataframe."""
        input_csv = os.path.join(self.temp_dir, 'empty.csv')
        data = {
            'x': [],
            'y': [],
            'z': [],
            't_stat': [],
            'p_value': [],
            'n_voxels': []
        }
        df = pd.DataFrame(data)
        df.to_csv(input_csv, index=False)

        result_df = label_clusters_with_atlasq(
            cluster_csv=input_csv,
            atlases=[]
        )
        assert len(result_df) == 0

    @patch('label_clusters_with_fsl_atlasq.check_atlasq_available')
    def test_atlasq_not_available(self, mock_check):
        """Test graceful handling when atlasq is not available."""
        mock_check.return_value = False

        input_csv = os.path.join(self.temp_dir, 'clusters.csv')
        data = {
            'x': [-37],
            'y': [-22],
            'z': [58],
            't_stat': [3.2],
            'p_value': [0.001],
            'n_voxels': [145]
        }
        df = pd.DataFrame(data)
        df.to_csv(input_csv, index=False)

        # Should still run but without atlas labels
        result_df = label_clusters_with_atlasq(
            cluster_csv=input_csv,
            atlases=['talairach'],
            output_csv=None
        )
        assert len(result_df) == 1


class TestCoordinateParsing(unittest.TestCase):
    """Test parsing of various coordinate formats."""

    @patch('subprocess.run')
    def test_parse_talairach_hierarchy(self, mock_run):
        """Test parsing Talairach hierarchical output."""
        output = "coordinate\t-37.00 -22.00 58.00\tLeft Cerebrum.Frontal Lobe.Precentral Gyrus.Gray Matter.Brodmann area 4"
        mock_run.return_value = Mock(returncode=0, stdout=output, stderr='')

        result = query_atlasq(-37, -22, 58, 'talairach')
        assert result['region'] == 'Precentral Gyrus'
        assert 'Brodmann' not in result['region']

    @patch('subprocess.run')
    def test_parse_with_special_characters(self, mock_run):
        """Test parsing regions with special characters."""
        output = "coordinate\t0.00 0.00 0.00\tRight Cerebrum.Temporal Lobe.Superior Temporal Gyrus (STG).Gray Matter"
        mock_run.return_value = Mock(returncode=0, stdout=output, stderr='')

        result = query_atlasq(0, 0, 0, 'talairach')
        assert result is not None
        assert 'Superior Temporal Gyrus' in result['region'] or 'STG' in result['region']


class TestIntegration(unittest.TestCase):
    """Integration tests with real FSL atlasq if available."""

    @unittest.skipUnless(
        check_atlasq_available(),
        "FSL atlasq not available"
    )
    def test_real_atlasq_query(self):
        """Test real atlasq query if FSL is installed."""
        # Test coordinate in precentral gyrus
        result = query_atlasq_probabilistic(-37, -22, 58, 'harvardoxford-cortical')
        assert result is not None
        assert len(result) > 0
        assert 'region' in result[0]
        assert 'proportion' in result[0]

    @unittest.skipUnless(
        check_atlasq_available(),
        "FSL atlasq not available"
    )
    def test_real_atlas_list(self):
        """Test listing real atlases if FSL is installed."""
        atlases = list_available_atlases()
        assert len(atlases) > 0
        # Check for some expected atlases
        assert any('talairach' in a.lower() for a in atlases) or \
               any('aal' in a.lower() for a in atlases)


if __name__ == '__main__':
    unittest.main()
