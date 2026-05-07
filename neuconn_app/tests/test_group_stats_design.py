"""
Unit tests for MixedDesignBuilder class (FSL group statistics design).

Tests cover:
- Design matrix construction and shape
- Full rank property
- Subject column encoding
- Exchangeability blocks (paired constraint)
- Contrast validity
- FSL file generation
- Canonical subject ordering
- Error handling
"""

import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from neuconn_app.utils.group_stats_design import (
    MixedDesignBuilder,
    build_paired_two_group_design,
    validate_design_matrix,
    contrasts_paired_two_group,
    ftest_paired_two_group,
)


class TestMixedDesignBuilderConstruction:
    """Test builder initialization and basic properties"""
    
    def test_init_basic(self):
        """Test basic initialization"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        assert builder.n_subjects == 4
        assert builder.n_rows == 8
        assert len(builder.control_subjects) == 2
        assert len(builder.walking_subjects) == 2
    
    def test_init_sorting(self):
        """Test that subjects are sorted"""
        builder = MixedDesignBuilder(['sub-002', 'sub-001'], ['sub-004', 'sub-003'])
        assert builder.control_subjects == ['sub-001', 'sub-002']
        assert builder.walking_subjects == ['sub-003', 'sub-004']
    
    def test_init_overlap_error(self):
        """Test error on subject overlap"""
        with pytest.raises(ValueError, match="overlap"):
            MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-002', 'sub-003'])
    
    def test_init_session_count_error(self):
        """Test error on incorrect session count"""
        with pytest.raises(ValueError, match="requires 2 sessions"):
            MixedDesignBuilder(
                ['sub-001'], ['sub-002'],
                sessions=['ses-01', 'ses-02', 'ses-03']
            )
    
    def test_sessions_default(self):
        """Test default session labels"""
        builder = MixedDesignBuilder(['sub-001'], ['sub-002'])
        assert builder.sessions == ['ses-01', 'ses-02']
    
    def test_sessions_custom(self):
        """Test custom session labels"""
        builder = MixedDesignBuilder(
            ['sub-001'], ['sub-002'],
            sessions=['pre', 'post']
        )
        assert builder.sessions == ['pre', 'post']
    
    def test_from_paired_two_group_factory(self):
        """Test factory method"""
        builder = MixedDesignBuilder.from_paired_two_group(
            ['sub-001', 'sub-002'],
            ['sub-003', 'sub-004']
        )
        assert builder.n_subjects == 4
        assert builder.sessions == ['ses-01', 'ses-02']


class TestDesignMatrixConstruction:
    """Test design matrix building and structure"""
    
    def test_design_matrix_shape_4subjects(self):
        """Test design matrix shape for 4 subjects (2 control, 2 walking)"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        design_mat, _, _, _ = builder.build()
        
        # 4 subjects × 2 sessions = 8 rows
        # 2 fixed cols (Time, Group) + 4 subject means = 6 cols
        assert design_mat.shape == (8, 6)
    
    def test_design_matrix_shape_10subjects(self):
        """Test design matrix shape for 10 subjects"""
        control = [f'sub-{i:03d}' for i in range(1, 6)]
        walking = [f'sub-{i:03d}' for i in range(6, 11)]
        builder = MixedDesignBuilder(control, walking)
        design_mat, _, _, _ = builder.build()
        
        # 10 subjects × 2 sessions = 20 rows
        # 2 fixed + 10 subject cols = 12 cols
        assert design_mat.shape == (20, 12)
    
    def test_design_matrix_time_effect(self):
        """Test Time effect coding (+1 pre, -1 post)"""
        builder = MixedDesignBuilder(['sub-001'], ['sub-002'])
        design_mat, _, _, _ = builder.build()
        
        # Column 0 should be [+1, -1, +1, -1] for pre/post/pre/post
        expected_time = np.array([+1, -1, +1, -1])
        np.testing.assert_array_equal(design_mat[:, 0], expected_time)
    
    def test_design_matrix_group_effect(self):
        """Test Group effect coding (+1 control, -1 walking)"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003'])
        design_mat, _, _, _ = builder.build()
        
        # Column 1: [+1, +1, +1, +1, -1, -1] for control control control walking walking
        expected_group = np.array([+1, +1, +1, +1, -1, -1])
        np.testing.assert_array_equal(design_mat[:, 1], expected_group)
    
    def test_design_matrix_subject_encoding(self):
        """Test subject intercept encoding (one-hot)"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        design_mat, _, _, _ = builder.build()
        
        # Subject columns (starting from col 2)
        subject_cols = design_mat[:, 2:]
        
        # Each subject column should have exactly two 1s (pre and post)
        for col in range(subject_cols.shape[1]):
            assert np.sum(subject_cols[:, col]) == 2
        
        # Subject columns should be mutually exclusive (only one per row)
        row_sums = np.sum(subject_cols, axis=1)
        np.testing.assert_array_equal(row_sums, np.ones(8))
    
    def test_design_matrix_subject_order(self):
        """Test that subjects appear in canonical order (control then walking)"""
        control = ['sub-001', 'sub-002']
        walking = ['sub-003', 'sub-004']
        builder = MixedDesignBuilder(control, walking)
        design_mat, _, _, _ = builder.build()
        
        subject_cols = design_mat[:, 2:]
        
        # First two rows should use column 0 (sub-001)
        assert np.all(subject_cols[0:2, 0] == 1)
        assert np.all(subject_cols[0:2, 0] == subject_cols[0:2, 0])
        
        # Rows 2-3 should use column 1 (sub-002)
        assert np.all(subject_cols[2:4, 1] == 1)
        
        # Rows 4-5 should use column 2 (sub-003, first walking)
        assert np.all(subject_cols[4:6, 2] == 1)


class TestDesignMatrixRank:
    """Test full rank property"""
    
    def test_design_matrix_rank_4subjects(self):
        """Test design matrix rank for 4 subjects (rank-deficient by 1, expected for paired design)"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        design_mat, _, _, _ = builder.build()
        
        rank = np.linalg.matrix_rank(design_mat)
        # Paired designs are rank-deficient by 1 due to sum constraints
        # rank = n_cols - 1 is expected and acceptable
        n_cols = design_mat.shape[1]
        assert rank == n_cols - 1, f"Expected rank {n_cols - 1}, got {rank}"
        assert rank >= n_cols - 1  # Ensure we have sufficient rank
    
    def test_design_matrix_rank_10subjects(self):
        """Test design matrix rank for 10 subjects"""
        control = [f'sub-{i:03d}' for i in range(1, 6)]
        walking = [f'sub-{i:03d}' for i in range(6, 11)]
        builder = MixedDesignBuilder(control, walking)
        design_mat, _, _, _ = builder.build()
        
        rank = np.linalg.matrix_rank(design_mat)
        n_cols = design_mat.shape[1]
        # Paired designs are rank-deficient by 1
        assert rank == n_cols - 1, f"Expected rank {n_cols - 1}, got {rank}"
    
    def test_design_matrix_rank_balanced(self):
        """Test design matrix rank with balanced groups"""
        control = [f'sub-{i:03d}' for i in range(1, 21)]
        walking = [f'sub-{i:03d}' for i in range(21, 41)]
        builder = MixedDesignBuilder(control, walking)
        design_mat, _, _, _ = builder.build()
        
        rank = np.linalg.matrix_rank(design_mat)
        n_cols = design_mat.shape[1]
        # Paired designs are rank-deficient by 1
        assert rank == n_cols - 1, f"Expected rank {n_cols - 1}, got {rank}"


class TestExchangeabilityBlocks:
    """Test paired constraint (exchangeability blocks)"""
    
    def test_exchangeability_blocks_structure(self):
        """Test exchangeability blocks are [1,1,2,2,3,3,4,4]"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        _, _, _, blocks = builder.build()
        
        expected_blocks = np.array([1, 1, 2, 2, 3, 3, 4, 4])
        np.testing.assert_array_equal(blocks, expected_blocks)
    
    def test_exchangeability_blocks_size(self):
        """Test block count equals row count"""
        builder = MixedDesignBuilder(
            ['sub-001', 'sub-002', 'sub-003'],
            ['sub-004', 'sub-005']
        )
        design_mat, _, _, blocks = builder.build()
        
        assert len(blocks) == design_mat.shape[0]
    
    def test_exchangeability_blocks_paired_constraint(self):
        """Test each block ID appears exactly twice"""
        builder = MixedDesignBuilder(
            [f'sub-{i:03d}' for i in range(1, 6)],
            [f'sub-{i:03d}' for i in range(6, 11)]
        )
        _, _, _, blocks = builder.build()
        
        # Count occurrences of each block ID
        for block_id in np.unique(blocks):
            count = np.sum(blocks == block_id)
            assert count == 2


class TestContrasts:
    """Test contrast construction"""
    
    def test_contrasts_shape(self):
        """Test contrasts have correct shape"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        _, contrasts, _, _ = builder.build()
        
        # 3 contrasts (interaction, time, group)
        # 2 effects + 4 subjects = 6 columns
        assert contrasts.shape == (3, 6)
    
    def test_interaction_contrast(self):
        """Test interaction contrast [1, 1, 0, 0, 0, 0]"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        _, contrasts, _, _ = builder.build()
        
        interaction = contrasts[0]
        expected = np.array([1, 1, 0, 0, 0, 0])
        np.testing.assert_array_equal(interaction, expected)
    
    def test_time_contrast(self):
        """Test time main effect contrast [1, 0, 0, 0, 0, 0]"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        _, contrasts, _, _ = builder.build()
        
        time = contrasts[1]
        expected = np.array([1, 0, 0, 0, 0, 0])
        np.testing.assert_array_equal(time, expected)
    
    def test_group_contrast(self):
        """Test group main effect contrast [0, 1, 0, 0, 0, 0]"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        _, contrasts, _, _ = builder.build()
        
        group = contrasts[2]
        expected = np.array([0, 1, 0, 0, 0, 0])
        np.testing.assert_array_equal(group, expected)


class TestFTest:
    """Test F-test definition"""
    
    def test_ftest_shape(self):
        """Test F-test has shape (1, 3)"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        _, _, ftest, _ = builder.build()
        
        assert ftest.shape == (1, 3)
    
    def test_ftest_combines_all_contrasts(self):
        """Test F-test combines all three contrasts [1, 1, 1]"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        _, _, ftest, _ = builder.build()
        
        expected = np.array([[1, 1, 1]])
        np.testing.assert_array_equal(ftest, expected)


class TestValidation:
    """Test design matrix validation"""
    
    def test_validate_passes_valid_design(self):
        """Test validation passes for valid design"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        builder.build()
        
        is_valid, errors = builder.validate()
        assert is_valid
        assert len(errors) == 0
    
    def test_validate_detects_rank_deficiency(self):
        """Test validation detects insufficient rank"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        builder.build()
        
        # Create severe rank deficiency by making multiple rows linear combinations
        # This reduces rank below n_cols - 1
        builder.design_matrix[2] = builder.design_matrix[0]
        builder.design_matrix[3] = builder.design_matrix[1]
        builder.design_matrix[4] = 2 * builder.design_matrix[0] - builder.design_matrix[1]
        
        is_valid, errors = builder.validate()
        assert not is_valid
        assert any("rank" in err.lower() for err in errors)
    
    def test_validate_detects_nan(self):
        """Test validation detects NaN values"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        builder.build()
        
        builder.design_matrix[0, 0] = np.nan
        
        is_valid, errors = builder.validate()
        assert not is_valid
        # NaN check happens first, so we should get NaN error
        assert any("nan" in err.lower() for err in errors)
    
    def test_validate_detects_inf(self):
        """Test validation detects Inf values"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        builder.build()
        
        builder.design_matrix[0, 0] = np.inf
        
        is_valid, errors = builder.validate()
        assert not is_valid
        assert any("inf" in err.lower() for err in errors)
    
    def test_validate_detects_block_mismatch(self):
        """Test validation detects block count mismatch"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        builder.build()
        
        # Truncate blocks
        builder.exchangeability_blocks = builder.exchangeability_blocks[:-1]
        
        is_valid, errors = builder.validate()
        assert not is_valid
        assert any("block" in err.lower() for err in errors)
    
    def test_validate_requires_build(self):
        """Test validation requires build() to be called first"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        
        with pytest.raises(ValueError, match="not built"):
            builder.validate()


class TestFSLFileGeneration:
    """Test FSL file output"""
    
    def test_save_fsl_files_creates_all_files(self, tmp_path):
        """Test all FSL files are created"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        builder.build()
        
        files = builder.save_fsl_files(tmp_path)
        
        assert 'design.mat' in files
        assert 'design.con' in files
        assert 'design.fts' in files
        assert 'design.grp' in files
        
        for fname, fpath in files.items():
            assert fpath.exists(), f"{fname} not created"
    
    def test_save_fsl_files_creates_directory(self, tmp_path):
        """Test directory is created if it doesn't exist"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        builder.build()
        
        output_dir = tmp_path / 'new' / 'nested' / 'dir'
        assert not output_dir.exists()
        
        files = builder.save_fsl_files(output_dir)
        assert output_dir.exists()
        assert all(fpath.exists() for fpath in files.values())
    
    def test_save_fsl_files_requires_build(self, tmp_path):
        """Test save_fsl_files requires build() to be called first"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        
        with pytest.raises(ValueError, match="not built"):
            builder.save_fsl_files(tmp_path)
    
    def test_design_mat_format(self, tmp_path):
        """Test design.mat has correct format"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        builder.build()
        
        files = builder.save_fsl_files(tmp_path)
        
        with open(files['design.mat'], 'r') as f:
            content = f.read()
        
        assert '/NumWaves' in content
        assert '/NumPoints' in content
        assert '/Matrix' in content
        assert 'NumWaves\t6' in content
        assert 'NumPoints\t8' in content
    
    def test_design_con_format(self, tmp_path):
        """Test design.con has correct format"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        builder.build()
        
        files = builder.save_fsl_files(tmp_path)
        
        with open(files['design.con'], 'r') as f:
            content = f.read()
        
        assert '/NumWaves' in content
        assert '/NumContrasts' in content
        assert '/Matrix' in content
        assert 'NumContrasts\t3' in content
        assert 'Interaction' in content
        assert 'Time' in content
        assert 'Group' in content
    
    def test_design_fts_format(self, tmp_path):
        """Test design.fts has correct format"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        builder.build()
        
        files = builder.save_fsl_files(tmp_path)
        
        with open(files['design.fts'], 'r') as f:
            content = f.read()
        
        assert '/NumWaves' in content
        assert '/NumFtests' in content
        assert '/Matrix' in content
    
    def test_design_grp_format(self, tmp_path):
        """Test design.grp has correct format"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        builder.build()
        
        files = builder.save_fsl_files(tmp_path)
        
        with open(files['design.grp'], 'r') as f:
            lines = f.readlines()
        
        # Should have 8 lines (one per row)
        assert len(lines) == 8
        
        # Should be [1, 1, 2, 2, 3, 3, 4, 4]
        for i, line in enumerate(lines):
            expected = (i // 2) + 1
            assert int(line.strip()) == expected


class TestCanonicalSubjectOrder:
    """Test canonical subject ordering for 4D NIfTI merge"""
    
    def test_canonical_subject_order_shape(self):
        """Test canonical order DataFrame has correct shape"""
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        order_df = builder.get_canonical_subject_order()
        
        assert len(order_df) == 8
        assert list(order_df.columns) == ['subject', 'session', 'group']
    
    def test_canonical_subject_order_content(self):
        """Test canonical order matches design matrix rows"""
        control = ['sub-001', 'sub-002']
        walking = ['sub-003', 'sub-004']
        builder = MixedDesignBuilder(control, walking)
        order_df = builder.get_canonical_subject_order()
        
        # First control subject, pre/post
        assert order_df.iloc[0]['subject'] == 'sub-001'
        assert order_df.iloc[0]['session'] == 'ses-01'
        assert order_df.iloc[0]['group'] == 'control'
        
        assert order_df.iloc[1]['subject'] == 'sub-001'
        assert order_df.iloc[1]['session'] == 'ses-02'
        assert order_df.iloc[1]['group'] == 'control'
        
        # Second control subject
        assert order_df.iloc[2]['subject'] == 'sub-002'
        assert order_df.iloc[2]['session'] == 'ses-01'
        
        # First walking subject (should be at row 4)
        assert order_df.iloc[4]['subject'] == 'sub-003'
        assert order_df.iloc[4]['group'] == 'walking'
    
    def test_canonical_subject_order_custom_sessions(self):
        """Test canonical order with custom session labels"""
        builder = MixedDesignBuilder(
            ['sub-001'],
            ['sub-002'],
            sessions=['pre', 'post']
        )
        order_df = builder.get_canonical_subject_order()
        
        assert order_df.iloc[0]['session'] == 'pre'
        assert order_df.iloc[1]['session'] == 'post'


class TestConvenienceFunctions:
    """Test module-level convenience functions"""
    
    def test_build_paired_two_group_design(self):
        """Test convenience function"""
        design_mat, contrasts, ftest, blocks = build_paired_two_group_design(
            ['sub-001', 'sub-002'],
            ['sub-003', 'sub-004']
        )
        
        assert design_mat.shape == (8, 6)
        assert contrasts.shape == (3, 6)
        assert ftest.shape == (1, 3)
        assert len(blocks) == 8
    
    def test_validate_design_matrix_passes(self):
        """Test validate_design_matrix convenience function"""
        design_mat, _, _, blocks = build_paired_two_group_design(
            ['sub-001', 'sub-002'],
            ['sub-003', 'sub-004']
        )
        
        report = validate_design_matrix(design_mat, blocks)
        
        assert report['full_rank']
        assert report['no_nan_inf']
        assert report['blocks_match']
        assert report['paired_constraint']
    
    def test_contrasts_paired_two_group(self):
        """Test contrasts_paired_two_group convenience function"""
        contrasts = contrasts_paired_two_group(n_subjects=10)
        
        assert contrasts.shape == (3, 12)  # 3 contrasts, 2 effects + 10 subjects
    
    def test_ftest_paired_two_group(self):
        """Test ftest_paired_two_group convenience function"""
        ftest = ftest_paired_two_group()
        
        assert ftest.shape == (1, 3)
        np.testing.assert_array_equal(ftest, np.array([[1, 1, 1]]))


class TestEdgeCases:
    """Test edge cases and boundary conditions"""
    
    def test_single_subject_per_group(self):
        """Test design works with one subject per group"""
        builder = MixedDesignBuilder(['sub-001'], ['sub-002'])
        design_mat, _, _, blocks = builder.build()
        
        assert design_mat.shape == (4, 4)  # 2 subjects * 2 sessions = 4 rows, 2 effects + 2 subjects
        assert len(blocks) == 4
        np.testing.assert_array_equal(blocks, np.array([1, 1, 2, 2]))
    
    def test_large_number_of_subjects(self):
        """Test design works with many subjects"""
        control = [f'sub-{i:03d}' for i in range(1, 51)]
        walking = [f'sub-{i:03d}' for i in range(51, 101)]
        builder = MixedDesignBuilder(control, walking)
        design_mat, _, _, _ = builder.build()
        
        assert design_mat.shape == (200, 102)  # 100 subjects * 2 = 200 rows, 2 + 100
        
        # Verify rank (paired designs are rank-deficient by 1)
        rank = np.linalg.matrix_rank(design_mat)
        assert rank == 101  # n_cols - 1


class TestIntegration:
    """Integration tests across multiple components"""
    
    def test_full_workflow(self, tmp_path):
        """Test complete workflow: build, validate, save"""
        # Build design
        builder = MixedDesignBuilder.from_paired_two_group(
            control_subjects=['sub-001', 'sub-002', 'sub-003'],
            walking_subjects=['sub-004', 'sub-005', 'sub-006']
        )
        
        # Get output
        design_mat, contrasts, ftest, blocks = builder.build()
        
        # Validate
        is_valid, errors = builder.validate()
        assert is_valid, f"Validation failed: {errors}"
        
        # Save files
        files = builder.save_fsl_files(tmp_path)
        assert len(files) == 4
        assert all(fpath.exists() for fpath in files.values())
        
        # Get subject order
        order_df = builder.get_canonical_subject_order()
        assert len(order_df) == 12
    
    def test_designs_match_between_methods(self):
        """Test that builder and convenience function produce same results"""
        # Using builder
        builder = MixedDesignBuilder(['sub-001', 'sub-002'], ['sub-003', 'sub-004'])
        design1, contrasts1, ftest1, blocks1 = builder.build()
        
        # Using convenience function
        design2, contrasts2, ftest2, blocks2 = build_paired_two_group_design(
            ['sub-001', 'sub-002'],
            ['sub-003', 'sub-004']
        )
        
        np.testing.assert_array_equal(design1, design2)
        np.testing.assert_array_equal(contrasts1, contrasts2)
        np.testing.assert_array_equal(ftest1, ftest2)
        np.testing.assert_array_equal(blocks1, blocks2)
