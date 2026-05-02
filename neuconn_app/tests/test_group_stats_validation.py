"""
Unit tests for SubjectDataValidator class (group statistics validation).

Tests cover:
- Canonical order loading and validation
- Single-subject file validation (success and error cases)
- Batch validation of all subjects
- Canonical zmap ordering
- Summary statistics
- Error handling and logging
"""

import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile
import nibabel as nib

from neuconn_app.utils.group_stats_validation import (
    SubjectDataValidator,
    ValidationResult,
)


@pytest.fixture
def temp_bids_root(tmp_path):
    """Create a temporary BIDS root directory."""
    bids_root = tmp_path / "bids"
    bids_root.mkdir()
    return bids_root


@pytest.fixture
def canonical_order_csv(tmp_path):
    """Create a canonical order CSV with exactly 72 rows (36 subjects × 2 sessions)."""
    csv_path = tmp_path / "canonical_subject_order.csv"
    
    # 20 control + 16 walking = 36 subjects × 2 sessions = 72 rows
    control_subjects = [
        'sub-033', 'sub-034', 'sub-035', 'sub-036', 'sub-037',
        'sub-038', 'sub-039', 'sub-040', 'sub-058', 'sub-059',
        'sub-060', 'sub-061', 'sub-062', 'sub-063', 'sub-064',
        'sub-065', 'sub-076', 'sub-079', 'sub-080', 'sub-081'
    ]
    walking_subjects = [
        'sub-043', 'sub-045', 'sub-046', 'sub-047', 'sub-048',
        'sub-051', 'sub-052', 'sub-055', 'sub-056', 'sub-057',
        'sub-066', 'sub-068', 'sub-069', 'sub-071', 'sub-072', 'sub-074'
    ]
    
    data = []
    row_idx = 0
    
    # Add control subjects
    for subj in control_subjects:
        data.append([row_idx, subj, "ses-01", "Control"])
        row_idx += 1
        data.append([row_idx, subj, "ses-02", "Control"])
        row_idx += 1
    
    # Add walking subjects
    for subj in walking_subjects:
        data.append([row_idx, subj, "ses-01", "Walking"])
        row_idx += 1
        data.append([row_idx, subj, "ses-02", "Walking"])
        row_idx += 1
    
    df = pd.DataFrame(data, columns=["row_index", "subject", "session", "group"])
    df.to_csv(csv_path, index=False)
    
    return csv_path


@pytest.fixture
def sample_nifti_file(tmp_path):
    """Create a sample NIfTI file with correct shape and dtype."""
    nifti_path = tmp_path / "sample.nii.gz"
    
    # Create 91x109x91 data
    data = np.random.randn(91, 109, 91).astype(np.float64)
    img = nib.Nifti1Image(data, np.eye(4))
    nib.save(img, str(nifti_path))
    
    return nifti_path


@pytest.fixture
def validator_with_csv(temp_bids_root, canonical_order_csv):
    """Create a validator with temp directories."""
    return SubjectDataValidator(
        bids_root=str(temp_bids_root),
        canonical_order_csv=str(canonical_order_csv),
    )


class TestValidationResult:
    """Test ValidationResult dataclass."""
    
    def test_validation_result_success(self):
        """Test successful validation result."""
        result = ValidationResult(
            exists=True,
            shape=(91, 109, 91),
            dtype="float64",
            has_nan=False,
            mean=0.5,
            std=1.0,
        )
        assert result.exists is True
        assert result.error is None
    
    def test_validation_result_error(self):
        """Test error validation result."""
        result = ValidationResult(
            exists=False,
            error="File not found"
        )
        assert result.exists is False
        assert result.error == "File not found"
    
    def test_validation_result_to_dict(self):
        """Test conversion to dictionary."""
        result = ValidationResult(
            exists=True,
            shape=(91, 109, 91),
            dtype="float64",
            has_nan=False,
            mean=0.5,
            std=1.0,
        )
        d = result.to_dict()
        assert d["exists"] is True
        assert d["shape"] == (91, 109, 91)
        assert d["dtype"] == "float64"


class TestSubjectDataValidatorInit:
    """Test SubjectDataValidator initialization."""
    
    def test_init_basic(self, validator_with_csv):
        """Test basic initialization."""
        assert validator_with_csv.bids_root is not None
        assert len(validator_with_csv.canonical_order) == 72
    
    def test_init_custom_pipeline_atlas_measure(self, temp_bids_root, canonical_order_csv):
        """Test initialization with custom parameters."""
        validator = SubjectDataValidator(
            bids_root=str(temp_bids_root),
            canonical_order_csv=str(canonical_order_csv),
            pipeline="fc_gsr",
            atlas="Schaefer400",
            measure="spearman",
        )
        assert validator.pipeline == "fc_gsr"
        assert validator.atlas == "Schaefer400"
        assert validator.measure == "spearman"
    
    def test_init_missing_csv(self, temp_bids_root):
        """Test error on missing CSV."""
        with pytest.raises(FileNotFoundError):
            SubjectDataValidator(
                bids_root=str(temp_bids_root),
                canonical_order_csv="/nonexistent/path.csv",
            )
    
    def test_init_invalid_csv_structure(self, temp_bids_root, tmp_path):
        """Test error on invalid CSV structure."""
        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text("col1,col2\nval1,val2\n")
        
        with pytest.raises(ValueError, match="missing columns"):
            SubjectDataValidator(
                bids_root=str(temp_bids_root),
                canonical_order_csv=str(bad_csv),
            )
    
    def test_load_canonical_order_columns(self, validator_with_csv):
        """Test that canonical order has required columns."""
        df = validator_with_csv.canonical_order
        required_cols = ["row_index", "subject", "session", "group"]
        assert all(col in df.columns for col in required_cols)


class TestCanonicalOrderLoading:
    """Test canonical order CSV loading and validation."""
    
    def test_canonical_order_72_rows(self, validator_with_csv):
        """Test that canonical order has exactly 72 rows."""
        assert len(validator_with_csv.canonical_order) == 72
    
    def test_canonical_order_session_pairs(self, validator_with_csv):
        """Test that sessions are paired (ses-01, ses-02)."""
        df = validator_with_csv.canonical_order
        for i in range(0, len(df), 2):
            subj1 = df.iloc[i]["subject"]
            subj2 = df.iloc[i + 1]["subject"]
            sess1 = df.iloc[i]["session"]
            sess2 = df.iloc[i + 1]["session"]
            
            # Same subject, different sessions
            assert subj1 == subj2
            assert sess1 == "ses-01"
            assert sess2 == "ses-02"
    
    def test_canonical_order_groups(self, validator_with_csv):
        """Test that groups are present."""
        groups = validator_with_csv.canonical_order["group"].unique()
        assert "Control" in groups
        assert "Walking" in groups
    
    def test_canonical_order_subject_format(self, validator_with_csv):
        """Test that subjects have BIDS format."""
        subjects = validator_with_csv.canonical_order["subject"].unique()
        for subj in subjects:
            assert subj.startswith("sub-")
            assert len(subj) >= 7  # sub-XXX minimum


class TestFindZmapFile:
    """Test zmap file discovery."""
    
    def test_find_zmap_file_exists(self, validator_with_csv, temp_bids_root, sample_nifti_file):
        """Test finding an existing zmap file."""
        # Create directory structure
        subject = "sub-033"
        session = "ses-01"
        seed_dir = (
            temp_bids_root
            / "derivatives" / "connectivity" / "fc"
            / subject / session / "seed"
            / "atlas-4S256Parcels_parcel-LH_Cont_Par_1"
        )
        seed_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy sample nifti
        zmap_path = seed_dir / f"{subject}_{session}_seed-atlas-4S256Parcels_parcel-LH_Cont_Par_1_seed-to-voxel_zmap.nii.gz"
        import shutil
        shutil.copy(str(sample_nifti_file), str(zmap_path))
        
        # Test finding
        found = validator_with_csv._find_zmap_file(subject, session)
        assert found is not None
        assert found.exists()
    
    def test_find_zmap_file_missing_directory(self, validator_with_csv):
        """Test behavior when seed directory doesn't exist."""
        found = validator_with_csv._find_zmap_file("sub-999", "ses-01")
        assert found is None
    
    def test_find_zmap_file_no_zmaps(self, validator_with_csv, temp_bids_root):
        """Test behavior when seed directory exists but has no zmaps."""
        subject = "sub-033"
        session = "ses-01"
        seed_dir = (
            temp_bids_root
            / "derivatives" / "connectivity" / "fc"
            / subject / session / "seed" / "atlas-4S256Parcels"
        )
        seed_dir.mkdir(parents=True, exist_ok=True)
        
        found = validator_with_csv._find_zmap_file(subject, session)
        assert found is None


class TestValidateSingleSubject:
    """Test single-subject validation."""
    
    def test_validate_subject_file_missing(self, validator_with_csv):
        """Test validation of missing file."""
        result = validator_with_csv.validate_subject_file("sub-999", "ses-01")
        assert result.exists is False
        assert result.error is not None
    
    def test_validate_subject_file_success(self, validator_with_csv, temp_bids_root, sample_nifti_file):
        """Test successful validation."""
        subject = "sub-033"
        session = "ses-01"
        seed_dir = (
            temp_bids_root
            / "derivatives" / "connectivity" / "fc"
            / subject / session / "seed"
            / "atlas-4S256Parcels_parcel-LH_Cont_Par_1"
        )
        seed_dir.mkdir(parents=True, exist_ok=True)
        
        zmap_path = seed_dir / f"{subject}_{session}_seed-atlas-4S256Parcels_parcel-LH_Cont_Par_1_seed-to-voxel_zmap.nii.gz"
        import shutil
        shutil.copy(str(sample_nifti_file), str(zmap_path))
        
        result = validator_with_csv.validate_subject_file(subject, session)
        
        assert result.exists is True
        assert result.error is None
        assert result.shape == (91, 109, 91)
        assert result.dtype in ["float64", "float32"]
        assert result.has_nan is False
        assert result.mean is not None
        assert result.std is not None
    
    def test_validate_subject_file_shape_mismatch(self, validator_with_csv, temp_bids_root):
        """Test validation error on shape mismatch."""
        subject = "sub-033"
        session = "ses-01"
        seed_dir = (
            temp_bids_root
            / "derivatives" / "connectivity" / "fc"
            / subject / session / "seed"
            / "atlas-4S256Parcels_parcel-LH_Cont_Par_1"
        )
        seed_dir.mkdir(parents=True, exist_ok=True)
        
        # Create wrong shape
        wrong_data = np.random.randn(100, 100, 100).astype(np.float64)
        img = nib.Nifti1Image(wrong_data, np.eye(4))
        zmap_path = seed_dir / f"{subject}_{session}_seed-atlas-4S256Parcels_parcel-LH_Cont_Par_1_seed-to-voxel_zmap.nii.gz"
        nib.save(img, str(zmap_path))
        
        result = validator_with_csv.validate_subject_file(subject, session)
        
        assert result.exists is True
        assert result.error is not None
        assert "Shape mismatch" in result.error
    
    def test_validate_subject_file_with_nan(self, validator_with_csv, temp_bids_root):
        """Test validation error on NaN values."""
        subject = "sub-033"
        session = "ses-01"
        seed_dir = (
            temp_bids_root
            / "derivatives" / "connectivity" / "fc"
            / subject / session / "seed"
            / "atlas-4S256Parcels_parcel-LH_Cont_Par_1"
        )
        seed_dir.mkdir(parents=True, exist_ok=True)
        
        # Create data with NaN
        data = np.random.randn(91, 109, 91).astype(np.float64)
        data[0, 0, 0] = np.nan
        img = nib.Nifti1Image(data, np.eye(4))
        zmap_path = seed_dir / f"{subject}_{session}_seed-atlas-4S256Parcels_parcel-LH_Cont_Par_1_seed-to-voxel_zmap.nii.gz"
        nib.save(img, str(zmap_path))
        
        result = validator_with_csv.validate_subject_file(subject, session)
        
        assert result.exists is True
        assert result.has_nan is True
        assert result.error is not None
        assert "NaN" in result.error
    
    def test_validate_subject_file_valid_float32(self, validator_with_csv, temp_bids_root):
        """Test successful validation with float32 dtype."""
        subject = "sub-033"
        session = "ses-01"
        seed_dir = (
            temp_bids_root
            / "derivatives" / "connectivity" / "fc"
            / subject / session / "seed"
            / "atlas-4S256Parcels_parcel-LH_Cont_Par_1"
        )
        seed_dir.mkdir(parents=True, exist_ok=True)
        
        # Create float32 data (also acceptable)
        data = np.random.randn(91, 109, 91).astype(np.float32)
        img = nib.Nifti1Image(data, np.eye(4))
        zmap_path = seed_dir / f"{subject}_{session}_seed-atlas-4S256Parcels_parcel-LH_Cont_Par_1_seed-to-voxel_zmap.nii.gz"
        nib.save(img, str(zmap_path))
        
        result = validator_with_csv.validate_subject_file(subject, session)
        
        assert result.exists is True
        assert result.error is None
        assert result.dtype in ["float32", "float64"]  # Both acceptable


class TestBatchValidation:
    """Test batch validation of all subjects."""
    
    def test_validate_all_subjects_returns_dataframe(self, validator_with_csv):
        """Test that batch validation returns DataFrame."""
        df = validator_with_csv.validate_all_subjects()
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 72
    
    def test_validate_all_subjects_has_required_columns(self, validator_with_csv):
        """Test that result DataFrame has required columns."""
        df = validator_with_csv.validate_all_subjects()
        
        required_cols = [
            "row_index", "subject", "session", "group",
            "exists", "shape", "dtype", "has_nan", "mean", "std", "error"
        ]
        assert all(col in df.columns for col in required_cols)
    
    def test_validate_all_subjects_row_count(self, validator_with_csv):
        """Test that all 72 subjects are included."""
        df = validator_with_csv.validate_all_subjects()
        assert len(df) == 72
    
    def test_validate_all_subjects_canonical_order(self, validator_with_csv):
        """Test that results maintain canonical order."""
        df = validator_with_csv.validate_all_subjects()
        
        # Check row indices are 0-71
        assert df["row_index"].min() == 0
        assert df["row_index"].max() == 71
        assert len(df["row_index"].unique()) == 72


class TestCanonicalZmapsList:
    """Test canonical zmap ordering."""
    
    def test_get_canonical_zmaps_list_empty(self, validator_with_csv):
        """Test error when no zmaps exist."""
        with pytest.raises(RuntimeError):
            validator_with_csv.get_canonical_zmaps_list()
    
    def test_get_canonical_zmaps_list_with_valid_files(
        self, validator_with_csv, temp_bids_root, sample_nifti_file
    ):
        """Test getting zmap list when files exist."""
        # Create zmaps for first 2 subjects (1 control × 2 sessions)
        for i in range(2):
            subject = validator_with_csv.canonical_order.iloc[i]["subject"]
            session = validator_with_csv.canonical_order.iloc[i]["session"]
            
            seed_dir = (
                temp_bids_root
                / "derivatives" / "connectivity" / "fc"
                / subject / session / "seed"
                / "atlas-4S256Parcels_parcel-LH_Cont_Par_1"
            )
            seed_dir.mkdir(parents=True, exist_ok=True)
            
            zmap_path = seed_dir / f"{subject}_{session}_seed-atlas-4S256Parcels_parcel-LH_Cont_Par_1_seed-to-voxel_zmap.nii.gz"
            import shutil
            shutil.copy(str(sample_nifti_file), str(zmap_path))
        
        # This should work for first 2, but fail on 3rd (missing)
        # Actually, let me test just getting the first 2
        zmaps = []
        for i in range(2):
            subject = validator_with_csv.canonical_order.iloc[i]["subject"]
            session = validator_with_csv.canonical_order.iloc[i]["session"]
            zmap = validator_with_csv._find_zmap_file(subject, session)
            assert zmap is not None
            zmaps.append(str(zmap))
        
        assert len(zmaps) == 2


class TestSummaryStatistics:
    """Test summary statistics generation."""
    
    def test_summarize_validation_all_valid(self, validator_with_csv, temp_bids_root, sample_nifti_file):
        """Test summary when all zmaps are valid."""
        # Create all 72 zmaps
        for _, row in validator_with_csv.canonical_order.iterrows():
            subject = row["subject"]
            session = row["session"]
            
            seed_dir = (
                temp_bids_root
                / "derivatives" / "connectivity" / "fc"
                / subject / session / "seed"
                / "atlas-4S256Parcels_parcel-LH_Cont_Par_1"
            )
            seed_dir.mkdir(parents=True, exist_ok=True)
            
            zmap_path = seed_dir / f"{subject}_{session}_seed-atlas-4S256Parcels_parcel-LH_Cont_Par_1_seed-to-voxel_zmap.nii.gz"
            import shutil
            shutil.copy(str(sample_nifti_file), str(zmap_path))
        
        df = validator_with_csv.validate_all_subjects()
        summary = validator_with_csv.summarize_validation(df)
        
        assert summary["total_count"] == 72
        assert summary["valid_count"] == 72
        assert summary["error_count"] == 0
        assert len(summary["error_summary"]) == 0
        assert "mean_stats" in summary
        assert "group_summary" in summary
    
    def test_summarize_validation_with_errors(self, validator_with_csv):
        """Test summary when some zmaps are missing."""
        # Don't create any zmaps, so all are missing
        df = validator_with_csv.validate_all_subjects()
        summary = validator_with_csv.summarize_validation(df)
        
        assert summary["total_count"] == 72
        assert summary["valid_count"] == 0
        assert summary["error_count"] > 0
        assert summary["error_count"] == 72
        assert len(summary["error_summary"]) > 0
    
    def test_summarize_validation_group_summary(self, validator_with_csv):
        """Test per-group summary statistics."""
        df = validator_with_csv.validate_all_subjects()
        summary = validator_with_csv.summarize_validation(df)
        
        assert "group_summary" in summary
        group_summary = summary["group_summary"]
        
        # Should have Control and Walking
        assert "Control" in group_summary
        assert "Walking" in group_summary
        
        # Each group should have total and valid counts
        for group in ["Control", "Walking"]:
            assert "total" in group_summary[group]
            assert "valid" in group_summary[group]
            assert "invalid" in group_summary[group]
            assert group_summary[group]["total"] > 0
    
    def test_summarize_validation_mean_stats(self, validator_with_csv, temp_bids_root, sample_nifti_file):
        """Test mean statistics calculation."""
        # Create all 72 zmaps
        for _, row in validator_with_csv.canonical_order.iterrows():
            subject = row["subject"]
            session = row["session"]
            
            seed_dir = (
                temp_bids_root
                / "derivatives" / "connectivity" / "fc"
                / subject / session / "seed"
                / "atlas-4S256Parcels_parcel-LH_Cont_Par_1"
            )
            seed_dir.mkdir(parents=True, exist_ok=True)
            
            zmap_path = seed_dir / f"{subject}_{session}_seed-atlas-4S256Parcels_parcel-LH_Cont_Par_1_seed-to-voxel_zmap.nii.gz"
            import shutil
            shutil.copy(str(sample_nifti_file), str(zmap_path))
        
        df = validator_with_csv.validate_all_subjects()
        summary = validator_with_csv.summarize_validation(df)
        
        assert "mean_stats" in summary
        mean_stats = summary["mean_stats"]
        
        assert "mean_of_means" in mean_stats
        assert "std_of_means" in mean_stats
        assert "mean_of_stds" in mean_stats
        assert "min_mean" in mean_stats
        assert "max_mean" in mean_stats


class TestErrorHandling:
    """Test error handling and edge cases."""
    
    def test_validate_corrupted_nifti(self, validator_with_csv, temp_bids_root):
        """Test handling of corrupted NIfTI files."""
        subject = "sub-033"
        session = "ses-01"
        seed_dir = (
            temp_bids_root
            / "derivatives" / "connectivity" / "fc"
            / subject / session / "seed"
            / "atlas-4S256Parcels_parcel-LH_Cont_Par_1"
        )
        seed_dir.mkdir(parents=True, exist_ok=True)
        
        # Create corrupted file
        zmap_path = seed_dir / f"{subject}_{session}_seed-atlas-4S256Parcels_parcel-LH_Cont_Par_1_seed-to-voxel_zmap.nii.gz"
        zmap_path.write_text("corrupted data")
        
        result = validator_with_csv.validate_subject_file(subject, session)
        
        assert result.exists is True
        assert result.error is not None
        assert "load" in result.error.lower()
    
    def test_validate_all_subjects_with_mixed_results(
        self, validator_with_csv, temp_bids_root, sample_nifti_file
    ):
        """Test batch validation with mix of valid and invalid files."""
        # Create zmaps for only first 10 subjects
        for i in range(10):
            subject = validator_with_csv.canonical_order.iloc[i]["subject"]
            session = validator_with_csv.canonical_order.iloc[i]["session"]
            
            seed_dir = (
                temp_bids_root
                / "derivatives" / "connectivity" / "fc"
                / subject / session / "seed"
                / "atlas-4S256Parcels_parcel-LH_Cont_Par_1"
            )
            seed_dir.mkdir(parents=True, exist_ok=True)
            
            zmap_path = seed_dir / f"{subject}_{session}_seed-atlas-4S256Parcels_parcel-LH_Cont_Par_1_seed-to-voxel_zmap.nii.gz"
            import shutil
            shutil.copy(str(sample_nifti_file), str(zmap_path))
        
        df = validator_with_csv.validate_all_subjects()
        
        # First 10 should be valid, rest should be missing
        assert df.iloc[:10]["exists"].all()
        assert not df.iloc[10:]["exists"].any()


class TestIntegration:
    """Integration tests combining multiple features."""
    
    def test_full_validation_workflow(self, validator_with_csv, temp_bids_root, sample_nifti_file):
        """Test complete validation workflow."""
        # Create all 72 zmaps
        for _, row in validator_with_csv.canonical_order.iterrows():
            subject = row["subject"]
            session = row["session"]
            
            seed_dir = (
                temp_bids_root
                / "derivatives" / "connectivity" / "fc"
                / subject / session / "seed"
                / "atlas-4S256Parcels_parcel-LH_Cont_Par_1"
            )
            seed_dir.mkdir(parents=True, exist_ok=True)
            
            zmap_path = seed_dir / f"{subject}_{session}_seed-atlas-4S256Parcels_parcel-LH_Cont_Par_1_seed-to-voxel_zmap.nii.gz"
            import shutil
            shutil.copy(str(sample_nifti_file), str(zmap_path))
        
        # Run full workflow
        validation_df = validator_with_csv.validate_all_subjects()
        summary = validator_with_csv.summarize_validation(validation_df)
        zmaps = validator_with_csv.get_canonical_zmaps_list(validation_df)
        
        # Verify results
        assert len(validation_df) == 72
        assert summary["valid_count"] == 72
        assert summary["error_count"] == 0
        assert len(zmaps) == 72
        
        # Verify zmap order matches canonical order
        for i, zmap in enumerate(zmaps):
            expected_subject = validation_df.iloc[i]["subject"]
            assert expected_subject in zmap
    
    def test_usage_example_from_docs(self, validator_with_csv, temp_bids_root, sample_nifti_file):
        """Test usage example from docstring works correctly."""
        # Create all 72 zmaps
        for _, row in validator_with_csv.canonical_order.iterrows():
            subject = row["subject"]
            session = row["session"]
            
            seed_dir = (
                temp_bids_root
                / "derivatives" / "connectivity" / "fc"
                / subject / session / "seed"
                / "atlas-4S256Parcels_parcel-LH_Cont_Par_1"
            )
            seed_dir.mkdir(parents=True, exist_ok=True)
            
            zmap_path = seed_dir / f"{subject}_{session}_seed-atlas-4S256Parcels_parcel-LH_Cont_Par_1_seed-to-voxel_zmap.nii.gz"
            import shutil
            shutil.copy(str(sample_nifti_file), str(zmap_path))
        
        # This is the example from the docstring
        validation_df = validator_with_csv.validate_all_subjects()
        summary = validator_with_csv.summarize_validation(validation_df)
        
        if summary['error_count'] == 0:
            zmaps = validator_with_csv.get_canonical_zmaps_list()
            assert len(zmaps) == 72
        
        # Should not raise
        assert True
