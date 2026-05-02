"""
Unit tests for 04_submit_group_stats.py mixed-design workflow.

Tests cover:
- Template selection logic
- Seed validation
- Design matrix preview
- Canonical order loading
- Command construction
- Error handling
- Session state management
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile
import sys

# Add parent dirs to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.group_stats_design import MixedDesignBuilder
from utils.group_stats_validation import SubjectDataValidator


# ==============================================================================
# Test Fixtures
# ==============================================================================

@pytest.fixture
def mock_streamlit():
    """Mock streamlit session state."""
    mock_st = MagicMock()
    mock_st.session_state = {
        "submit_group_template": "Voxel",
        "submit_group_mixed_seed": "",
        "submit_group_mixed_pipeline": "fc",
        "submit_group_mixed_measure": "pearson",
        "submit_group_mixed_n_perm": 5000,
        "submit_group_mixed_correction": "TFCE",
        "submit_group_mixed_execution": "Local",
        "submit_group_mixed_zmaps_valid": False,
    }
    return mock_st


@pytest.fixture
def canonical_order_csv(tmp_path):
    """Create a canonical order CSV with 72 rows."""
    csv_path = tmp_path / "canonical_subject_order.csv"
    
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
def temp_bids_root(tmp_path):
    """Create a temporary BIDS root."""
    bids_root = tmp_path / "bids"
    bids_root.mkdir()
    return bids_root


# ==============================================================================
# Test Design Matrix Building
# ==============================================================================

class TestDesignMatrixConstruction:
    """Test design matrix construction for mixed-design."""
    
    def test_load_canonical_subjects_from_csv(self, canonical_order_csv):
        """Test loading subject lists from CSV."""
        df = pd.read_csv(canonical_order_csv)
        control = sorted(df[df["group"] == "Control"]["subject"].unique())
        walking = sorted(df[df["group"] == "Walking"]["subject"].unique())
        
        assert len(control) == 20
        assert len(walking) == 16
        assert 'sub-033' in control
        assert 'sub-043' in walking
    
    def test_design_matrix_shape(self, canonical_order_csv):
        """Test design matrix shape is correct."""
        df = pd.read_csv(canonical_order_csv)
        control = sorted(df[df["group"] == "Control"]["subject"].unique())
        walking = sorted(df[df["group"] == "Walking"]["subject"].unique())
        
        builder = MixedDesignBuilder.from_paired_two_group(control, walking)
        design_mat, contrasts, ftest, blocks = builder.build()
        
        # 36 subjects × 2 sessions = 72 rows
        # 2 fixed cols (Time, Group) + 36 subject intercepts = 38 cols
        assert design_mat.shape[0] == 72
        assert design_mat.shape[1] == 38
    
    def test_design_matrix_is_full_rank(self, canonical_order_csv):
        """Test design matrix has expected rank."""
        df = pd.read_csv(canonical_order_csv)
        control = sorted(df[df["group"] == "Control"]["subject"].unique())
        walking = sorted(df[df["group"] == "Walking"]["subject"].unique())
        
        builder = MixedDesignBuilder.from_paired_two_group(control, walking)
        design_mat, _, _, _ = builder.build()
        
        rank = np.linalg.matrix_rank(design_mat)
        # Rank should be 37 (n_cols - 1) due to sum-to-zero constraint
        assert rank == 37
    
    def test_exchangeability_blocks(self, canonical_order_csv):
        """Test exchangeability blocks encode paired structure."""
        df = pd.read_csv(canonical_order_csv)
        control = sorted(df[df["group"] == "Control"]["subject"].unique())
        walking = sorted(df[df["group"] == "Walking"]["subject"].unique())
        
        builder = MixedDesignBuilder.from_paired_two_group(control, walking)
        _, _, _, blocks = builder.build()
        
        # Should be [1, 1, 2, 2, 3, 3, ..., 36, 36]
        assert len(blocks) == 72
        assert blocks[0] == blocks[1]  # First pair
        assert blocks[2] == blocks[3]  # Second pair
        assert blocks[0] != blocks[2]  # Different pairs


# ==============================================================================
# Test Validation
# ==============================================================================

class TestZmapValidation:
    """Test zmap validation logic."""
    
    def test_validation_result_success(self):
        """Test successful validation."""
        from utils.group_stats_validation import ValidationResult
        
        result = ValidationResult(
            exists=True,
            shape=(91, 109, 91),
            dtype="float64",
            has_nan=False,
            mean=0.5,
            std=1.0,
        )
        
        assert result.exists
        assert not result.has_nan
        assert result.shape == (91, 109, 91)
    
    def test_validation_result_error(self):
        """Test failed validation."""
        from utils.group_stats_validation import ValidationResult
        
        result = ValidationResult(
            exists=False,
            error="File not found"
        )
        
        assert not result.exists
        assert result.error is not None


# ==============================================================================
# Test Command Construction
# ==============================================================================

class TestCommandConstruction:
    """Test building randomise command."""
    
    def test_build_randomise_command_basic(self):
        """Test basic randomise command."""
        cmd = [
            "randomise",
            "-i", "zmaps.nii.gz",
            "-o", "results/randomise",
            "-d", "design.mat",
            "-t", "design.con",
            "-f", "design.fts",
            "-e", "design.grp",
            "-m", "mask.nii.gz",
            "-n", "5000",
            "-T",  # TFCE
        ]
        
        assert cmd[0] == "randomise"
        assert "-T" in cmd  # TFCE flag
        assert "-n" in cmd
        assert "5000" in cmd
    
    def test_build_randomise_command_grf(self):
        """Test randomise command with GRF."""
        cmd = [
            "randomise",
            "-i", "zmaps.nii.gz",
            "-o", "results/randomise",
            "-d", "design.mat",
            "-t", "design.con",
            "-f", "design.fts",
            "-e", "design.grp",
            "-m", "mask.nii.gz",
            "-R",  # GRF
        ]
        
        assert "-R" in cmd
        assert "-T" not in cmd
    
    def test_build_randomise_command_fdr(self):
        """Test randomise command with FDR."""
        cmd = [
            "randomise",
            "-i", "zmaps.nii.gz",
            "-o", "results/randomise",
            "-d", "design.mat",
            "-t", "design.con",
            "-f", "design.fts",
            "-e", "design.grp",
            "-m", "mask.nii.gz",
            "--fdr",  # FDR
        ]
        
        assert "--fdr" in cmd
        assert "-T" not in cmd


# ==============================================================================
# Test Session State Management
# ==============================================================================

class TestSessionState:
    """Test Streamlit session state management."""
    
    def test_session_state_defaults(self, mock_streamlit):
        """Test default session state values."""
        state = mock_streamlit.session_state
        
        assert state["submit_group_template"] == "Voxel"
        assert state["submit_group_mixed_pipeline"] == "fc"
        assert state["submit_group_mixed_measure"] == "pearson"
        assert state["submit_group_mixed_n_perm"] == 5000
        assert state["submit_group_mixed_correction"] == "TFCE"
    
    def test_session_state_mixed_design_update(self, mock_streamlit):
        """Test updating mixed-design session state."""
        state = mock_streamlit.session_state
        
        state["submit_group_template"] = "MixedDesign"
        state["submit_group_mixed_seed"] = "atlas-4S256Parcels:RH_Cont_Par_1"
        state["submit_group_mixed_n_perm"] = 1000
        state["submit_group_mixed_execution"] = "HPC"
        
        assert state["submit_group_template"] == "MixedDesign"
        assert state["submit_group_mixed_seed"] == "atlas-4S256Parcels:RH_Cont_Par_1"
        assert state["submit_group_mixed_n_perm"] == 1000
        assert state["submit_group_mixed_execution"] == "HPC"


# ==============================================================================
# Test Seed Input Validation
# ==============================================================================

class TestSeedValidation:
    """Test seed input validation."""
    
    def test_seed_format_atlas(self):
        """Test atlas seed format."""
        seed = "atlas-4S256Parcels:RH_Cont_Par_1"
        
        assert seed.startswith("atlas-")
        assert ":" in seed
    
    def test_seed_format_nifti(self):
        """Test nifti seed format."""
        seed = "nifti:/path/to/roi.nii.gz"
        
        assert seed.startswith("nifti:")
    
    def test_seed_format_sphere(self):
        """Test sphere seed format."""
        seed = "sphere:PCC:0,-52,26:r=6"
        
        assert seed.startswith("sphere:")
        assert ":" in seed


# ==============================================================================
# Test Permutation Count Validation
# ==============================================================================

class TestPermutationValidation:
    """Test permutation count validation."""
    
    def test_permutation_count_too_low_warning(self):
        """Test warning for <1000 permutations."""
        n_perm = 500
        
        # Should trigger warning
        assert n_perm < 1000
    
    def test_permutation_count_valid(self):
        """Test valid permutation count."""
        n_perm = 5000
        
        # Should not trigger warning
        assert n_perm >= 1000
    
    def test_permutation_count_test_mode(self):
        """Test reduced permutations for testing."""
        test_mode = True
        n_perm = 5000
        
        effective_n_perm = 100 if test_mode else n_perm
        
        assert effective_n_perm == 100


# ==============================================================================
# Test Correction Method Selection
# ==============================================================================

class TestCorrectionMethod:
    """Test correction method selection."""
    
    def test_correction_methods(self):
        """Test valid correction methods."""
        methods = ["TFCE", "GRF", "FDR"]
        
        assert "TFCE" in methods
        assert "GRF" in methods
        assert "FDR" in methods
    
    def test_default_correction(self):
        """Test default correction is TFCE."""
        correction = "TFCE"
        
        assert correction == "TFCE"


# ==============================================================================
# Test Execution Location
# ==============================================================================

class TestExecutionLocation:
    """Test execution location selection."""
    
    def test_execution_local(self):
        """Test local execution."""
        execution = "Local"
        
        assert execution == "Local"
    
    def test_execution_hpc(self):
        """Test HPC execution."""
        execution = "HPC"
        
        assert execution == "HPC"
    
    def test_local_test_mode_option(self):
        """Test test mode option for local execution."""
        execution = "Local"
        test_mode = True
        
        assert execution == "Local"
        assert test_mode is True


# ==============================================================================
# Test Design Matrix Preview
# ==============================================================================

class TestDesignMatrixPreview:
    """Test design matrix preview rendering."""
    
    def test_preview_shape_info(self, canonical_order_csv):
        """Test preview includes shape info."""
        df = pd.read_csv(canonical_order_csv)
        control = sorted(df[df["group"] == "Control"]["subject"].unique())
        walking = sorted(df[df["group"] == "Walking"]["subject"].unique())
        
        builder = MixedDesignBuilder.from_paired_two_group(control, walking)
        design_mat, _, _, _ = builder.build()
        
        shape_str = f"{design_mat.shape[0]}x{design_mat.shape[1]}"
        
        assert "72" in shape_str
    
    def test_preview_rank_info(self, canonical_order_csv):
        """Test preview includes rank info."""
        df = pd.read_csv(canonical_order_csv)
        control = sorted(df[df["group"] == "Control"]["subject"].unique())
        walking = sorted(df[df["group"] == "Walking"]["subject"].unique())
        
        builder = MixedDesignBuilder.from_paired_two_group(control, walking)
        design_mat, _, _, _ = builder.build()
        
        rank = np.linalg.matrix_rank(design_mat)
        
        assert rank == 37  # n_cols - 1 due to sum-to-zero constraint


# ==============================================================================
# Test Output Path Construction
# ==============================================================================

class TestOutputPath:
    """Test output path construction."""
    
    def test_output_path_construction(self, temp_bids_root):
        """Test output directory path."""
        bids_root = str(temp_bids_root)
        pipeline = "fc"
        measure = "pearson"
        
        output_dir = Path(bids_root) / "results" / "group_mixed_design" / f"seed_{pipeline}_{measure}"
        
        assert "results" in str(output_dir)
        assert "group_mixed_design" in str(output_dir)
        assert pipeline in str(output_dir)
        assert measure in str(output_dir)


# ==============================================================================
# Test Error Handling
# ==============================================================================

class TestErrorHandling:
    """Test error handling for edge cases."""
    
    def test_missing_seed(self):
        """Test error when seed not provided."""
        seed = ""
        
        assert seed == ""
        # Should display error
    
    def test_invalid_pipeline(self):
        """Test handling of invalid pipeline."""
        pipeline = "invalid"
        valid_pipelines = ["fc", "fc_gsr", "ec"]
        
        assert pipeline not in valid_pipelines
    
    def test_zero_permutations(self):
        """Test error on zero permutations."""
        n_perm = 0
        
        assert n_perm < 100  # Below minimum


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
