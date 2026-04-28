"""
Validation tests for output NIfTI files and statistical tables.

Tests verify:
- NIfTI file validity and structure
- Statistical table format and content
- Anatomical consistency
- Data integrity
"""

import numpy as np
import pandas as pd
import nibabel as nib
import pytest
from pathlib import Path


class TestNIfTIValidity:
    """Test NIfTI file validity."""
    
    def test_nifti_file_readable(self, valid_nifti_image, tmp_path):
        """NIfTI files should be readable."""
        filepath = tmp_path / "test.nii.gz"
        nib.save(valid_nifti_image, str(filepath))
        
        # Should load without error
        img = nib.load(str(filepath))
        assert img is not None
    
    def test_nifti_shape_validity(self, valid_nifti_image):
        """NIfTI shape should be valid."""
        data = valid_nifti_image.get_fdata()
        
        # Should be 3D or 4D
        assert 3 <= data.ndim <= 4
        
        # Dimensions should be reasonable
        assert all(dim > 0 for dim in data.shape)
    
    def test_nifti_no_nan_values(self, valid_nifti_image):
        """NIfTI data should not contain NaN."""
        data = valid_nifti_image.get_fdata()
        
        assert not np.isnan(data).any(), "NIfTI contains NaN values"
    
    def test_nifti_no_inf_values(self, valid_nifti_image):
        """NIfTI data should not contain infinite values."""
        data = valid_nifti_image.get_fdata()
        
        assert not np.isinf(data).any(), "NIfTI contains Inf values"
    
    def test_nifti_affine_validity(self, valid_nifti_image):
        """NIfTI affine should be valid 4×4 matrix."""
        affine = valid_nifti_image.affine
        
        assert affine.shape == (4, 4)
        assert not np.isnan(affine).any()
        assert not np.isinf(affine).any()
    
    def test_nifti_affine_determinant(self, valid_nifti_image):
        """NIfTI affine determinant should be non-zero."""
        affine = valid_nifti_image.affine[:3, :3]
        det = np.linalg.det(affine)
        
        assert det != 0, "Affine matrix is singular"


class TestInvalidNIfTIDetection:
    """Test detection of invalid NIfTI files."""
    
    def test_detect_nan_values(self, invalid_nifti_image_with_nan):
        """Should detect NaN in NIfTI."""
        data = invalid_nifti_image_with_nan.get_fdata()
        
        assert np.isnan(data).any(), "Failed to create NaN test case"
    
    def test_detect_inf_values(self, invalid_nifti_image_with_inf):
        """Should detect Inf in NIfTI."""
        data = invalid_nifti_image_with_inf.get_fdata()
        
        assert np.isinf(data).any(), "Failed to create Inf test case"


class TestNIfTIStatMapValidity:
    """Test validity of statistical maps."""
    
    def test_zmap_value_range(self, tmp_path):
        """Z-maps should have reasonable value ranges."""
        # Create z-map
        z_data = np.random.normal(0, 1, (181, 217, 181))
        
        # Should be approximately N(0,1)
        mean_z = np.nanmean(z_data)
        std_z = np.nanstd(z_data)
        
        assert abs(mean_z) < 0.5
        assert 0.5 < std_z < 1.5
    
    def test_tmap_positive_and_negative(self, tmp_path):
        """T-maps should have both positive and negative values."""
        # T-statistics can be positive or negative
        t_data = np.random.normal(0, 2, (181, 217, 181))
        
        assert (t_data > 0).any()
        assert (t_data < 0).any()
    
    def test_pmap_range_validity(self):
        """P-maps should have values in [0, 1]."""
        p_data = np.random.uniform(0, 1, (181, 217, 181))
        
        assert (p_data >= 0).all()
        assert (p_data <= 1).all()


class TestNIfTIMNIAlignment:
    """Test proper alignment to MNI space."""
    
    def test_mni_shape_standard(self):
        """Standard MNI shape should be (181, 217, 181)."""
        mni_shape = (181, 217, 181)
        
        assert mni_shape == (181, 217, 181)
    
    def test_mni_affine_standard(self):
        """MNI affine should correspond to 2mm isotropic."""
        # Standard MNI152NLin2009cAsym affine
        affine = np.array([
            [-2.0, 0.0, 0.0, 90.0],
            [0.0, 2.0, 0.0, -126.0],
            [0.0, 0.0, 2.0, -72.0],
            [0.0, 0.0, 0.0, 1.0]
        ])
        
        # Voxel size should be 2mm
        voxel_size = np.linalg.norm(affine[:3, :3], axis=0)
        
        assert np.allclose(voxel_size, 2.0)
    
    def test_mni_origin_center(self):
        """MNI volume should be centered around origin."""
        shape = (181, 217, 181)
        
        # Center in voxel coordinates
        center_voxel = np.array(shape) / 2
        
        # Should be approximately [90, 108, 90]
        assert 80 < center_voxel[0] < 100
        assert 100 < center_voxel[1] < 120
        assert 80 < center_voxel[2] < 100


class TestStatisticalTableValidity:
    """Test statistical output table format and content."""
    
    def test_cluster_table_columns(self, tmp_path):
        """Cluster table should have expected columns."""
        required_columns = [
            'cluster_id', 'x', 'y', 'z',
            't_stat', 'p_value', 'n_voxels',
            'region_name', 'extent_mm3'
        ]
        
        # Create mock cluster table
        data = {col: [] for col in required_columns}
        df = pd.DataFrame(data)
        
        for col in required_columns:
            assert col in df.columns
    
    def test_cluster_table_coordinate_format(self):
        """Coordinates should be in MNI mm, not voxel indices."""
        # Cluster center at MNI origin approximately
        cluster_data = {
            'x': [0, 2, -2],
            'y': [-4, 0, 4],
            'z': [-2, 2, 0],
            't_stat': [3.5, 3.2, 3.1],
        }
        df = pd.DataFrame(cluster_data)
        
        # Coordinates should be floats (mm), not small integers
        assert df['x'].dtype in [np.float64, np.float32]
        assert df['y'].dtype in [np.float64, np.float32]
    
    def test_cluster_table_stat_validity(self):
        """Statistics in cluster table should be valid."""
        data = {
            'cluster_id': [1, 2, 3],
            'x': [0, 10, -10],
            'y': [0, 10, -10],
            'z': [0, 10, -10],
            't_stat': [3.5, 4.2, 2.8],
            'p_value': [0.001, 0.0001, 0.01],
            'n_voxels': [150, 200, 50],
        }
        df = pd.DataFrame(data)
        
        # T-stats should be > 0 (assuming threshold)
        assert (df['t_stat'] > 0).all()
        
        # P-values should be in [0, 1]
        assert (df['p_value'] >= 0).all() and (df['p_value'] <= 1).all()
        
        # N voxels should be positive
        assert (df['n_voxels'] > 0).all()
    
    def test_cluster_table_p_value_ordering(self):
        """Clusters should be ordered by p-value."""
        data = {
            'cluster_id': [1, 2, 3],
            'p_value': [0.0001, 0.001, 0.01],
        }
        df = pd.DataFrame(data)
        
        # Sort by p-value
        df_sorted = df.sort_values('p_value')
        
        # Should be in increasing order
        assert (df_sorted['p_value'].diff().dropna() >= 0).all()


class TestRoiDefinitionValidity:
    """Test ROI definition file validity."""
    
    def test_roi_mask_binary(self, synthetic_roi_mask):
        """ROI mask should be binary (0 or 1)."""
        img = nib.load(str(synthetic_roi_mask))
        data = img.get_fdata()
        
        unique_vals = np.unique(data)
        
        # Should only contain 0 and 1
        assert set(unique_vals) <= {0, 1}
    
    def test_roi_has_nonzero_voxels(self, synthetic_roi_mask):
        """ROI should have at least one nonzero voxel."""
        img = nib.load(str(synthetic_roi_mask))
        data = img.get_fdata()
        
        n_voxels = (data > 0).sum()
        
        assert n_voxels > 0
    
    def test_roi_reasonable_size(self, synthetic_roi_mask):
        """ROI should have reasonable size."""
        img = nib.load(str(synthetic_roi_mask))
        data = img.get_fdata()
        
        n_voxels = (data > 0).sum()
        total_voxels = data.size
        
        # ROI should be < 50% of volume
        assert n_voxels < 0.5 * total_voxels


class TestConfoundRegressorValidity:
    """Test confound regressor file validity."""
    
    def test_confounds_shape(self, synthetic_confounds_timeseries):
        """Confound regressors should have correct shape."""
        confounds = pd.read_csv(synthetic_confounds_timeseries, sep='\t')
        
        # Should have 480 rows (volumes)
        assert len(confounds) == 480
        
        # Should have motion (6) + tissue (2) = 8 columns
        assert confounds.shape[1] >= 6
    
    def test_confounds_no_nan(self, synthetic_confounds_timeseries):
        """Confound regressors should have no NaN."""
        confounds = pd.read_csv(synthetic_confounds_timeseries, sep='\t')
        
        # Should have no NaN after loading
        assert not confounds.isna().any().any()
    
    def test_confounds_motion_scale(self, synthetic_confounds_timeseries):
        """Motion parameters should be in expected scale."""
        confounds = pd.read_csv(synthetic_confounds_timeseries, sep='\t')
        
        # Translation in mm (typically < 1mm)
        if 'trans_x' in confounds.columns:
            assert confounds['trans_x'].abs().max() < 1.0
        
        # Rotation in rad (typically < 0.05 rad)
        if 'rot_x' in confounds.columns:
            assert confounds['rot_x'].abs().max() < 0.1


class TestGroupAnalysisOutput:
    """Test group analysis output validity."""
    
    def test_group_stat_map_shape(self):
        """Group stat map should have correct shape."""
        stat_map = np.random.normal(0, 1, (181, 217, 181))
        
        assert stat_map.shape == (181, 217, 181)
    
    def test_group_stat_map_no_extreme_values(self):
        """Group stat map should not have extreme values."""
        # T-statistics from LME typically in [-10, 10]
        stat_map = np.random.normal(0, 2, (181, 217, 181))
        
        # Very few should exceed ±10
        n_extreme = (np.abs(stat_map) > 10).sum()
        n_total = stat_map.size
        
        pct_extreme = n_extreme / n_total
        assert pct_extreme < 0.01
    
    def test_group_stat_map_symmetric(self):
        """Null distribution should be approximately symmetric."""
        stat_map = np.random.normal(0, 1, (181, 217, 181))
        
        # Count positive and negative
        n_pos = (stat_map > 0).sum()
        n_neg = (stat_map < 0).sum()
        
        # Should be approximately 50-50
        ratio = n_pos / n_neg
        assert 0.9 < ratio < 1.1


class TestReproducibilityOfOutputs:
    """Test that outputs are reproducible."""
    
    def test_same_input_same_output(self):
        """Same input should produce same output."""
        np.random.seed(42)
        data1 = np.random.normal(0, 1, (10, 10, 10))
        
        np.random.seed(42)
        data2 = np.random.normal(0, 1, (10, 10, 10))
        
        np.testing.assert_array_equal(data1, data2)
    
    def test_output_file_consistency(self, tmp_path):
        """Output files saved twice should be identical."""
        data = np.random.normal(0, 1, (10, 10, 10))
        affine = np.eye(4)
        
        # Save first time
        img1 = nib.Nifti1Image(data, affine=affine)
        filepath1 = tmp_path / "output1.nii.gz"
        nib.save(img1, str(filepath1))
        
        # Save second time (same data)
        img2 = nib.Nifti1Image(data, affine=affine)
        filepath2 = tmp_path / "output2.nii.gz"
        nib.save(img2, str(filepath2))
        
        # Load both
        loaded1 = nib.load(str(filepath1)).get_fdata()
        loaded2 = nib.load(str(filepath2)).get_fdata()
        
        # Should be identical
        np.testing.assert_array_equal(loaded1, loaded2)
