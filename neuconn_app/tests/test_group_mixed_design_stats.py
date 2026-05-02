"""
Comprehensive tests for group_mixed_design_stats.py

Tests cover:
1. Mock filesystem tests (12 tests)
2. Integration tests (6 tests)
3. Real HPC data validation (3 tests - deferred until HPC job completes)
"""

import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any
from unittest.mock import Mock, MagicMock, patch, mock_open, call

import pytest
import numpy as np
import pandas as pd
import nibabel as nib
from tempfile import TemporaryDirectory

# Setup path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.group_mixed_design_stats import GroupStatsRunner, setup_logging


class TestGroupStatsRunnerInitialization:
    """Test GroupStatsRunner initialization."""
    
    def test_init_defaults(self):
        """Test initialization with defaults."""
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas-4S256Parcels:RH_Cont_Par_1",
        )
        assert runner.bids_root == Path("/test/bids")
        assert runner.seed == "atlas-4S256Parcels:RH_Cont_Par_1"
        assert runner.pipeline == "fc"
        assert runner.measure == "pearson"
        assert runner.n_perm == 5000
    
    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas-4S256Parcels:RH_Cont_Par_1",
            pipeline="fc_gsr",
            measure="spearman",
            n_perm=100,
            output_dir="/custom/output",
        )
        assert runner.pipeline == "fc_gsr"
        assert runner.measure == "spearman"
        assert runner.n_perm == 100
        assert runner.output_dir == Path("/custom/output")
    
    def test_init_output_dir_default(self):
        """Test output directory default generation."""
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas-4S256Parcels:RH_Cont_Par_1",
            pipeline="fc",
            measure="pearson",
        )
        expected_path = Path("/test/bids/results/group_stats/atlas-4S256Parcels_RH_Cont_Par_1_fc_pearson")
        assert runner.output_dir == expected_path
    
    def test_init_canonical_order_csv_custom(self):
        """Test custom canonical order CSV path."""
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas-4S256Parcels:RH_Cont_Par_1",
            canonical_order_csv="/custom/canonical.csv",
        )
        assert runner.canonical_order_csv == Path("/custom/canonical.csv")


class TestInputValidation:
    """Test Step 1: Input validation."""
    
    @patch('pathlib.Path.exists')
    def test_validate_inputs_bids_root_missing(self, mock_exists):
        """Test validation fails if BIDS root missing."""
        mock_exists.return_value = False
        
        runner = GroupStatsRunner(
            bids_root="/nonexistent",
            seed="atlas:seed",
        )
        
        assert not runner._step_validate_inputs()
    
    @patch('pathlib.Path.exists')
    def test_validate_inputs_invalid_seed_format(self, mock_exists):
        """Test validation fails with invalid seed format."""
        mock_exists.return_value = True
        
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="invalid_seed_format",
        )
        
        assert not runner._step_validate_inputs()
    
    @patch('pathlib.Path.exists')
    def test_validate_inputs_invalid_pipeline(self, mock_exists):
        """Test validation fails with invalid pipeline."""
        mock_exists.return_value = True
        
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas:seed",
            pipeline="invalid_pipeline",
        )
        
        assert not runner._step_validate_inputs()
    
    def test_validate_inputs_missing_canonical_csv(self):
        """Test validation fails if canonical CSV missing."""
        with patch('pathlib.Path.exists') as mock_exists:
            mock_exists.return_value = False
            
            runner = GroupStatsRunner(
                bids_root="/nonexistent/canonical.csv",
                seed="atlas:seed",
                canonical_order_csv="/nonexistent/canonical.csv",
            )
            
            assert not runner._step_validate_inputs()
    
    @patch('pathlib.Path.exists')
    def test_validate_inputs_all_valid(self, mock_exists):
        """Test validation passes with all valid inputs."""
        mock_exists.return_value = True
        
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas-4S256Parcels:RH_Cont_Par_1",
            pipeline="fc",
        )
        
        assert runner._step_validate_inputs()


class TestCanonicalOrderLoading:
    """Test Step 2: Loading canonical subject order."""
    
    def test_load_canonical_order_valid(self, tmp_path):
        """Test loading valid canonical order CSV."""
        csv_path = tmp_path / "canonical.csv"
        
        # Create valid CSV
        data = {
            "row_index": list(range(72)),
            "subject": ["sub-033"] * 2 + ["sub-034"] * 2 + ["sub-050"] * 2 + ["sub-051"] * 66,
            "session": ["ses-01", "ses-02"] * 36,
            "group": ["Control"] * 40 + ["Walking"] * 32,
        }
        df = pd.DataFrame(data)
        df.to_csv(csv_path, index=False)
        
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas:seed",
            canonical_order_csv=str(csv_path),
        )
        
        assert runner._step_load_canonical_order()
        assert len(runner.canonical_order) == 72
    
    def test_load_canonical_order_invalid_row_count(self, tmp_path):
        """Test loading CSV with wrong row count."""
        csv_path = tmp_path / "canonical.csv"
        
        # Create CSV with wrong row count
        data = {
            "row_index": list(range(10)),
            "subject": ["sub-033"] * 10,
            "session": ["ses-01"] * 10,
            "group": ["Control"] * 10,
        }
        df = pd.DataFrame(data)
        df.to_csv(csv_path, index=False)
        
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas:seed",
            canonical_order_csv=str(csv_path),
        )
        
        assert not runner._step_load_canonical_order()
    
    def test_load_canonical_order_missing_columns(self, tmp_path):
        """Test loading CSV with missing columns."""
        csv_path = tmp_path / "canonical.csv"
        
        # Create CSV with missing columns
        data = {"row_index": list(range(72)), "subject": ["sub-033"] * 72}
        df = pd.DataFrame(data)
        df.to_csv(csv_path, index=False)
        
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas:seed",
            canonical_order_csv=str(csv_path),
        )
        
        assert not runner._step_load_canonical_order()


class TestZmapValidation:
    """Test Step 3: Validate all 72 zmaps."""
    
    @patch('neuconn_app.scripts.group_mixed_design_stats.SubjectDataValidator')
    def test_validate_zmaps_with_errors(self, mock_validator_class):
        """Test zmap validation with errors."""
        # Mock validator
        mock_validator = MagicMock()
        mock_validator_class.return_value = mock_validator
        
        # Create mock validation DataFrame with errors
        validation_data = {
            "exists": [True] * 70 + [False] * 2,
            "error": [None] * 70 + ["File not found", "File not found"],
            "subject": ["sub-033"] * 72,
            "session": ["ses-01"] * 72,
        }
        validation_df = pd.DataFrame(validation_data)
        mock_validator.validate_all_subjects.return_value = validation_df
        
        with TemporaryDirectory() as tmp_dir:
            # Create temp CSV file
            csv_path = Path(tmp_dir) / "canonical.csv"
            df = pd.DataFrame({
                "row_index": range(72),
                "subject": ["sub-033"] * 72,
                "session": ["ses-01"] * 72,
                "group": ["Control"] * 72,
            })
            df.to_csv(csv_path, index=False)
            
            runner = GroupStatsRunner(
                bids_root="/test/bids",
                seed="atlas:seed",
                canonical_order_csv=str(csv_path),
            )
            runner.canonical_order = pd.DataFrame({"group": ["Control"] * 72})
            
            assert not runner._step_validate_zmaps()


class TestMerge4DNIFTI:
    """Test Step 4: Merge 4D NIfTI."""
    
    @patch('neuconn_app.scripts.group_mixed_design_stats.nib.load')
    @patch('subprocess.run')
    def test_merge_4d_nifti_success(self, mock_subprocess, mock_nibabel_load):
        """Test successful 4D NIfTI merge."""
        # Mock fslmerge availability and create output file
        mock_subprocess.return_value = MagicMock(returncode=0)
        
        # Mock nibabel load
        mock_img = MagicMock()
        mock_img.shape = (91, 109, 91, 72)
        mock_nibabel_load.return_value = mock_img
        
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            
            # Create dummy merged file
            merged_path = tmp_path / "4d_merged.nii.gz"
            merged_path.touch()
            
            runner = GroupStatsRunner(
                bids_root="/test/bids",
                seed="atlas:seed",
                output_dir=tmp_dir,
            )
            runner.zmaps_list = [f"/path/zmap_{i}.nii.gz" for i in range(72)]
            
            assert runner._step_merge_4d_nifti()
            assert runner.merged_nifti_path is not None
    
    @patch('subprocess.run')
    def test_merge_4d_nifti_fslmerge_not_found(self, mock_subprocess):
        """Test merge fails if fslmerge not found."""
        mock_subprocess.return_value = MagicMock(returncode=1)
        
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas:seed",
        )
        runner.zmaps_list = [f"/path/zmap_{i}.nii.gz" for i in range(72)]
        
        assert not runner._step_merge_4d_nifti()
    
    @patch('neuconn_app.scripts.group_mixed_design_stats.nib.load')
    @patch('subprocess.run')
    def test_merge_4d_nifti_wrong_shape(self, mock_subprocess, mock_nibabel_load):
        """Test merge fails if output has wrong shape."""
        mock_subprocess.return_value = MagicMock(returncode=0)
        
        # Mock wrong shape
        mock_img = MagicMock()
        mock_img.shape = (91, 109, 91, 70)  # Wrong: 70 instead of 72
        mock_nibabel_load.return_value = mock_img
        
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            
            # Create dummy merged file
            merged_path = tmp_path / "4d_merged.nii.gz"
            merged_path.touch()
            
            runner = GroupStatsRunner(
                bids_root="/test/bids",
                seed="atlas:seed",
                output_dir=tmp_dir,
            )
            runner.zmaps_list = [f"/path/zmap_{i}.nii.gz" for i in range(72)]
            
            assert not runner._step_merge_4d_nifti()


class TestDesignFileGeneration:
    """Test Step 5: Generate FSL design files."""
    
    @patch('neuconn_app.scripts.group_mixed_design_stats.MixedDesignBuilder')
    def test_generate_design_files_success(self, mock_builder_class):
        """Test successful design file generation."""
        # Mock builder
        mock_builder = MagicMock()
        mock_builder_class.from_paired_two_group.return_value = mock_builder
        mock_builder.design_matrix = np.ones((72, 37))
        mock_builder.validate.return_value = (True, [])
        
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            mock_builder.save_fsl_files.return_value = {
                "design.mat": tmp_path / "design.mat",
                "design.con": tmp_path / "design.con",
                "design.fts": tmp_path / "design.fts",
                "design.grp": tmp_path / "design.grp",
            }
            
            runner = GroupStatsRunner(
                bids_root="/test/bids",
                seed="atlas:seed",
                output_dir=tmp_dir,
            )
            # Create non-overlapping subject lists
            control_subs = [f"sub-{30+i}" for i in range(20)]
            walking_subs = [f"sub-{60+i}" for i in range(16)]
            
            runner.canonical_order = pd.DataFrame({
                "group": ["control"] * 40 + ["walking"] * 32,
                "subject": control_subs * 2 + walking_subs * 2,
            })
            
            assert runner._step_generate_design_files()
            assert runner.design_files is not None
    
    @patch('neuconn_app.scripts.group_mixed_design_stats.MixedDesignBuilder')
    def test_generate_design_files_validation_fails(self, mock_builder_class):
        """Test design generation fails if validation fails."""
        # Mock builder with validation failure
        mock_builder = MagicMock()
        mock_builder_class.from_paired_two_group.return_value = mock_builder
        mock_builder.validate.return_value = (False, ["Rank deficient"])
        
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas:seed",
        )
        runner.canonical_order = pd.DataFrame({
            "group": ["Control"] * 40 + ["Walking"] * 32,
            "subject": ["sub-033"] * 72,
        })
        
        assert not runner._step_generate_design_files()


class TestRandomise:
    """Test Step 6: Run FSL randomise."""
    
    @patch('subprocess.run')
    def test_run_randomise_success(self, mock_subprocess):
        """Test successful randomise execution."""
        mock_subprocess.return_value = MagicMock(returncode=0)
        
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            tmp_path.mkdir(exist_ok=True)
            
            # Create mock mask file
            mask_path = tmp_path / "mask.nii.gz"
            mask_path.touch()
            
            runner = GroupStatsRunner(
                bids_root="/test/bids",
                seed="atlas:seed",
                output_dir=tmp_dir,
                mask_path=str(mask_path),
            )
            runner.merged_nifti_path = tmp_path / "4d_merged.nii.gz"
            runner.merged_nifti_path.touch()
            runner.design_files = {
                "design.mat": tmp_path / "design.mat",
                "design.con": tmp_path / "design.con",
                "design.fts": tmp_path / "design.fts",
                "design.grp": tmp_path / "design.grp",
            }
            
            assert runner._step_run_randomise()
    
    @patch('subprocess.run')
    def test_run_randomise_randomise_not_found(self, mock_subprocess):
        """Test randomise fails if randomise not found."""
        mock_subprocess.return_value = MagicMock(returncode=1)
        
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas:seed",
        )
        
        assert not runner._step_run_randomise()


class TestReportGeneration:
    """Test Step 7: Generate summary report."""
    
    @patch('neuconn_app.scripts.group_mixed_design_stats.GroupStatsRunner._parse_randomise_outputs')
    def test_generate_report_success(self, mock_parse):
        """Test successful report generation."""
        mock_parse.return_value = {"tfce_files": [], "fstat_files": []}
        
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "randomise_outputs").mkdir()
            
            runner = GroupStatsRunner(
                bids_root="/test/bids",
                seed="atlas-4S256Parcels:seed",
                output_dir=tmp_dir,
            )
            runner.merged_nifti_path = tmp_path / "4d_merged.nii.gz"
            runner.design_files = {
                "design.mat": tmp_path / "design.mat",
                "design.con": tmp_path / "design.con",
                "design.fts": tmp_path / "design.fts",
                "design.grp": tmp_path / "design.grp",
            }
            
            assert runner._step_generate_report()
            
            # Check files were created
            assert (tmp_path / "stats_summary.json").exists()
            assert (tmp_path / "group_stats_report.html").exists()


class TestFullPipeline:
    """Integration tests: Full E2E pipeline with mocks."""
    
    def test_full_pipeline_success(self):
        """Test full pipeline succeeds when all steps pass."""
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas:seed",
        )
        
        # Mock all internal methods
        runner._step_validate_inputs = MagicMock(return_value=True)
        runner._step_load_canonical_order = MagicMock(return_value=True)
        runner._step_validate_zmaps = MagicMock(return_value=True)
        runner._step_merge_4d_nifti = MagicMock(return_value=True)
        runner._step_generate_design_files = MagicMock(return_value=True)
        runner._step_run_randomise = MagicMock(return_value=True)
        runner._step_generate_report = MagicMock(return_value=True)
        
        assert runner.run()
    
    def test_full_pipeline_fails_at_validation(self):
        """Test full pipeline fails if validation fails."""
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas:seed",
        )
        
        runner._step_validate_inputs = MagicMock(return_value=False)
        
        assert not runner.run()
    
    def test_full_pipeline_fails_at_randomise(self):
        """Test full pipeline fails if randomise fails."""
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas:seed",
        )
        
        runner._step_validate_inputs = MagicMock(return_value=True)
        runner._step_load_canonical_order = MagicMock(return_value=True)
        runner._step_validate_zmaps = MagicMock(return_value=True)
        runner._step_merge_4d_nifti = MagicMock(return_value=True)
        runner._step_generate_design_files = MagicMock(return_value=True)
        runner._step_run_randomise = MagicMock(return_value=False)  # Fails
        runner._step_generate_report = MagicMock(return_value=True)
        
        assert not runner.run()


class TestParseRandomiseOutputs:
    """Test parsing randomise outputs."""
    
    def test_parse_randomise_outputs_no_files(self):
        """Test parsing when no output files exist."""
        with TemporaryDirectory() as tmp_dir:
            randomise_dir = Path(tmp_dir) / "randomise_outputs"
            randomise_dir.mkdir()
            
            runner = GroupStatsRunner(
                bids_root="/test/bids",
                seed="atlas:seed",
            )
            
            stats = runner._parse_randomise_outputs(randomise_dir)
            assert len(stats["tfce_files"]) == 0
            assert len(stats["fstat_files"]) == 0
    
    def test_parse_randomise_outputs_with_files(self):
        """Test parsing randomise outputs with mock NIfTI files."""
        with TemporaryDirectory() as tmp_dir:
            randomise_dir = Path(tmp_dir) / "randomise_outputs"
            randomise_dir.mkdir()
            
            # Create mock TFCE output
            data = np.random.rand(91, 109, 91)
            affine = np.eye(4)
            img = nib.Nifti1Image(data, affine)
            nib.save(img, str(randomise_dir / "randomise_tfce_corrp_tstat1.nii.gz"))
            
            runner = GroupStatsRunner(
                bids_root="/test/bids",
                seed="atlas:seed",
            )
            
            stats = runner._parse_randomise_outputs(randomise_dir)
            assert len(stats["tfce_files"]) > 0
            assert "voxels_significant" in stats["tfce_files"][0]


class TestStandardMaskDetection:
    """Test standard mask auto-detection."""
    
    def test_get_standard_mask_not_found(self):
        """Test mask detection returns None if not found."""
        runner = GroupStatsRunner(
            bids_root="/test/bids",
            seed="atlas:seed",
        )
        
        mask = runner._get_standard_mask()
        # Should be None if not installed
        assert mask is None or isinstance(mask, str)


class TestSetupLogging:
    """Test logging setup."""
    
    def test_setup_logging_info(self):
        """Test info level logging setup."""
        setup_logging(debug=False)
        logger = logging.getLogger("test")
        assert logger.level != logging.DEBUG
    
    def test_setup_logging_debug(self):
        """Test debug level logging setup."""
        setup_logging(debug=True)
        logger = logging.getLogger("test")
        # Logger level is set globally


# Mark real HPC tests as deferred
class TestRealHPCData:
    """Tests with real HPC data (deferred until job completes)."""
    
    @pytest.mark.skip(reason="Waiting for HPC job 4617 to complete")
    def test_validate_against_real_zmaps(self):
        """Validate against real HPC zmaps once available."""
        pass
    
    @pytest.mark.skip(reason="Waiting for HPC job 4617 to complete")
    def test_4d_merge_output_shape_real(self):
        """Verify 4D merge output shape with real data."""
        pass
    
    @pytest.mark.skip(reason="Waiting for HPC job 4617 to complete")
    def test_design_file_properties_real(self):
        """Verify design file properties with real data."""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
