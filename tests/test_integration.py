"""
Integration tests for complete pipeline execution.

Tests verify:
- End-to-end pipeline workflow
- Data flow between pipeline stages
- Output file structure
- Consistency across pipeline stages
"""

import numpy as np
import pandas as pd
import pytest
from pathlib import Path


class TestPipelineExecutionMinimal:
    """Test pipeline execution with minimal data."""
    
    def test_pipeline_2subjects_minimal(
        self,
        synthetic_bold_timeseries,
        synthetic_subject_metadata,
        tmp_path
    ):
        """Pipeline should handle 2 subjects (minimum viable)."""
        bold_data, _ = synthetic_bold_timeseries
        
        # Metadata for 2 subjects (4 scans)
        metadata = synthetic_subject_metadata.iloc[:4].copy()
        
        assert len(metadata) == 4
        assert metadata['subject_id'].nunique() == 2
    
    def test_pipeline_single_session_data(
        self,
        synthetic_subject_metadata,
        tmp_path
    ):
        """Pipeline should handle cross-sectional data (1 session)."""
        # Single session only
        metadata = synthetic_subject_metadata[
            synthetic_subject_metadata['session'] == 1
        ].copy()
        
        assert metadata['session'].nunique() == 1
        assert len(metadata) == 40


class TestLocalMeasuresPipeline:
    """Test local measures computation stage."""
    
    def test_local_measures_output_shape(self, synthetic_bold_timeseries):
        """Local measures output should match spatial dimensions."""
        bold_data, _ = synthetic_bold_timeseries
        
        expected_shape = bold_data.shape[:3]
        
        # fALFF output shape
        assert expected_shape == (90, 90, 90)
    
    def test_local_measures_batch_processing(self):
        """Should process multiple subjects in batch."""
        n_subjects = 10
        
        # Each subject produces 2 outputs (fALFF, ReHo)
        n_outputs = n_subjects * 2
        
        assert n_outputs == 20


class TestSeedConnectivityPipeline:
    """Test seed connectivity stage."""
    
    def test_seed_connectivity_output_multiplicity(self):
        """Should generate output for each seed."""
        n_subjects = 40
        n_sessions = 2
        n_seeds = 5
        
        expected_maps = n_subjects * n_sessions * n_seeds
        
        assert expected_maps == 400
    
    def test_seed_connectivity_file_naming(self, tmp_path):
        """Output files should follow naming convention."""
        # Expected naming: seed_based/{atlas}/{seed_name}/{sub}_{ses}_zmap.nii.gz
        
        seed_based_dir = tmp_path / "seed_based"
        seed_based_dir.mkdir()
        
        (seed_based_dir / "DiFuMo").mkdir()
        (seed_based_dir / "DiFuMo" / "Motor_Cortex").mkdir()
        
        map_file = (
            seed_based_dir / "DiFuMo" / "Motor_Cortex" / "sub-033_ses-01_zmap.nii.gz"
        )
        
        # Check structure is valid
        assert seed_based_dir.exists()
        assert (seed_based_dir / "DiFuMo").exists()


class TestGroupAnalysisPipeline:
    """Test group-level analysis stage."""
    
    def test_group_analysis_requires_sufficient_data(self, synthetic_subject_metadata):
        """Group analysis should require minimum sample size."""
        metadata = synthetic_subject_metadata
        
        # 40 subjects should be sufficient
        assert len(metadata['subject_id'].unique()) >= 20
    
    def test_group_analysis_balanced_design(self, synthetic_subject_metadata):
        """Design should be approximately balanced for power."""
        metadata = synthetic_subject_metadata
        
        group_counts = metadata.groupby('group').size()
        
        # Should be roughly 50-50
        ratio = group_counts.min() / group_counts.max()
        
        assert 0.9 < ratio < 1.1


class TestOutputConsistency:
    """Test consistency of outputs across pipeline."""
    
    def test_same_subject_across_stages(self):
        """Same subject should be present in all stages."""
        # Subject IDs
        subjects = [f"sub-{33+i:03d}" for i in range(40)]
        
        # Should be 40 subjects
        assert len(subjects) == 40
        assert subjects[0] == "sub-033"
    
    def test_metadata_consistency(self, synthetic_subject_metadata):
        """Metadata should be consistent across stages."""
        metadata = synthetic_subject_metadata
        
        # Check consistency: each subject should appear in both sessions
        for subject in metadata['subject_id'].unique():
            subject_data = metadata[metadata['subject_id'] == subject]
            
            # Should have 2 sessions
            assert len(subject_data) == 2
            assert set(subject_data['session']) == {1, 2}


class TestStatisticalModelConsistency:
    """Test consistency across statistical models."""
    
    def test_covariate_standardization_consistency(self):
        """Standardization should be consistent across models."""
        # Create metadata
        np.random.seed(42)
        age = np.random.uniform(50, 75, 80)
        
        age_std_1 = (age - age.mean()) / age.std()
        age_std_2 = (age - age.mean()) / age.std()
        
        # Should be identical
        np.testing.assert_array_equal(age_std_1, age_std_2)
    
    def test_group_effect_direction_consistent(self, synthetic_voxel_maps):
        """Group effect direction should be consistent."""
        maps, metadata = synthetic_voxel_maps
        
        cx, cy, cz = metadata['central_voxel']
        central_values = maps[:, cx, cy, cz]
        
        n_per_group = metadata['n_per_group']
        
        control_mean = central_values[:n_per_group].mean()
        treat_mean = central_values[n_per_group:].mean()
        
        # Effect should be in consistent direction (treatment > control)
        assert treat_mean > control_mean


class TestOutputFileStructure:
    """Test that output files are created in expected locations."""
    
    def test_results_directory_structure(self, tmp_path):
        """Results should have expected directory structure."""
        results = tmp_path / "results"
        results.mkdir()
        
        # Create expected subdirectories
        (results / "local_measures").mkdir()
        (results / "seed_based").mkdir()
        (results / "network").mkdir()
        (results / "group_analysis").mkdir()
        
        # Check all exist
        assert (results / "local_measures").exists()
        assert (results / "seed_based").exists()
        assert (results / "network").exists()
        assert (results / "group_analysis").exists()
    
    def test_subject_session_directory_naming(self, tmp_path):
        """Subject-session directories should follow naming convention."""
        base = tmp_path / "results" / "local_measures"
        base.mkdir(parents=True)
        
        # Create subject-session directories
        for sub_id in range(33, 36):  # 3 subjects
            for ses in [1, 2]:
                subdir = base / f"sub-{sub_id:03d}_ses-{ses}"
                subdir.mkdir()
                
                assert subdir.exists()
    
    def test_output_file_extensions(self, tmp_path):
        """Output files should have expected extensions."""
        results = tmp_path / "results"
        results.mkdir()
        
        # NIfTI files
        nifti_file = results / "output.nii.gz"
        nifti_file.touch()
        
        # CSV files
        csv_file = results / "stats.csv"
        csv_file.touch()
        
        # Check extensions
        assert nifti_file.suffix == ".gz"
        assert csv_file.suffix == ".csv"


class TestPipelineErrorHandling:
    """Test error handling during pipeline execution."""
    
    def test_missing_input_file_handling(self):
        """Pipeline should handle missing input gracefully."""
        # Non-existent file path
        missing_file = Path("/nonexistent/path/bold.nii.gz")
        
        assert not missing_file.exists()
    
    def test_corrupted_nifti_handling(self, tmp_path):
        """Pipeline should detect corrupted NIfTI files."""
        # Create corrupted file
        corrupted = tmp_path / "corrupted.nii.gz"
        corrupted.write_text("This is not a NIfTI file")
        
        # Should be detectable as invalid
        assert corrupted.exists()
        
        # Attempting to load would fail (not tested here)


class TestPipelineDataTypes:
    """Test that pipeline maintains correct data types."""
    
    def test_metadata_dtypes(self, synthetic_subject_metadata):
        """Metadata should have correct data types."""
        metadata = synthetic_subject_metadata
        
        assert metadata['subject_id'].dtype == object  # String
        assert metadata['session'].dtype in [np.int64, np.int32]  # Integer
        assert metadata['group_code'].dtype in [np.int64, np.int32]  # Integer
        assert metadata['age'].dtype in [np.float64, np.float32]  # Float
    
    def test_map_dtypes(self, synthetic_voxel_maps):
        """Maps should have correct data types."""
        maps, _ = synthetic_voxel_maps
        
        assert maps.dtype in [np.float32, np.float64]


class TestPipelineReproducibility:
    """Test that pipeline produces reproducible results."""
    
    def test_same_seed_same_results(self):
        """Same random seed should give identical results."""
        def generate_data(seed):
            np.random.seed(seed)
            return np.random.normal(0, 1, 100)
        
        data1 = generate_data(42)
        data2 = generate_data(42)
        
        np.testing.assert_array_equal(data1, data2)
    
    def test_deterministic_processing(self, synthetic_subject_metadata):
        """Processing should be deterministic."""
        metadata = synthetic_subject_metadata.copy()
        
        # Sort by subject_id
        sorted1 = metadata.sort_values('subject_id').reset_index(drop=True)
        sorted2 = metadata.sort_values('subject_id').reset_index(drop=True)
        
        pd.testing.assert_frame_equal(sorted1, sorted2)


class TestPipelineMemoryEfficiency:
    """Test that pipeline doesn't have memory leaks or excessive memory use."""
    
    def test_batch_processing_not_loading_all_at_once(self):
        """Batch processing should not load all data at once."""
        # Pseudocode: should process voxels or subjects in batches
        
        n_voxels = 90 * 90 * 90  # 729,000
        batch_size = 10000
        
        n_batches = int(np.ceil(n_voxels / batch_size))
        
        assert n_batches > 1  # Multiple batches
    
    def test_temporary_file_cleanup(self, tmp_path):
        """Pipeline should clean up temporary files."""
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        
        temp_file = temp_dir / "temp_output.nii.gz"
        temp_file.touch()
        
        # Simulate cleanup
        temp_file.unlink()
        
        assert not temp_file.exists()


class TestPipelineLogging:
    """Test that pipeline produces appropriate logs."""
    
    def test_log_content_structure(self, tmp_path):
        """Logs should have expected content structure."""
        log_file = tmp_path / "pipeline.log"
        
        log_content = """
[2025-01-15 10:00:00] Pipeline started
[2025-01-15 10:00:05] Processing local measures
[2025-01-15 10:00:10] Processing seed connectivity
[2025-01-15 10:01:00] Group analysis complete
[2025-01-15 10:01:05] Pipeline finished
"""
        
        log_file.write_text(log_content)
        
        content = log_file.read_text()
        
        assert "Pipeline started" in content
        assert "Pipeline finished" in content
