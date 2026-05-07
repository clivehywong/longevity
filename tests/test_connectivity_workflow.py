import shlex
from pathlib import Path

import pytest

from neuconn_app.utils.connectivity_workflow import (
    ConnectivitySubmission,
    ConnectivityWorkflowManager,
    ConnectivityWorkflowState,
)


def make_config(tmp_path: Path) -> dict:
    project_root = tmp_path / "project"
    bids_dir = project_root / "bids"
    bids_dir.mkdir(parents=True, exist_ok=True)
    return {
        "project_root": str(project_root),
        "paths": {
            "project_root": str(project_root),
            "bids_dir": str(bids_dir),
            "subject_level_dir": str(project_root / "derivatives" / "subject_level"),
            "group_level_dir": str(project_root / "derivatives" / "group_level"),
        },
        "hpc": {
            "host": "cluster.example.edu",
            "user": "tester",
            "remote_paths": {"base": str(project_root)},
            "slurm": {
                "partition": "default",
                "default_memory": "16G",
                "default_time": "06:00:00",
            },
        },
    }


def make_submission(submission_id="sub-1", analysis_type="seed_connectivity"):
    return ConnectivitySubmission(
        submission_id=submission_id,
        analysis_type=analysis_type,
        job_id="12345",
        submitted_at="2026-04-29T12:00:00",
        options={"atlas": "4S256Parcels"},
        subjects=["sub-033", "sub-034"],
        status="submitted",
        output_dir="/remote/results",
    )


def test_state_round_trip_serialization():
    state = ConnectivityWorkflowState()
    state.add(make_submission())

    restored = ConnectivityWorkflowState.from_dict(state.to_dict())

    assert list(restored.submissions) == ["sub-1"]
    assert restored.submissions["sub-1"].analysis_type == "seed_connectivity"
    assert restored.submissions["sub-1"].subjects == ["sub-033", "sub-034"]


def test_state_load_best_effort_skips_malformed_entries():
    restored = ConnectivityWorkflowState.from_dict(
        {
            "submissions": {
                "good": make_submission("good").__dict__,
                "bad-analysis": {"submission_id": "bad-analysis", "analysis_type": "bogus"},
                "not-a-dict": "broken",
            }
        }
    )

    assert list(restored.submissions) == ["good"]


def test_add_update_and_list_by_type():
    state = ConnectivityWorkflowState()
    state.add(make_submission("seed", "seed_connectivity"))
    state.add(make_submission("network", "network_connectivity"))

    state.update_status("seed", "running", job_id="999")

    assert state.submissions["seed"].status == "running"
    assert state.submissions["seed"].job_id == "999"
    assert [s.submission_id for s in state.list_by_type("network_connectivity")] == ["network"]


def test_build_subject_level_command_seed_analysis(tmp_path):
    """build_subject_level_command for seed_connectivity uses --analysis seed."""
    manager = ConnectivityWorkflowManager(make_config(tmp_path))
    cmd = manager.build_subject_level_command(
        "seed_connectivity",
        {
            "pipeline": "fc",
            "measures": "pearson,spearman",
            "seeds": ["atlas-4S256Parcels:LH_Vis_1", "sphere:0,-52,26,r=6,name=PCC"],
            "bids_root": "/data/bids",
            "out_root": "derivatives/connectivity",
            "max_parallel": 20,
            "time": "06:00:00",
            "memory": "16G",
            "partition": "default",
            "output_dir": None,
            "log_dir": "",
        },
        ["sub-033", "sub-034"],
    )
    parts = shlex.split(cmd)

    assert parts[:2] == ["python", str(tmp_path / "project" / "script" / "hpc_submit_subject_level.py")]
    assert "--analysis" in parts and parts[parts.index("--analysis") + 1] == "seed"
    assert "--pipeline" in parts and parts[parts.index("--pipeline") + 1] == "fc"
    assert "--measures" in parts and parts[parts.index("--measures") + 1] == "pearson,spearman"
    # repeated --seed flags
    seed_indices = [i for i, p in enumerate(parts) if p == "--seed"]
    assert len(seed_indices) == 2
    assert parts[seed_indices[0] + 1] == "atlas-4S256Parcels:LH_Vis_1"
    assert parts[seed_indices[1] + 1] == "sphere:0,-52,26,r=6,name=PCC"
    assert "--subjects" in parts and parts[parts.index("--subjects") + 1] == "sub-033,sub-034"
    # old flag names must not appear
    assert "--analysis-type" not in parts
    assert "--seeds" not in parts
    assert "--output-dir" not in parts
    assert "--log-dir" not in parts


def test_build_subject_level_command_network_analysis(tmp_path):
    """build_subject_level_command for network_connectivity uses --analysis network."""
    manager = ConnectivityWorkflowManager(make_config(tmp_path))
    cmd = manager.build_subject_level_command(
        "network_connectivity",
        {
            "pipeline": "fc_gsr",
            "atlases": ["4S256Parcels", "Glasser"],
            "measures": "pearson",
            "bids_root": "/data/bids",
        },
        ["sub-033"],
    )
    parts = shlex.split(cmd)

    assert parts[parts.index("--analysis") + 1] == "network"
    assert parts[parts.index("--pipeline") + 1] == "fc_gsr"
    # repeated --atlas flags
    atlas_indices = [i for i, p in enumerate(parts) if p == "--atlas"]
    assert len(atlas_indices) == 2
    assert {parts[i + 1] for i in atlas_indices} == {"4S256Parcels", "Glasser"}


def test_build_subject_level_command_local_measures_raises(tmp_path):
    """local_measures is no longer submitted; raises ValueError."""
    manager = ConnectivityWorkflowManager(make_config(tmp_path))
    with pytest.raises(ValueError, match="local_measures"):
        manager.build_subject_level_command("local_measures", {}, ["sub-033"])


@pytest.mark.parametrize("analysis_type", ["seed_connectivity", "network_connectivity"])
def test_build_subject_level_command_for_supported_analyses(tmp_path, analysis_type):
    """seed_connectivity and network_connectivity both produce valid commands."""
    manager = ConnectivityWorkflowManager(make_config(tmp_path))
    options = {
        "pipeline": "fc",
        "measures": "pearson",
        "bids_root": "/data",
    }
    if analysis_type == "seed_connectivity":
        options["seeds"] = ["atlas-4S256Parcels:LH_Vis_1"]
    else:
        options["atlases"] = ["4S256Parcels"]

    cmd = manager.build_subject_level_command(analysis_type, options, ["sub-033"])
    parts = shlex.split(cmd)

    expected_flag = "seed" if analysis_type == "seed_connectivity" else "network"
    assert parts[parts.index("--analysis") + 1] == expected_flag
    assert parts[parts.index("--pipeline") + 1] == "fc"
    assert "--analysis-type" not in parts


def test_build_group_level_command_voxel_kind(tmp_path):
    """build_group_level_command with kind=voxel passes --kind voxel and related flags."""
    manager = ConnectivityWorkflowManager(make_config(tmp_path))
    cmd = manager.build_group_level_command(
        {
            "kind": "voxel",
            "pipeline": "fc",
            "measure": "alff",
            "contrast": "ses-02_vs_ses-01",
            "method": "tfce",
            "n_permutations": 5000,
            "group_csv": "bids/participants.tsv",
            "out": "results/group_voxel",
            "mask": "/data/mask.nii.gz",
            "test_mode": True,
        }
    )
    parts = shlex.split(cmd)

    assert parts[:2] == ["python", str(tmp_path / "project" / "script" / "hpc_submit_group_level.py")]
    assert parts[parts.index("--kind") + 1] == "voxel"
    assert parts[parts.index("--pipeline") + 1] == "fc"
    assert parts[parts.index("--measure") + 1] == "alff"
    assert parts[parts.index("--contrast") + 1] == "ses-02_vs_ses-01"
    assert parts[parts.index("--method") + 1] == "tfce"
    assert parts[parts.index("--n-permutations") + 1] == "5000"
    assert parts[parts.index("--mask") + 1] == "/data/mask.nii.gz"
    assert "--test-mode" in parts


def test_build_group_level_command_matrix_kind(tmp_path):
    """build_group_level_command with kind=matrix passes matrix-specific flags."""
    manager = ConnectivityWorkflowManager(make_config(tmp_path))
    cmd = manager.build_group_level_command(
        {
            "kind": "matrix",
            "pipeline": "fc",
            "matrix_kind": "network",
            "atlas": "4S256Parcels",
            "measure": "pearson",
            "contrast": "ses-02_vs_ses-01",
            "method": "nbs",
            "threshold": 3.0,
            "n_permutations": 1000,
            "alpha": 0.05,
            "group_csv": "bids/participants.tsv",
            "out": "results/group_matrix",
        }
    )
    parts = shlex.split(cmd)

    assert parts[parts.index("--kind") + 1] == "matrix"
    assert parts[parts.index("--matrix-kind") + 1] == "network"
    assert parts[parts.index("--atlas") + 1] == "4S256Parcels"
    assert parts[parts.index("--method") + 1] == "nbs"
    assert parts[parts.index("--threshold") + 1] == "3.0"
    assert parts[parts.index("--alpha") + 1] == "0.05"


def test_build_group_level_command_legacy_tfce_options(tmp_path):
    """Legacy --correction-method / --n-permutations flags still work."""
    manager = ConnectivityWorkflowManager(make_config(tmp_path))
    cmd = manager.build_group_level_command(
        {
            "subject_job_id": "12345",
            "correction_method": "tfce",
            "n_permutations": 5000,
            "test_mode": True,
        }
    )
    parts = shlex.split(cmd)

    assert parts[:2] == ["python", str(tmp_path / "project" / "script" / "hpc_submit_group_level.py")]
    assert parts[parts.index("--subject-job-id") + 1] == "12345"
    assert parts[parts.index("--correction-method") + 1] == "tfce"
    assert parts[parts.index("--n-permutations") + 1] == "5000"
    assert "--test-mode" in parts


def test_dry_run_submit_returns_record_and_persists_under_bids_parent(tmp_path):
    manager = ConnectivityWorkflowManager(make_config(tmp_path))

    submission = manager.submit(
        "seed_connectivity",
        {
            "pipeline": "fc",
            "measures": "pearson",
            "seeds": ["atlas-4S256Parcels:LH_Vis_1"],
            "max_parallel": 10,
            "memory": None,
        },
        ["sub-033"],
        dry_run=True,
    )

    assert submission.job_id == "DRY_RUN"
    assert submission.status == "submitted"
    assert "command_preview" in submission.options
    assert "--memory" not in shlex.split(submission.options["command_preview"])
    assert manager.state_file == tmp_path / "project" / ".neuconn" / "connectivity_workflow_state.json"
    assert submission.submission_id in manager.load_state().submissions


class FakeConnection:
    def __init__(self, responses):
        self.responses = responses
        self.commands = []
        self.connected = False

    @property
    def is_connected(self):
        return self.connected

    def connect(self):
        self.connected = True

    def execute(self, command, timeout=60):
        self.commands.append(command)
        return self.responses.pop(0)


def test_refresh_status_and_cancel_use_hpc_connection(tmp_path):
    connection = FakeConnection([
        ("RUNNING\n", "", 0),
        ("", "", 0),
    ])
    manager = ConnectivityWorkflowManager(make_config(tmp_path), connection=connection)
    state = ConnectivityWorkflowState()
    state.add(make_submission("sub-1", "network_connectivity"))
    manager.save_state(state)

    assert manager.refresh_status("sub-1") == "running"
    assert manager.cancel("sub-1") is True

    assert connection.commands[0].startswith("sacct -j 12345")
    assert connection.commands[1] == "scancel 12345"
    assert manager.load_state().submissions["sub-1"].status == "cancelled"
