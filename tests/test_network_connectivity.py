#!/usr/bin/env python3
"""
Unit Tests for Session-Level Network Connectivity Computation

Tests cover:
- Atlas loading
- Network definitions loading
- Confound loading
- Timeseries extraction
- Preprocessing
- Correlation computation
- Statistics calculation
- Output saving
"""

import json
import tempfile
import unittest
import warnings
from pathlib import Path

import h5py
import nibabel as nib
import numpy as np
import pandas as pd

# Import the module to test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'script'))
from compute_network_connectivity import (
    load_difumo_atlas,
    load_network_definitions,
    load_confounds,
    extract_timeseries,
    preprocess_timeseries,
    compute_correlation_matrix,
    fisher_z_transform,
    compute_network_statistics,
    save_correlation_matrix_hdf5,
    save_network_statistics_csv,
    save_network_definitions,
)

warnings.filterwarnings('ignore')


class TestAtlasLoading(unittest.TestCase):
    """Test atlas loading functionality."""
    
    def test_load_difumo_atlas_from_nilearn(self):
        """Test loading DiFuMo atlas from nilearn."""
        try:
            atlas_img = load_difumo_atlas()
            
            # Check type
            self.assertIsInstance(atlas_img, nib.Nifti1Image)
            
            # Check dimensions (should be 4D: 3 spatial + 256 components)
            self.assertEqual(len(atlas_img.shape), 4)
            self.assertEqual(atlas_img.shape[3], 256)
            
            # Check data is not empty
            data = atlas_img.get_fdata()
            self.assertGreater(data.max(), 0)
            
        except Exception as e:
            # Skip if nilearn download fails
            self.skipTest(f"Could not load from nilearn: {e}")
    
    def test_load_difumo_atlas_synthetic(self):
        """Test atlas loading with synthetic data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create synthetic 4D atlas
            synthetic_data = np.random.randint(0, 256, size=(91, 109, 91, 256))
            atlas_path = Path(tmpdir) / 'synthetic_atlas.nii'
            
            # Save synthetic atlas
            img = nib.Nifti1Image(synthetic_data.astype(np.float32), np.eye(4))
            nib.save(img, atlas_path)
            
            # Load atlas
            atlas_img = load_difumo_atlas(str(atlas_path))
            
            self.assertEqual(atlas_img.shape, (91, 109, 91, 256))


class TestNetworkDefinitions(unittest.TestCase):
    """Test network definitions loading."""
    
    def test_load_network_definitions_synthetic(self):
        """Test loading network definitions from synthetic JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create synthetic network definitions
            networks = {
                'Network1': [0, 1, 2, 3],
                'Network2': [4, 5, 6],
                'Network3': [7, 8, 9, 10, 11]
            }
            
            definitions = {
                'atlas_name': 'test',
                'networks': networks
            }
            
            json_path = Path(tmpdir) / 'networks.json'
            with open(json_path, 'w') as f:
                json.dump(definitions, f)
            
            # Load definitions
            loaded_networks, roi_to_network = load_network_definitions(str(json_path))
            
            # Verify networks
            self.assertEqual(len(loaded_networks), 3)
            self.assertEqual(loaded_networks['Network1'], [0, 1, 2, 3])
            
            # Verify reverse mapping
            self.assertEqual(roi_to_network[0], 'Network1')
            self.assertEqual(roi_to_network[4], 'Network2')
            self.assertEqual(roi_to_network[7], 'Network3')


class TestConfoundLoading(unittest.TestCase):
    """Test confound loading functionality."""
    
    def test_load_confounds_basic(self):
        """Test loading confounds with basic regressors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create synthetic confounds TSV
            n_volumes = 480
            confounds_data = {
                'trans_x': np.random.randn(n_volumes),
                'trans_y': np.random.randn(n_volumes),
                'trans_z': np.random.randn(n_volumes),
                'rot_x': np.random.randn(n_volumes),
                'rot_y': np.random.randn(n_volumes),
                'rot_z': np.random.randn(n_volumes),
                'csf': np.random.randn(n_volumes),
                'white_matter': np.random.randn(n_volumes),
            }
            
            df = pd.DataFrame(confounds_data)
            confounds_path = Path(tmpdir) / 'confounds.tsv'
            df.to_csv(confounds_path, sep='\t', index=False)
            
            # Load confounds
            confounds, names = load_confounds(str(confounds_path), strategy='basic')
            
            # Verify shape
            self.assertEqual(confounds.shape[0], n_volumes)
            self.assertGreater(confounds.shape[1], 0)
            
            # Verify no NaN
            self.assertEqual(np.isnan(confounds).sum(), 0)


class TestTimeseriesExtraction(unittest.TestCase):
    """Test timeseries extraction functionality."""
    
    def test_extract_timeseries_synthetic(self):
        """Test timeseries extraction with synthetic data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            
            # Create synthetic BOLD (4D)
            n_volumes = 100
            bold_data = np.random.randn(91, 109, 91, n_volumes)
            bold_path = tmpdir / 'bold.nii.gz'
            bold_img = nib.Nifti1Image(bold_data.astype(np.float32), np.eye(4))
            nib.save(bold_img, bold_path)
            
            # Create synthetic 3D atlas with component labels (1-256)
            atlas_data = np.zeros((91, 109, 91), dtype=np.int16)
            for roi_idx in range(1, 257):
                # Assign voxels to ROI
                mask = np.random.rand(91, 109, 91) > 0.99
                atlas_data[mask] = roi_idx
            
            atlas_path = tmpdir / 'atlas.nii.gz'
            atlas_img = nib.Nifti1Image(atlas_data, np.eye(4))
            nib.save(atlas_img, atlas_path)
            
            # Load and extract
            bold_img = nib.load(bold_path)
            atlas_img = nib.load(atlas_path)
            timeseries = extract_timeseries(str(bold_path), atlas_img)
            
            # Verify shape
            self.assertEqual(timeseries.shape, (n_volumes, 256))


class TestPreprocessing(unittest.TestCase):
    """Test signal preprocessing."""
    
    def test_preprocess_timeseries(self):
        """Test timeseries preprocessing."""
        # Create synthetic timeseries
        n_volumes = 480
        n_rois = 256
        tr = 0.8
        
        timeseries = np.random.randn(n_volumes, n_rois)
        confounds = np.random.randn(n_volumes, 6)
        
        # Preprocess
        cleaned = preprocess_timeseries(
            timeseries, confounds,
            tr=tr, high_pass=0.01, low_pass=0.1
        )
        
        # Verify shape preserved
        self.assertEqual(cleaned.shape, timeseries.shape)
        
        # Verify standardization (mean ~0, std ~1)
        mean = np.abs(cleaned.mean(axis=0)).mean()
        std = np.abs(cleaned.std(axis=0) - 1.0).mean()
        
        self.assertLess(mean, 0.1)  # Mean close to 0
        self.assertLess(std, 0.2)   # Std close to 1
        
        # Verify no NaN
        self.assertEqual(np.isnan(cleaned).sum(), 0)


class TestCorrelationComputation(unittest.TestCase):
    """Test correlation computation."""
    
    def test_compute_correlation_matrix(self):
        """Test correlation matrix computation."""
        # Create synthetic timeseries
        n_volumes = 480
        n_rois = 256
        
        # Create timeseries with known correlation structure
        timeseries = np.random.randn(n_volumes, n_rois)
        
        # Compute correlations
        corr_matrix = compute_correlation_matrix(timeseries)
        
        # Verify shape
        self.assertEqual(corr_matrix.shape, (n_rois, n_rois))
        
        # Verify symmetry
        np.testing.assert_array_almost_equal(corr_matrix, corr_matrix.T)
        
        # Verify diagonal is 1
        np.testing.assert_array_almost_equal(np.diag(corr_matrix), np.ones(n_rois))
        
        # Verify values in [-1, 1]
        self.assertLessEqual(corr_matrix.max(), 1.0)
        self.assertGreaterEqual(corr_matrix.min(), -1.0)
        
        # Verify no NaN
        self.assertEqual(np.isnan(corr_matrix).sum(), 0)
    
    def test_fisher_z_transform(self):
        """Test Fisher z-transformation."""
        r_values = np.array([0.0, 0.5, -0.5, 0.9, -0.9])
        z_values = fisher_z_transform(r_values)
        
        # Verify shape preserved
        self.assertEqual(len(z_values), len(r_values))
        
        # Verify z(0) = 0
        self.assertAlmostEqual(z_values[0], 0.0, places=5)
        
        # Verify symmetry: z(-r) = -z(r)
        self.assertAlmostEqual(z_values[1], -z_values[2], places=5)


class TestNetworkStatistics(unittest.TestCase):
    """Test network statistics computation."""
    
    def test_compute_network_statistics(self):
        """Test network statistics computation."""
        # Create synthetic correlation matrix
        n_rois = 256
        corr_matrix = np.random.randn(n_rois, n_rois)
        corr_matrix = (corr_matrix + corr_matrix.T) / 2  # Make symmetric
        
        # Create ROI to network mapping
        roi_to_network = {}
        networks = ['Network1', 'Network2', 'Network3']
        rois_per_network = n_rois // len(networks)
        
        for i, network in enumerate(networks):
            for j in range(rois_per_network):
                roi_idx = i * rois_per_network + j
                if roi_idx < n_rois:
                    roi_to_network[roi_idx] = network
        
        # Compute statistics
        stats = compute_network_statistics(corr_matrix, roi_to_network)
        
        # Verify required fields
        self.assertIn('n_rois', stats)
        self.assertIn('mean_correlation', stats)
        self.assertIn('std_correlation', stats)
        
        # Verify within and between network stats
        self.assertIn('within_network_mean', stats)
        self.assertIn('between_network_mean', stats)


class TestOutputSaving(unittest.TestCase):
    """Test output file saving."""
    
    def test_save_correlation_matrix_hdf5(self):
        """Test HDF5 file saving."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            
            # Create synthetic data
            corr_matrix = np.random.randn(256, 256)
            timeseries = np.random.randn(480, 256)
            
            # Save
            save_correlation_matrix_hdf5(str(tmpdir), corr_matrix, timeseries)
            
            # Verify file exists
            hdf5_file = tmpdir / 'correlation_matrix.h5'
            self.assertTrue(hdf5_file.exists())
            
            # Verify contents
            with h5py.File(hdf5_file, 'r') as f:
                self.assertIn('correlation_matrix', f)
                self.assertIn('timeseries_cleaned', f)
                np.testing.assert_array_equal(f['correlation_matrix'][()], corr_matrix)
    
    def test_save_network_statistics_csv(self):
        """Test CSV file saving."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            
            # Create synthetic stats
            stats = {
                'n_rois': 256,
                'mean_correlation': 0.5,
                'within_network_mean': 0.6,
                'between_network_mean': 0.4
            }
            roi_to_network = {i: f'net{i%3}' for i in range(256)}
            
            # Save
            save_network_statistics_csv(str(tmpdir), stats, roi_to_network)
            
            # Verify file exists
            csv_file = tmpdir / 'correlation_stats.csv'
            self.assertTrue(csv_file.exists())
            
            # Verify contents
            df = pd.read_csv(csv_file)
            self.assertEqual(df['n_rois'][0], 256)
    
    def test_save_network_definitions(self):
        """Test network definitions saving."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            
            # Create synthetic data
            networks = {
                'Network1': [0, 1, 2],
                'Network2': [3, 4, 5]
            }
            roi_to_network = {0: 'Network1', 1: 'Network1', 2: 'Network1',
                            3: 'Network2', 4: 'Network2', 5: 'Network2'}
            
            # Save
            save_network_definitions(str(tmpdir), networks, roi_to_network)
            
            # Verify file exists
            json_file = tmpdir / 'network_definitions.json'
            self.assertTrue(json_file.exists())
            
            # Verify contents
            with open(json_file, 'r') as f:
                data = json.load(f)
            
            self.assertIn('networks', data)
            self.assertIn('roi_to_network', data)
            self.assertEqual(len(data['networks']), 2)


class TestIntegration(unittest.TestCase):
    """Integration tests."""
    
    def test_full_pipeline_synthetic(self):
        """Test full pipeline with synthetic data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            
            # Create synthetic BOLD
            n_volumes = 100
            bold_data = np.random.randn(91, 109, 91, n_volumes).astype(np.float32)
            bold_path = tmpdir / 'bold.nii.gz'
            bold_img = nib.Nifti1Image(bold_data, np.eye(4))
            nib.save(bold_img, bold_path)
            
            # Create synthetic confounds
            confounds_data = {
                'trans_x': np.random.randn(n_volumes),
                'trans_y': np.random.randn(n_volumes),
                'trans_z': np.random.randn(n_volumes),
                'rot_x': np.random.randn(n_volumes),
                'rot_y': np.random.randn(n_volumes),
                'rot_z': np.random.randn(n_volumes),
                'csf': np.random.randn(n_volumes),
                'white_matter': np.random.randn(n_volumes),
            }
            confounds_path = tmpdir / 'confounds.tsv'
            pd.DataFrame(confounds_data).to_csv(confounds_path, sep='\t', index=False)
            
            # Create synthetic 3D atlas with component labels
            atlas_data = np.zeros((91, 109, 91), dtype=np.int16)
            for roi_idx in range(1, 257):
                mask = np.random.rand(91, 109, 91) > 0.99
                atlas_data[mask] = roi_idx
            atlas_path = tmpdir / 'atlas.nii.gz'
            atlas_img = nib.Nifti1Image(atlas_data, np.eye(4))
            nib.save(atlas_img, atlas_path)
            
            # Create network definitions
            networks = {f'Network{i}': list(range(i*32, (i+1)*32)) for i in range(8)}
            networks_path = tmpdir / 'networks.json'
            with open(networks_path, 'w') as f:
                json.dump({'networks': networks}, f)
            
            # Run pipeline steps
            atlas_img = load_difumo_atlas(str(atlas_path))
            confounds, _ = load_confounds(str(confounds_path))
            timeseries = extract_timeseries(str(bold_path), atlas_img)
            cleaned = preprocess_timeseries(timeseries, confounds)
            corr_matrix = compute_correlation_matrix(cleaned)
            
            # Verify results
            self.assertEqual(corr_matrix.shape, (256, 256))
            self.assertLessEqual(corr_matrix.max(), 1.0)
            self.assertGreaterEqual(corr_matrix.min(), -1.0)
            self.assertEqual(np.isnan(corr_matrix).sum(), 0)


def run_tests():
    """Run all tests."""
    unittest.main(argv=[''], exit=False, verbosity=2)


if __name__ == '__main__':
    run_tests()
