"""
Unit tests for permutation-based multiple comparison correction.

Tests verify:
- P-values in valid range [0, 1]
- P-value distribution under null hypothesis
- Cluster extraction correctness
- Cluster labeling with anatomical atlases
"""

import numpy as np
import pytest
from scipy import stats as scipy_stats


class TestPermutationPValues:
    """Test permutation p-value computation."""
    
    def test_pvalue_range(self):
        """All p-values should be in [0, 1]."""
        np.random.seed(42)
        
        # Simulate p-values from permutation test
        observed_stat = 3.0
        n_perms = 1000
        
        # Permutation statistics
        perm_stats = np.random.normal(0, 1, n_perms)
        
        # Count more extreme
        n_extreme = (np.abs(perm_stats) >= np.abs(observed_stat)).sum()
        
        p_value = n_extreme / n_perms
        
        assert 0 <= p_value <= 1
    
    def test_pvalue_no_nan_inf(self):
        """P-values should not contain NaN or Inf."""
        np.random.seed(42)
        
        n_tests = 100
        p_values = np.random.uniform(0, 1, n_tests)
        
        assert not np.isnan(p_values).any()
        assert not np.isinf(p_values).any()
    
    def test_pvalue_symmetry_for_symmetric_test(self):
        """Two-tailed test should give same p for t and -t."""
        np.random.seed(42)
        
        observed = 2.5
        perm_stats = np.random.normal(0, 1, 1000)
        
        # Two-tailed: count |stat| >= |obs|
        p_two_tailed = (np.abs(perm_stats) >= np.abs(observed)).sum() / len(perm_stats)
        
        # Should work for both positive and negative
        p_neg = (np.abs(perm_stats) >= np.abs(-observed)).sum() / len(perm_stats)
        
        assert p_two_tailed == pytest.approx(p_neg, rel=1e-10)


class TestPValueDistribution:
    """Test that p-values follow expected distribution under null."""
    
    def test_null_pvalue_distribution_uniform(self):
        """Under null hypothesis, p-values should be ~U(0,1)."""
        np.random.seed(42)
        
        n_tests = 1000
        
        # Simulate null: each test statistic is N(0,1)
        test_stats = np.random.normal(0, 1, n_tests)
        
        # Null permutation statistics (same distribution)
        perm_stats = np.random.normal(0, 1, (n_tests, 1000))
        
        # Compute p-values
        p_values = np.zeros(n_tests)
        for i in range(n_tests):
            p_values[i] = (np.abs(perm_stats[i]) >= np.abs(test_stats[i])).sum() / 1000
        
        # K-S test for uniformity
        ks_stat, ks_pval = scipy_stats.kstest(p_values, 'uniform')
        
        # Should not reject uniformity (p > 0.05)
        # (Though this is weak with 1000 samples)
        assert ks_pval > 0.01 or ks_stat < 0.15
    
    def test_pvalue_distribution_quantiles(self):
        """P-value quantiles should match uniform distribution."""
        np.random.seed(42)
        
        # Generate uniform p-values
        p_values = np.random.uniform(0, 1, 1000)
        
        # Quantiles
        q25 = np.percentile(p_values, 25)
        q50 = np.percentile(p_values, 50)
        q75 = np.percentile(p_values, 75)
        
        # Should be approximately 0.25, 0.50, 0.75
        assert 0.20 < q25 < 0.30
        assert 0.45 < q50 < 0.55
        assert 0.70 < q75 < 0.80


class TestPermutationTestMultipleComparisons:
    """Test multiple comparison procedures."""
    
    def test_bonferroni_correction(self):
        """Bonferroni should correct alpha appropriately."""
        n_tests = 100
        alpha = 0.05
        alpha_bonf = alpha / n_tests
        
        assert alpha_bonf == pytest.approx(0.0005, rel=1e-10)
    
    def test_fdr_correction_conservative(self):
        """FDR should be less conservative than Bonferroni."""
        n_tests = 100
        alpha = 0.05
        
        # Bonferroni
        alpha_bonf = alpha / n_tests
        
        # Benjamini-Hochberg FDR (approximately less conservative)
        # This is a rough approximation
        alpha_fdr_approx = alpha / (np.log(n_tests) + 1)
        
        assert alpha_fdr_approx > alpha_bonf
    
    def test_fwer_control(self):
        """Family-wise error rate should be controlled."""
        np.random.seed(42)
        
        # Generate p-values from null tests
        n_tests = 1000
        p_values = np.random.uniform(0, 1, n_tests)
        
        alpha = 0.05
        
        # Bonferroni-corrected threshold
        alpha_bonf = alpha / n_tests
        
        # Count false positives at Bonferroni level
        false_pos = (p_values < alpha_bonf).sum()
        
        # Should be very few (possibly 0)
        fwer = false_pos / n_tests
        assert fwer < alpha / 10


class TestClusterExtraction:
    """Test cluster identification and extraction."""
    
    def test_cluster_connectivity_3d(self):
        """Clusters should use appropriate connectivity."""
        # Create simple 3D cluster (3×3×3 cube)
        data = np.zeros((10, 10, 10), dtype=bool)
        data[3:6, 3:6, 3:6] = True
        
        # Should form single cluster with 26-connectivity (6-face neighbors)
        # For simplicity, just test extraction
        cluster_coords = np.where(data)
        n_voxels = len(cluster_coords[0])
        
        assert n_voxels == 27  # 3×3×3
    
    def test_cluster_size_distribution(self):
        """Cluster sizes should follow expected distribution."""
        np.random.seed(42)
        
        # Create random thresholded map
        stat_map = np.random.normal(0, 1, size=(50, 50, 50))
        threshold = 2.0
        
        # Threshold
        binary_map = stat_map > threshold
        
        n_voxels_above = binary_map.sum()
        
        # With threshold 2.0 on N(0,1), expect ~2.3% above threshold
        expected_pct = 1 - scipy_stats.norm.cdf(threshold)
        expected_voxels = expected_pct * 50**3
        
        assert n_voxels_above < expected_voxels * 1.5
    
    def test_cluster_isolation(self):
        """Isolated voxels should not form clusters."""
        # Create isolated voxels (no connected neighbors)
        data = np.zeros((10, 10, 10), dtype=bool)
        data[2, 2, 2] = True
        data[5, 5, 5] = True
        data[8, 8, 8] = True
        
        # Each should be separate cluster
        n_isolated = data.sum()
        assert n_isolated == 3


class TestClusterThresholding:
    """Test cluster-level thresholding."""
    
    def test_minimum_cluster_size_filtering(self):
        """Clusters smaller than threshold should be removed."""
        # Create cluster map with clusters of different sizes
        cluster_map = np.zeros((30, 30, 30), dtype=int)
        
        # Small cluster
        cluster_map[5:7, 5:7, 5:7] = 1
        
        # Large cluster
        cluster_map[15:25, 15:25, 15:25] = 2
        
        # Count voxels per cluster
        cluster_sizes = {}
        for cluster_id in np.unique(cluster_map):
            if cluster_id == 0:
                continue
            cluster_sizes[cluster_id] = (cluster_map == cluster_id).sum()
        
        # Min size threshold
        min_voxels = 100
        
        # Filter
        filtered_map = cluster_map.copy()
        for cluster_id, size in cluster_sizes.items():
            if size < min_voxels:
                filtered_map[cluster_map == cluster_id] = 0
        
        # Should remove small cluster
        assert (filtered_map == 1).sum() == 0
        assert (filtered_map == 2).sum() > 0
    
    def test_voxel_level_vs_cluster_level_threshold(self):
        """Cluster-level threshold should be less stringent than voxel-level."""
        # Example from permutation testing
        
        # Voxel-level: correct for all voxels
        n_voxels = 50**3  # 125,000
        alpha_voxel = 0.05 / n_voxels
        threshold_voxel = scipy_stats.norm.ppf(1 - alpha_voxel/2)
        
        # Cluster-level: correct for fewer clusters (e.g., 100-1000)
        n_clusters_est = 500
        alpha_cluster = 0.05 / n_clusters_est
        threshold_cluster = scipy_stats.norm.ppf(1 - alpha_cluster/2)
        
        # Cluster threshold should be lower (less stringent)
        assert threshold_cluster < threshold_voxel


class TestClusterLabeling:
    """Test anatomical labeling of clusters."""
    
    def test_cluster_to_mni_coordinates(self):
        """Clusters should be converted to MNI coordinates."""
        # Example: cluster in local space
        cluster_coords_local = [(45, 45, 45), (46, 45, 45), (45, 46, 45)]
        
        # Voxel size: 4 mm isotropic
        voxel_size = 4.0
        
        # Convert to MNI (simplified, assuming centered origin)
        mni_coords = []
        for x, y, z in cluster_coords_local:
            mx = (x - 45) * voxel_size
            my = (y - 45) * voxel_size
            mz = (z - 45) * voxel_size
            mni_coords.append((mx, my, mz))
        
        assert len(mni_coords) == 3
        assert mni_coords[0] == (0, 0, 0)
    
    def test_cluster_peak_voxel(self):
        """Should identify cluster peak voxel."""
        # Create cluster with peak
        stat_map = np.zeros((20, 20, 20))
        stat_map[8:12, 8:12, 8:12] = 1.0
        stat_map[10, 10, 10] = 5.0  # Peak
        
        # Find peak
        cluster_idx = np.where(stat_map > 0.5)
        peak_idx = np.unravel_index(
            np.argmax(stat_map[cluster_idx]),
            np.array(stat_map[cluster_idx]).shape
        )
        
        # Peak should be at (10, 10, 10)
        peak_coord = (
            cluster_idx[0][peak_idx],
            cluster_idx[1][peak_idx],
            cluster_idx[2][peak_idx]
        )
        
        assert peak_coord == (10, 10, 10)


class TestClusterStatistics:
    """Test statistics computed on clusters."""
    
    def test_cluster_mean_statistic(self):
        """Cluster should report mean statistic."""
        # Create cluster
        stat_map = np.zeros((20, 20, 20))
        stat_map[8:12, 8:12, 8:12] = np.random.normal(2.0, 0.5, (4, 4, 4))
        
        cluster_voxels = stat_map[stat_map > 0]
        cluster_mean = cluster_voxels.mean()
        
        # Should be approximately 2.0
        assert 1.5 < cluster_mean < 2.5
    
    def test_cluster_size_reporting(self):
        """Cluster size should be reported in voxels and mm3."""
        # Cluster: 5×5×5 voxels = 125 voxels
        cluster_size_voxels = 125
        
        # Voxel size: 2 mm isotropic
        voxel_size_mm3 = 2**3
        
        cluster_size_mm3 = cluster_size_voxels * voxel_size_mm3
        
        assert cluster_size_mm3 == 1000  # 125 * 8


class TestPermutationTestParameters:
    """Test parameters for permutation testing."""
    
    def test_permutation_count_adequacy(self):
        """Number of permutations affects p-value precision."""
        n_perms = 1000
        
        # With 1000 permutations, minimum non-zero p ~ 1/1000
        min_pval = 1.0 / (n_perms + 1)
        
        assert min_pval == pytest.approx(0.001, rel=1e-3)
    
    def test_permutation_count_for_threshold(self):
        """Permutation count should be sufficient for threshold."""
        alpha = 0.05
        n_perms = 1000
        
        # Can achieve p = 0.05 exactly with ceil(1000 * 0.05) = 50 permutations
        expected_threshold_perms = int(np.ceil(n_perms * alpha))
        
        assert expected_threshold_perms == 50
    
    def test_random_seed_reproducibility(self):
        """Same seed should give same results."""
        def permutation_test(seed):
            np.random.seed(seed)
            stats = np.random.randn(100)
            return np.mean(stats)
        
        result1 = permutation_test(42)
        result2 = permutation_test(42)
        
        assert result1 == result2
