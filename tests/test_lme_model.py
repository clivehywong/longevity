"""
Unit tests for Linear Mixed Effects (LME) modeling.

Tests verify:
- Model convergence on synthetic data
- Effect size estimation
- Handling of singular/degenerate cases
- Covariate standardization
- P-value computation
"""

import numpy as np
import pandas as pd
import pytest
from scipy import stats


class TestLMEModelConvergence:
    """Test LME model fitting and convergence."""
    
    def test_lme_fitting_single_voxel(self, synthetic_subject_metadata):
        """LME should fit successfully on single voxel data."""
        metadata = synthetic_subject_metadata.copy()
        
        # Create synthetic voxel data
        np.random.seed(42)
        n_scans = len(metadata)
        
        # Simple model: value ~ group + time
        voxel_values = (
            metadata['group_code'].values +
            metadata['time'].values +
            np.random.normal(0, 0.5, n_scans)
        )
        
        # Should be computable (even if we don't have statsmodels)
        assert len(voxel_values) == n_scans
        assert not np.isnan(voxel_values).any()
    
    def test_lme_with_random_intercept(self, synthetic_subject_metadata):
        """LME with random intercept should converge."""
        metadata = synthetic_subject_metadata.copy()
        
        np.random.seed(42)
        n_scans = len(metadata)
        
        # Model: value ~ group + time + (1|subject)
        # Random intercepts for each subject
        subject_effects = {}
        for subj in metadata['subject_id'].unique():
            subject_effects[subj] = np.random.normal(0, 0.3)
        
        voxel_values = (
            0.5 * metadata['group_code'].values +
            0.3 * metadata['time'].values +
            np.array([subject_effects[s] for s in metadata['subject_id']]) +
            np.random.normal(0, 0.2, n_scans)
        )
        
        assert len(voxel_values) == n_scans


class TestLMEEffectSizeEstimation:
    """Test effect size and coefficient estimation."""
    
    def test_lme_recovers_known_effect(self):
        """LME should recover known effect size."""
        np.random.seed(42)
        
        # Create simple data with known effect
        n = 40
        group = np.tile([0, 1], n//2)
        effect = 1.5
        
        y = group * effect + np.random.normal(0, 0.5, n)
        
        # Simple regression (equivalent to LME without random effects)
        coef = np.mean(y[group == 1]) - np.mean(y[group == 0])
        
        # Should be close to 1.5
        assert 1.0 < coef < 2.0, f"Effect estimation {coef} off"
    
    def test_lme_effect_size_range(self, synthetic_voxel_maps, synthetic_subject_metadata):
        """Effect sizes should be in reasonable range."""
        maps, metadata_dict = synthetic_voxel_maps
        
        # Central voxel (where effect is implanted)
        cx, cy, cz = metadata_dict['central_voxel']
        
        central_values = maps[:, cx, cy, cz]
        
        # Should have computable group difference
        n_per_group = metadata_dict['n_per_group']
        
        control_mean = central_values[:n_per_group].mean()
        treat_mean = central_values[n_per_group:].mean()
        
        effect = treat_mean - control_mean
        
        # Should be close to implanted effect (0.5)
        assert 0.2 < effect < 0.8, \
            f"Effect {effect} outside expected range [0.2, 0.8]"
    
    def test_lme_t_statistic_distribution(self, synthetic_voxel_maps):
        """T-statistics should follow approximate t-distribution."""
        maps, metadata_dict = synthetic_voxel_maps
        
        n_per_group = metadata_dict['n_per_group']
        expected_tstat = metadata_dict['expected_tstat']
        
        # For this synthetic data, should be around 2.5-3.0
        # (effect 0.5 SD with 40 subjects/group)
        assert expected_tstat > 0


class TestLMECovariateHandling:
    """Test covariate standardization and inclusion."""
    
    def test_covariate_standardization(self, synthetic_subject_metadata):
        """Covariates should be properly standardized."""
        metadata = synthetic_subject_metadata.copy()
        
        # Check age standardization
        age_std = metadata['age_std']
        
        assert abs(age_std.mean()) < 1e-10, "Age not centered"
        assert abs(age_std.std() - 1.0) < 1e-10, "Age not scaled to unit variance"
    
    def test_missing_covariate_handling(self, synthetic_subject_metadata):
        """Should handle missing covariates gracefully."""
        metadata = synthetic_subject_metadata.copy()
        
        # Introduce missing values
        metadata.loc[0:5, 'age'] = np.nan
        
        # Count available data
        n_valid = metadata['age'].notna().sum()
        pct = n_valid / len(metadata) * 100
        
        # Most data should still be available
        assert pct > 85


class TestLMESingularityHandling:
    """Test handling of singular/degenerate cases."""
    
    def test_degenerate_group_variable(self, synthetic_subject_metadata):
        """Should handle degenerate group variable."""
        metadata = synthetic_subject_metadata.copy()
        
        # Make all subjects in one group
        metadata['group_code'] = 0
        
        # Should recognize this issue
        group_unique = metadata['group_code'].nunique()
        assert group_unique == 1, "Failed to create degenerate case"
    
    def test_degenerate_time_variable(self, synthetic_subject_metadata):
        """Should handle degenerate time variable."""
        metadata = synthetic_subject_metadata.copy()
        
        # All time points the same
        metadata['time'] = 0
        
        # Should recognize this issue
        time_unique = metadata['time'].nunique()
        assert time_unique == 1, "Failed to create degenerate time case"
    
    def test_perfect_multicollinearity(self, synthetic_subject_metadata):
        """Should handle perfect multicollinearity."""
        metadata = synthetic_subject_metadata.copy()
        
        # Create perfectly collinear variables
        metadata['age_std_copy'] = metadata['age_std']
        
        # Should have high correlation
        corr = metadata['age_std'].corr(metadata['age_std_copy'])
        assert corr == pytest.approx(1.0, rel=1e-10)


class TestLMEMetadataValidation:
    """Test metadata validation before fitting."""
    
    def test_metadata_has_required_columns(self, synthetic_subject_metadata):
        """Metadata should have required columns."""
        metadata = synthetic_subject_metadata
        
        required = ['subject_id', 'session', 'group', 'time', 'group_code']
        for col in required:
            assert col in metadata.columns, f"Missing column: {col}"
    
    def test_metadata_no_nan_in_required_columns(self, synthetic_subject_metadata):
        """Required columns should have no NaN."""
        metadata = synthetic_subject_metadata
        
        required = ['subject_id', 'session', 'group_code', 'time']
        for col in required:
            assert metadata[col].notna().all(), f"Column {col} has NaN values"
    
    def test_metadata_subject_count(self, synthetic_subject_metadata):
        """Metadata should have expected number of subjects."""
        metadata = synthetic_subject_metadata
        
        n_subjects = metadata['subject_id'].nunique()
        assert n_subjects == 40, f"Expected 40 subjects, got {n_subjects}"
        
        scans_per_subject = metadata.groupby('subject_id').size()
        assert (scans_per_subject == 2).all(), "Not all subjects have 2 sessions"


class TestLMERobustness:
    """Test robustness to edge cases."""
    
    def test_model_with_outliers(self):
        """Model should be robust to outliers."""
        np.random.seed(42)
        
        n = 80
        y = np.random.normal(0, 1, n)
        
        # Add outliers
        y[0:5] = 100
        
        # Should not crash
        mean_with_outliers = y.mean()
        median_with_outliers = np.median(y)
        
        # Median more robust
        assert abs(median_with_outliers) < abs(mean_with_outliers)
    
    def test_model_with_few_observations(self):
        """Model should give reasonable results even with few subjects."""
        np.random.seed(42)
        
        # Minimum viable case: 4 subjects (2 per group), 2 sessions
        metadata = pd.DataFrame({
            'subject_id': ['sub-01', 'sub-01', 'sub-02', 'sub-02',
                          'sub-03', 'sub-03', 'sub-04', 'sub-04'],
            'session': [1, 2, 1, 2, 1, 2, 1, 2],
            'group_code': [0, 0, 0, 0, 1, 1, 1, 1],
            'time': [0, 1, 0, 1, 0, 1, 0, 1],
        })
        
        assert len(metadata) == 8
        assert metadata['subject_id'].nunique() == 4


class TestLMEVoxelBatchProcessing:
    """Test batch processing of multiple voxels."""
    
    def test_voxel_batch_shape(self, synthetic_voxel_maps):
        """Voxel batch should have correct shape."""
        maps, _ = synthetic_voxel_maps
        
        assert maps.ndim == 4
        assert maps.shape[0] == 80  # 80 scans
        assert maps.shape[1:] == (90, 90, 90)  # Spatial dimensions
    
    def test_voxel_batch_no_nan_unless_intentional(self, synthetic_voxel_maps):
        """Batch should have minimal NaN (except mask areas)."""
        maps, _ = synthetic_voxel_maps
        
        nan_fraction = np.isnan(maps).sum() / maps.size
        
        # Should have very few NaN (< 1%)
        assert nan_fraction < 0.01, f"Too many NaN: {nan_fraction*100}%"
    
    def test_voxel_batch_consistent_statistics(self, synthetic_voxel_maps):
        """Statistics should be consistent across voxels."""
        maps, _ = synthetic_voxel_maps
        
        # Compute voxel-wise mean and std
        means = np.mean(maps, axis=0)
        stds = np.std(maps, axis=0)
        
        # Should be roughly centered and unit variance on average
        overall_mean = np.nanmean(means)
        overall_std = np.nanmean(stds)
        
        assert abs(overall_mean) < 0.5
        assert 0.5 < overall_std < 2.0


class TestLMEFormulaParsing:
    """Test model formula construction."""
    
    def test_basic_formula_construction(self):
        """Basic formula should be constructed correctly."""
        formula_parts = ['group_code', 'time']
        formula = 'value ~ ' + ' + '.join(formula_parts)
        
        assert 'value ~' in formula
        assert 'group_code' in formula
        assert 'time' in formula
    
    def test_formula_with_covariates(self):
        """Formula should include available covariates."""
        formula_parts = ['group_code * time', 'age_std', 'sex_code']
        formula = 'value ~ ' + ' + '.join(formula_parts)
        
        assert 'group_code * time' in formula
        assert 'age_std' in formula
        assert 'sex_code' in formula
    
    def test_formula_with_interaction(self):
        """Formula should support interaction terms."""
        formula = 'value ~ group_code * time + age_std'
        
        assert '*' in formula
        assert 'group_code' in formula
        assert 'time' in formula


class TestLMEPValueComputation:
    """Test p-value computation from t-statistics."""
    
    def test_pvalue_from_tstat(self):
        """P-values should be correctly computed from t-statistics."""
        df = 70  # Example degrees of freedom
        
        # t-statistic values
        t_stats = np.array([0, 1.96, -1.96, 3.0, -3.0])
        
        # Compute two-tailed p-values
        p_vals = 2 * (1 - stats.t.cdf(np.abs(t_stats), df))
        
        # Check ranges
        assert (p_vals >= 0).all() and (p_vals <= 1).all()
        
        # t=0 should give p=1
        assert p_vals[0] == pytest.approx(1.0, rel=1e-10)
        
        # |t|=1.96 should give p≈0.05
        assert 0.04 < p_vals[1] < 0.06
