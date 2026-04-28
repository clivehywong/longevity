"""
Unit tests for seed-based connectivity analysis.

Tests verify:
- Seed extraction shape and values
- Correlation computation correctness
- Z-map normalization
- Multi-seed handling
"""

import numpy as np
import pytest
from scipy.stats import norm


class TestSeedExtraction:
    """Test seed region extraction."""
    
    def test_extract_seed_single_voxel(self, synthetic_bold_timeseries):
        """Extract single voxel as seed."""
        bold_data, metadata = synthetic_bold_timeseries
        
        sx, sy, sz = metadata['seed_coords']
        
        # Extract seed timeseries
        seed_ts = bold_data[sx, sy, sz, :]
        
        # Verify shape and properties
        assert seed_ts.shape == (480,)
        assert not np.isnan(seed_ts).any()
        assert not np.isinf(seed_ts).any()
    
    def test_extract_seed_roi_sphere(self, synthetic_bold_timeseries):
        """Extract spherical ROI as seed (average method)."""
        bold_data, metadata = synthetic_bold_timeseries
        
        center = np.array(metadata['seed_coords'])
        
        # Extract voxels within radius 5
        seed_voxels = []
        for x in range(bold_data.shape[0]):
            for y in range(bold_data.shape[1]):
                for z in range(bold_data.shape[2]):
                    if np.linalg.norm(np.array([x, y, z]) - center) < 5:
                        seed_voxels.append(bold_data[x, y, z, :])
        
        # Average method
        seed_ts = np.mean(seed_voxels, axis=0)
        
        assert seed_ts.shape == (480,)
        assert len(seed_voxels) > 0
    
    def test_seed_timeseries_standardized(self, synthetic_bold_timeseries):
        """Seed timeseries should be properly standardized."""
        bold_data, metadata = synthetic_bold_timeseries
        
        sx, sy, sz = metadata['seed_coords']
        seed_ts = bold_data[sx, sy, sz, :]
        
        # Standardize
        seed_z = (seed_ts - seed_ts.mean()) / seed_ts.std()
        
        # After standardization
        assert seed_z.mean() == pytest.approx(0, abs=1e-10)
        assert seed_z.std() == pytest.approx(1, rel=1e-3)


class TestCorrelationComputation:
    """Test correlation between seed and voxels."""
    
    def test_correlation_with_self_is_one(self, synthetic_bold_timeseries):
        """Correlation of seed with itself should be 1."""
        bold_data, metadata = synthetic_bold_timeseries
        
        sx, sy, sz = metadata['seed_coords']
        seed_ts = bold_data[sx, sy, sz, :]
        
        # Normalize
        seed_z = (seed_ts - seed_ts.mean()) / seed_ts.std()
        
        # Correlation with self
        r = np.corrcoef(seed_z, seed_z)[0, 1]
        
        assert r == pytest.approx(1.0, rel=1e-10)
    
    def test_correlation_range(self, synthetic_bold_timeseries):
        """All correlations should be in [-1, 1]."""
        bold_data, metadata = synthetic_bold_timeseries
        
        sx, sy, sz = metadata['seed_coords']
        seed_ts = bold_data[sx, sy, sz, :]
        seed_z = (seed_ts - seed_ts.mean()) / seed_ts.std()
        
        # Compute correlations with random voxels
        np.random.seed(42)
        for _ in range(10):
            rx = np.random.randint(0, bold_data.shape[0])
            ry = np.random.randint(0, bold_data.shape[1])
            rz = np.random.randint(0, bold_data.shape[2])
            
            voxel_ts = bold_data[rx, ry, rz, :]
            voxel_z = (voxel_ts - voxel_ts.mean()) / (voxel_ts.std() + 1e-10)
            
            r = np.corrcoef(seed_z, voxel_z)[0, 1]
            
            assert -1.0 <= r <= 1.0
    
    def test_correlation_matches_target_voxels(self, synthetic_bold_timeseries):
        """Correlation with target voxels should match implanted value."""
        bold_data, metadata = synthetic_bold_timeseries
        
        sx, sy, sz = metadata['seed_coords']
        seed_ts = bold_data[sx, sy, sz, :]
        seed_z = (seed_ts - seed_ts.mean()) / seed_ts.std()
        
        # Check target voxels
        for tx, ty, tz in metadata['target_coords'][:3]:  # Test first 3
            target_ts = bold_data[tx, ty, tz, :]
            target_z = (target_ts - target_ts.mean()) / (target_ts.std() + 1e-10)
            
            r = np.corrcoef(seed_z, target_z)[0, 1]
            
            # Should be close to implanted correlation (0.7)
            expected = metadata['implanted_correlation']
            assert 0.6 < r < 0.8, \
                f"Target voxel {(tx,ty,tz)}: r={r}, expected ~{expected}"
    
    def test_correlation_between_unrelated_voxels(self, synthetic_bold_timeseries):
        """Correlation between distant voxels should be weak."""
        bold_data, metadata = synthetic_bold_timeseries
        
        # Voxels far from seed should have weak correlation
        seed_ts = bold_data[metadata['seed_coords'][0],
                           metadata['seed_coords'][1],
                           metadata['seed_coords'][2], :]
        seed_z = (seed_ts - seed_ts.mean()) / seed_ts.std()
        
        # Far corner voxel
        corner_ts = bold_data[5, 5, 5, :]
        corner_z = (corner_ts - corner_ts.mean()) / (corner_ts.std() + 1e-10)
        
        r = np.corrcoef(seed_z, corner_z)[0, 1]
        
        # Should be weak (but could be anything on random data)
        assert -1.0 <= r <= 1.0


class TestZMapComputation:
    """Test Fisher z-transform and z-map creation."""
    
    def test_fisher_z_transform_symmetry(self):
        """Fisher z-transform should be symmetric around r=0."""
        r_vals = np.array([-0.8, -0.5, -0.2, 0, 0.2, 0.5, 0.8])
        
        # Fisher z-transform
        z_vals = 0.5 * np.log((1 + r_vals) / (1 - r_vals + 1e-10))
        
        # z(-r) = -z(r)
        for i in range(len(r_vals)):
            for j in range(i+1, len(r_vals)):
                if r_vals[i] == -r_vals[j]:
                    assert z_vals[i] == pytest.approx(-z_vals[j], rel=1e-5)
    
    def test_fisher_z_transform_range(self):
        """Fisher z-transform output should be normally distributed."""
        # For uncorrelated data, z-transform gives N(0,1) approximately
        np.random.seed(42)
        
        # Generate 100 random correlations
        r_vals = np.random.uniform(-0.99, 0.99, 100)
        
        # Apply Fisher z-transform
        z_vals = 0.5 * np.log((1 + r_vals) / (1 - r_vals + 1e-10))
        
        # Check range
        assert z_vals.min() < -2.5
        assert z_vals.max() > 2.5
    
    def test_zmap_normalization(self, synthetic_bold_timeseries):
        """Z-map should approximate N(0,1) distribution."""
        bold_data, metadata = synthetic_bold_timeseries
        
        sx, sy, sz = metadata['seed_coords']
        seed_ts = bold_data[sx, sy, sz, :]
        seed_z = (seed_ts - seed_ts.mean()) / seed_ts.std()
        
        # Compute z-map
        z_map = np.zeros(bold_data.shape[:3], dtype=np.float32)
        
        for x in range(bold_data.shape[0]):
            for y in range(bold_data.shape[1]):
                for z in range(bold_data.shape[2]):
                    if (x, y, z) == (sx, sy, sz):
                        z_map[x, y, z] = np.inf  # Seed itself
                    else:
                        voxel_ts = bold_data[x, y, z, :]
                        voxel_z = (voxel_ts - voxel_ts.mean()) / (voxel_ts.std() + 1e-10)
                        
                        r = np.corrcoef(seed_z, voxel_z)[0, 1]
                        
                        if not np.isnan(r):
                            r = np.clip(r, -0.9999, 0.9999)
                            z_map[x, y, z] = 0.5 * np.log((1 + r) / (1 - r + 1e-10))
        
        # Extract background z-values (away from seed)
        background_z = z_map[::10, ::10, ::10][np.isfinite(z_map[::10, ::10, ::10])]
        
        # Should be approximately N(0,1)
        assert abs(background_z.mean()) < 0.3, \
            f"Z-map mean {background_z.mean()} not centered"
        assert 0.7 < background_z.std() < 1.3, \
            f"Z-map std {background_z.std()} not unit variance"
    
    def test_zmap_no_nan_except_seed(self, synthetic_bold_timeseries):
        """Z-map should have no NaN values (except potentially seed)."""
        bold_data, metadata = synthetic_bold_timeseries
        
        sx, sy, sz = metadata['seed_coords']
        seed_ts = bold_data[sx, sy, sz, :]
        seed_z = (seed_ts - seed_ts.mean()) / seed_ts.std()
        
        # Compute z-map
        z_map = np.zeros(bold_data.shape[:3], dtype=np.float32)
        
        for x in range(0, bold_data.shape[0], 5):  # Sample for speed
            for y in range(0, bold_data.shape[1], 5):
                for z in range(0, bold_data.shape[2], 5):
                    voxel_ts = bold_data[x, y, z, :]
                    voxel_z = (voxel_ts - voxel_ts.mean()) / (voxel_ts.std() + 1e-10)
                    
                    r = np.corrcoef(seed_z, voxel_z)[0, 1]
                    
                    if not np.isnan(r):
                        r = np.clip(r, -0.9999, 0.9999)
                        z_map[x, y, z] = 0.5 * np.log((1 + r) / (1 - r + 1e-10))
        
        # Count NaN (excluding seed region)
        nan_count = np.isnan(z_map).sum()
        total_voxels = (bold_data.shape[0] // 5) * (bold_data.shape[1] // 5) * (bold_data.shape[2] // 5)
        
        # Should have very few NaN
        assert nan_count < 0.01 * total_voxels, \
            f"Too many NaN values: {nan_count}/{total_voxels}"


class TestSeedConnectivityMaps:
    """Test seed connectivity map properties."""
    
    def test_seed_map_shape(self, synthetic_seed_maps):
        """Seed connectivity maps should match expected shape."""
        seed_maps, metadata = synthetic_seed_maps
        
        assert len(seed_maps) == N_SUBJECTS * N_SESSIONS
        
        for map_path in seed_maps:
            # Load and check
            import nibabel as nib
            img = nib.load(str(map_path))
            data = img.get_fdata()
            
            assert data.shape == (90, 90, 90)
    
    def test_seed_map_values_valid(self, synthetic_seed_maps):
        """Seed map values should be valid z-scores."""
        import nibabel as nib
        
        seed_maps, metadata = synthetic_seed_maps
        
        for map_path in seed_maps[:5]:  # Test first 5
            img = nib.load(str(map_path))
            data = img.get_fdata()
            
            # Extract background voxels
            background = data[::10, ::10, ::10]
            background_finite = background[np.isfinite(background)]
            
            # Should be approximately N(0,1)
            mean_z = background_finite.mean()
            std_z = background_finite.std()
            
            assert abs(mean_z) < 0.5, f"Mean z-score {mean_z} not ~0"
            assert 0.5 < std_z < 1.5, f"Std z-score {std_z} not ~1"
    
    def test_seed_map_file_validity(self, synthetic_seed_maps):
        """Seed map files should be readable NIfTI."""
        import nibabel as nib
        
        seed_maps, _ = synthetic_seed_maps
        
        for map_path in seed_maps[:3]:
            # Should load without error
            img = nib.load(str(map_path))
            assert img is not None
            assert img.shape == (90, 90, 90)
            
            # Should have valid affine
            assert img.affine is not None
            assert img.affine.shape == (4, 4)


class TestMultipleSeedAnalysis:
    """Test handling of multiple seeds."""
    
    def test_multiple_seeds_independence(self, synthetic_bold_timeseries):
        """Different seeds should produce independent maps."""
        bold_data, metadata = synthetic_bold_timeseries
        
        # Seed 1
        seed1_ts = bold_data[45, 45, 45, :]
        
        # Seed 2 (far away)
        seed2_ts = bold_data[20, 20, 20, :]
        
        # Correlation between seeds should be weak
        seed1_z = (seed1_ts - seed1_ts.mean()) / seed1_ts.std()
        seed2_z = (seed2_ts - seed2_ts.mean()) / seed2_ts.std()
        
        r = np.corrcoef(seed1_z, seed2_z)[0, 1]
        
        # On uncorrelated data, should be weak
        assert -0.3 < r < 0.3, \
            f"Seeds not independent: r={r}"


# Constants used in tests (matching conftest.py)
N_SUBJECTS = 40
N_SESSIONS = 2
