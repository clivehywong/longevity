"""
tests/test_hpc_submit_wrappers.py — dry-run tests for the XCP-D-driven HPC
submission wrappers.

Tests verify that the SLURM script bodies and group-level command strings
contain the correct backend invocations, flag names, and propagated values.
These tests never write to disk or invoke sbatch; they only inspect the
generated strings.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make script/ importable (no package install required)
_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "script"
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from hpc_submit_subject_level import (
    DEFAULT_XCPD_ATLASES,
    DEFAULT_XCPD_MEASURES,
    build_xcpd_session_pairs,
    generate_xcpd_subject_script,
)
from hpc_submit_group_level import (
    build_xcpd_group_command,
    generate_xcpd_group_script,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SEED_SPEC_ATLAS = "atlas-4S256Parcels:LH_Vis_1"
SEED_SPEC_SPHERE = "sphere:0,-52,26,r=6,name=PCC"
SEED_SPEC_NIFTI = "nifti:/path/to/roi.nii.gz,name=DLPFC"

DEFAULT_PAIRS = [("sub-033", "ses-01"), ("sub-033", "ses-02"), ("sub-034", "ses-01")]


# ---------------------------------------------------------------------------
# Subject-level: seed analysis
# ---------------------------------------------------------------------------

class TestSeedAnalysisScript:
    def test_calls_seed_backend(self):
        script = generate_xcpd_subject_script(
            analysis="seed",
            pipeline="fc",
            measures="pearson",
            seeds=[SEED_SPEC_ATLAS],
            atlases=None,
            bids_root="/data/longevity",
            out_root="derivatives/connectivity",
            session_pairs=DEFAULT_PAIRS,
        )
        assert "compute_seed_connectivity_xcpd.py" in script
        assert "compute_network_connectivity_xcpd.py" not in script

    def test_pipeline_flag_propagated(self):
        for pipeline in ("fc", "fc_gsr", "ec"):
            script = generate_xcpd_subject_script(
                analysis="seed",
                pipeline=pipeline,
                measures="pearson",
                seeds=[SEED_SPEC_ATLAS],
                atlases=None,
                bids_root="/data",
                out_root="deriv",
                session_pairs=DEFAULT_PAIRS,
            )
            assert f"--pipeline {pipeline}" in script

    def test_seed_flags_present_and_repeated(self):
        seeds = [SEED_SPEC_ATLAS, SEED_SPEC_SPHERE, SEED_SPEC_NIFTI]
        script = generate_xcpd_subject_script(
            analysis="seed",
            pipeline="fc",
            measures="pearson",
            seeds=seeds,
            atlases=None,
            bids_root="/data",
            out_root="deriv",
            session_pairs=DEFAULT_PAIRS,
        )
        assert script.count("--seed") == 3

    def test_measures_flag_propagated(self):
        measures = "pearson,spearman,partial_correlation"
        script = generate_xcpd_subject_script(
            analysis="seed",
            pipeline="fc",
            measures=measures,
            seeds=[SEED_SPEC_ATLAS],
            atlases=None,
            bids_root="/data",
            out_root="deriv",
            session_pairs=DEFAULT_PAIRS,
        )
        assert measures in script

    def test_slurm_array_size_matches_pairs(self):
        pairs = [("sub-033", "ses-01"), ("sub-034", "ses-01"), ("sub-035", "ses-02")]
        script = generate_xcpd_subject_script(
            analysis="seed",
            pipeline="fc",
            measures="pearson",
            seeds=[SEED_SPEC_ATLAS],
            atlases=None,
            bids_root="/data",
            out_root="deriv",
            session_pairs=pairs,
        )
        assert f"--array=1-{len(pairs)}" in script

    def test_test_mode_limits_to_two_pairs(self):
        script = generate_xcpd_subject_script(
            analysis="seed",
            pipeline="fc",
            measures="pearson",
            seeds=[SEED_SPEC_ATLAS],
            atlases=None,
            bids_root="/data",
            out_root="deriv",
            session_pairs=DEFAULT_PAIRS,
            test_mode=True,
        )
        assert "--array=1-2" in script

    def test_manifest_markers_present(self):
        script = generate_xcpd_subject_script(
            analysis="seed",
            pipeline="fc",
            measures="pearson",
            seeds=[SEED_SPEC_ATLAS],
            atlases=None,
            bids_root="/data",
            out_root="deriv",
            session_pairs=DEFAULT_PAIRS,
        )
        assert "outputs/expected" in script
        assert "outputs/done" in script
        assert "_seed.expected" in script
        assert "_seed.done" in script

    def test_force_flag_propagated(self):
        script = generate_xcpd_subject_script(
            analysis="seed",
            pipeline="fc",
            measures="pearson",
            seeds=[SEED_SPEC_ATLAS],
            atlases=None,
            bids_root="/data",
            out_root="deriv",
            session_pairs=DEFAULT_PAIRS,
            force=True,
        )
        assert "--force" in script

    def test_bids_root_embedded(self):
        script = generate_xcpd_subject_script(
            analysis="seed",
            pipeline="fc",
            measures="pearson",
            seeds=[SEED_SPEC_ATLAS],
            atlases=None,
            bids_root="/my/special/bids",
            out_root="deriv",
            session_pairs=DEFAULT_PAIRS,
        )
        assert "/my/special/bids" in script

    def test_raises_when_seeds_empty(self):
        with pytest.raises(ValueError, match="seeds"):
            generate_xcpd_subject_script(
                analysis="seed",
                pipeline="fc",
                measures="pearson",
                seeds=[],
                atlases=None,
                bids_root="/data",
                out_root="deriv",
                session_pairs=DEFAULT_PAIRS,
            )

    def test_raises_on_invalid_analysis(self):
        with pytest.raises(ValueError, match="analysis"):
            generate_xcpd_subject_script(
                analysis="local_measures",
                pipeline="fc",
                measures="pearson",
                seeds=[SEED_SPEC_ATLAS],
                atlases=None,
                bids_root="/data",
                out_root="deriv",
                session_pairs=DEFAULT_PAIRS,
            )


# ---------------------------------------------------------------------------
# Subject-level: network analysis
# ---------------------------------------------------------------------------

class TestNetworkAnalysisScript:
    def test_calls_network_backend(self):
        script = generate_xcpd_subject_script(
            analysis="network",
            pipeline="fc",
            measures="pearson",
            seeds=None,
            atlases=["4S256Parcels"],
            bids_root="/data",
            out_root="deriv",
            session_pairs=DEFAULT_PAIRS,
        )
        assert "compute_network_connectivity_xcpd.py" in script
        assert "compute_seed_connectivity_xcpd.py" not in script

    def test_atlas_flags_present_and_repeated(self):
        atlases = ["4S256Parcels", "Glasser", "Gordon"]
        script = generate_xcpd_subject_script(
            analysis="network",
            pipeline="fc",
            measures="pearson",
            seeds=None,
            atlases=atlases,
            bids_root="/data",
            out_root="deriv",
            session_pairs=DEFAULT_PAIRS,
        )
        assert script.count("--atlas") == 3

    def test_default_atlases_used_when_none_given(self):
        script = generate_xcpd_subject_script(
            analysis="network",
            pipeline="fc",
            measures="pearson",
            seeds=None,
            atlases=None,
            bids_root="/data",
            out_root="deriv",
            session_pairs=DEFAULT_PAIRS,
        )
        for atlas in DEFAULT_XCPD_ATLASES:
            assert atlas in script

    def test_measures_propagated(self):
        script = generate_xcpd_subject_script(
            analysis="network",
            pipeline="fc_gsr",
            measures=DEFAULT_XCPD_MEASURES,
            seeds=None,
            atlases=["4S256Parcels"],
            bids_root="/data",
            out_root="deriv",
            session_pairs=DEFAULT_PAIRS,
        )
        assert DEFAULT_XCPD_MEASURES in script

    def test_manifest_markers_present(self):
        script = generate_xcpd_subject_script(
            analysis="network",
            pipeline="fc",
            measures="pearson",
            seeds=None,
            atlases=["4S256Parcels"],
            bids_root="/data",
            out_root="deriv",
            session_pairs=DEFAULT_PAIRS,
        )
        assert "_network.expected" in script
        assert "_network.done" in script

    def test_subject_session_lookup_table_embedded(self):
        pairs = [("sub-033", "ses-01"), ("sub-034", "ses-02")]
        script = generate_xcpd_subject_script(
            analysis="network",
            pipeline="fc",
            measures="pearson",
            seeds=None,
            atlases=["4S256Parcels"],
            bids_root="/data",
            out_root="deriv",
            session_pairs=pairs,
        )
        assert '"sub-033"' in script
        assert '"ses-01"' in script
        assert '"sub-034"' in script
        assert '"ses-02"' in script


# ---------------------------------------------------------------------------
# Group-level: voxel stats
# ---------------------------------------------------------------------------

class TestGroupVoxelCommand:
    def test_routes_to_voxel_backend(self):
        cmd = build_xcpd_group_command(
            kind="voxel",
            bids_root="/data",
            pipeline="fc",
            measure="alff",
            contrast="ses-02_vs_ses-01",
            method="grf",
            group_csv="bids/participants.tsv",
            out="results/voxel",
        )
        assert "group_voxel_stats_xcpd.py" in cmd
        assert "group_matrix_stats.py" not in cmd

    def test_pipeline_measure_method_present(self):
        cmd = build_xcpd_group_command(
            kind="voxel",
            bids_root="/data",
            pipeline="fc_gsr",
            measure="reho",
            contrast="ses-02_vs_ses-01",
            method="tfce",
            group_csv="bids/participants.tsv",
            out="results/voxel",
            n_permutations=5000,
        )
        assert "--pipeline fc_gsr" in cmd
        assert "--measure reho" in cmd
        assert "--method tfce" in cmd
        assert "--n-permutations 5000" in cmd

    def test_mask_flag_optional(self):
        cmd_without = build_xcpd_group_command(
            kind="voxel", bids_root="/data", pipeline="fc",
            measure="alff", contrast="c", method="fdr",
            group_csv="bids/participants.tsv", out="out",
        )
        assert "--mask" not in cmd_without

        cmd_with = build_xcpd_group_command(
            kind="voxel", bids_root="/data", pipeline="fc",
            measure="alff", contrast="c", method="fdr",
            group_csv="bids/participants.tsv", out="out",
            mask="/data/mni_mask.nii.gz",
        )
        assert "--mask" in cmd_with
        assert "/data/mni_mask.nii.gz" in cmd_with

    def test_invalid_kind_raises(self):
        with pytest.raises(ValueError, match="kind"):
            build_xcpd_group_command(
                kind="unknown", bids_root="/data", pipeline="fc",
                measure="alff", contrast="c", method="grf",
                group_csv="bids/participants.tsv", out="out",
            )


# ---------------------------------------------------------------------------
# Group-level: matrix stats
# ---------------------------------------------------------------------------

class TestGroupMatrixCommand:
    def test_routes_to_matrix_backend(self):
        cmd = build_xcpd_group_command(
            kind="matrix",
            bids_root="/data",
            pipeline="fc",
            measure="pearson",
            contrast="ses-02_vs_ses-01",
            method="nbs",
            group_csv="bids/participants.tsv",
            out="results/matrix",
            matrix_kind="network",
            atlas="4S256Parcels",
        )
        assert "group_matrix_stats.py" in cmd
        assert "group_voxel_stats_xcpd.py" not in cmd

    def test_matrix_kind_forwarded_as_kind(self):
        cmd = build_xcpd_group_command(
            kind="matrix",
            bids_root="/data",
            pipeline="fc",
            measure="pearson",
            contrast="c",
            method="paired_t_fdr",
            group_csv="bids/participants.tsv",
            out="out",
            matrix_kind="seed",
            seed_id="PCC",
        )
        assert "--kind seed" in cmd
        assert "--seed-id PCC" in cmd

    def test_nbs_flags_present(self):
        cmd = build_xcpd_group_command(
            kind="matrix",
            bids_root="/data",
            pipeline="fc",
            measure="pearson",
            contrast="c",
            method="nbs",
            group_csv="bids/participants.tsv",
            out="out",
            matrix_kind="network",
            atlas="Glasser",
            threshold=3.0,
            n_permutations=2000,
            alpha=0.05,
        )
        assert "--method nbs" in cmd
        assert "--threshold 3.0" in cmd
        assert "--n-permutations 2000" in cmd
        assert "--alpha 0.05" in cmd
        assert "--atlas Glasser" in cmd


# ---------------------------------------------------------------------------
# Group-level: SLURM script generation
# ---------------------------------------------------------------------------

class TestGroupSlurmScript:
    def test_voxel_script_calls_correct_backend(self):
        script = generate_xcpd_group_script(
            kind="voxel",
            bids_root="/data",
            pipeline="fc",
            measure="alff",
            contrast="ses-02_vs_ses-01",
            method="grf",
            group_csv="bids/participants.tsv",
            out="results/voxel",
        )
        assert "group_voxel_stats_xcpd.py" in script
        assert "#SBATCH" in script

    def test_matrix_script_calls_correct_backend(self):
        script = generate_xcpd_group_script(
            kind="matrix",
            bids_root="/data",
            pipeline="fc",
            measure="pearson",
            contrast="ses-02_vs_ses-01",
            method="nbs",
            group_csv="bids/participants.tsv",
            out="results/matrix",
            matrix_kind="network",
            atlas="4S256Parcels",
        )
        assert "group_matrix_stats.py" in script

    def test_dependency_line_included_when_subject_job_given(self):
        script = generate_xcpd_group_script(
            kind="voxel",
            bids_root="/data",
            pipeline="fc",
            measure="alff",
            contrast="c",
            method="grf",
            group_csv="bids/participants.tsv",
            out="out",
            subject_job_id="99999",
        )
        assert "afterok:99999" in script


# ---------------------------------------------------------------------------
# Session-pair discovery
# ---------------------------------------------------------------------------

class TestBuildXcpdSessionPairs:
    def test_scans_xcpd_directory(self, tmp_path):
        bids_root = tmp_path
        xcpd_dir = bids_root / "derivatives" / "preprocessing" / "xcpd" / "fc"
        (xcpd_dir / "sub-033" / "ses-01").mkdir(parents=True)
        (xcpd_dir / "sub-033" / "ses-02").mkdir(parents=True)
        (xcpd_dir / "sub-034" / "ses-01").mkdir(parents=True)

        pairs = build_xcpd_session_pairs(bids_root, pipeline="fc")
        assert ("sub-033", "ses-01") in pairs
        assert ("sub-033", "ses-02") in pairs
        assert ("sub-034", "ses-01") in pairs
        assert len(pairs) == 3

    def test_subject_filter_applied(self, tmp_path):
        bids_root = tmp_path
        xcpd_dir = bids_root / "derivatives" / "preprocessing" / "xcpd" / "fc"
        (xcpd_dir / "sub-033" / "ses-01").mkdir(parents=True)
        (xcpd_dir / "sub-034" / "ses-01").mkdir(parents=True)

        pairs = build_xcpd_session_pairs(bids_root, pipeline="fc", subjects=["sub-033"])
        assert all(sub == "sub-033" for sub, _ in pairs)
        assert len(pairs) == 1

    def test_falls_back_to_bids_when_xcpd_absent(self, tmp_path):
        bids_dir = tmp_path / "bids"
        (bids_dir / "sub-033" / "ses-01").mkdir(parents=True)
        (bids_dir / "sub-033" / "ses-02").mkdir(parents=True)

        pairs = build_xcpd_session_pairs(tmp_path, pipeline="fc")
        assert ("sub-033", "ses-01") in pairs
        assert ("sub-033", "ses-02") in pairs

    def test_empty_when_nothing_found(self, tmp_path):
        pairs = build_xcpd_session_pairs(tmp_path / "nonexistent", pipeline="fc")
        assert pairs == []
